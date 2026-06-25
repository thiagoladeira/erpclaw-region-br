"""NF-e Avançada — Advanced NF-e features — ERPClaw Region BR

Advanced NF-e operations:
  - Manifestação do Destinatário (confirmação, ciência, desconhecimento, operação realizada)
  - Download NF-e XML from SEFAZ (Distribuição DFe)
  - Complementary NF-e (adjust values)
  - Return NF-e (CFOP for devolution)
  - Contingency NF-e (offline mode)
  - Export NF-e XML generation (with DI/RE)
  - DANFE PDF generation (via weasyprint or HTML fallback)

Actions:
  manifestar-nfe              — Manifestação do Destinatário
  download-nfe-xml            — Download XML from SEFAZ
  create-nfe-complementar     — Complementary NF-e
  create-nfe-devolucao        — Return NF-e
  create-nfe-contingencia     — Contingency NF-e (offline)
  gerar-xml-nfe-exportacao    — NF-e for export
  imprimir-danfe-pdf          — Generate DANFE as PDF

Usage: python3 nfe_avancada.py --action <action> --flags ...
"""
from __future__ import annotations

import base64
import json
import os
import re
import sys
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

# ── erpclaw_lib imports ────────────────────────────────────────────────
sys.path.insert(0, os.path.expanduser("~/.openclaw/erpclaw/lib"))
from erpclaw_lib.response import ok, err
from erpclaw_lib.db import get_connection, DEFAULT_DB_PATH

# ── Local imports ──────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from nfe_xml_gen import _clean_cnpj, _codigo_uf, _calc_dv_mod11
codigo_uf = _codigo_uf
from nfe_signer import sign_nfe_event_xml, validate_certificate

# Try optional deps
HAS_LXML = False
try:
    from lxml import etree  # noqa: F811
    HAS_LXML = True
except ImportError:
    pass

HAS_WEASYPRINT = False
try:
    import weasyprint
    HAS_WEASYPRINT = True
except ImportError:
    pass

HAS_REPORTLAB = False
try:
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    HAS_REPORTLAB = True
except ImportError:
    pass


# ═══════════════════════════════════════════════════════════════════════
# MANIFESTAÇÃO DO DESTINATÁRIO
# ═══════════════════════════════════════════════════════════════════════

MANIFESTACAO_TIPOS = {
    "confirmacao": "210200",
    "ciencia": "210210",
    "desconhecimento": "210220",
    "operacao_realizada": "210240",
}

MANIFESTACAO_DESCRICOES = {
    "210200": "Confirmacao da Operacao",
    "210210": "Ciencia da Emissao",
    "210220": "Desconhecimento da Operacao",
    "210240": "Operacao realizada",
}


def _build_evento_manifestacao(nfe: dict, tipo: str, evento_id: str,
                                now: datetime, cfg: dict) -> str:
    """Build event XML for Manifestação do Destinatário."""
    chave = nfe["chave_acesso"]
    cnpj_dest = _extract_cnpj_from_chave(chave)
    uf = cfg.get("uf", "SP")
    c_orgao = codigo_uf(uf)
    tp_amb = "1" if nfe.get("ambiente") == "producao" else "2"
    tp_evento = MANIFESTACAO_TIPOS.get(tipo, "210210")
    desc_evento = MANIFESTACAO_DESCRICOES.get(tp_evento, "Ciencia da Emissao")

    evento_clean = evento_id.replace("-", "")[:16]

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<evento xmlns="http://www.portalfiscal.inf.br/nfe" versao="1.00">
  <infEvento Id="ID{evento_clean}">
    <cOrgao>{c_orgao}</cOrgao>
    <tpAmb>{tp_amb}</tpAmb>
    <CNPJ>{cnpj_dest}</CNPJ>
    <chNFe>{chave}</chNFe>
    <dhEvento>{now.strftime('%Y-%m-%dT%H:%M:%S')}-03:00</dhEvento>
    <tpEvento>{tp_evento}</tpEvento>
    <nSeqEvento>1</nSeqEvento>
    <verEvento>1.00</verEvento>
    <detEvento versao="1.00">
      <descEvento>{desc_evento}</descEvento>
      <xJust>{desc_evento}</xJust>
    </detEvento>
  </infEvento>
</evento>"""


def manifestar_nfe(conn, args):
    """Send Manifestação do Destinatário to SEFAZ.

    Args: --nfe-out-id (recipient), --tipo-manifestacao
          (confirmacao|ciencia|desconhecimento|operacao_realizada)
    """
    nfe_id = args.nfe_out_id
    tipo = args.tipo_manifestacao

    if not nfe_id:
        return err("--nfe-out-id is required (NF-e where company is recipient)")
    if not tipo:
        return err("--tipo-manifestacao is required: "
                   "confirmacao, ciencia, desconhecimento, operacao_realizada")
    if tipo not in MANIFESTACAO_TIPOS:
        return err(f"Invalid tipo-manifestacao: {tipo}. "
                   f"Valid: {', '.join(MANIFESTACAO_TIPOS.keys())}")

    # Load NF-e — could be imported NF-e (nfe_import) or outbound NF-e
    row = conn.execute(
        "SELECT * FROM nfe_import WHERE id = ?", (nfe_id,)
    ).fetchone()
    if not row:
        row = conn.execute(
            "SELECT * FROM br_nfe_out WHERE id = ?", (nfe_id,)
        ).fetchone()

    if not row:
        return err(f"NF-e not found: {nfe_id}")

    nfe = dict(row)

    # For imported NF-e, we need to construct some fields differently
    if "chave_acesso" not in nfe:
        return err("NF-e record has no chave_acesso")

    # Get company config for certificate
    cid = nfe.get("company_id", "")
    cfg = conn.execute(
        "SELECT * FROM br_nfe_config WHERE company_id = ?", (cid,)
    ).fetchone()
    if not cfg:
        return err(f"No NF-e config for company {cid}. Run configure-nfe first.")

    cfg = dict(cfg)
    cert_path = cfg.get("certificado_path", "")
    cert_pass = cfg.get("certificado_password", "")
    uf = cfg.get("uf", "SP")
    ambiente = nfe.get("ambiente", cfg.get("ambiente", "homologacao"))

    if not cert_path or not os.path.isfile(cert_path):
        return err("Certificate not configured or missing")

    try:
        cert_pass = base64.b64decode(cert_pass.encode("ascii")).decode("utf-8")
    except Exception:
        pass

    # Build manifestação evento
    evento_id = str(uuid4())
    now = datetime.now()
    evento_xml = _build_evento_manifestacao(nfe, tipo, evento_id, now, cfg)

    # Store event
    event_db_id = str(uuid4())
    tp_evento = MANIFESTACAO_TIPOS[tipo]
    event_label = MANIFESTACAO_DESCRICOES.get(tp_evento, tipo)

    conn.execute("""
        INSERT OR IGNORE INTO br_nfe_event (
            id, nfe_out_id, tipo_evento, numero_sequencial,
            xml_evento, status, ambiente, company_id, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        event_db_id, nfe_id, tipo, 1,
        evento_xml, "pendente", ambiente, cid,
        now.isoformat(), now.isoformat(),
    ))

    # Sign the event
    try:
        signed_evento = sign_nfe_event_xml(evento_xml, cert_path, cert_pass)
    except Exception as e:
        conn.commit()
        return err(f"Signing failed: {e}")

    conn.execute(
        "UPDATE br_nfe_event SET xml_evento_signed = ?, status = 'enviado', updated_at = ? WHERE id = ?",
        (signed_evento, now.isoformat(), event_db_id)
    )

    # Try to transmit to SEFAZ
    try:
        from sefaz_ws import send_soap_request, get_sefaz_url, SOAP_ACTIONS
        url = get_sefaz_url(uf, ambiente, "NFeRecepcaoEvento")
        soap_action = SOAP_ACTIONS["NFeRecepcaoEvento"]

        evento_body = signed_evento
        if "<evento " in signed_evento:
            start = signed_evento.find("<evento ")
            evento_body = signed_evento[start:]

        env_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<envEvento xmlns="http://www.portalfiscal.inf.br/nfe" versao="1.00">
  <idLote>1</idLote>
{evento_body}
</envEvento>"""

        result = send_soap_request(url, soap_action, env_xml, cert_path, cert_pass)
    except ImportError:
        result = {"success": False, "error": "sefaz_ws not available"}
    except Exception as e:
        result = {"success": False, "error": str(e)}

    if result.get("success"):
        conn.execute("""
            UPDATE br_nfe_event SET
                protocolo = ?, status = 'processado',
                data_processamento = ?, motivo_status = ?,
                updated_at = ?
            WHERE id = ?
        """, (
            result.get("protocolo", ""),
            now.isoformat(),
            f"Manifestação {tipo} registrada",
            now.isoformat(), event_db_id,
        ))
    else:
        conn.execute(
            "UPDATE br_nfe_event SET status = 'rejeitado', motivo_status = ?, updated_at = ? WHERE id = ?",
            (result.get("error", str(result)), now.isoformat(), event_db_id)
        )

    conn.commit()

    return ok({
        "nfe_id": nfe_id,
        "chave_acesso": nfe["chave_acesso"],
        "tipo_manifestacao": tipo,
        "evento_id": event_db_id,
        "status": "processado" if result.get("success") else "rejeitado",
        "message": result.get("message") or result.get("error",
                   f"Manifestação {tipo} registrada"),
    })


# ═══════════════════════════════════════════════════════════════════════
# DOWNLOAD NF-e XML — Distribuição DFe
# ═══════════════════════════════════════════════════════════════════════

def download_nfe_xml(conn, args):
    """Download NF-e XML from SEFAZ (Distribuição DFe).

    Downloads XML of NF-es where company is recipient (destinatário).

    Args: --chave-acesso, --company-id, --output-path (optional)
    """
    chave = args.chave_acesso
    cid = args.company_id
    if not chave:
        return err("--chave-acesso is required")
    if not cid:
        return err("--company-id is required")

    # Get company fiscal data
    row = conn.execute(
        "SELECT cnpj FROM company_fiscal WHERE company_id = ?", (cid,)
    ).fetchone()
    if not row or not row["cnpj"]:
        return err("Company CNPJ not found in company_fiscal")

    cnpj_dest = _clean_cnpj(row["cnpj"])

    # Get NF-e config for cert
    cfg = conn.execute(
        "SELECT * FROM br_nfe_config WHERE company_id = ?", (cid,)
    ).fetchone()
    if not cfg:
        return err(f"No NF-e config for company {cid}")

    cfg = dict(cfg)
    cert_path = cfg.get("certificado_path", "")
    cert_pass = cfg.get("certificado_password", "")
    uf = cfg.get("uf", "SP")
    ambiente = cfg.get("ambiente", "homologacao")

    if not cert_path or not os.path.isfile(cert_path):
        return err("Certificate not configured or missing")

    try:
        cert_pass = base64.b64decode(cert_pass.encode("ascii")).decode("utf-8")
    except Exception:
        pass

    # Build distribuição DFe request
    cnpj_clean = _clean_cnpj(cnpj_dest)
    tp_amb = "1" if ambiente == "producao" else "2"

    dist_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<distDFeInt xmlns="http://www.portalfiscal.inf.br/nfe" versao="1.01">
  <tpAmb>{tp_amb}</tpAmb>
  <cUFAutor>{codigo_uf(uf)}</cUFAutor>
  <CNPJ>{cnpj_clean}</CNPJ>
  <consChNFe>
    <chNFe>{chave}</chNFe>
  </consChNFe>
</distDFeInt>"""

    try:
        from sefaz_ws import send_soap_request, get_sefaz_url

        url = get_sefaz_url(uf, ambiente, "NFeDistribuicaoDFe")
        soap_action = "http://www.portalfiscal.inf.br/nfe/wsdl/NFeDistribuicaoDFe/nfeDistDFeInteresse"

        result = send_soap_request(url, soap_action, dist_xml, cert_path, cert_pass)

        if not result.get("success"):
            return err(f"Download failed: {result.get('error', 'Unknown error')}")

        response_xml = result.get("xml_response", "")

        # Extract the NF-e XML from the response
        nfe_xml = _extract_nfe_from_dist_response(response_xml)
        if not nfe_xml:
            # Check if the response has a procNFe or NFe
            nfe_xml = _extract_tag_content(response_xml, "NFe")
            if not nfe_xml:
                nfe_xml = _extract_tag_content(response_xml, "procNFe")

        if not nfe_xml:
            # Return the raw response so user can inspect
            return err("NF-e XML not found in distribution response. "
                       "NF-e may not be available or already downloaded.")

        # Decode base64 if encoded (DNFe uses base64)
        if "<NFe" not in nfe_xml and "<nfeProc" not in nfe_xml:
            try:
                decoded = base64.b64decode(nfe_xml.strip())
                nfe_xml = decoded.decode("utf-8")
            except Exception:
                pass

        # Save to output
        output_dir = os.path.expanduser("~/.openclaw/erpclaw/nfe/xml/downloaded")
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, f"NFe-{chave}.xml")

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(nfe_xml)

        return ok({
            "chave_acesso": chave,
            "xml_path": output_path,
            "xml_size": len(nfe_xml),
            "message": "NF-e XML downloaded successfully from SEFAZ",
        })

    except ImportError:
        return err("sefaz_ws module not available")
    except Exception as e:
        return err(f"Download error: {e}")


def _extract_nfe_from_dist_response(xml: str) -> str | None:
    """Extract the actual NF-e XML from a distribuição DFe response."""
    # Try several extraction methods
    for tag in ["NFe", "nfeProc", "procNFe"]:
        content = _extract_tag_content(xml, tag)
        if content and len(content) > 200:
            return content

    # Try base64 decoding the docZip section
    doc_zip = _extract_tag_content(xml, "docZip")
    if doc_zip:
        try:
            import gzip
            decoded = base64.b64decode(doc_zip.strip())
            decompressed = gzip.decompress(decoded).decode("utf-8")
            return decompressed
        except Exception:
            pass

    return None


# ═══════════════════════════════════════════════════════════════════════
# COMPLEMENTARY NF-e
# ═══════════════════════════════════════════════════════════════════════

def create_nfe_complementar(conn, args):
    """Create a complementary NF-e to adjust values of an existing NF-e.

    Args: --nfe-complementar-id (original NF-e), --company-id
    """
    original_id = args.nfe_complementar_id
    cid = args.company_id
    if not original_id:
        return err("--nfe-complementar-id is required (original NF-e to complement)")
    if not cid:
        return err("--company-id is required")

    # Load original NF-e
    orig = conn.execute(
        "SELECT * FROM br_nfe_out WHERE id = ?", (original_id,)
    ).fetchone()
    if not orig:
        return err(f"Original NF-e not found: {original_id}")

    orig = dict(orig)

    if orig["status"] not in ("autorizado",):
        return err(f"Original NF-e must be 'autorizado', current: {orig['status']}")

    # Get config
    cfg = conn.execute(
        "SELECT * FROM br_nfe_config WHERE company_id = ?", (cid,)
    ).fetchone()
    if not cfg:
        return err(f"No NF-e config for company {cid}")
    cfg = dict(cfg)

    # Load original items
    items = conn.execute(
        "SELECT * FROM br_nfe_out_item WHERE nfe_out_id = ? ORDER BY numero_item",
        (original_id,)
    ).fetchall()
    items = [dict(it) for it in items]

    # Get next number
    nfe_id = str(uuid4())
    numero = cfg.get("proximo_numero", 1)
    chave = _make_chave_for_nfe(cfg, numero, datetime.now(), "55")

    now = datetime.now()
    data_emissao = now.strftime("%Y-%m-%d")

    # Complementary NF-e references original
    info_complementar = f"NF-e Complementar — Referente a NF-e Nº {orig['numero']} Série {orig['serie']}"

    # Insert complementary NF-e
    conn.execute("""
        INSERT INTO br_nfe_out (
            id, chave_acesso, numero, serie, modelo, tipo_operacao,
            data_emissao, data_saida, hora_saida,
            natureza_operacao, cfop_principal, finalidade,
            sales_invoice_id,
            customer_id, customer_name, customer_cnpj, customer_cpf,
            customer_ie, customer_isuf, customer_email,
            info_complementar,
            valor_produtos, valor_total, valor_desconto,
            valor_frete, valor_seguro, outras_despesas,
            base_icms, valor_icms,
            base_ipi, valor_ipi, valor_pis, valor_cofins,
            status, ambiente, company_id,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                  ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        nfe_id, chave, numero, orig["serie"], orig["modelo"], orig["tipo_operacao"],
        data_emissao, data_emissao, "12:00:00",
        orig.get("natureza_operacao", "COMPLEMENTO DE VALOR"),
        orig.get("cfop_principal", "5101"), "complementar",
        orig.get("sales_invoice_id", ""),
        orig.get("customer_id", ""), orig.get("customer_name", ""),
        orig.get("customer_cnpj", ""), orig.get("customer_cpf", ""),
        orig.get("customer_ie", ""), orig.get("customer_isuf", ""),
        orig.get("customer_email", ""),
        info_complementar,
        orig.get("valor_produtos", "0.00"), orig.get("valor_total", "0.00"),
        orig.get("valor_desconto", "0.00"),
        orig.get("valor_frete", "0.00"), orig.get("valor_seguro", "0.00"),
        orig.get("outras_despesas", "0.00"),
        orig.get("base_icms", "0.00"), orig.get("valor_icms", "0.00"),
        orig.get("base_ipi", "0.00"), orig.get("valor_ipi", "0.00"),
        orig.get("valor_pis", "0.00"), orig.get("valor_cofins", "0.00"),
        "rascunho", cfg.get("ambiente", "homologacao"), cid,
        now.isoformat(), now.isoformat(),
    ))

    conn.execute(
        "UPDATE br_nfe_config SET proximo_numero = ?, updated_at = ? WHERE id = ?",
        (numero + 1, now.isoformat(), cfg["id"])
    )

    # Copy items
    for item in items:
        conn.execute("""
            INSERT INTO br_nfe_out_item (
                id, nfe_out_id, numero_item, codigo_produto, descricao,
                ncm, cfop, cst_icms, cst_pis, cst_cofins,
                unidade, quantidade, valor_unitario, valor_total,
                base_icms, aliquota_icms, valor_icms,
                base_ipi, aliquota_ipi, valor_ipi,
                aliquota_pis, valor_pis, aliquota_cofins, valor_cofins,
                company_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            str(uuid4()), nfe_id, item["numero_item"], item.get("codigo_produto", ""),
            item["descricao"], item.get("ncm", ""), item.get("cfop", ""),
            item.get("cst_icms", ""), item.get("cst_pis", ""),
            item.get("cst_cofins", ""),
            item.get("unidade", "UN"), item.get("quantidade", "0.0"),
            item.get("valor_unitario", "0.00"), item.get("valor_total", "0.00"),
            item.get("base_icms", "0.00"), item.get("aliquota_icms", "0.00"),
            item.get("valor_icms", "0.00"),
            item.get("base_ipi", "0.00"), item.get("aliquota_ipi", "0.00"),
            item.get("valor_ipi", "0.00"),
            item.get("aliquota_pis", "0.00"), item.get("valor_pis", "0.00"),
            item.get("aliquota_cofins", "0.00"), item.get("valor_cofins", "0.00"),
            cid,
        ))

    conn.commit()

    return ok({
        "nfe_out_id": nfe_id,
        "chave_acesso": chave,
        "numero": numero,
        "original_nfe_id": original_id,
        "original_numero": orig.get("numero"),
        "status": "rascunho",
        "message": f"Complementary NF-e {numero} created, referencing NF-e {orig.get('numero')}",
    })


# ═══════════════════════════════════════════════════════════════════════
# RETURN NF-e (DEVOLUÇÃO)
# ═══════════════════════════════════════════════════════════════════════

def create_nfe_devolucao(conn, args):
    """Create a return NF-e (devolução) referencing an original NF-e.

    Uses CFOP for devolution based on direction.

    Args: --nfe-out-id (original NF-e to return), --company-id
    """
    original_id = args.nfe_out_id or args.nfe_complementar_id
    cid = args.company_id
    if not original_id:
        return err("--nfe-out-id is required (original NF-e being returned)")
    if not cid:
        return err("--company-id is required")

    # Load original NF-e
    orig = conn.execute(
        "SELECT * FROM br_nfe_out WHERE id = ?", (original_id,)
    ).fetchone()
    if not orig:
        # Maybe an imported NF-e
        row = conn.execute(
            "SELECT * FROM nfe_import WHERE id = ?", (original_id,)
        ).fetchone()
        if not row:
            return err(f"Original NF-e not found: {original_id}")
        orig = dict(row)

    orig = dict(orig)

    if orig["status"] not in ("autorizado", "imported", "posted", "validated"):
        return err(f"Original NF-e must be authorized/validated before devolution. Current: {orig['status']}")

    # Get config
    cfg = conn.execute(
        "SELECT * FROM br_nfe_config WHERE company_id = ?", (cid,)
    ).fetchone()
    if not cfg:
        return err(f"No NF-e config for company {cid}")
    cfg = dict(cfg)

    # Determine CFOP for devolução
    # If the original is a purchase (entry), devolution uses CFOP 5.203/6.203
    # If it's a sale, devolution uses CFOP 1.203/2.203
    is_imported = "nfe_import" in str(type(orig))
    cfop_devol = "5203" if is_imported else "1203"  # internal devolução

    # Get next number
    nfe_id = str(uuid4())
    numero = cfg.get("proximo_numero", 1)
    chave = _make_chave_for_nfe(cfg, numero, datetime.now(), "55")

    now = datetime.now()
    data_emissao = now.strftime("%Y-%m-%d")

    customer_id = orig.get("customer_id", "")
    customer_name = orig.get("customer_name", "")
    customer_cnpj = orig.get("customer_cnpj", "")
    customer_cpf = orig.get("customer_cpf", "")
    customer_ie = orig.get("customer_ie", "")
    customer_isuf = orig.get("customer_isuf", "")
    customer_email = orig.get("customer_email", "")

    # For devolução of entry NF-e, the roles are reversed
    if is_imported:
        # We're returning to the supplier, so emitente becomes customer
        customer_name = orig.get("emitente_nome", "")
        customer_cnpj = orig.get("emitente_cnpj", "")
        customer_ie = orig.get("emitente_ie", "")

    info_complementar = (f"NF-e de Devolução (CFOP {cfop_devol}) — "
                         f"Referente a NF-e Nº {orig.get('numero', orig.get('numero_nfe', ''))}")

    valor_produtos = orig.get("valor_produtos", "0.00")
    valor_total = orig.get("valor_total", "0.00")
    valor_icms = orig.get("valor_icms", "0.00")

    conn.execute("""
        INSERT INTO br_nfe_out (
            id, chave_acesso, numero, serie, modelo, tipo_operacao,
            data_emissao, data_saida, hora_saida,
            natureza_operacao, cfop_principal, finalidade,
            customer_id, customer_name, customer_cnpj, customer_cpf,
            customer_ie, customer_isuf, customer_email,
            info_complementar,
            valor_produtos, valor_total, valor_desconto,
            valor_frete, valor_seguro, outras_despesas,
            base_icms, valor_icms,
            base_ipi, valor_ipi, valor_pis, valor_cofins,
            status, ambiente, company_id,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                  ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        nfe_id, chave, numero, "1", "55", "saida",
        data_emissao, data_emissao, "12:00:00",
        f"DEVOLUÇÃO DE MERCADORIA — CFOP {cfop_devol}",
        cfop_devol, "devolucao",
        customer_id, customer_name, customer_cnpj, customer_cpf,
        customer_ie, customer_isuf, customer_email,
        info_complementar,
        valor_produtos, valor_total, "0.00",
        "0.00", "0.00", "0.00",
        valor_produtos, valor_icms,
        valor_produtos, "0.00", "0.00", "0.00",
        "rascunho", cfg.get("ambiente", "homologacao"), cid,
        now.isoformat(), now.isoformat(),
    ))

    conn.execute(
        "UPDATE br_nfe_config SET proximo_numero = ?, updated_at = ? WHERE id = ?",
        (numero + 1, now.isoformat(), cfg["id"])
    )

    conn.commit()

    return ok({
        "nfe_out_id": nfe_id,
        "chave_acesso": chave,
        "numero": numero,
        "cfop": cfop_devol,
        "original_nfe_id": original_id,
        "status": "rascunho",
        "message": f"Return NF-e {numero} created (CFOP {cfop_devol})",
    })


# ═══════════════════════════════════════════════════════════════════════
# CONTINGENCY NF-e (OFFLINE)
# ═══════════════════════════════════════════════════════════════════════

def create_nfe_contingencia(conn, args):
    """Create an NF-e in contingency mode (offline).

    When SEFAZ webservices are unavailable, NF-e can be emitted
    offline and transmitted later (FS-DA or DPEC format).

    Args: --company-id, --sales-invoice-id
    """
    cid = args.company_id
    si_id = args.sales_invoice_id
    if not cid or not si_id:
        return err("--company-id and --sales-invoice-id are required")

    # Get config
    cfg = conn.execute(
        "SELECT * FROM br_nfe_config WHERE company_id = ?", (cid,)
    ).fetchone()
    if not cfg:
        return err(f"No NF-e config for company {cid}")
    cfg = dict(cfg)

    # Get next number
    nfe_id = str(uuid4())
    numero = cfg.get("proximo_numero", 1)
    now = datetime.now()
    data_emissao = now.strftime("%Y-%m-%d")

    # For contingency mode, use a special chave with tpEmis=9
    # tpEmis: 1=normal, 2=FS, 3=SCAN, 4=DPEC, 5=FSDA, 7=SVC-AN, 8=SVC-RS, 9=offline
    uf_cod = codigo_uf(cfg.get("uf", "SP"))
    ano_mes = now.strftime("%y%m")
    cnpj_clean = "00000000000000"  # will be replaced
    comp = conn.execute(
        "SELECT tax_id FROM company WHERE id = ?", (cid,)
    ).fetchone()
    if comp and comp["tax_id"]:
        cnpj_clean = _clean_cnpj(comp["tax_id"])

    num_str = str(numero).zfill(9)
    mod = "55"
    serie = cfg.get("serie_default", "1").zfill(3)
    tp_emis = "9"  # contingency offline

    chave_base = f"{uf_cod}{ano_mes}{cnpj_clean[:14]}{mod}{serie}{num_str}{tp_emis}"
    dv = _calc_dv_mod11(chave_base)
    chave = f"{chave_base}{dv}"

    info_complementar = (f"NF-e EMITIDA EM CONTINGÊNCIA OFFLINE — "
                         f"tpEmis=9 — Transmitir quando serviços SEFAZ estiverem disponíveis")

    # Load sales invoice
    si = conn.execute(
        "SELECT * FROM sales_invoice WHERE id = ?", (si_id,)
    ).fetchone()
    if not si:
        return err(f"Sales invoice not found: {si_id}")
    si = dict(si)

    customer = None
    if si.get("customer_id"):
        customer = conn.execute(
            "SELECT * FROM customer WHERE id = ? AND company_id = ?",
            (si["customer_id"], cid)
        ).fetchone()
    if customer:
        customer = dict(customer)

    customer_name = customer.get("name", "") if customer else ""
    customer_cnpj = ""
    customer_cpf = ""
    if customer:
        tax_id = customer.get("tax_id", "") or ""
        tax_digits = "".join(ch for ch in tax_id if ch.isdigit())
        if len(tax_digits) == 14:
            customer_cnpj = tax_digits
        elif len(tax_digits) == 11:
            customer_cpf = tax_digits

    # Calculate item totals
    items = conn.execute("""
        SELECT sii.*, i.name as item_name
        FROM sales_invoice_item sii
        JOIN item i ON i.id = sii.item_id
        WHERE sii.sales_invoice_id = ?
        ORDER BY sii.line_number
    """, (si_id,)).fetchall()

    total_produtos = Decimal("0")
    for it in items:
        rd = dict(it)
        qty = Decimal(str(rd.get("quantity", "1")))
        price = Decimal(str(rd.get("unit_price", "0")))
        total_produtos += qty * price

    valor_total = str(total_produtos)

    conn.execute("""
        INSERT INTO br_nfe_out (
            id, chave_acesso, numero, serie, modelo, tipo_operacao,
            data_emissao, data_saida, hora_saida,
            natureza_operacao, cfop_principal, finalidade,
            sales_invoice_id,
            customer_id, customer_name, customer_cnpj, customer_cpf,
            info_complementar,
            valor_produtos, valor_total, valor_desconto,
            valor_frete, valor_seguro, outras_despesas,
            base_icms, valor_icms,
            base_ipi, valor_ipi, valor_pis, valor_cofins,
            status, ambiente, company_id,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                  ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        nfe_id, chave, numero, serie, mod, "saida",
        data_emissao, data_emissao, "12:00:00",
        si.get("description", "VENDA DE MERCADORIA — CONTINGÊNCIA"),
        "5102", "normal",  # NOTE: contingency NF-e may need special finalidade
        si_id,
        customer.get("id", "") if customer else "",
        customer_name, customer_cnpj, customer_cpf,
        info_complementar,
        str(total_produtos), valor_total, "0.00",
        "0.00", "0.00", "0.00",
        str(total_produtos), str(round(total_produtos * Decimal("0.18"), 2)),
        str(total_produtos), "0.00", "0.00", "0.00",
        "rascunho", cfg.get("ambiente", "homologacao"), cid,
        now.isoformat(), now.isoformat(),
    ))

    conn.execute(
        "UPDATE br_nfe_config SET proximo_numero = ?, updated_at = ? WHERE id = ?",
        (numero + 1, now.isoformat(), cfg["id"])
    )

    conn.commit()

    return ok({
        "nfe_out_id": nfe_id,
        "chave_acesso": chave,
        "numero": numero,
        "tp_emis": "9",
        "status": "rascunho",
        "message": f"Contingency NF-e {numero} created (offline mode — tpEmis=9). "
                   f"Transmit when SEFAZ is available.",
    })


# ═══════════════════════════════════════════════════════════════════════
# EXPORT NF-e XML (with DI/RE)
# ═══════════════════════════════════════════════════════════════════════

def gerar_xml_nfe_exportacao(conn, args):
    """Generate NF-e XML for export (with DI/RE — Drawback).

    Args: --company-id, --sales-invoice-id, --di-numero, --di-data
    """
    cid = args.company_id
    si_id = args.sales_invoice_id
    if not cid or not si_id:
        return err("--company-id and --sales-invoice-id are required")

    # Load sales invoice
    si = conn.execute(
        "SELECT * FROM sales_invoice WHERE id = ? AND company_id = ?",
        (si_id, cid)
    ).fetchone()
    if not si:
        return err(f"Sales invoice not found: {si_id}")
    si = dict(si)

    # Get config
    cfg = conn.execute(
        "SELECT * FROM br_nfe_config WHERE company_id = ?", (cid,)
    ).fetchone()
    if not cfg:
        return err(f"No NF-e config for company {cid}")
    cfg = dict(cfg)

    # Get company data
    comp = conn.execute(
        "SELECT * FROM company WHERE id = ?", (cid,)
    ).fetchone()
    comp = dict(comp) if comp else {}
    cnpj_emit = _clean_cnpj(comp.get("tax_id", "00000000000000"))

    # Company fiscal data
    fiscal = conn.execute(
        "SELECT * FROM company_fiscal WHERE company_id = ?", (cid,)
    ).fetchone()
    fiscal = dict(fiscal) if fiscal else {}

    # Customer data
    customer_id = si.get("customer_id", "")
    customer = None
    if customer_id:
        customer = conn.execute(
            "SELECT * FROM customer WHERE id = ?", (customer_id,)
        ).fetchone()
    customer = dict(customer) if customer else {}

    # DI/RE data
    di_numero = args.di_numero or ""
    di_data = args.di_data or ""

    nfe_id = str(uuid4())
    numero = cfg.get("proximo_numero", 1)
    chave = _make_chave_for_nfe(cfg, numero, datetime.now(), "55")

    now = datetime.now()
    data_emissao = now.strftime("%Y-%m-%d")

    # Export CFOP entries (7.101, 7.102, etc.)
    cfop = "7101"
    uf_dest = "EX"

    info_complementar = "NF-e de Exportação"
    if di_numero:
        info_complementar += f" — DI Nº {di_numero}"
        if di_data:
            info_complementar += f" — Data DI: {di_data}"

    # Calculate items
    items = conn.execute("""
        SELECT sii.*, i.name as item_name
        FROM sales_invoice_item sii
        JOIN item i ON i.id = sii.item_id
        WHERE sii.sales_invoice_id = ?
        ORDER BY sii.line_number
    """, (si_id,)).fetchall()

    total_produtos = Decimal("0")
    for it in items:
        rd = dict(it)
        qty = Decimal(str(rd.get("quantity", "1")))
        price = Decimal(str(rd.get("unit_price", "0")))
        total_produtos += qty * price

    valor_total = str(total_produtos)

    conn.execute("""
        INSERT INTO br_nfe_out (
            id, chave_acesso, numero, serie, modelo, tipo_operacao,
            data_emissao, data_saida, hora_saida,
            natureza_operacao, cfop_principal, finalidade,
            sales_invoice_id,
            customer_id, customer_name, customer_cnpj, customer_cpf,
            info_complementar,
            valor_produtos, valor_total, valor_desconto,
            valor_frete, valor_seguro, outras_despesas,
            base_icms, valor_icms,
            base_ipi, valor_ipi, valor_pis, valor_cofins, valor_ii,
            status, ambiente, company_id,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                  ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        nfe_id, chave, numero, "1", "55", "saida",
        data_emissao, data_emissao, "12:00:00",
        "EXPORTAÇÃO DE PRODUTOS",
        cfop, "normal",
        si_id,
        customer_id, customer.get("name", ""), "", "",
        info_complementar,
        str(total_produtos), valor_total, "0.00",
        "0.00", "0.00", "0.00",
        "0.00", "0.00",  # ICMS exempt for export
        str(total_produtos), "0.00", "0.00", "0.00", "0.00",  # IPI exempt for export
        "rascunho", cfg.get("ambiente", "homologacao"), cid,
        now.isoformat(), now.isoformat(),
    ))

    # Store items with export CFOP
    for idx, it in enumerate(items):
        rd = dict(it)
        qty = Decimal(str(rd.get("quantity", "1")))
        price = Decimal(str(rd.get("unit_price", "0")))
        total = qty * price

        conn.execute("""
            INSERT INTO br_nfe_out_item (
                id, nfe_out_id, numero_item, codigo_produto, descricao,
                ncm, cfop, cst_icms, cst_pis, cst_cofins,
                unidade, quantidade, valor_unitario, valor_total,
                base_icms, aliquota_icms, valor_icms,
                base_ipi, aliquota_ipi, valor_ipi,
                aliquota_pis, valor_pis, aliquota_cofins, valor_cofins,
                company_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            str(uuid4()), nfe_id, idx + 1,
            rd.get("item_id", ""), rd.get("item_name", rd.get("description", "")),
            "", cfop, "", "", "",
            "UN", str(qty), str(price), str(total),
            "0.00", "0.00", "0.00",
            "0.00", "0.00", "0.00",
            "0.00", "0.00", "0.00", "0.00",
            cid,
        ))

    conn.execute(
        "UPDATE br_nfe_config SET proximo_numero = ?, updated_at = ? WHERE id = ?",
        (numero + 1, now.isoformat(), cfg["id"])
    )

    conn.commit()

    return ok({
        "nfe_out_id": nfe_id,
        "chave_acesso": chave,
        "numero": numero,
        "cfop": cfop,
        "di_numero": di_numero,
        "di_data": di_data,
        "status": "rascunho",
        "message": f"Export NF-e {numero} created (CFOP {cfop}, DI {di_numero})",
    })


# ═══════════════════════════════════════════════════════════════════════
# DANFE PDF GENERATION
# ═══════════════════════════════════════════════════════════════════════

def imprimir_danfe_pdf(conn, args):
    """Generate DANFE as PDF for a given NF-e.

    Tries weasyprint first (best quality), then reportlab (fallback),
    then pure HTML (always available).

    Args: --nfe-out-id, --danfe-output (optional)
    """
    nfe_id = args.nfe_out_id
    if not nfe_id:
        return err("--nfe-out-id is required")

    row = conn.execute("SELECT * FROM br_nfe_out WHERE id = ?", (nfe_id,)).fetchone()
    if not row:
        return err(f"NF-e not found: {nfe_id}")

    nfe = dict(row)

    # Build DANFE HTML (reuse the generator from nfe_emission)
    danfe_html = _generate_danfe_html_full(nfe)

    # Determine output path
    output_path = getattr(args, "danfe_output", None)
    if not output_path:
        output_dir = os.path.expanduser("~/.openclaw/erpclaw/nfe/danfe")
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, f"DANFE-NFe-{nfe['numero']}.pdf")

    pdf_generated = False
    result_format = "html"

    # Try weasyprint first (best quality PDF from HTML)
    if HAS_WEASYPRINT and output_path.endswith(".pdf"):
        try:
            weasyprint.HTML(string=danfe_html).write_pdf(output_path)
            pdf_generated = True
            result_format = "pdf"
        except Exception as e:
            # Fall through to reportlab
            pass

    # Try reportlab as fallback
    if not pdf_generated and HAS_REPORTLAB and output_path.endswith(".pdf"):
        try:
            _generate_danfe_reportlab_pdf(nfe, output_path)
            pdf_generated = True
            result_format = "pdf_reportlab"
        except Exception as e:
            pass

    # HTML fallback
    if not pdf_generated:
        if output_path.endswith(".pdf"):
            output_path = output_path.replace(".pdf", ".html")
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(danfe_html)
        result_format = "html"

    # Update DB
    now = datetime.now().isoformat()
    conn.execute(
        "UPDATE br_nfe_out SET danfe_path = ?, updated_at = ? WHERE id = ?",
        (output_path, now, nfe_id)
    )
    conn.commit()

    return ok({
        "nfe_out_id": nfe_id,
        "chave_acesso": nfe["chave_acesso"],
        "danfe_path": output_path,
        "format": result_format,
        "weasyprint_available": HAS_WEASYPRINT,
        "reportlab_available": HAS_REPORTLAB,
        "message": f"DANFE generated as {result_format.upper()}",
    })


# ═══════════════════════════════════════════════════════════════════════
# DANFE HTML generation (full layout)
# ═══════════════════════════════════════════════════════════════════════

def _generate_danfe_html_full(nfe: dict) -> str:
    """Generate a full DANFE HTML layout following SEFAZ standard.

    4 sections: Header, Products, Totals, Footer + Barcode.
    """
    nfe_numero = str(nfe.get("numero", ""))
    nfe_serie = str(nfe.get("serie", "1"))
    chave = str(nfe.get("chave_acesso", ""))
    chave_fmt = _format_chave_nfe(chave)
    protocolo = str(nfe.get("protocolo") or "—")
    data_emissao = str(nfe.get("data_emissao", ""))
    data_saida = str(nfe.get("data_saida") or data_emissao)
    nat_op = str(nfe.get("natureza_operacao", ""))

    # Format CNPJ
    cnpj_emit_raw = _clean_cnpj("")
    comp_cnpj = ""
    try:
        comp_cnpj = _clean_cnpj(str(nfe.get("customer_cnpj", "")))
    except Exception:
        pass
    if comp_cnpj and len(comp_cnpj) == 14:
        cnpj_emit_raw = comp_cnpj

    cnpj_emit_fmt = ""
    if len(cnpj_emit_raw) == 14:
        cnpj_emit_fmt = f"{cnpj_emit_raw[:2]}.{cnpj_emit_raw[2:5]}.{cnpj_emit_raw[5:8]}/{cnpj_emit_raw[8:12]}-{cnpj_emit_raw[12:14]}"

    customer_name = str(nfe.get("customer_name", ""))
    customer_cnpj = str(nfe.get("customer_cnpj", ""))
    customer_ie = str(nfe.get("customer_ie", ""))

    if len(customer_cnpj) == 14:
        customer_cnpj = f"{customer_cnpj[:2]}.{customer_cnpj[2:5]}.{customer_cnpj[5:8]}/{customer_cnpj[8:12]}-{customer_cnpj[12:14]}"

    # Values
    v_prod = str(nfe.get("valor_produtos", "0.00"))
    v_bc_icms = str(nfe.get("base_icms", "0.00"))
    v_icms = str(nfe.get("valor_icms", "0.00"))
    v_bc_st = str(nfe.get("base_icms_st", "0.00"))
    v_st = str(nfe.get("valor_icms_st", "0.00"))
    v_frete = str(nfe.get("valor_frete", "0.00"))
    v_seguro = str(nfe.get("valor_seguro", "0.00"))
    v_desc = str(nfe.get("valor_desconto", "0.00"))
    v_ipi = str(nfe.get("valor_ipi", "0.00"))
    v_outras = str(nfe.get("outras_despesas", "0.00"))
    v_total = str(nfe.get("valor_total", "0.00"))

    status = str(nfe.get("status", ""))
    status_class = f"status-{status}"

    info = str(nfe.get("info_complementar", ""))

    # Build DANFE HTML
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<title>DANFE — NF-e {nfe_numero}</title>
<style>
  @page {{ size: A4; margin: 5mm; }}
  body {{ font-family: "Courier New", monospace; margin: 0; padding: 5mm; font-size: 8pt; }}
  .header {{ text-align: center; border: 1px solid #000; padding: 3mm; margin-bottom: 2mm; }}
  .title {{ font-size: 14pt; font-weight: bold; }}
  .subtitle {{ font-size: 9pt; margin-top: 1mm; }}
  .section {{ border: 1px solid #000; margin-bottom: 2mm; }}
  .section-title {{ background: #ccc; padding: 1mm 3mm; font-weight: bold; font-size: 8pt; }}
  .row {{ display: flex; border-bottom: 1px solid #000; }}
  .col {{ flex: 1; padding: 1mm 2mm; border-right: 1px solid #000; }}
  .col:last-child {{ border-right: none; }}
  .col-2 {{ flex: 2; }}
  .col-3 {{ flex: 3; }}
  .label {{ font-size: 6pt; color: #666; }}
  .value {{ font-size: 9pt; font-weight: bold; }}
  .right {{ text-align: right; }}
  .center {{ text-align: center; }}
  .chave {{ font-family: "Courier New", monospace; letter-spacing: 2px; font-size: 10pt; }}
  .barcode {{ text-align: center; border: 1px dashed #000; padding: 3mm; margin: 2mm 0; }}
  .barcode-text {{ font-family: "Libre Barcode 39", "Courier New", monospace; font-size: 32pt; }}
  .protocolo {{ background: #f0f0f0; padding: 2mm; }}
  .total-row {{ background: #eee; font-weight: bold; }}
  .footer {{ text-align: center; font-size: 7pt; margin-top: 2mm; }}
  .status-badge {{ display: inline-block; padding: 1mm 4mm; font-weight: bold; font-size: 9pt; }}
  .status-rascunho {{ background: #e0e0e0; }}
  .status-autorizado {{ background: #d4edda; color: #155724; }}
  .status-cancelado {{ background: #f8d7da; color: #721c24; }}
  .status-enviado {{ background: #fff3cd; color: #856404; }}

  table {{ width: 100%; border-collapse: collapse; }}
  th, td {{ border: 1px solid #000; padding: 1mm 2mm; font-size: 7pt; }}
  th {{ background: #eee; text-align: center; }}
</style>
</head>
<body>

<!-- SECTION 1: HEADER -->
<div class="header">
  <div class="title">DANFE</div>
  <div class="subtitle">Documento Auxiliar da Nota Fiscal Eletrônica</div>
  <div style="margin-top:2mm; font-size:8pt;">
    <strong>NF-e Nº {nfe_numero} — Série {nfe_serie}</strong> &nbsp;|&nbsp;
    <strong>Data Emissão:</strong> {data_emissao} &nbsp;|&nbsp;
    <span class="status-badge {status_class}">{status.upper()}</span>
  </div>
</div>

<!-- CHAVE DE ACESSO -->
<div class="section">
  <div class="section-title">Chave de Acesso</div>
  <div class="row">
    <div class="col center chave">{chave_fmt}</div>
  </div>
</div>

<!-- EMITENTE / DESTINATÁRIO -->
<div class="section">
  <div class="section-title">Emitente</div>
  <div class="row">
    <div class="col col-2"><span class="label">CNPJ</span><br><span class="value">{cnpj_emit_fmt}</span></div>
    <div class="col col-2"><span class="label">Inscrição Estadual</span><br><span class="value">{nfe.get('customer_ie', '—')}</span></div>
    <div class="col"><span class="label">Natureza Operação</span><br><span class="value">{nat_op}</span></div>
  </div>
</div>

<div class="section">
  <div class="section-title">Destinatário / Remetente</div>
  <div class="row">
    <div class="col col-3"><span class="label">Nome / Razão Social</span><br><span class="value">{customer_name}</span></div>
    <div class="col"><span class="label">CNPJ</span><br><span class="value">{customer_cnpj}</span></div>
    <div class="col"><span class="label">IE</span><br><span class="value">{customer_ie}</span></div>
  </div>
  <div class="row">
    <div class="col"><span class="label">Data Emissão</span><br><span class="value">{data_emissao}</span></div>
    <div class="col"><span class="label">Data Saída</span><br><span class="value">{data_saida}</span></div>
    <div class="col"><span class="label">CFOP</span><br><span class="value">{nfe.get('cfop_principal', '')}</span></div>
    <div class="col"><span class="label">Finalidade</span><br><span class="value">{nfe.get('finalidade', '')}</span></div>
  </div>
</div>

<!-- SECTION 2: PRODUTOS (simplified) -->
<div class="section">
  <div class="section-title">Produtos / Serviços</div>
  <div><em style="font-size:7pt; padding:1mm 3mm;">(Detalhamento na cópia completa da NF-e)</em></div>
</div>

<!-- SECTION 3: TOTALS -->
<div class="section">
  <div class="section-title">Cálculo do Imposto</div>
  <div class="row">
    <div class="col"><span class="label">Base de Cálculo ICMS</span><br><span class="value right">R$ {v_bc_icms}</span></div>
    <div class="col"><span class="label">Valor ICMS</span><br><span class="value right">R$ {v_icms}</span></div>
    <div class="col"><span class="label">Base ICMS ST</span><br><span class="value right">R$ {v_bc_st}</span></div>
    <div class="col"><span class="label">Valor ICMS ST</span><br><span class="value right">R$ {v_st}</span></div>
  </div>
  <div class="row">
    <div class="col"><span class="label">Valor Frete</span><br><span class="value right">R$ {v_frete}</span></div>
    <div class="col"><span class="label">Valor Seguro</span><br><span class="value right">R$ {v_seguro}</span></div>
    <div class="col"><span class="label">Desconto</span><br><span class="value right">R$ {v_desc}</span></div>
    <div class="col"><span class="label">Outras Despesas</span><br><span class="value right">R$ {v_outras}</span></div>
  </div>
  <div class="row">
    <div class="col"><span class="label">Valor IPI</span><br><span class="value right">R$ {v_ipi}</span></div>
    <div class="col"><span class="label">Valor Produtos</span><br><span class="value right">R$ {v_prod}</span></div>
    <div class="col col-2 total-row"><span class="label">VALOR TOTAL DA NOTA</span><br><span class="value right" style="font-size:12pt;">R$ {v_total}</span></div>
  </div>
</div>

<!-- PROTOCOLO -->
<div class="section protocolo">
  <div class="section-title">Protocolo de Autorização de Uso</div>
  <div class="row">
    <div class="col center">
      <span class="label">Nº Protocolo</span><br>
      <span class="value">{protocolo}</span>
    </div>
  </div>
</div>

<!-- SECTION 4: FOOTER + BARCODE -->
<div class="barcode">
  <div class="barcode-text">{chave[:43] if len(chave) >= 43 else chave}</div>
  <span class="label">Representação Gráfica da Chave de Acesso</span>
</div>

<!-- INFORMACOES COMPLEMENTARES -->
<div class="section">
  <div class="section-title">Informações Complementares</div>
  <div class="row">
    <div class="col" style="padding:2mm 3mm; font-size:7pt;">{info or '—'}</div>
  </div>
</div>

<div class="footer">
  Documento gerado por ERPClaw Region BR — DANFE Generator v1.5.0 | NF-e Nº {nfe_numero} | {data_emissao}
</div>

</body>
</html>"""


def _generate_danfe_reportlab_pdf(nfe: dict, output_path: str):
    """Generate DANFE PDF using ReportLab."""
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(
        output_path, pagesize=A4,
        leftMargin=10*mm, rightMargin=10*mm,
        topMargin=10*mm, bottomMargin=10*mm
    )

    elements = []

    # Title
    title_style = ParagraphStyle(
        "DANFE_Title", parent=styles["Title"],
        fontSize=16, alignment=1, spaceAfter=4*mm
    )
    elements.append(Paragraph("DANFE — Documento Auxiliar da NF-e", title_style))

    # NF-e info
    nfe_num = str(nfe.get("numero", ""))
    nfe_data = str(nfe.get("data_emissao", ""))

    info_style = ParagraphStyle(
        "Info", parent=styles["Normal"],
        fontSize=9, alignment=1, spaceAfter=2*mm
    )
    elements.append(Paragraph(
        f"NF-e Nº {nfe_num} — Data: {nfe_data} — Status: {nfe.get('status', '').upper()}",
        info_style
    ))

    # Section 1: Emission data
    data = [
        ["Dados da NF-e", ""],
        ["Chave de Acesso", nfe.get("chave_acesso", "")],
        ["Natureza da Operação", nfe.get("natureza_operacao", "")],
        ["Protocolo", nfe.get("protocolo", "—")],
        ["Destinatário", nfe.get("customer_name", "")],
        ["CNPJ Destinatário", nfe.get("customer_cnpj", "")],
    ]

    table = Table(data, colWidths=[50*mm, 120*mm])
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Courier"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("FONTSIZE", (0, 0), (0, 0), 10),
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("SPAN", (0, 0), (-1, 0)),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(table)
    elements.append(Spacer(1, 5*mm))

    # Section 2: Values
    data_totals = [
        ["Totais", ""],
        ["Valor Produtos", f"R$ {nfe.get('valor_produtos', '0.00')}"],
        ["Valor ICMS", f"R$ {nfe.get('valor_icms', '0.00')}"],
        ["Valor IPI", f"R$ {nfe.get('valor_ipi', '0.00')}"],
        ["Desconto", f"R$ {nfe.get('valor_desconto', '0.00')}"],
        ["VALOR TOTAL", f"R$ {nfe.get('valor_total', '0.00')}"],
    ]

    table2 = Table(data_totals, colWidths=[50*mm, 120*mm])
    table2.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Courier"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("FONTSIZE", (0, 0), (0, 0), 10),
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("SPAN", (0, 0), (-1, 0)),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("FONTNAME", (0, 5), (-1, 5), "Courier-Bold"),
    ]))
    elements.append(table2)
    elements.append(Spacer(1, 5*mm))

    # Section 3: Footer
    footer_style = ParagraphStyle(
        "Footer", parent=styles["Normal"],
        fontSize=7, alignment=1
    )
    elements.append(Paragraph(
        f"Documento gerado por ERPClaw Region BR — DANFE v1.5.0",
        footer_style
    ))

    doc.build(elements)


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════

def _format_chave_nfe(chave: str) -> str:
    """Format 44-char chave_acesso with spaces."""
    if len(chave) < 44:
        return chave
    parts = [chave[i:i+4] for i in range(0, 44, 4)]
    return " ".join(parts)


def _extract_cnpj_from_chave(chave: str) -> str:
    """Extract CNPJ from chave de acesso (positions 7-20)."""
    if len(chave) >= 20:
        return chave[6:20]
    return "00000000000000"


def _extract_tag_content(xml_text: str, tag: str) -> str | None:
    """Extract content between a full XML tag (including nested content)."""
    open_tag = f"<{tag}>"
    open_tag_attrs = f"<{tag} "
    close_tag = f"</{tag}>"

    start = xml_text.find(open_tag_attrs)
    if start < 0:
        start = xml_text.find(open_tag)
    if start < 0:
        return None

    if xml_text[start:start + len(open_tag_attrs)] == open_tag_attrs:
        # Has attributes — find >
        gt = xml_text.find(">", start)
        if gt < 0:
            return None
        start = gt + 1
    else:
        start += len(open_tag)

    # Find matching close tag
    end = xml_text.find(close_tag, start)
    if end < 0:
        return None

    return xml_text[start:end]


def _make_chave_for_nfe(cfg: dict, numero: int, now: datetime, modelo: str) -> str:
    """Generate a chave_acesso for NF-e."""
    uf_cod = codigo_uf(cfg.get("uf", "SP"))
    ano_mes = now.strftime("%y%m")
    cnpj_clean = "00000000000000"
    num_str = str(numero).zfill(9)
    serie = cfg.get("serie_default", "1").zfill(3)
    tp_emis = cfg.get("tipo_emissao", "normal")
    tp_emis_code = "1" if tp_emis == "normal" else "9"
    cod_num = "00000001"  # random code

    chave_base = f"{uf_cod}{ano_mes}{cnpj_clean}{modelo}{serie}{num_str}{tp_emis_code}{cod_num}"
    dv = _calc_dv_mod11(chave_base)
    return f"{chave_base}{dv}"


# ═══════════════════════════════════════════════════════════════════════
# ACTIONS — Wired into db_query.py
# ═══════════════════════════════════════════════════════════════════════

ACTIONS = {
    "manifestar-nfe": manifestar_nfe,
    "download-nfe-xml": download_nfe_xml,
    "create-nfe-complementar": create_nfe_complementar,
    "create-nfe-devolucao": create_nfe_devolucao,
    "create-nfe-contingencia": create_nfe_contingencia,
    "gerar-xml-nfe-exportacao": gerar_xml_nfe_exportacao,
    "imprimir-danfe-pdf": imprimir_danfe_pdf,
}
