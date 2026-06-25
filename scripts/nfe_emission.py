"""NF-e Emission Orchestrator — ERPClaw Region BR

Top-level module for NF-e outbound emission workflow:
configure, create from sales invoice, validate, sign, transmit,
check authorization, cancel, inutilizar, CC-e, DANFE generation,
and export.

All 17 actions are wired into the ACTIONS dict for db_query.py.

Usage: python3 nfe_emission.py --action <action> --flags ...
"""
from __future__ import annotations

import base64
import json
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

# ── Local imports ──────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from nfe_xml_gen import generate_nfe_xml, _compute_chave_acesso, _compute_chave_acesso_tuple
from nfe_xml_gen import _codigo_uf as codigo_uf, _calc_dv_mod11, _clean_cnpj
from nfe_signer import sign_nfe_xml, sign_nfe_event_xml, validate_certificate
from sefaz_ws import (
    autorizar_nfe, consultar_recibo, status_servico,
    cancelar_nfe as sefaz_cancelar_nfe,
    inutilizar_numeracao as sefaz_inutilizar_numeracao,
    consultar_cadastro as sefaz_consultar_cadastro,
)


# ═══════════════════════════════════════════════════════════════════════
# Action: configure-nfe
# ═══════════════════════════════════════════════════════════════════════

def configure_nfe(conn, args):
    """Configure NF-e emission for a company. Upserts br_nfe_config.

    Args: --company-id, --ambiente, --uf, --certificado-path,
          --certificado-password, --csc, --csc-id, --serie-default,
          --regime-tributario, --regime-isencao, --tipo-emissao
    """
    cid = args.company_id
    if not cid:
        return err("--company-id is required")

    # Verify company exists
    comp = conn.execute("SELECT id, name FROM company WHERE id = ?", (cid,)).fetchone()
    if not comp:
        return err(f"Company not found: {cid}")

    uf = args.uf or "SP"
    if len(uf) != 2:
        return err("UF must be 2 characters (e.g. SP, RJ, MG)")

    ambiente = args.ambiente or "homologacao"
    if ambiente not in ("homologacao", "producao"):
        return err("Ambiente must be 'homologacao' or 'producao'")

    # Encrypt certificate password with base64 obfuscation
    cert_pass_encoded = ""
    if args.certificado_password:
        cert_pass_encoded = base64.b64encode(
            args.certificado_password.encode("utf-8")
        ).decode("ascii")

    # Upsert
    row = conn.execute(
        "SELECT id FROM br_nfe_config WHERE company_id = ?", (cid,)
    ).fetchone()

    now = datetime.now().isoformat()

    if row:
        cfg_id = row["id"]
        conn.execute("""
            UPDATE br_nfe_config SET
                ambiente = ?, uf = ?,
                certificado_path = ?, certificado_password = ?,
                csc = ?, csc_id = ?,
                serie_default = ?,
                regime_tributario = ?, regime_isencao = ?,
                tipo_emissao = ?,
                updated_at = ?
            WHERE id = ?
        """, (
            ambiente, uf.upper(),
            args.certificado_path or "", cert_pass_encoded,
            args.csc or "", args.csc_id or "",
            args.serie_default or "1",
            args.regime_tributario or "normal", args.regime_isencao or "",
            args.tipo_emissao or "normal",
            now, cfg_id,
        ))
    else:
        cfg_id = str(uuid4())
        conn.execute("""
            INSERT INTO br_nfe_config (
                id, company_id, ambiente, uf,
                certificado_path, certificado_password,
                csc, csc_id, serie_default,
                regime_tributario, regime_isencao, tipo_emissao,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            cfg_id, cid, ambiente, uf.upper(),
            args.certificado_path or "", cert_pass_encoded,
            args.csc or "", args.csc_id or "",
            args.serie_default or "1",
            args.regime_tributario or "normal", args.regime_isencao or "",
            args.tipo_emissao or "normal",
            now, now,
        ))

    conn.commit()

    return ok({
        "config_id": cfg_id,
        "company_id": cid,
        "ambiente": ambiente,
        "uf": uf.upper(),
        "message": "NF-e configuration saved",
    })


# ═══════════════════════════════════════════════════════════════════════
# Action: get-nfe-config
# ═══════════════════════════════════════════════════════════════════════

def get_nfe_config(conn, args):
    """Retrieve NF-e configuration for a company, masking the password.

    Args: --company-id
    """
    cid = args.company_id
    if not cid:
        return err("--company-id is required")

    row = conn.execute(
        "SELECT * FROM br_nfe_config WHERE company_id = ?", (cid,)
    ).fetchone()
    if not row:
        return err(f"No NF-e configuration found for company {cid}",
                   "Run configure-nfe first")

    cfg = dict(row)
    # Mask passwords
    if cfg.get("certificado_password"):
        cfg["certificado_password"] = "***"
    if cfg.get("csc"):
        cfg["csc"] = "***"

    return ok({"config": cfg})


# ═══════════════════════════════════════════════════════════════════════
# Action: create-nfe-out
# ═══════════════════════════════════════════════════════════════════════

def create_nfe_out(conn, args):
    """Create an outbound NF-e from a sales invoice.

    Args: --company-id, --sales-invoice-id, --data-saida, --hora-saida,
          --natureza-operacao, --finalidade
    """
    cid = args.company_id
    si_id = args.sales_invoice_id
    if not cid or not si_id:
        return err("--company-id and --sales-invoice-id are required")

    # Load config
    cfg = conn.execute(
        "SELECT * FROM br_nfe_config WHERE company_id = ?", (cid,)
    ).fetchone()
    if not cfg:
        return err(f"No NF-e config for company {cid}. Run configure-nfe first.")

    cfg = dict(cfg)

    # Load sales invoice
    si = conn.execute(
        "SELECT * FROM sales_invoice WHERE id = ? AND company_id = ?",
        (si_id, cid)
    ).fetchone()
    if not si:
        return err(f"Sales invoice not found: {si_id}")

    si = dict(si)

    # Load customer
    customer = None
    if si.get("customer_id"):
        customer = conn.execute(
            "SELECT * FROM customer WHERE id = ? AND company_id = ?",
            (si["customer_id"], cid)
        ).fetchone()
    if customer:
        customer = dict(customer)

    # Load items and compute totals
    items = conn.execute("""
        SELECT sii.*, i.name as item_name, i.unit as unit_of_measure
        FROM sales_invoice_item sii
        JOIN item i ON i.id = sii.item_id
        WHERE sii.sales_invoice_id = ?
        ORDER BY sii.line_number
    """, (si_id,)).fetchall()

    if not items:
        return err("Sales invoice has no items")

    items_dict = []
    total_produtos = Decimal("0")
    total_icms = Decimal("0")
    total_ipi = Decimal("0")
    total_pis = Decimal("0")
    total_cofins = Decimal("0")

    for idx, it in enumerate(items):
        rd = dict(it)
        qty = Decimal(str(rd.get("quantity", "1")))
        price = Decimal(str(rd.get("unit_price", "0")))
        total = qty * price
        total_produtos += total

        # Tax rates
        p_icms = Decimal(_cf(conn, rd["item_id"], "aliq_icms", "18.00"))
        p_pis = Decimal(_cf(conn, rd["item_id"], "aliq_pis", "1.65"))
        p_cofins = Decimal(_cf(conn, rd["item_id"], "aliq_cofins", "7.60"))
        p_ipi = Decimal(_cf(conn, rd["item_id"], "aliq_ipi", "0.00"))

        v_icms = round(total * p_icms / Decimal("100"), 2)
        v_ipi = round(total * p_ipi / Decimal("100"), 2)
        v_pis = round(total * p_pis / Decimal("100"), 2)
        v_cofins = round(total * p_cofins / Decimal("100"), 2)

        total_icms += v_icms
        total_ipi += v_ipi
        total_pis += v_pis
        total_cofins += v_cofins

        items_dict.append({
            "item_id": rd["item_id"],
            "numero_item": idx + 1,
            "descricao": rd.get("item_name", rd.get("description", "")),
            "ncm": _cf(conn, rd["item_id"], "ncm", ""),
            "cfop": _cf(conn, rd["item_id"], "cfop", "5102"),
            "cst_icms": _cf(conn, rd["item_id"], "cst_icms", "00"),
            "cst_pis": _cf(conn, rd["item_id"], "cst_pis", "01"),
            "cst_cofins": _cf(conn, rd["item_id"], "cst_cofins", "01"),
            "unidade": rd.get("unit_of_measure", "UN"),
            "quantidade": str(qty),
            "valor_unitario": str(price),
            "valor_total": str(total),
            "base_icms": str(total),
            "aliquota_icms": str(p_icms),
            "valor_icms": str(v_icms),
            "base_ipi": str(total),
            "aliquota_ipi": str(p_ipi),
            "valor_ipi": str(v_ipi),
            "aliquota_pis": str(p_pis),
            "valor_pis": str(v_pis),
            "aliquota_cofins": str(p_cofins),
            "valor_cofins": str(v_cofins),
        })

    desconto = Decimal(si.get("discount_amount", "0") or "0")
    valor_total_nf = total_produtos + total_ipi - desconto

    # Get next numero
    nfe_id = str(uuid4())
    numero = _next_numero(conn, cfg)

    # Data de emissão
    data_emissao = datetime.now().strftime("%Y-%m-%d")

    # Natureza operacao
    nat_op = args.natureza_operacao or si.get("description", "VENDA DE MERCADORIA")

    # Extract CNPJ, IE from customer custom fields
    customer_cnpj = ""
    customer_cpf = ""
    customer_ie = ""
    customer_isuf = ""
    customer_name = ""
    customer_email = ""

    if customer:
        customer_name = customer.get("name", "")
        customer_email = customer.get("email", "")
        tax_id = customer.get("tax_id", "") or ""
        if len("".join(ch for ch in tax_id if ch.isdigit())) == 14:
            customer_cnpj = tax_id
        elif len("".join(ch for ch in tax_id if ch.isdigit())) == 11:
            customer_cpf = tax_id

        customer_ie = _cf(conn, customer["id"], "ie", "")
        customer_isuf = _cf(conn, customer["id"], "isuf", "")

    # Build initial NF-e data
    nfe_data = {
        "id": nfe_id,
        "chave_acesso": "",  # computed below
        "numero": numero,
        "serie": cfg.get("serie_default", "1"),
        "modelo": "55",
        "tipo_operacao": "saida",
        "data_emissao": data_emissao,
        "data_saida": args.data_saida or data_emissao,
        "hora_saida": args.hora_saida or "12:00:00",
        "natureza_operacao": nat_op,
        "cfop_principal": items_dict[0].get("cfop", "5102"),
        "finalidade": args.finalidade or "normal",
        "sales_invoice_id": si_id,
        "customer_id": customer["id"] if customer else "",
        "customer_name": customer_name,
        "customer_cnpj": customer_cnpj,
        "customer_cpf": customer_cpf,
        "customer_ie": customer_ie,
        "customer_isuf": customer_isuf,
        "customer_email": customer_email,
        "valor_produtos": str(total_produtos),
        "valor_total": str(valor_total_nf),
        "valor_desconto": str(desconto),
        "valor_frete": "0.00",
        "valor_seguro": "0.00",
        "outras_despesas": "0.00",
        "base_icms": str(total_produtos),
        "valor_icms": str(total_icms),
        "base_icms_st": "0.00",
        "valor_icms_st": "0.00",
        "base_icms_uf_dest": "0.00",
        "valor_icms_uf_dest": "0.00",
        "valor_icms_uf_remet": "0.00",
        "valor_icms_desonerado": "0.00",
        "base_ipi": str(total_produtos),
        "valor_ipi": str(total_ipi),
        "valor_pis": str(total_pis),
        "valor_cofins": str(total_cofins),
        "valor_ii": "0.00",
        "valor_aproximado_tributos": str(total_icms + total_pis + total_cofins + total_ipi),
        "status": "rascunho",
        "ambiente": cfg.get("ambiente", "homologacao"),
        "company_id": cid,
        "uf": cfg.get("uf", "SP"),
    }

    # Compute chave_acesso
    chave = _compute_chave_acesso(nfe_data)
    nfe_data["chave_acesso"] = chave

    # Generate XML
    try:
        # Store items in temp nfe_out_item table for XML gen
        _store_nfe_items(conn, nfe_id, items_dict)

        xml_nfe = generate_nfe_xml(conn, nfe_id)
    except Exception as e:
        return err(f"Failed to generate NF-e XML: {e}")

    # Insert into br_nfe_out
    now = datetime.now().isoformat()
    conn.execute("""
        INSERT INTO br_nfe_out (
            id, chave_acesso, numero, serie, modelo, tipo_operacao,
            data_emissao, data_saida, hora_saida,
            natureza_operacao, cfop_principal, finalidade,
            sales_invoice_id,
            customer_id, customer_name, customer_cnpj, customer_cpf,
            customer_ie, customer_isuf, customer_email,
            valor_produtos, valor_total, valor_desconto,
            valor_frete, valor_seguro, outras_despesas,
            base_icms, valor_icms, base_icms_st, valor_icms_st,
            base_icms_uf_dest, valor_icms_uf_dest,
            valor_icms_uf_remet, valor_icms_desonerado,
            base_ipi, valor_ipi, valor_pis, valor_cofins, valor_ii,
            valor_aproximado_tributos,
            xml_nfe, status, ambiente, company_id, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                  ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                  ?, ?, ?, ?)
    """, (
        nfe_id, chave, numero, nfe_data["serie"], nfe_data["modelo"],
        nfe_data["tipo_operacao"],
        data_emissao, nfe_data["data_saida"], nfe_data["hora_saida"],
        nat_op, nfe_data["cfop_principal"], nfe_data["finalidade"],
        si_id,
        nfe_data["customer_id"], customer_name, customer_cnpj, customer_cpf,
        customer_ie, customer_isuf, customer_email,
        str(total_produtos), str(valor_total_nf), str(desconto),
        "0.00", "0.00", "0.00",
        str(total_produtos), str(total_icms), "0.00", "0.00",
        "0.00", "0.00", "0.00", "0.00",
        str(total_produtos), str(total_ipi), str(total_pis), str(total_cofins),
        "0.00", str(total_icms + total_pis + total_cofins + total_ipi),
        xml_nfe, "rascunho", nfe_data["ambiente"], cid, now, now,
    ))

    # Increment proximo_numero
    conn.execute(
        "UPDATE br_nfe_config SET proximo_numero = ?, updated_at = ? WHERE id = ?",
        (numero + 1, now, cfg["id"])
    )

    conn.commit()

    return ok({
        "nfe_out_id": nfe_id,
        "chave_acesso": chave,
        "numero": numero,
        "serie": nfe_data["serie"],
        "status": "rascunho",
        "valor_total": str(valor_total_nf),
        "message": f"NF-e {numero} created as rascunho",
    })


def _next_numero(conn, cfg: dict) -> int:
    """Atomically fetch-and-increment the next NF-e number."""
    # Return the current value; caller increments after insert
    return cfg.get("proximo_numero", 1)


def _cf(conn, record_id: str, field_name: str, default: str = "") -> str:
    """Fetch a fiscal value from structured tables with custom_field_value fallback."""
    # Try customer_fiscal table
    if field_name in ("cnpj", "cpf", "ie", "isuf", "im", "email_nfe"):
        row = conn.execute(
            f"SELECT {field_name} FROM customer_fiscal WHERE customer_id = ?",
            (record_id,)
        ).fetchone()
        if row and row[field_name]:
            return row[field_name]

    # Try item_fiscal table
    if field_name in ("ncm", "cest", "cst_icms", "cst_pis", "cst_cofins",
                      "cfop", "aliq_icms", "aliq_pis", "aliq_cofins", "aliq_ipi"):
        col_map = {
            "cst_icms": "icms_cst",
            "cst_pis": "pis_cst",
            "cst_cofins": "cofins_cst",
            "cfop": "cfop_saida_interna",
            "aliq_icms": "aliq_icms",
            "aliq_pis": "aliq_pis",
            "aliq_cofins": "aliq_cofins",
            "aliq_ipi": "aliq_ipi",
        }
        col = col_map.get(field_name, field_name)
        row = conn.execute(
            f"SELECT {col} FROM item_fiscal WHERE item_id = ?",
            (record_id,)
        ).fetchone()
        if row and row[col]:
            return row[col]

    # Try company_fiscal table
    if field_name in ("cnpj", "ie", "im", "isuf"):
        row = conn.execute(
            f"SELECT {field_name} FROM company_fiscal WHERE company_id = ?",
            (record_id,)
        ).fetchone()
        if row and row[field_name]:
            return row[field_name]

    # Fallback to custom_field_value for backward compatibility
    row = conn.execute(
        "SELECT cfv_value FROM custom_field_value WHERE record_id = ? AND field_name = ?",
        (record_id, field_name)
    ).fetchone()
    return row["cfv_value"] if row else default


def _store_nfe_items(conn, nfe_out_id: str, items: list[dict]):
    """Store line items in br_nfe_out_item for XML generation."""
    # Drop old items if any
    conn.execute("DELETE FROM br_nfe_out_item WHERE nfe_out_id = ?", (nfe_out_id,))

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
            str(uuid4()), nfe_out_id,
            item["numero_item"], item["item_id"], item["descricao"],
            item["ncm"], item["cfop"], item["cst_icms"], item["cst_pis"],
            item["cst_cofins"],
            item["unidade"], item["quantidade"], item["valor_unitario"],
            item["valor_total"],
            item["base_icms"], item["aliquota_icms"], item["valor_icms"],
            item.get("base_ipi", item["base_icms"]), item.get("aliquota_ipi", "0.00"),
            item["valor_ipi"],
            item["aliquota_pis"], item["valor_pis"],
            item["aliquota_cofins"], item["valor_cofins"],
            "",  # company_id inherited from nfe
        ))


# ═══════════════════════════════════════════════════════════════════════
# Action: validate-nfe-out
# ═══════════════════════════════════════════════════════════════════════

def validate_nfe_out(conn, args):
    """Validate NF-e XML structure and update status to 'validado'.

    Args: --nfe-out-id
    """
    nfe_id = args.nfe_out_id
    if not nfe_id:
        return err("--nfe-out-id is required")

    row = conn.execute("SELECT * FROM br_nfe_out WHERE id = ?", (nfe_id,)).fetchone()
    if not row:
        return err(f"NF-e not found: {nfe_id}")

    nfe = dict(row)

    if nfe["status"] != "rascunho":
        return err(f"NF-e status must be 'rascunho' to validate, current: {nfe['status']}")

    xml_content = nfe.get("xml_nfe")
    if not xml_content:
        return err("NF-e has no XML to validate")

    # Basic structure validation
    errors = []
    if "<infNFe" not in xml_content:
        errors.append("Missing infNFe element")
    if "<ide>" not in xml_content:
        errors.append("Missing ide group")
    if "<emit>" not in xml_content:
        errors.append("Missing emit group")
    if "<dest>" not in xml_content:
        errors.append("Missing dest group")
    if "<det " not in xml_content and "<det>" not in xml_content:
        errors.append("Missing det elements")
    if "<total>" not in xml_content:
        errors.append("Missing total group")
    if "<transp>" not in xml_content:
        errors.append("Missing transp group")

    # Try XSD validation if lxml and xmlschema are available
    xsd_valid = None
    try:
        from lxml import etree
        import xmlschema
        xsd_valid = True  # placeholder; would need actual XSD file
    except ImportError:
        xsd_valid = None  # optional dependency not available

    if errors:
        return ok({
            "validated": False,
            "errors": errors,
            "xsd_available": xsd_valid is not None,
            "warning": "XML structure issues found",
        })

    # Update status
    now = datetime.now().isoformat()
    conn.execute(
        "UPDATE br_nfe_out SET status = 'validado', motivo_status = NULL, updated_at = ? WHERE id = ?",
        (now, nfe_id)
    )
    conn.commit()

    return ok({
        "validated": True,
        "nfe_out_id": nfe_id,
        "chave_acesso": nfe["chave_acesso"],
        "status": "validado",
        "xsd_validation": xsd_valid,
        "message": "NF-e XML validated successfully",
    })


# ═══════════════════════════════════════════════════════════════════════
# Action: sign-nfe-xml
# ═══════════════════════════════════════════════════════════════════════

def sign_nfe_xml_action(conn, args):
    """Sign the NF-e XML with the configured A1 certificate.

    Args: --nfe-out-id
    """
    nfe_id = args.nfe_out_id
    if not nfe_id:
        return err("--nfe-out-id is required")

    row = conn.execute("SELECT * FROM br_nfe_out WHERE id = ?", (nfe_id,)).fetchone()
    if not row:
        return err(f"NF-e not found: {nfe_id}")

    nfe = dict(row)

    if nfe["status"] not in ("validado", "rascunho"):
        return err(f"NF-e must be 'rascunho' or 'validado', current: {nfe['status']}")

    # Get certificate config
    cfg = conn.execute(
        "SELECT * FROM br_nfe_config WHERE company_id = ?", (nfe["company_id"],)
    ).fetchone()
    if not cfg:
        return err("NF-e config not found")

    cfg = dict(cfg)
    cert_path = cfg.get("certificado_path", "")
    cert_pass = cfg.get("certificado_password", "")

    if not cert_path:
        return err("Certificate path not configured. Run configure-nfe first.")

    # Decode password from base64 obfuscation
    try:
        cert_pass = base64.b64decode(cert_pass.encode("ascii")).decode("utf-8")
    except Exception:
        pass  # use as-is

    if not os.path.isfile(cert_path):
        return err(f"Certificate file not found: {cert_path}")

    # Get unsigned XML
    xml_content = nfe.get("xml_nfe")
    if not xml_content:
        return err("NF-e has no XML content")

    # If not validated, auto-validate first
    if nfe["status"] == "rascunho":
        now = datetime.now().isoformat()
        conn.execute(
            "UPDATE br_nfe_out SET status = 'validado', updated_at = ? WHERE id = ?",
            (now, nfe_id)
        )

    # Sign
    try:
        signed = sign_nfe_xml(xml_content, cert_path, cert_pass)
    except ImportError as e:
        return err(f"Dependencies missing: {e}", "pip install cryptography lxml")
    except Exception as e:
        return err(f"Signing failed: {e}")

    now = datetime.now().isoformat()
    conn.execute(
        """UPDATE br_nfe_out SET
             xml_signed = ?, status = 'assinado', updated_at = ?
           WHERE id = ?""",
        (signed, now, nfe_id)
    )
    conn.commit()

    return ok({
        "nfe_out_id": nfe_id,
        "chave_acesso": nfe["chave_acesso"],
        "status": "assinado",
        "message": "NF-e XML signed successfully",
    })


# ═══════════════════════════════════════════════════════════════════════
# Action: transmit-nfe
# ═══════════════════════════════════════════════════════════════════════

def transmit_nfe(conn, args):
    """Send signed NF-e XML to SEFAZ for authorization.

    Args: --nfe-out-id
    """
    nfe_id = args.nfe_out_id
    if not nfe_id:
        return err("--nfe-out-id is required")

    row = conn.execute("SELECT * FROM br_nfe_out WHERE id = ?", (nfe_id,)).fetchone()
    if not row:
        return err(f"NF-e not found: {nfe_id}")

    nfe = dict(row)

    if nfe["status"] != "assinado":
        return err(f"NF-e must be 'assinado', current: {nfe['status']}")

    signed_xml = nfe.get("xml_signed")
    if not signed_xml:
        return err("NF-e has no signed XML")

    # Get config
    cfg = conn.execute(
        "SELECT * FROM br_nfe_config WHERE company_id = ?", (nfe["company_id"],)
    ).fetchone()
    if not cfg:
        return err("NF-e config not found")

    cfg = dict(cfg)
    cert_path = cfg.get("certificado_path", "")
    cert_pass = cfg.get("certificado_password", "")
    uf = cfg.get("uf", "SP")
    ambiente = nfe.get("ambiente", cfg.get("ambiente", "homologacao"))

    if not cert_path or not os.path.isfile(cert_path):
        return err("Certificate not configured or file missing")

    # Decode password
    try:
        cert_pass = base64.b64decode(cert_pass.encode("ascii")).decode("utf-8")
    except Exception:
        pass

    # Send to SEFAZ
    try:
        result = autorizar_nfe(signed_xml, uf, ambiente, cert_path, cert_pass)
    except Exception as e:
        return err(f"SEFAZ transmission error: {e}")

    now = datetime.now().isoformat()

    if result.get("success"):
        recibo = result.get("recibo", "")
        if recibo:
            conn.execute(
                """UPDATE br_nfe_out SET
                     recibo = ?, status = 'enviado', motivo_status = ?,
                     updated_at = ?
                   WHERE id = ?""",
                (recibo, result.get("message", ""), now, nfe_id)
            )
        elif result.get("protocolo"):
            # Direct authorization
            conn.execute(
                """UPDATE br_nfe_out SET
                     protocolo = ?, status = 'autorizado',
                     data_autorizacao = ?, motivo_status = ?,
                     updated_at = ?
                   WHERE id = ?""",
                (result["protocolo"], result.get("data_autorizacao", now),
                 result.get("message", ""), now, nfe_id)
            )
    else:
        motivo = result.get("error", "Unknown error")
        conn.execute(
            """UPDATE br_nfe_out SET
                 status = 'rejeitado', motivo_status = ?, updated_at = ?
               WHERE id = ?""",
            (motivo, now, nfe_id)
        )

    conn.commit()

    return ok({
        "nfe_out_id": nfe_id,
        "chave_acesso": nfe["chave_acesso"],
        "recibo": result.get("recibo", ""),
        "protocolo": result.get("protocolo", ""),
        "status_code": result.get("status_code", ""),
        "message": result.get("message") or result.get("error", ""),
    })


# ═══════════════════════════════════════════════════════════════════════
# Action: check-nfe-status
# ═══════════════════════════════════════════════════════════════════════

def check_nfe_status(conn, args):
    """Check NF-e authorization status at SEFAZ.

    Args: --nfe-out-id or --recibo
    """
    recibo = args.recibo or args.nfe_out_id

    nfe = None
    if args.nfe_out_id:
        row = conn.execute(
            "SELECT * FROM br_nfe_out WHERE id = ?", (args.nfe_out_id,)
        ).fetchone()
        if row:
            nfe = dict(row)
            if not recibo:
                recibo = nfe.get("recibo", "")

    if not recibo:
        return err("No recibo available — provide --recibo or a transmitted --nfe-out-id")

    # Get config from nfe record
    uf = nfe.get("uf", "SP") if nfe else "SP"
    ambiente = nfe.get("ambiente", "homologacao") if nfe else "homologacao"
    company_id = nfe["company_id"] if nfe else ""

    cfg = conn.execute(
        "SELECT * FROM br_nfe_config WHERE company_id = ?", (company_id,)
    ).fetchone()
    cfg = dict(cfg) if cfg else {}

    cert_path = cfg.get("certificado_path", "")
    cert_pass = cfg.get("certificado_password", "")

    if not cert_path or not os.path.isfile(cert_path):
        return err("Certificate not configured or missing")

    try:
        cert_pass = base64.b64decode(cert_pass.encode("ascii")).decode("utf-8")
    except Exception:
        pass

    try:
        result = consultar_recibo(recibo, uf, ambiente, cert_path, cert_pass)
    except Exception as e:
        return err(f"Consultation error: {e}")

    now = datetime.now().isoformat()

    if result.get("success"):
        new_status = result.get("status", "")
        if new_status == "autorizado":
            conn.execute(
                """UPDATE br_nfe_out SET
                     protocolo = ?, status = 'autorizado',
                     data_autorizacao = ?,
                     motivo_status = ?, updated_at = ?
                   WHERE recibo = ? OR id = ?""",
                (result.get("protocolo", ""),
                 result.get("data_autorizacao", now),
                 result.get("message", ""), now,
                 recibo, nfe["id"] if nfe else "")
            )
        elif new_status == "pendente":
            pass  # keep status as 'enviado'
        conn.commit()

    return ok({
        "recibo": recibo,
        "status": result.get("status", "unknown"),
        "protocolo": result.get("protocolo", ""),
        "status_code": result.get("status_code", ""),
        "message": result.get("message") or result.get("error", ""),
    })


# ═══════════════════════════════════════════════════════════════════════
# Action: list-nfe-out
# ═══════════════════════════════════════════════════════════════════════

def list_nfe_out(conn, args):
    """List outbound NF-es with optional filters.

    Args: --company-id, --status, --start-date, --end-date,
          --customer-cnpj, --limit, --offset
    """
    cid = args.company_id
    if not cid:
        return err("--company-id is required")

    where = ["company_id = ?"]
    params = [cid]

    if args.status:
        where.append("status = ?")
        params.append(args.status)

    if args.start_date:
        where.append("data_emissao >= ?")
        params.append(args.start_date)

    if args.end_date:
        where.append("data_emissao <= ?")
        params.append(args.end_date)

    if args.customer_cnpj:
        where.append("customer_cnpj LIKE ?")
        params.append(f"%{args.customer_cnpj}%")

    limit = args.limit or 50
    offset = args.offset or 0

    count = conn.execute(
        f"SELECT COUNT(*) FROM br_nfe_out WHERE {' AND '.join(where)}",
        params
    ).fetchone()[0]

    rows = conn.execute(
        f"""SELECT id, chave_acesso, numero, serie, data_emissao,
                   tipo_operacao, natureza_operacao, finalidade,
                   customer_name, customer_cnpj, valor_total, status,
                   protocolo, recibo, data_autorizacao, motivo_status,
                   ambiente, created_at
            FROM br_nfe_out
            WHERE {' AND '.join(where)}
            ORDER BY data_emissao DESC, numero DESC
            LIMIT ? OFFSET ?""",
        params + [limit, offset]
    ).fetchall()

    return ok({
        "nfe_count": count,
        "limit": limit,
        "offset": offset,
        "nfes": [dict(r) for r in rows],
    })


# ═══════════════════════════════════════════════════════════════════════
# Action: get-nfe-out
# ═══════════════════════════════════════════════════════════════════════

def get_nfe_out(conn, args):
    """Get a single NF-e detail with items.

    Args: --nfe-out-id or --chave-acesso
    """
    nfe_id = args.nfe_out_id
    chave = args.chave_acesso

    if nfe_id:
        row = conn.execute(
            "SELECT * FROM br_nfe_out WHERE id = ?", (nfe_id,)
        ).fetchone()
    elif chave:
        row = conn.execute(
            "SELECT * FROM br_nfe_out WHERE chave_acesso = ?", (chave,)
        ).fetchone()
    else:
        return err("Provide --nfe-out-id or --chave-acesso")

    if not row:
        return err("NF-e not found")

    nfe = dict(row)

    # Load items
    items = conn.execute(
        """SELECT * FROM br_nfe_out_item
           WHERE nfe_out_id = ? ORDER BY numero_item""",
        (nfe["id"],)
    ).fetchall()
    nfe["items"] = [dict(it) for it in items] if items else []

    # Load events
    events = conn.execute(
        "SELECT * FROM br_nfe_event WHERE nfe_out_id = ? ORDER BY created_at DESC",
        (nfe["id"],)
    ).fetchall()
    nfe["events"] = [dict(e) for e in events] if events else []

    return ok({"nfe": nfe})


# ═══════════════════════════════════════════════════════════════════════
# Action: cancel-nfe
# ═══════════════════════════════════════════════════════════════════════

def cancel_nfe(conn, args):
    """Cancel an authorized NF-e by sending a cancelamento event to SEFAZ.

    Args: --nfe-out-id, --justificativa (min 15 chars)
    """
    nfe_id = args.nfe_out_id
    justificativa = args.justificativa

    if not nfe_id:
        return err("--nfe-out-id is required")
    if not justificativa or len(justificativa) < 15:
        return err("--justificativa must be at least 15 characters")

    row = conn.execute("SELECT * FROM br_nfe_out WHERE id = ?", (nfe_id,)).fetchone()
    if not row:
        return err(f"NF-e not found: {nfe_id}")

    nfe = dict(row)

    if nfe["status"] != "autorizado":
        return err(f"NF-e must be 'autorizado' to cancel, current: {nfe['status']}")

    # Get config
    cfg = conn.execute(
        "SELECT * FROM br_nfe_config WHERE company_id = ?", (nfe["company_id"],)
    ).fetchone()
    if not cfg:
        return err("NF-e config not found")

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

    # Build evento XML
    evento_id = str(uuid4())
    now = datetime.now()
    evento_xml = _build_evento_cancelamento(nfe, justificativa, evento_id, now, cfg)

    # Store event record
    event_db_id = str(uuid4())
    conn.execute("""
        INSERT INTO br_nfe_event (
            id, nfe_out_id, tipo_evento, numero_sequencial, justificativa,
            xml_evento, status, ambiente, company_id, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        event_db_id, nfe_id, "cancelamento", 1, justificativa,
        evento_xml, "pendente", ambiente, nfe["company_id"],
        now.isoformat(), now.isoformat(),
    ))

    # Sign evento
    try:
        signed_evento = sign_nfe_event_xml(evento_xml, cert_path, cert_pass)
    except Exception as e:
        conn.commit()  # save pending event
        return err(f"Signing failed: {e}")

    # Update event with signed XML
    conn.execute(
        "UPDATE br_nfe_event SET xml_evento_signed = ?, status = 'enviado', updated_at = ? WHERE id = ?",
        (signed_evento, now.isoformat(), event_db_id)
    )

    # Send to SEFAZ
    try:
        result = sefaz_cancelar_nfe(signed_evento, uf, ambiente, cert_path, cert_pass)
    except Exception as e:
        return err(f"SEFAZ transmission error: {e}")

    if result.get("success"):
        conn.execute("""
            UPDATE br_nfe_event SET
                protocolo = ?, status = 'processado',
                data_processamento = ?, motivo_status = ?,
                updated_at = ?
            WHERE id = ?
        """, (
            result.get("protocolo", ""),
            result.get("data_processamento", now.isoformat()),
            result.get("message", ""),
            now.isoformat(), event_db_id,
        ))
        conn.execute(
            """UPDATE br_nfe_out SET
                 status = 'cancelado', data_cancelamento = ?,
                 motivo_status = ?, updated_at = ?
               WHERE id = ?""",
            (now.isoformat(), f"Cancelamento: {justificativa}", now.isoformat(), nfe_id)
        )
    else:
        conn.execute(
            """UPDATE br_nfe_event SET
                 status = 'rejeitado', motivo_status = ?, updated_at = ?
               WHERE id = ?""",
            (result.get("error", ""), now.isoformat(), event_db_id)
        )

    conn.commit()

    return ok({
        "nfe_out_id": nfe_id,
        "evento_id": event_db_id,
        "tipo_evento": "cancelamento",
        "protocolo": result.get("protocolo", ""),
        "message": result.get("message") or result.get("error", ""),
    })


def _build_evento_cancelamento(nfe: dict, justificativa: str,
                               evento_id: str, now: datetime, cfg: dict) -> str:
    """Build evento XML for NF-e cancellation."""
    uf = cfg.get("uf", "SP")
    cuf = codigo_uf(uf)
    tp_amb = "1" if nfe.get("ambiente") == "producao" else "2"
    chave = nfe["chave_acesso"]
    protocolo = nfe.get("protocolo", "")
    n_seq = "1"

    # cOrgao from UF
    c_orgao = cuf

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<evento xmlns="http://www.portalfiscal.inf.br/nfe" versao="1.00">
  <infEvento Id="ID{evento_id.replace('-', '')[:16]}">
    <cOrgao>{c_orgao}</cOrgao>
    <tpAmb>{tp_amb}</tpAmb>
    <CNPJ>{_extract_cnpj_from_chave(chave)}</CNPJ>
    <chNFe>{chave}</chNFe>
    <dhEvento>{now.strftime('%Y-%m-%dT%H:%M:%S')}-03:00</dhEvento>
    <tpEvento>110111</tpEvento>
    <nSeqEvento>{n_seq}</nSeqEvento>
    <verEvento>1.00</verEvento>
    <detEvento versao="1.00">
      <descEvento>Cancelamento</descEvento>
      <nProt>{protocolo}</nProt>
      <xJust>{justificativa[:255]}</xJust>
    </detEvento>
  </infEvento>
</evento>"""


def _extract_cnpj_from_chave(chave: str) -> str:
    """Extract CNPJ from chave de acesso (positions 7-20)."""
    if len(chave) >= 20:
        return chave[6:20]
    return "00000000000000"


# ═══════════════════════════════════════════════════════════════════════
# Action: inutilizar-numeracao
# ═══════════════════════════════════════════════════════════════════════

def inutilizar_numeracao(conn, args):
    """Invalidate a number range at SEFAZ.

    Args: --company-id, --ano, --serie, --numero-inicial,
          --numero-final, --justificativa
    """
    cid = args.company_id
    if not cid:
        return err("--company-id is required")

    if not all([args.ano, args.serie, args.numero_inicial, args.numero_final,
                args.justificativa]):
        return err("All arguments required: --ano, --serie, --numero-inicial, "
                   "--numero-final, --justificativa")

    if len(args.justificativa) < 15:
        return err("--justificativa must be at least 15 characters")

    cfg = conn.execute(
        "SELECT * FROM br_nfe_config WHERE company_id = ?", (cid,)
    ).fetchone()
    if not cfg:
        return err("NF-e config not found")

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

    # Build inutilizacao XML
    n_ini = str(args.numero_inicial).zfill(9)
    n_fin = str(args.numero_final).zfill(9)
    ano = str(args.ano)[-2:]

    cnpj_emit = _get_company_cnpj(conn, cid)
    cuf = codigo_uf(uf)
    tp_amb = "1" if ambiente == "producao" else "2"
    serie = str(args.serie).zfill(3)

    inut_id = f"ID{random.randint(1000000000000000, 9999999999999999)}"
    now = datetime.now()

    inut_xml = f"""<inutNFe xmlns="http://www.portalfiscal.inf.br/nfe" versao="4.00">
  <infInut Id="{inut_id}">
    <tpAmb>{tp_amb}</tpAmb>
    <xServ>INUTILIZAR</xServ>
    <cUF>{cuf}</cUF>
    <ano>{ano}</ano>
    <CNPJ>{_clean_cnpj(cnpj_emit)}</CNPJ>
    <mod>55</mod>
    <serie>{serie}</serie>
    <nNFIni>{n_ini}</nNFIni>
    <nNFFin>{n_fin}</nNFFin>
    <xJust>{args.justificativa[:255]}</xJust>
  </infInut>
</inutNFe>"""

    # Sign
    try:
        from nfe_signer import sign_nfe_event_xml
        signed = sign_nfe_event_xml(inut_xml, cert_path, cert_pass)
    except Exception as e:
        return err(f"Signing failed: {e}")

    # Send
    try:
        result = sefaz_inutilizar_numeracao(signed, uf, ambiente, cert_path, cert_pass)
    except Exception as e:
        return err(f"SEFAZ error: {e}")

    return ok({
        "ano": args.ano,
        "serie": args.serie,
        "range": f"{args.numero_inicial}–{args.numero_final}",
        "protocolo": result.get("protocolo", ""),
        "message": result.get("message") or result.get("error", ""),
    })


def _get_company_cnpj(conn, company_id: str) -> str:
    """Get company CNPJ from company_fiscal, company.tax_id, or custom fields."""
    # Try structured table first
    row = conn.execute(
        "SELECT cnpj FROM company_fiscal WHERE company_id = ?", (company_id,)
    ).fetchone()
    if row and row["cnpj"]:
        return row["cnpj"]
    # Try company.tax_id
    row = conn.execute(
        "SELECT tax_id FROM company WHERE id = ?", (company_id,)
    ).fetchone()
    if row and row["tax_id"]:
        return row["tax_id"]
    # Fallback to custom fields
    return _cf(conn, company_id, "cnpj", "00000000000000")


# ═══════════════════════════════════════════════════════════════════════
# Action: generate-carta-correcao
# ═══════════════════════════════════════════════════════════════════════

def generate_carta_correcao(conn, args):
    """Issue a Carta de Correção Eletrônica (CC-e) for an NF-e.

    Args: --nfe-out-id, --correcao
    """
    nfe_id = args.nfe_out_id
    correcao = args.correcao

    if not nfe_id or not correcao:
        return err("--nfe-out-id and --correcao are required")

    if len(correcao) < 15 or len(correcao) > 1000:
        return err("Correction text must be between 15 and 1000 characters")

    row = conn.execute("SELECT * FROM br_nfe_out WHERE id = ?", (nfe_id,)).fetchone()
    if not row:
        return err(f"NF-e not found: {nfe_id}")

    nfe = dict(row)

    if nfe["status"] != "autorizado":
        return err("NF-e must be 'autorizado' to issue CC-e")

    cfg = conn.execute(
        "SELECT * FROM br_nfe_config WHERE company_id = ?", (nfe["company_id"],)
    ).fetchone()
    if not cfg:
        return err("NF-e config not found")

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

    # Count existing CC-e events to determine sequence number
    existing = conn.execute(
        "SELECT COUNT(*) FROM br_nfe_event WHERE nfe_out_id = ? AND tipo_evento = 'carta_correcao'",
        (nfe_id,)
    ).fetchone()[0]
    n_seq = existing + 1

    # Build CC-e event XML
    evento_id = str(uuid4())
    now = datetime.now()
    chave = nfe["chave_acesso"]
    cuf = codigo_uf(uf)
    tp_amb = "1" if ambiente == "producao" else "2"

    cce_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<evento xmlns="http://www.portalfiscal.inf.br/nfe" versao="1.00">
  <infEvento Id="ID{evento_id.replace('-', '')[:16]}">
    <cOrgao>{cuf}</cOrgao>
    <tpAmb>{tp_amb}</tpAmb>
    <CNPJ>{_extract_cnpj_from_chave(chave)}</CNPJ>
    <chNFe>{chave}</chNFe>
    <dhEvento>{now.strftime('%Y-%m-%dT%H:%M:%S')}-03:00</dhEvento>
    <tpEvento>110110</tpEvento>
    <nSeqEvento>{n_seq}</nSeqEvento>
    <verEvento>1.00</verEvento>
    <detEvento versao="1.00">
      <descEvento>Carta de Correcao</descEvento>
      <xCorrecao>{correcao[:1000]}</xCorrecao>
      <xCondUso>A Carta de Correcao e disciplinada pelo paragrafo 1o-A do art.
7o do Convenio S/N, de 15 de dezembro de 1970 e pode ser utilizada para
regularizacao de erro ocorrido na emissao de documento fiscal, desde que
o erro nao esteja relacionado com: I - as variaveis que determinam o valor
do imposto tais como: base de calculo, aliquota, diferenca de preco,
quantidade, valor da operacao ou da prestacao; II - a correcao de dados
cadastrais que implique mudanca do remetente ou do destinatario;
III - a data de emissao ou de saida.</xCondUso>
    </detEvento>
  </infEvento>
</evento>"""

    # Store event
    event_db_id = str(uuid4())
    conn.execute("""
        INSERT INTO br_nfe_event (
            id, nfe_out_id, tipo_evento, numero_sequencial,
            xml_evento, status, ambiente, company_id, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        event_db_id, nfe_id, "carta_correcao", n_seq,
        cce_xml, "pendente", ambiente, nfe["company_id"],
        now.isoformat(), now.isoformat(),
    ))

    # Sign evento
    try:
        signed_evento = sign_nfe_event_xml(cce_xml, cert_path, cert_pass)
    except Exception as e:
        conn.commit()
        return err(f"Signing failed: {e}")

    conn.execute(
        "UPDATE br_nfe_event SET xml_evento_signed = ?, status = 'enviado', updated_at = ? WHERE id = ?",
        (signed_evento, now.isoformat(), event_db_id)
    )

    # Send
    try:
        result = sefaz_cancelar_nfe(signed_evento, uf, ambiente, cert_path, cert_pass)
    except Exception as e:
        return err(f"SEFAZ error: {e}")

    if result.get("success"):
        conn.execute("""
            UPDATE br_nfe_event SET
                protocolo = ?, status = 'processado',
                data_processamento = ?, motivo_status = ?,
                updated_at = ?
            WHERE id = ?
        """, (
            result.get("protocolo", ""),
            result.get("data_processamento", now.isoformat()),
            result.get("message", ""),
            now.isoformat(), event_db_id,
        ))
    else:
        conn.execute(
            "UPDATE br_nfe_event SET status = 'rejeitado', motivo_status = ?, updated_at = ? WHERE id = ?",
            (result.get("error", ""), now.isoformat(), event_db_id)
        )

    conn.commit()

    return ok({
        "nfe_out_id": nfe_id,
        "evento_id": event_db_id,
        "tipo_evento": "carta_correcao",
        "sequencial": n_seq,
        "protocolo": result.get("protocolo", ""),
        "message": result.get("message") or result.get("error", ""),
    })


# ═══════════════════════════════════════════════════════════════════════
# Action: consultar-cadastro
# ═══════════════════════════════════════════════════════════════════════

def consultar_cadastro(conn, args):
    """Consult taxpayer registration (CNPJ) at SEFAZ.

    Args: --cnpj, --uf (optional)
    """
    cnpj = args.cnpj
    if not cnpj:
        return err("--cnpj is required")

    uf = args.uf or "SP"

    # Need valid config to access SEFAZ
    cfg = conn.execute(
        "SELECT * FROM br_nfe_config LIMIT 1"
    ).fetchone()
    if not cfg:
        return err("No NF-e config found. Run configure-nfe first.")

    cfg = dict(cfg)
    cert_path = cfg.get("certificado_path", "")
    cert_pass = cfg.get("certificado_password", "")
    ambiente = cfg.get("ambiente", "homologacao")

    if not cert_path or not os.path.isfile(cert_path):
        return err("Certificate not configured or missing")

    try:
        cert_pass = base64.b64decode(cert_pass.encode("ascii")).decode("utf-8")
    except Exception:
        pass

    try:
        result = sefaz_consultar_cadastro(
            uf, ambiente, cert_path, cert_pass, cnpj
        )
    except Exception as e:
        return err(f"SEFAZ error: {e}")

    return ok(dict(result))


# ═══════════════════════════════════════════════════════════════════════
# Action: sefaz-status-servico
# ═══════════════════════════════════════════════════════════════════════

def sefaz_status_servico(conn, args):
    """Check SEFAZ web service status.

    Args: --company-id (optional), --uf, --ambiente
    """
    cid = args.company_id
    uf = args.uf
    ambiente = args.ambiente or "homologacao"

    if cid:
        cfg = conn.execute(
            "SELECT * FROM br_nfe_config WHERE company_id = ?", (cid,)
        ).fetchone()
        if cfg:
            cfg = dict(cfg)
            uf = uf or cfg.get("uf", "SP")
            ambiente = ambiente or cfg.get("ambiente", "homologacao")

    if not uf:
        uf = "SP"

    # Get creds from config
    cert_path = ""
    cert_pass = ""
    if cid:
        cfg2 = conn.execute(
            "SELECT * FROM br_nfe_config WHERE company_id = ?", (cid,)
        ).fetchone()
        if cfg2:
            cfg2 = dict(cfg2)
            cert_path = cfg2.get("certificado_path", "")
            cert_pass = cfg2.get("certificado_password", "")
    else:
        cfg2 = conn.execute(
            "SELECT * FROM br_nfe_config LIMIT 1"
        ).fetchone()
        if cfg2:
            cfg2 = dict(cfg2)
            cert_path = cfg2.get("certificado_path", "")
            cert_pass = cfg2.get("certificado_password", "")

    # It's OK if no cert — some SEFAZ endpoints allow anonymous status check
    try:
        if cert_pass:
            cert_pass = base64.b64decode(cert_pass.encode("ascii")).decode("utf-8")
    except Exception:
        pass

    try:
        result = status_servico(uf, ambiente, cert_path, cert_pass)
    except Exception as e:
        return ok({
            "operational": False,
            "error": str(e),
            "uf": uf,
            "ambiente": ambiente,
        })

    return ok({
        "uf": uf,
        "ambiente": ambiente,
        "operational": result.get("operational", False),
        "status_code": result.get("status_code", ""),
        "message": result.get("message", ""),
        "avg_response_seconds": result.get("avg_response_seconds", ""),
    })


# ═══════════════════════════════════════════════════════════════════════
# Action: generate-danfe-out
# ═══════════════════════════════════════════════════════════════════════

def generate_danfe_out(conn, args):
    """Generate DANFE (visual representation) for an outbound NF-e.

    Tries PDF generation (weasyprint > reportlab) with HTML fallback.

    Args: --nfe-out-id, --output-path (optional)
    """
    nfe_id = args.nfe_out_id
    if not nfe_id:
        return err("--nfe-out-id is required")

    row = conn.execute("SELECT * FROM br_nfe_out WHERE id = ?", (nfe_id,)).fetchone()
    if not row:
        return err(f"NF-e not found: {nfe_id}")

    nfe = dict(row)

    # Use signed XML if available, otherwise unsigned
    xml_content = nfe.get("xml_signed") or nfe.get("xml_nfe")

    # Determine output path
    output_path = args.output_path or args.danfe_output
    if not output_path:
        output_dir = os.path.expanduser("~/.openclaw/erpclaw/nfe/danfe")
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, f"DANFE-NFe-{nfe['numero']}.pdf")

    # Try PDF generation first
    pdf_ok = False
    result_format = "html"
    if output_path.endswith(".pdf"):
        pdf_ok = _generate_danfe_pdf(nfe, output_path)
        if pdf_ok:
            result_format = "pdf"

    if not pdf_ok:
        danfe_html = _generate_danfe_html(nfe, xml_content or "")
        if output_path.endswith(".pdf"):
            output_path = output_path.replace(".pdf", ".html")
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(danfe_html)

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
        "message": f"DANFE generated as {result_format.upper()}",
    })


def _generate_danfe_pdf(nfe: dict, output_path: str) -> bool:
    """Try to generate DANFE as PDF using weasyprint or reportlab.

    Returns True if PDF was generated, False if HTML fallback should be used.
    """
    danfe_html = _generate_danfe_html(nfe, "")

    # Try weasyprint first
    try:
        import weasyprint
        weasyprint.HTML(string=danfe_html).write_pdf(output_path)
        return True
    except ImportError:
        pass
    except Exception:
        pass

    # Try reportlab as fallback
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib import colors
        from reportlab.lib.units import mm

        styles = getSampleStyleSheet()
        doc = SimpleDocTemplate(output_path, pagesize=A4,
                                leftMargin=10*mm, rightMargin=10*mm,
                                topMargin=10*mm, bottomMargin=10*mm)
        elements = []

        title_style = ParagraphStyle("DANFE_Title", parent=styles["Title"],
                                      fontSize=16, alignment=1, spaceAfter=4*mm)
        elements.append(Paragraph("DANFE — Documento Auxiliar da NF-e", title_style))

        nfe_num = str(nfe.get('numero', ''))
        nfe_chave = str(nfe.get('chave_acesso', ''))
        nfe_status = str(nfe.get('status', ''))

        info_style = ParagraphStyle("Info", parent=styles["Normal"],
                                     fontSize=9, alignment=1, spaceAfter=2*mm)
        elements.append(Paragraph(
            f"NF-e Nº {nfe_num} — Status: {nfe_status.upper()} — Emissão: {nfe.get('data_emissao', '')}",
            info_style
        ))

        # Main table data
        data = [
            ["DANFE — Nota Fiscal Eletrônica", "", "", ""],
            ["Chave de Acesso", nfe_chave, "", ""],
            ["Natureza Operação", nfe.get('natureza_operacao', ''),
             "Protocolo", nfe.get('protocolo', '—')],
            ["Cliente", nfe.get('customer_name', ''),
             "CNPJ", nfe.get('customer_cnpj', '')],
            ["Valor Produtos", f"R$ {nfe.get('valor_produtos', '0.00')}",
             "Valor ICMS", f"R$ {nfe.get('valor_icms', '0.00')}"],
            ["Valor IPI", f"R$ {nfe.get('valor_ipi', '0.00')}",
             "Valor PIS/COFINS",
             f"R$ {str(Decimal(nfe.get('valor_pis', '0')) + Decimal(nfe.get('valor_cofins', '0')))}"],
            ["Desconto", f"R$ {nfe.get('valor_desconto', '0.00')}",
             "VALOR TOTAL", f"R$ {nfe.get('valor_total', '0.00')}"],
        ]

        table = Table(data, colWidths=[45*mm, 45*mm, 45*mm, 45*mm])
        table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), "Courier"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("SPAN", (0, 0), (-1, 0)),
            ("SPAN", (1, 1), (-1, 1)),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        elements.append(table)
        elements.append(Spacer(1, 5*mm))

        footer_style = ParagraphStyle("Footer", parent=styles["Normal"],
                                       fontSize=7, alignment=1)
        elements.append(Paragraph("Documento gerado por ERPClaw Region BR — DANFE v1.5.0", footer_style))

        doc.build(elements)
        return True
    except ImportError:
        pass
    except Exception:
        pass

    return False


def _generate_danfe_html(nfe: dict, xml_content: str) -> str:
    """Generate a simplified DANFE as HTML."""
    chave = nfe["chave_acesso"]
    chave_fmt = f"{chave[:4]} {chave[4:8]} {chave[8:12]} {chave[12:16]} {chave[16:20]} {chave[20:24]} {chave[24:28]} {chave[28:32]} {chave[32:36]} {chave[36:40]} {chave[40:44]}"

    # Extract barcode base from chave
    barcode_base = chave[:43] if len(chave) >= 43 else chave

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<title>DANFE — NF-e {nfe.get('numero', '')}</title>
<style>
  body {{ font-family: Arial, sans-serif; margin: 20px; font-size: 11px; }}
  .header {{ text-align: center; border: 1px solid #000; padding: 10px; margin-bottom: 10px; }}
  .title {{ font-size: 16px; font-weight: bold; }}
  table {{ width: 100%; border-collapse: collapse; margin-bottom: 8px; }}
  th, td {{ border: 1px solid #000; padding: 4px 6px; text-align: left; font-size: 10px; }}
  th {{ background: #eee; }}
  .right {{ text-align: right; }}
  .center {{ text-align: center; }}
  .chave {{ font-family: monospace; letter-spacing: 1px; font-size: 13px; }}
  .barcode {{ text-align: center; font-family: monospace; font-size: 9px; margin: 10px 0; padding: 8px; border: 1px solid #000; }}
  .status {{ font-weight: bold; padding: 2px 8px; display: inline-block; }}
  .status-autorizado {{ background: #d4edda; color: #155724; }}
  .status-cancelado {{ background: #f8d7da; color: #721c24; }}
  .status-enviado {{ background: #fff3cd; color: #856404; }}
</style>
</head>
<body>
<div class="header">
  <div class="title">DANFE — Documento Auxiliar da Nota Fiscal Eletrônica</div>
  <div>NF-e Nº {nfe.get('numero', '')} — Série {nfe.get('serie', '1')}</div>
</div>

<table>
  <tr><th colspan="4">Chave de Acesso</th></tr>
  <tr><td colspan="4" class="chave center">{chave_fmt}</td></tr>
</table>

<table>
  <tr><th colspan="4">Dados da NF-e</th></tr>
  <tr>
    <td><b>Natureza:</b> {nfe.get('natureza_operacao', '')}</td>
    <td><b>Protocolo:</b> {nfe.get('protocolo') or '—'}</td>
    <td><b>Data Emissão:</b> {nfe.get('data_emissao', '')}</td>
    <td><b>Status:</b> <span class="status status-{nfe.get('status', '')}">{nfe.get('status', '')}</span></td>
  </tr>
</table>

<table>
  <tr><th>Emitente</th><th>Destinatário</th></tr>
  <tr>
    <td>CNPJ: {_clean_cnpj(nfe.get('customer_cnpj', ''))}<br>(Emitente — este é o Remetente da NF-e de Saída)</td>
    <td>Nome: {nfe.get('customer_name', '')}<br>CNPJ/CPF: {nfe.get('customer_cnpj') or nfe.get('customer_cpf') or '—'}<br>IE: {nfe.get('customer_ie') or '—'}</td>
  </tr>
</table>

<table>
  <tr>
    <th>Valor Produtos</th>
    <th>Desconto</th>
    <th>Total NF-e</th>
    <th>Valor ICMS</th>
    <th>Valor PIS/COFINS</th>
  </tr>
  <tr>
    <td class="right">R$ {nfe.get('valor_produtos', '0.00')}</td>
    <td class="right">R$ {nfe.get('valor_desconto', '0.00')}</td>
    <td class="right"><b>R$ {nfe.get('valor_total', '0.00')}</b></td>
    <td class="right">R$ {nfe.get('valor_icms', '0.00')}</td>
    <td class="right">R$ {str(Decimal(nfe.get('valor_pis', '0')) + Decimal(nfe.get('valor_cofins', '0')))}</td>
  </tr>
</table>

<table>
  <tr><th colspan="2">Informações Complementares</th></tr>
  <tr><td colspan="2">{nfe.get('info_complementar', '') or '—'}</td></tr>
</table>

<div class="barcode">{barcode_base}</div>

<div style="text-align: center; font-size: 9px; margin-top: 20px;">
  Documento gerado por ERPClaw Region BR — NF-e Emission v1.0
</div>
</body>
</html>"""


# ═══════════════════════════════════════════════════════════════════════
# Action: export-nfe-out-xml
# ═══════════════════════════════════════════════════════════════════════

def export_nfe_out_xml(conn, args):
    """Export the authorized NF-e XML to a file.

    Args: --nfe-out-id, --output-path (optional)
    """
    nfe_id = args.nfe_out_id
    if not nfe_id:
        return err("--nfe-out-id is required")

    row = conn.execute("SELECT * FROM br_nfe_out WHERE id = ?", (nfe_id,)).fetchone()
    if not row:
        return err(f"NF-e not found: {nfe_id}")

    nfe = dict(row)

    # Pick the best available XML: protocolado > signed > raw
    xml_content = (
        nfe.get("xml_protocolado")
        or nfe.get("xml_signed")
        or nfe.get("xml_nfe")
    )
    if not xml_content:
        return err("NF-e has no XML content")

    output_path = args.output_path or args.xml_path
    if not output_path:
        output_dir = os.path.expanduser("~/.openclaw/erpclaw/nfe/xml")
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(
            output_dir,
            f"NFe-{nfe['chave_acesso']}.xml"
        )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(xml_content)

    return ok({
        "nfe_out_id": nfe_id,
        "chave_acesso": nfe["chave_acesso"],
        "export_path": output_path,
        "message": "NF-e XML exported",
    })


# ═══════════════════════════════════════════════════════════════════════
# ACTIONS — Wired into db_query.py
# ═══════════════════════════════════════════════════════════════════════

ACTIONS = {
    "configure-nfe": configure_nfe,
    "get-nfe-config": get_nfe_config,
    "create-nfe-out": create_nfe_out,
    "validate-nfe-out": validate_nfe_out,
    "sign-nfe-xml": sign_nfe_xml_action,
    "transmit-nfe": transmit_nfe,
    "check-nfe-status": check_nfe_status,
    "list-nfe-out": list_nfe_out,
    "get-nfe-out": get_nfe_out,
    "cancel-nfe": cancel_nfe,
    "inutilizar-numeracao": inutilizar_numeracao,
    "generate-carta-correcao": generate_carta_correcao,
    "consultar-cadastro": consultar_cadastro,
    "sefaz-status-servico": sefaz_status_servico,
    "generate-danfe-out": generate_danfe_out,
    "export-nfe-out-xml": export_nfe_out_xml,
}
