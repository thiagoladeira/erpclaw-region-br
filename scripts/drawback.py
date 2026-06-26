"""Drawback & Export NF-e — ERPClaw Region BR

Brazilian Drawback regime management: suspension/exemption of federal
taxes on imports used to manufacture products for export. Also handles
NF-e for Exportação (tipoOperacao=3, with DI/RE/Drawback info).

Drawback: mechanism where a company imports raw materials or components
with suspended federal taxes (II, IPI, PIS, COFINS) provided the
finished product is exported within a specified timeframe.

Actions (5):
  configure-drawback     — Register a drawback act (Ato Concessório)
  import-drawback-nfe    — Link an imported NF-e to a drawback act
  generate-drawback-report — Report of drawback usage by act/period
  list-drawback-acts     — List all drawback acts with filters
  create-nfe-exportacao  — Generate NF-e for export (with DI/RE/Drawback)

All monetary values stored as TEXT (Decimal strings). All IDs as TEXT UUID4.
Parameterized SQL queries throughout.
"""
from __future__ import annotations

import os
import random
import sys
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

# ── erpclaw_lib imports ────────────────────────────────────────────────
sys.path.insert(0, os.path.expanduser("~/.openclaw/erpclaw/lib"))
from erpclaw_lib.response import ok, err
from erpclaw_lib.db import get_connection, DEFAULT_DB_PATH


# ═══════════════════════════════════════════════════════════════════════
# Action: configure-drawback
# ═══════════════════════════════════════════════════════════════════════

def configure_drawback(conn, args):
    """Register a Drawback Act (Ato Concessório).

    Args: --company-id (required), --ac-numero (required), --ac-data (required),
          --ac-vencimento, --modalidade, --valor-concedido
    """
    company_id = args.company_id
    if not company_id:
        return err("--company-id is required")

    ac_numero = args.ac_numero
    if not ac_numero:
        return err("--ac-numero (Ato Concessório number) is required")

    ac_data = args.ac_data
    if not ac_data:
        return err("--ac-data is required (format: YYYY-MM-DD)")

    # Validate date format
    try:
        datetime.strptime(ac_data, "%Y-%m-%d")
    except ValueError:
        return err("--ac-data must be in YYYY-MM-DD format")

    modalidade = args.modalidade or "suspensao"
    if modalidade not in ("suspensao", "isencao", "restituicao"):
        return err("--modalidade must be 'suspensao', 'isencao', or 'restituicao'")

    valor_concedido = args.valor_concedido or "0.00"

    # Validate company exists
    company = conn.execute(
        "SELECT id FROM company WHERE id = ?", (company_id,)
    ).fetchone()
    if not company:
        return err("Company not found")

    # Check for duplicate AC number
    existing = conn.execute(
        "SELECT id FROM drawback_act WHERE ac_numero = ? AND company_id = ?",
        (ac_numero, company_id)
    ).fetchone()
    if existing:
        return err(f"Drawback act {ac_numero} already registered for this company")

    now = datetime.now().isoformat()
    act_id = str(uuid4())

    conn.execute("""
        INSERT INTO drawback_act (id, ac_numero, ac_data, ac_vencimento,
            modalidade, valor_concedido, valor_utilizado, status,
            company_id, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, '0.00', 'ativo', ?, ?, ?)
    """, (
        act_id, ac_numero, ac_data, args.ac_vencimento,
        modalidade, valor_concedido,
        company_id, now, now,
    ))
    conn.commit()

    row = conn.execute(
        "SELECT * FROM drawback_act WHERE id = ?", (act_id,)
    ).fetchone()

    return ok({
        "registered": True,
        "act": dict(row),
        "ac_numero": ac_numero,
        "modalidade": modalidade,
    })


# ═══════════════════════════════════════════════════════════════════════
# Action: import-drawback-nfe
# ═══════════════════════════════════════════════════════════════════════

def import_drawback_nfe(conn, args):
    """Link an imported NF-e to a drawback act for tax suspension tracking.

    Args: --company-id (required), --drawback-act-id (required),
          --nfe-import-id, --di-numero, --valor-mercadorias,
          --valor-impostos-suspensos, --data-importacao
    """
    company_id = args.company_id
    if not company_id:
        return err("--company-id is required")

    act_id = args.drawback_act_id
    if not act_id:
        return err("--drawback-act-id is required")

    # Validate drawback act exists
    act_row = conn.execute(
        "SELECT * FROM drawback_act WHERE id = ? AND company_id = ?",
        (act_id, company_id)
    ).fetchone()
    if not act_row:
        return err("Drawback act not found or belongs to different company")

    act = dict(act_row)

    if act["status"] != "ativo":
        return err(f"Drawback act status is '{act['status']}', must be 'ativo'")

    if act.get("ac_vencimento"):
        try:
            venc = datetime.strptime(act["ac_vencimento"], "%Y-%m-%d")
            if venc < datetime.now():
                return err(f"Drawback act expired on {act['ac_vencimento']}")
        except ValueError:
            pass

    # Validate NF-e import if linked
    nfe_import_id = args.nfe_import_id
    if nfe_import_id:
        try:
            nfe_row = conn.execute(
                "SELECT id, valor_total, emitente_nome, emitente_cnpj, data_emissao FROM nfe_import WHERE id = ?",
                (nfe_import_id,)
            ).fetchone()
            if not nfe_row:
                return err(f"NF-e import not found: {nfe_import_id}")
        except Exception:
            pass  # nfe_import table might not exist

    now = datetime.now().isoformat()
    import_id = str(uuid4())

    valor_mercadorias = str(args.valor_mercadorias or "0.00")
    valor_impostos_suspensos = str(args.valor_impostos_suspensos or "0.00")

    conn.execute("""
        INSERT INTO drawback_import (id, drawback_act_id, nfe_import_id,
            di_numero, valor_mercadorias, valor_impostos_suspensos,
            data_importacao, company_id, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        import_id, act_id, nfe_import_id,
        args.di_numero, valor_mercadorias, valor_impostos_suspensos,
        args.data_importacao, company_id, now, now,
    ))

    # Update drawback act: increment valor_utilizado
    try:
        valor_atual = Decimal(act.get("valor_utilizado", "0"))
        valor_novo = valor_atual + Decimal(valor_impostos_suspensos)
        conn.execute(
            "UPDATE drawback_act SET valor_utilizado = ?, updated_at = ? WHERE id = ?",
            (str(valor_novo), now, act_id)
        )
    except Exception:
        pass

    conn.commit()

    row = conn.execute(
        "SELECT * FROM drawback_import WHERE id = ?", (import_id,)
    ).fetchone()
    act_updated = conn.execute(
        "SELECT * FROM drawback_act WHERE id = ?", (act_id,)
    ).fetchone()

    return ok({
        "linked": True,
        "drawback_import": dict(row),
        "drawback_act": dict(act_updated),
        "ac_numero": act["ac_numero"],
    })


# ═══════════════════════════════════════════════════════════════════════
# Action: generate-drawback-report
# ═══════════════════════════════════════════════════════════════════════

def generate_drawback_report(conn, args):
    """Generate a report of drawback usage by act and period.

    Args: --company-id, --drawback-act-id, --start-date, --end-date,
          --limit, --offset
    """
    company_id = args.company_id
    act_id = args.drawback_act_id

    conditions = ["1=1"]
    params_act = []
    params_imp = []

    if company_id:
        conditions_act = ["company_id = ?"]
        params_act.append(company_id)

    if act_id:
        conditions_act = ["id = ?"] if not company_id else ["id = ?", "company_id = ?"]
        params_act = [act_id] if not company_id else [act_id, company_id]

    where_act = " AND ".join(conditions_act) if company_id or act_id else "1=1"

    acts = conn.execute(
        f"SELECT * FROM drawback_act WHERE {where_act} ORDER BY ac_data DESC",
        params_act
    ).fetchall()

    report = []
    total_suspensos = Decimal("0")
    total_mercadorias = Decimal("0")

    for act_row in acts:
        act = dict(act_row)

        # Get imports linked to this act
        imp_conditions = ["drawback_act_id = ?"]
        imp_params = [act["id"]]

        if args.start_date:
            imp_conditions.append("data_importacao >= ?")
            imp_params.append(args.start_date)
        if args.end_date:
            imp_conditions.append("data_importacao <= ?")
            imp_params.append(args.end_date)

        where_imp = " AND ".join(imp_conditions)
        imports = conn.execute(
            f"SELECT * FROM drawback_import WHERE {where_imp} ORDER BY data_importacao ASC",
            imp_params
        ).fetchall()

        imports_list = [dict(imp) for imp in imports]

        act_suspensos = Decimal("0")
        act_mercadorias = Decimal("0")

        for imp in imports:
            try:
                act_suspensos += Decimal(imp["valor_impostos_suspensos"] or "0")
            except Exception:
                pass
            try:
                act_mercadorias += Decimal(imp["valor_mercadorias"] or "0")
            except Exception:
                pass

        total_suspensos += act_suspensos
        total_mercadorias += act_mercadorias

        # Check expiry
        expiry_status = "OK"
        if act.get("ac_vencimento"):
            try:
                venc = datetime.strptime(act["ac_vencimento"], "%Y-%m-%d")
                days_left = (venc - datetime.now()).days
                if days_left < 0:
                    expiry_status = "EXPIRED"
                elif days_left < 90:
                    expiry_status = f"EXPIRING ({days_left} days)"
            except ValueError:
                expiry_status = "UNKNOWN"

        report.append({
            "ac_numero": act["ac_numero"],
            "ac_data": act["ac_data"],
            "ac_vencimento": act.get("ac_vencimento"),
            "modalidade": act["modalidade"],
            "status": act["status"],
            "expiry_status": expiry_status,
            "valor_concedido": act["valor_concedido"],
            "valor_utilizado": act["valor_utilizado"],
            "imports_count": len(imports),
            "total_suspensos": str(act_suspensos),
            "total_mercadorias": str(act_mercadorias),
            "percent_utilized": _safe_pct(act["valor_utilizado"], act["valor_concedido"]),
            "imports": imports_list[:50],  # Limit details
        })

    return ok({
        "report": report,
        "acts_count": len(acts),
        "total_impostos_suspensos": str(total_suspensos),
        "total_mercadorias": str(total_mercadorias),
    })


def _safe_pct(utilizado: str, concedido: str) -> str:
    """Safely calculate percentage utilized."""
    try:
        u = Decimal(utilizado or "0")
        c = Decimal(concedido or "0")
        if c > 0:
            return f"{(u / c * 100).quantize(Decimal('0.01'))}%"
    except Exception:
        pass
    return "0.00%"


# ═══════════════════════════════════════════════════════════════════════
# Action: list-drawback-acts
# ═══════════════════════════════════════════════════════════════════════

def list_drawback_acts(conn, args):
    """List drawback acts with filters.

    Args: --company-id, --search, --limit, --offset
    """
    conditions = ["1=1"]
    params = []

    if args.company_id:
        conditions.append("company_id = ?")
        params.append(args.company_id)

    if args.search:
        conditions.append("ac_numero LIKE ?")
        params.append(f"%{args.search}%")

    where = " AND ".join(conditions)
    limit = min(args.limit or 50, 500)
    offset = args.offset or 0

    rows = conn.execute(
        f"SELECT * FROM drawback_act WHERE {where} ORDER BY ac_data DESC LIMIT ? OFFSET ?",
        (*params, limit, offset)
    ).fetchall()

    total = conn.execute(
        f"SELECT COUNT(*) FROM drawback_act WHERE {where}", params
    ).fetchone()[0]

    acts = []
    for r in rows:
        act = dict(r)

        # Attach import count
        import_count = conn.execute(
            "SELECT COUNT(*) FROM drawback_import WHERE drawback_act_id = ?",
            (act["id"],)
        ).fetchone()[0]

        act["imports_linked"] = import_count
        acts.append(act)

    return ok({
        "acts": acts,
        "total": total,
        "limit": limit,
        "offset": offset,
    })


# ═══════════════════════════════════════════════════════════════════════
# Action: create-nfe-exportacao
# ═══════════════════════════════════════════════════════════════════════

def create_nfe_exportacao(conn, args):
    """Generate an NF-e for export (NF-e Exportação with DI/RE/Drawback info).

    Creates a br_nfe_out record with export-specific data including
    DI (Declaração de Importação) and Drawback reference.

    Args: --company-id (required), --sales-invoice-id,
          --customer-id, --customer-cnpj, --customer-name,
          --di-numero, --di-data, --di-vencimento,
          --cnpj-beneficiario, --uf-despacho, --drawback-act-id
    """
    company_id = args.company_id
    if not company_id:
        return err("--company-id is required")

    # Validate NFe config exists
    config_row = conn.execute(
        "SELECT * FROM br_nfe_config WHERE company_id = ?",
        (company_id,)
    ).fetchone()
    if not config_row:
        return err("NF-e not configured for this company. Run configure-nfe first.")

    config = dict(config_row)

    # Get next number
    numero = config["proximo_numero"]

    # Build chave de acesso
    from nfe_xml_gen import _compute_chave_acesso_tuple, _codigo_uf

    uf = config.get("uf", "RJ")
    serie = config.get("serie_default", "1")
    now = datetime.now()

    chave = _compute_chave_acesso_tuple(
        uf, now.year, now.month,
        company_id, numero, serie=serie,
        modelo="55", tp_emis=1,
    )

    # Determine export data
    customer_id = args.customer_id
    customer_name = args.customer_name or "EXPORTACAO"
    customer_cnpj = args.customer_cnpj or ""
    sales_invoice_id = args.sales_invoice_id

    # Get values from sales invoice if provided
    valor_produtos = "0.00"
    valor_total = "0.00"

    if sales_invoice_id:
        try:
            si_row = conn.execute(
                """SELECT id, total_amount, customer_id
                   FROM sales_invoice WHERE id = ?""",
                (sales_invoice_id,)
            ).fetchone()
            if si_row:
                si = dict(si_row)
                valor_total = si.get("total_amount", "0.00")
                valor_produtos = valor_total
                if not customer_id:
                    customer_id = si.get("customer_id")
                if customer_id and not customer_name:
                    cust_row = conn.execute(
                        "SELECT name, tax_id FROM customer WHERE id = ?",
                        (customer_id,)
                    ).fetchone()
                    if cust_row:
                        customer_name = cust_row["name"] or "EXPORTACAO"
                        customer_cnpj = cust_row["tax_id"] or ""
        except Exception:
            pass

    # Build XML for export NF-e
    try:
        from nfe_xml_gen import generate_nfe_xml

        xml_nfe = generate_nfe_xml(
            company_id=company_id,
            numero=numero,
            serie=serie,
            natureza_operacao="EXPORTACAO",
            finalidade="normal",  # Not 'complementar' or 'ajuste'
            customer_cnpj=customer_cnpj,
            customer_name=customer_name,
            valor_total=valor_total,
            valor_produtos=valor_produtos,
            cfop="7.101",  # Venda de produção do estabelecimento para o exterior
            data_emissao=now.strftime("%Y-%m-%d"),
            hora_saida=now.strftime("%H:%M:%S"),
            uf=uf,
            ambiente=config.get("ambiente", "homologacao"),
        )
    except Exception as e:
        xml_nfe = f"<!-- Export NF-e XML generation failed: {e} -->"
        # Create minimal XML
        xml_nfe = _build_export_nfe_xml(
            chave=chave, numero=numero, serie=serie,
            empresa=company_id, cliente=customer_name,
            cnpj_cliente=customer_cnpj, valor=valor_total,
            cfop="7.101", data=now.strftime("%Y-%m-%d"),
            uf=uf, ambiente=config.get("ambiente", "homologacao"),
        )

    # Generate export-specific info complementar
    info_complementar_parts = []
    if args.di_numero:
        info_complementar_parts.append(f"DI: {args.di_numero}")
        if args.di_data:
            info_complementar_parts.append(f"Data DI: {args.di_data}")

    if args.drawback_act_id:
        act_row = conn.execute(
            "SELECT ac_numero FROM drawback_act WHERE id = ?",
            (args.drawback_act_id,)
        ).fetchone()
        if act_row:
            info_complementar_parts.append(f"Drawback Ato Concessorio: {act_row['ac_numero']}")

    if args.cnpj_beneficiario:
        info_complementar_parts.append(f"CNPJ Beneficiario: {args.cnpj_beneficiario}")

    if args.uf_despacho:
        info_complementar_parts.append(f"UF Despacho: {args.uf_despacho}")

    info_complementar = "; ".join(info_complementar_parts) if info_complementar_parts else None

    now_iso = now.isoformat()
    nfe_id = str(uuid4())

    conn.execute("""
        INSERT INTO br_nfe_out (id, chave_acesso, numero, serie, modelo,
            tipo_operacao, data_emissao, data_saida, hora_saida,
            natureza_operacao, cfop_principal, finalidade,
            sales_invoice_id, customer_id, customer_name, customer_cnpj,
            valor_produtos, valor_total, valor_desconto, valor_frete,
            valor_seguro, outras_despesas, base_icms, valor_icms,
            base_icms_st, valor_icms_st, base_ipi, valor_ipi,
            valor_pis, valor_cofins, valor_ii,
            info_complementar, xml_nfe, status, ambiente,
            company_id, created_at, updated_at)
        VALUES (?, ?, ?, ?, '55', 'saida', ?, ?, ?,
            'EXPORTACAO', '7.101', 'normal',
            ?, ?, ?, ?,
            ?, ?, '0.00', '0.00',
            '0.00', '0.00', '0.00', '0.00',
            '0.00', '0.00', '0.00', '0.00',
            '0.00', '0.00', '0.00',
            ?, ?, 'rascunho', ?,
            ?, ?, ?)
    """, (
        nfe_id, chave, numero, serie,
        now.strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S"),
        sales_invoice_id, customer_id, customer_name, customer_cnpj,
        valor_produtos, valor_total,
        info_complementar, xml_nfe,
        config.get("ambiente", "homologacao"),
        company_id, now_iso, now_iso,
    ))

    # Increment next number
    conn.execute(
        "UPDATE br_nfe_config SET proximo_numero = ?, updated_at = ? WHERE id = ?",
        (numero + 1, now_iso, config["id"])
    )

    conn.commit()

    row = conn.execute("SELECT * FROM br_nfe_out WHERE id = ?", (nfe_id,)).fetchone()

    return ok({
        "created": True,
        "nfe_out": dict(row),
        "chave_acesso": chave,
        "numero": numero,
        "tipo": "exportacao",
        "drawback_linked": args.drawback_act_id is not None,
        "info_complementar": info_complementar,
    })


def _build_export_nfe_xml(**kw) -> str:
    """Build a minimal NF-e export XML when nfe_xml_gen is not available."""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<NFe xmlns="http://www.portalfiscal.inf.br/nfe">
  <infNFe Id="NFe{kw['chave']}" versao="4.00">
    <ide>
      <cUF>33</cUF>
      <natOp>EXPORTACAO</natOp>
      <mod>55</mod>
      <serie>{kw['serie']}</serie>
      <nNF>{kw['numero']}</nNF>
      <dhEmi>{kw['data']}T{kw.get('hora', '00:00:00')}-03:00</dhEmi>
      <tpNF>1</tpNF>
      <idDest>3</idDest>
      <cMunFG>3302409</cMunFG>
      <tpImp>1</tpImp>
      <tpEmis>1</tpEmis>
      <cDV>0</cDV>
      <tpAmb>{'1' if kw.get('ambiente') == 'producao' else '2'}</tpAmb>
      <finNFe>1</finNFe>
      <indFinal>0</indFinal>
      <indPres>0</indPres>
      <indIntermed>0</indIntermed>
      <procEmi>0</procEmi>
      <verProc>ERPClaw-Region-BR-1.5</verProc>
    </ide>
    <emit>
      <CNPJ>00000000000000</CNPJ>
      <xNome>EXPORTADOR</xNome>
    </emit>
    <dest>
      <CNPJ>{kw.get('cnpj_cliente', '')}</CNPJ>
      <xNome>{kw.get('cliente', 'EXPORTACAO')}</xNome>
      <enderDest>
        <xLgr>EXTERIOR</xLgr>
        <nro>S/N</nro>
        <xBairro>EXTERIOR</xBairro>
        <cMun>9999999</cMun>
        <xMun>EXTERIOR</xMun>
        <UF>EX</UF>
        <CEP>00000000</CEP>
        <cPais>9999</cPais>
        <xPais>EXTERIOR</xPais>
      </enderDest>
    </dest>
    <total>
      <ICMSTot>
        <vBC>0.00</vBC>
        <vICMS>0.00</vICMS>
        <vBCST>0.00</vBCST>
        <vST>0.00</vST>
        <vProd>{kw.get('valor', '0.00')}</vProd>
        <vFrete>0.00</vFrete>
        <vSeg>0.00</vSeg>
        <vDesc>0.00</vDesc>
        <vII>0.00</vII>
        <vIPI>0.00</vIPI>
        <vPIS>0.00</vPIS>
        <vCOFINS>0.00</vCOFINS>
        <vOutro>0.00</vOutro>
        <vNF>{kw.get('valor', '0.00')}</vNF>
      </ICMSTot>
    </total>
  </infNFe>
</NFe>"""


# ═══════════════════════════════════════════════════════════════════════
# ACTIONS registry
# ═══════════════════════════════════════════════════════════════════════

ACTIONS: dict = {
    "configure-drawback": configure_drawback,
    "import-drawback-nfe": import_drawback_nfe,
    "generate-drawback-report": generate_drawback_report,
    "list-drawback-acts": list_drawback_acts,
    "create-nfe-exportacao": create_nfe_exportacao,
}
