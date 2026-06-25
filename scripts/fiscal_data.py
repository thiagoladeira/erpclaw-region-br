#!/usr/bin/env python3
"""ERPClaw Region BR — Fiscal Data Management

Structured fiscal tables for Brazilian compliance:
  - company_fiscal: CNPJ/IE/IM/cadastral data for the company
  - customer_fiscal: CNPJ/CPF/IE/IM/cadastral data for customers
  - item_fiscal: NCM/CEST/CFOP/CST/tax rates for items

10 actions: CRUD for each entity + safe migration from custom_field_value.
"""
import os
import sys
from uuid import uuid4

# Add shared lib to path
sys.path.insert(0, os.path.expanduser("~/.openclaw/erpclaw/lib"))
from erpclaw_lib.db import get_connection
from erpclaw_lib.response import ok, err

# ═══════════════════════════════════════════════════════════════════════
# Validation Helpers
# ═══════════════════════════════════════════════════════════════════════

# IE length ranges per UF (basic format check)
_IE_UF_RANGES = {
    "AC": (13, 13), "AL": (9, 9),   "AP": (9, 9),   "AM": (9, 9),
    "BA": (8, 9),   "CE": (9, 9),   "DF": (13, 13), "ES": (9, 9),
    "GO": (9, 9),   "MA": (9, 9),   "MT": (11, 11), "MS": (9, 9),
    "MG": (13, 13), "PA": (9, 9),   "PB": (9, 9),   "PR": (10, 10),
    "PE": (9, 14),  "PI": (9, 9),   "RJ": (8, 8),   "RN": (9, 10),
    "RS": (10, 10), "RO": (14, 14), "RR": (9, 9),   "SC": (9, 9),
    "SP": (12, 12), "SE": (9, 9),   "TO": (9, 11),
}


def _clean_digits(text: str) -> str:
    """Remove non-digit characters from a string."""
    if not text:
        return ""
    return "".join(ch for ch in str(text) if ch.isdigit())


def _valida_cnpj(cnpj: str) -> bool:
    """Validate CNPJ check digits.

    Algorithm:
      - 14 digits
      - First DV: weights 5,4,3,2,9,8,7,6,5,4,3,2 over first 12 digits
      - Second DV: weights 6,5,4,3,2,9,8,7,6,5,4,3,2 over first 13 digits
    """
    cnpj = _clean_digits(cnpj)
    if len(cnpj) != 14:
        return False
    # Reject known invalid patterns
    if cnpj == cnpj[0] * 14:
        return False

    def _calc_dv(digits, weights):
        total = sum(int(d) * w for d, w in zip(digits, weights))
        remainder = total % 11
        return 0 if remainder < 2 else 11 - remainder

    # First DV
    pesos1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    dv1 = _calc_dv(cnpj[:12], pesos1)
    if dv1 != int(cnpj[12]):
        return False

    # Second DV
    pesos2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    dv2 = _calc_dv(cnpj[:13], pesos2)
    if dv2 != int(cnpj[13]):
        return False

    return True


def _valida_cpf(cpf: str) -> bool:
    """Validate CPF check digits.

    Algorithm:
      - 11 digits
      - First DV: weights 10,9,8,7,6,5,4,3,2 over first 9 digits
      - Second DV: weights 11,10,9,8,7,6,5,4,3,2 over first 10 digits
    """
    cpf = _clean_digits(cpf)
    if len(cpf) != 11:
        return False
    # Reject known invalid patterns
    if cpf == cpf[0] * 11:
        return False

    def _calc_dv(digits, weights):
        total = sum(int(d) * w for d, w in zip(digits, weights))
        remainder = total % 11
        return 0 if remainder < 2 else 11 - remainder

    # First DV
    pesos1 = [10, 9, 8, 7, 6, 5, 4, 3, 2]
    dv1 = _calc_dv(cpf[:9], pesos1)
    if dv1 != int(cpf[9]):
        return False

    # Second DV
    pesos2 = [11, 10, 9, 8, 7, 6, 5, 4, 3, 2]
    dv2 = _calc_dv(cpf[:10], pesos2)
    if dv2 != int(cpf[10]):
        return False

    return True


def _valida_ie(ie: str, uf: str) -> bool:
    """Validate IE format per UF (basic length check).

    Full per-UF validation algorithms are complex. This performs:
      - Uppercase UF normalization
      - Length range check per UF
      - Digit-only check
    """
    if not ie or not uf:
        return True  # IE is optional, skip if not provided
    uf = uf.upper().strip()
    ie_clean = _clean_digits(ie)
    if not ie_clean:
        return True  # Empty after cleaning is fine
    if uf not in _IE_UF_RANGES:
        # Unknown UF: accept but warn
        return True
    lo, hi = _IE_UF_RANGES[uf]
    if lo <= len(ie_clean) <= hi:
        return True
    return False


# ═══════════════════════════════════════════════════════════════════════
# Company Fiscal Actions
# ═══════════════════════════════════════════════════════════════════════

def add_company_fiscal(conn, args):
    """Add or update Brazilian tax identifiers for a company.

    Args: --company-id (required), --cnpj (required), --inscricao-estadual,
          --inscricao-municipal, --inscricao-suframa, --razao-social,
          --nome-fantasia, --cnae-principal, --crt, --regime-isencao,
          --logradouro, --numero, --complemento, --bairro, --cep,
          --municipio-codigo, --municipio-nome, --uf, --telefone, --email
    """
    company_id = args.company_id
    cnpj = _clean_digits(args.cnpj or "")

    # Validate CNPJ
    if not _valida_cnpj(cnpj):
        return err("Invalid CNPJ check digits")

    # Validate IE if provided
    ie = _clean_digits(getattr(args, "inscricao_estadual", None) or "")
    uf = (getattr(args, "uf", None) or "").upper().strip()
    if ie and uf:
        if not _valida_ie(ie, uf):
            uf_range = _IE_UF_RANGES.get(uf, (0, 0))
            return err(f"IE length {len(ie)} not valid for UF {uf} (expected {uf_range[0]}-{uf_range[1]} digits)")

    # Check if record exists
    existing = conn.execute(
        "SELECT id FROM company_fiscal WHERE company_id = ?",
        (company_id,)
    ).fetchone()

    data = {
        "cnpj": cnpj,
        "inscricao_estadual": ie or None,
        "inscricao_municipal": _clean_digits(getattr(args, "inscricao_municipal", None) or "") or None,
        "inscricao_suframa": _clean_digits(getattr(args, "inscricao_suframa", None) or "") or None,
        "razao_social": getattr(args, "razao_social", None) or None,
        "nome_fantasia": getattr(args, "nome_fantasia", None) or None,
        "cnae_principal": _clean_digits(getattr(args, "cnae_principal", None) or "") or None,
        "crt": getattr(args, "crt", None) or "3",
        "regime_isencao": getattr(args, "regime_isencao", None) or None,
        "logradouro": getattr(args, "logradouro", None) or None,
        "numero": getattr(args, "numero", None) or None,
        "complemento": getattr(args, "complemento", None) or None,
        "bairro": getattr(args, "bairro", None) or None,
        "cep": _clean_digits(getattr(args, "cep", None) or "") or None,
        "municipio_codigo": _clean_digits(getattr(args, "municipio_codigo", None) or "") or None,
        "municipio_nome": getattr(args, "municipio_nome", None) or None,
        "uf": uf or None,
        "telefone": getattr(args, "telefone", None) or None,
        "email": getattr(args, "email", None) or None,
    }

    if existing:
        # UPDATE
        set_clauses = ", ".join(f"{k} = ?" for k in data)
        set_clauses += ", updated_at = CURRENT_TIMESTAMP"
        values = list(data.values()) + [existing["id"]]
        conn.execute(
            f"UPDATE company_fiscal SET {set_clauses} WHERE id = ?",
            values
        )
        conn.commit()
        return ok({
            "status": "updated",
            "id": existing["id"],
            "company_id": company_id,
            "cnpj": cnpj,
        })
    else:
        # INSERT
        record_id = str(uuid4())
        columns = ["id", "company_id"] + list(data.keys())
        placeholders = ["?", "?"] + ["?" for _ in data]
        values = [record_id, company_id] + list(data.values())
        try:
            conn.execute(
                f"INSERT INTO company_fiscal ({', '.join(columns)}) VALUES ({', '.join(placeholders)})",
                values
            )
            conn.commit()
        except Exception as e:
            return err(f"Failed to insert company_fiscal: {e}")
        return ok({
            "status": "created",
            "id": record_id,
            "company_id": company_id,
            "cnpj": cnpj,
        })


def get_company_fiscal(conn, args):
    """Get Brazilian tax identifiers for a company.

    Args: --company-id (required)
    """
    company_id = args.company_id
    if not company_id:
        return err("--company-id is required")

    row = conn.execute(
        "SELECT * FROM company_fiscal WHERE company_id = ?",
        (company_id,)
    ).fetchone()
    if not row:
        return err(f"No fiscal data found for company {company_id}")
    return ok(dict(row))


def list_company_fiscal(conn, args):
    """List all companies with Brazilian fiscal data.

    Args: --limit, --offset
    """
    limit = min(getattr(args, "limit", 50) or 50, 200)
    offset = getattr(args, "offset", 0) or 0
    rows = conn.execute(
        "SELECT * FROM company_fiscal ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (limit, offset)
    ).fetchall()
    return ok({
        "rows": [dict(r) for r in rows],
        "limit": limit,
        "offset": offset,
    })


# ═══════════════════════════════════════════════════════════════════════
# Customer Fiscal Actions
# ═══════════════════════════════════════════════════════════════════════

def add_customer_fiscal(conn, args):
    """Add or update Brazilian tax identifiers for a customer.

    Args: --customer-id (required), --cnpj, --cpf, --ie, --isuf, --im,
          --contribuinte-icms, --crt, --logradouro, --numero, --complemento,
          --bairro, --cep, --municipio-codigo, --municipio-nome, --uf,
          --telefone, --email-nfe
    """
    customer_id = args.customer_id
    if not customer_id:
        return err("--customer-id is required")

    cnpj = _clean_digits(getattr(args, "cnpj", None) or "")
    cpf = _clean_digits(getattr(args, "cpf", None) or "")

    # At least one of CNPJ or CPF required
    if not cnpj and not cpf:
        return err("At least one of --cnpj or --cpf is required")

    # Validate CNPJ if provided
    if cnpj and not _valida_cnpj(cnpj):
        return err("Invalid CNPJ check digits")

    # Validate CPF if provided
    if cpf and not _valida_cpf(cpf):
        return err("Invalid CPF check digits")

    # Validate IE if provided
    ie = _clean_digits(getattr(args, "ie", None) or "")
    uf = (getattr(args, "uf", None) or "").upper().strip()
    if ie and uf:
        if not _valida_ie(ie, uf):
            uf_range = _IE_UF_RANGES.get(uf, (0, 0))
            return err(f"IE length {len(ie)} not valid for UF {uf} (expected {uf_range[0]}-{uf_range[1]} digits)")

    # contribuinte_icms
    contrib_icms = getattr(args, "contribuinte_icms", None)
    if contrib_icms is not None:
        contrib_icms = int(contrib_icms)
        if contrib_icms not in (0, 1, 2):
            return err("--contribuinte-icms must be 0 (NÃO), 1 (SIM), or 2 (ISENTO)")

    # Check if record exists
    existing = conn.execute(
        "SELECT id FROM customer_fiscal WHERE customer_id = ?",
        (customer_id,)
    ).fetchone()

    data = {
        "cnpj": cnpj or None,
        "cpf": cpf or None,
        "ie": ie or None,
        "isuf": _clean_digits(getattr(args, "isuf", None) or "") or None,
        "im": _clean_digits(getattr(args, "im", None) or "") or None,
        "contribuinte_icms": contrib_icms if contrib_icms is not None else 1,
        "crt": getattr(args, "crt", None) or "3",
        "logradouro": getattr(args, "logradouro", None) or None,
        "numero": getattr(args, "numero", None) or None,
        "complemento": getattr(args, "complemento", None) or None,
        "bairro": getattr(args, "bairro", None) or None,
        "cep": _clean_digits(getattr(args, "cep", None) or "") or None,
        "municipio_codigo": _clean_digits(getattr(args, "municipio_codigo", None) or "") or None,
        "municipio_nome": getattr(args, "municipio_nome", None) or None,
        "uf": uf or None,
        "telefone": getattr(args, "telefone", None) or None,
        "email_nfe": getattr(args, "email_nfe", None) or None,
    }

    if existing:
        set_clauses = ", ".join(f"{k} = ?" for k in data)
        set_clauses += ", updated_at = CURRENT_TIMESTAMP"
        values = list(data.values()) + [existing["id"]]
        conn.execute(
            f"UPDATE customer_fiscal SET {set_clauses} WHERE id = ?",
            values
        )
        conn.commit()
        return ok({
            "status": "updated",
            "id": existing["id"],
            "customer_id": customer_id,
        })
    else:
        record_id = str(uuid4())
        columns = ["id", "customer_id"] + list(data.keys())
        placeholders = ["?", "?"] + ["?" for _ in data]
        values = [record_id, customer_id] + list(data.values())
        try:
            conn.execute(
                f"INSERT INTO customer_fiscal ({', '.join(columns)}) VALUES ({', '.join(placeholders)})",
                values
            )
            conn.commit()
        except Exception as e:
            return err(f"Failed to insert customer_fiscal: {e}")
        return ok({
            "status": "created",
            "id": record_id,
            "customer_id": customer_id,
        })


def get_customer_fiscal(conn, args):
    """Get Brazilian tax identifiers for a customer.

    Args: --customer-id (required)
    """
    customer_id = args.customer_id
    if not customer_id:
        return err("--customer-id is required")

    row = conn.execute(
        "SELECT * FROM customer_fiscal WHERE customer_id = ?",
        (customer_id,)
    ).fetchone()
    if not row:
        return err(f"No fiscal data found for customer {customer_id}")
    return ok(dict(row))


def list_customer_fiscal(conn, args):
    """List customers with Brazilian fiscal data.

    Args: --company-id, --uf, --limit, --offset
    """
    limit = min(getattr(args, "limit", 50) or 50, 200)
    offset = getattr(args, "offset", 0) or 0

    query = "SELECT * FROM customer_fiscal WHERE 1=1"
    params = []

    # Filter by company_id via join if provided
    company_id = getattr(args, "company_id", None)
    if company_id:
        query += " AND customer_id IN (SELECT id FROM customer WHERE company_id = ?)"
        params.append(company_id)

    uf = getattr(args, "uf", None)
    if uf:
        query += " AND uf = ?"
        params.append(uf.upper().strip())

    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    rows = conn.execute(query, params).fetchall()
    return ok({
        "rows": [dict(r) for r in rows],
        "limit": limit,
        "offset": offset,
    })


# ═══════════════════════════════════════════════════════════════════════
# Item Fiscal Actions
# ═══════════════════════════════════════════════════════════════════════

def add_item_fiscal(conn, args):
    """Add or update Brazilian tax classification for an item.

    Args: --item-id (required), --ncm, --cest, --gtin, --gtin-trib,
          --origem, --ex-tipi, --cfop-saida-interna, --cfop-saida-interestadual,
          --cfop-saida-exterior, --cfop-entrada-interna, --cfop-entrada-interestadual,
          --cfop-entrada-exterior, --icms-cst, --pis-cst, --cofins-cst, --ipi-cst,
          --aliq-icms, --aliq-icms-st, --aliq-pis, --aliq-cofins, --aliq-ipi,
          --aliq-iss, --mva-st, --reducao-base-icms, --reducao-base-icms-st,
          --company-id (required)
    """
    item_id = args.item_id
    company_id = args.company_id

    if not item_id:
        return err("--item-id is required")
    if not company_id:
        return err("--company-id is required")

    ncm = _clean_digits(getattr(args, "ncm", None) or "")

    # Validate origem
    origem = getattr(args, "origem", None)
    if origem is not None:
        if origem not in ("0", "1", "2", "3", "4", "5", "6", "7", "8"):
            return err("--origem must be 0-8")

    # Check if record exists
    existing = conn.execute(
        "SELECT id FROM item_fiscal WHERE item_id = ?",
        (item_id,)
    ).fetchone()

    data = {
        "ncm": ncm or None,
        "cest": _clean_digits(getattr(args, "cest", None) or "") or None,
        "gtin": _clean_digits(getattr(args, "gtin", None) or "") or None,
        "gtin_trib": _clean_digits(getattr(args, "gtin_trib", None) or "") or None,
        "origem": origem if origem is not None else "0",
        "ex_tipi": getattr(args, "ex_tipi", None) or None,
        "cfop_saida_interna": getattr(args, "cfop_saida_interna", None) or None,
        "cfop_saida_interestadual": getattr(args, "cfop_saida_interestadual", None) or None,
        "cfop_saida_exterior": getattr(args, "cfop_saida_exterior", None) or None,
        "cfop_entrada_interna": getattr(args, "cfop_entrada_interna", None) or None,
        "cfop_entrada_interestadual": getattr(args, "cfop_entrada_interestadual", None) or None,
        "cfop_entrada_exterior": getattr(args, "cfop_entrada_exterior", None) or None,
        "icms_cst": getattr(args, "icms_cst", None) or None,
        "pis_cst": getattr(args, "pis_cst", None) or None,
        "cofins_cst": getattr(args, "cofins_cst", None) or None,
        "ipi_cst": getattr(args, "ipi_cst", None) or None,
        "aliq_icms": getattr(args, "aliq_icms", None) or "18.00",
        "aliq_icms_st": getattr(args, "aliq_icms_st", None) or "0.00",
        "aliq_pis": getattr(args, "aliq_pis", None) or "1.65",
        "aliq_cofins": getattr(args, "aliq_cofins", None) or "7.60",
        "aliq_ipi": getattr(args, "aliq_ipi", None) or "0.00",
        "aliq_iss": getattr(args, "aliq_iss", None) or "0.00",
        "mva_st": getattr(args, "mva_st", None) or "0.00",
        "reducao_base_icms": getattr(args, "reducao_base_icms", None) or "0.00",
        "reducao_base_icms_st": getattr(args, "reducao_base_icms_st", None) or "0.00",
    }

    if existing:
        set_clauses = ", ".join(f"{k} = ?" for k in data)
        set_clauses += ", updated_at = CURRENT_TIMESTAMP"
        values = list(data.values()) + [existing["id"]]
        conn.execute(
            f"UPDATE item_fiscal SET {set_clauses} WHERE id = ?",
            values
        )
        conn.commit()
        return ok({
            "status": "updated",
            "id": existing["id"],
            "item_id": item_id,
        })
    else:
        record_id = str(uuid4())
        columns = ["id", "item_id", "company_id"] + list(data.keys())
        placeholders = ["?", "?", "?"] + ["?" for _ in data]
        values = [record_id, item_id, company_id] + list(data.values())
        try:
            conn.execute(
                f"INSERT INTO item_fiscal ({', '.join(columns)}) VALUES ({', '.join(placeholders)})",
                values
            )
            conn.commit()
        except Exception as e:
            return err(f"Failed to insert item_fiscal: {e}")
        return ok({
            "status": "created",
            "id": record_id,
            "item_id": item_id,
        })


def get_item_fiscal(conn, args):
    """Get Brazilian tax classification for an item.

    Args: --item-id (required)
    """
    item_id = args.item_id
    if not item_id:
        return err("--item-id is required")

    row = conn.execute(
        "SELECT * FROM item_fiscal WHERE item_id = ?",
        (item_id,)
    ).fetchone()
    if not row:
        return err(f"No fiscal data found for item {item_id}")
    return ok(dict(row))


def list_item_fiscal(conn, args):
    """List items with Brazilian tax classification.

    Args: --company-id, --ncm, --limit, --offset
    """
    limit = min(getattr(args, "limit", 50) or 50, 200)
    offset = getattr(args, "offset", 0) or 0

    query = "SELECT * FROM item_fiscal WHERE 1=1"
    params = []

    company_id = getattr(args, "company_id", None)
    if company_id:
        query += " AND company_id = ?"
        params.append(company_id)

    ncm = getattr(args, "ncm", None)
    if ncm:
        query += " AND ncm = ?"
        params.append(_clean_digits(ncm))

    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    rows = conn.execute(query, params).fetchall()
    return ok({
        "rows": [dict(r) for r in rows],
        "limit": limit,
        "offset": offset,
    })


# ═══════════════════════════════════════════════════════════════════════
# Migration: custom_field_value → structured tables
# ═══════════════════════════════════════════════════════════════════════

def migrate_fiscal_data(conn, args):
    """Migrate Brazilian fiscal data from custom_field_value to new tables.

    This is SAFE migration — reads from custom_field_value, writes to the
    new structured tables, never deletes old data.

    Args: --company-id (required)

    Mapping:
      - company-level fields (field_name in cnpj, ie, im, isuf, razao_social,
        nome_fantasia, cnae, crt, regime_isencao, cep, uf, etc.)
        → company_fiscal (when record_id matches a company.id)

      - customer-level fields (field_name in cnpj, cpf, ie, im, isuf,
        contribuinte_icms, email_nfe, uf, etc.)
        → customer_fiscal (when record_id matches a customer.id)

      - item-level fields (field_name in ncm, cest, cfop, cst_icms,
        cst_pis, cst_cofins, aliquota_icms, etc.)
        → item_fiscal (when record_id matches an item.id)
    """
    company_id = args.company_id
    if not company_id:
        return err("--company-id is required for migration")

    migrated = {"company_fiscal": 0, "customer_fiscal": 0, "item_fiscal": 0}
    skipped = {"company_fiscal": 0, "customer_fiscal": 0, "item_fiscal": 0}

    # ------------------------------------------------------------------
    # Fetch all custom_field_value records for this company's domain
    # ------------------------------------------------------------------
    # Company IDs under this tenant
    company_ids = {
        r["id"] for r in conn.execute(
            "SELECT id FROM company WHERE id = ?", (company_id,)
        ).fetchall()
    }
    # Also include child records: items and customers of this company
    if company_ids:
        customer_ids = {
            r["id"] for r in conn.execute(
                "SELECT id FROM customer WHERE company_id = ?", (company_id,)
            ).fetchall()
        }
        item_ids = {
            r["id"] for r in conn.execute(
                "SELECT id FROM item WHERE company_id = ?", (company_id,)
            ).fetchall()
        }
    else:
        customer_ids = set()
        item_ids = set()

    # ------------------------------------------------------------------
    # Migrate company fiscal data
    # ------------------------------------------------------------------
    company_field_map = {
        "cnpj": "cnpj",
        "ie": "inscricao_estadual",
        "im": "inscricao_municipal",
        "isuf": "inscricao_suframa",
        "razao_social": "razao_social",
        "nome_fantasia": "nome_fantasia",
        "cnae": "cnae_principal",
        "crt": "crt",
        "regime_isencao": "regime_isencao",
        "logradouro": "logradouro",
        "numero": "numero",
        "complemento": "complemento",
        "bairro": "bairro",
        "cep": "cep",
        "municipio_codigo": "municipio_codigo",
        "municipio_nome": "municipio_nome",
        "uf": "uf",
        "telefone": "telefone",
        "email": "email",
    }

    for comp_id in company_ids:
        # Check if already has fiscal record
        existing = conn.execute(
            "SELECT id FROM company_fiscal WHERE company_id = ?", (comp_id,)
        ).fetchone()
        if existing:
            skipped["company_fiscal"] += 1
            continue

        # Gather values from custom fields
        values = {}
        for cf_key, col_name in company_field_map.items():
            row = conn.execute(
                "SELECT cfv_value FROM custom_field_value WHERE record_id = ? AND field_name = ?",
                (comp_id, cf_key)
            ).fetchone()
            if row and row["cfv_value"]:
                values[col_name] = row["cfv_value"]

        if not values:
            continue

        # Validate CNPJ if present
        cnpj_clean = _clean_digits(values.get("cnpj", ""))
        if cnpj_clean and not _valida_cnpj(cnpj_clean):
            # CNPJ invalid, skip but log
            continue

        record_id = str(uuid4())
        columns = ["id", "company_id"] + list(values.keys())
        placeholders = ["?", "?"] + ["?" for _ in values]
        params = [record_id, comp_id] + list(values.values())
        try:
            conn.execute(
                f"INSERT INTO company_fiscal ({', '.join(columns)}) VALUES ({', '.join(placeholders)})",
                params
            )
            migrated["company_fiscal"] += 1
        except Exception:
            skipped["company_fiscal"] += 1

    # ------------------------------------------------------------------
    # Migrate customer fiscal data
    # ------------------------------------------------------------------
    customer_field_map = {
        "cnpj": "cnpj",
        "cpf": "cpf",
        "ie": "ie",
        "im": "im",
        "isuf": "isuf",
        "contribuinte_icms": "contribuinte_icms",
        "crt": "crt",
        "logradouro": "logradouro",
        "numero": "numero",
        "complemento": "complemento",
        "bairro": "bairro",
        "cep": "cep",
        "municipio_codigo": "municipio_codigo",
        "municipio_nome": "municipio_nome",
        "uf": "uf",
        "telefone": "telefone",
        "email_nfe": "email_nfe",
    }

    for cust_id in customer_ids:
        existing = conn.execute(
            "SELECT id FROM customer_fiscal WHERE customer_id = ?", (cust_id,)
        ).fetchone()
        if existing:
            skipped["customer_fiscal"] += 1
            continue

        values = {}
        for cf_key, col_name in customer_field_map.items():
            row = conn.execute(
                "SELECT cfv_value FROM custom_field_value WHERE record_id = ? AND field_name = ?",
                (cust_id, cf_key)
            ).fetchone()
            if row and row["cfv_value"]:
                values[col_name] = row["cfv_value"]

        # Must have at least CNPJ or CPF
        if not values.get("cnpj") and not values.get("cpf"):
            continue

        # Validate identifiers
        cnpj_clean = _clean_digits(values.get("cnpj", ""))
        cpf_clean = _clean_digits(values.get("cpf", ""))
        if cnpj_clean and not _valida_cnpj(cnpj_clean):
            continue
        if cpf_clean and not _valida_cpf(cpf_clean):
            continue

        record_id = str(uuid4())
        columns = ["id", "customer_id"] + list(values.keys())
        placeholders = ["?", "?"] + ["?" for _ in values]
        params = [record_id, cust_id] + list(values.values())
        try:
            conn.execute(
                f"INSERT INTO customer_fiscal ({', '.join(columns)}) VALUES ({', '.join(placeholders)})",
                params
            )
            migrated["customer_fiscal"] += 1
        except Exception:
            skipped["customer_fiscal"] += 1

    # ------------------------------------------------------------------
    # Migrate item fiscal data
    # ------------------------------------------------------------------
    item_field_map = {
        "ncm": "ncm",
        "cest": "cest",
        "gtin": "gtin",
        "gtin_trib": "gtin_trib",
        "origem": "origem",
        "ex_tipi": "ex_tipi",
        "cfop": "cfop_saida_interna",
        "cfop_saida_interna": "cfop_saida_interna",
        "cfop_saida_interestadual": "cfop_saida_interestadual",
        "cfop_saida_exterior": "cfop_saida_exterior",
        "cfop_entrada_interna": "cfop_entrada_interna",
        "cfop_entrada_interestadual": "cfop_entrada_interestadual",
        "cfop_entrada_exterior": "cfop_entrada_exterior",
        "cst_icms": "icms_cst",
        "icms_cst": "icms_cst",
        "cst_pis": "pis_cst",
        "pis_cst": "pis_cst",
        "cst_cofins": "cofins_cst",
        "cofins_cst": "cofins_cst",
        "cst_ipi": "ipi_cst",
        "ipi_cst": "ipi_cst",
        "aliq_icms": "aliq_icms",
        "aliquota_icms": "aliq_icms",
        "aliq_icms_st": "aliq_icms_st",
        "aliq_pis": "aliq_pis",
        "aliquota_pis": "aliq_pis",
        "aliq_cofins": "aliq_cofins",
        "aliquota_cofins": "aliq_cofins",
        "aliq_ipi": "aliq_ipi",
        "aliquota_ipi": "aliq_ipi",
        "aliq_iss": "aliq_iss",
        "mva_st": "mva_st",
        "reducao_base_icms": "reducao_base_icms",
        "reducao_base_icms_st": "reducao_base_icms_st",
    }

    for it_id in item_ids:
        existing = conn.execute(
            "SELECT id FROM item_fiscal WHERE item_id = ?", (it_id,)
        ).fetchone()
        if existing:
            skipped["item_fiscal"] += 1
            continue

        values = {}
        seen_cols = set()
        for cf_key, col_name in item_field_map.items():
            if col_name in seen_cols:
                continue  # Skip duplicates (aliases)
            row = conn.execute(
                "SELECT cfv_value FROM custom_field_value WHERE record_id = ? AND field_name = ?",
                (it_id, cf_key)
            ).fetchone()
            if row and row["cfv_value"]:
                values[col_name] = row["cfv_value"]
                seen_cols.add(col_name)

        if not values:
            continue

        record_id = str(uuid4())
        columns = ["id", "item_id", "company_id"] + list(values.keys())
        placeholders = ["?", "?", "?"] + ["?" for _ in values]
        params = [record_id, it_id, company_id] + list(values.values())
        try:
            conn.execute(
                f"INSERT INTO item_fiscal ({', '.join(columns)}) VALUES ({', '.join(placeholders)})",
                params
            )
            migrated["item_fiscal"] += 1
        except Exception:
            skipped["item_fiscal"] += 1

    # ------------------------------------------------------------------
    # Commit and report
    # ------------------------------------------------------------------
    conn.commit()
    return ok({
        "status": "completed",
        "company_id": company_id,
        "migrated": migrated,
        "skipped": skipped,
        "note": "Old custom_field_value records preserved. No data was deleted.",
    })


# ═══════════════════════════════════════════════════════════════════════
# Action Registry
# ═══════════════════════════════════════════════════════════════════════

ACTIONS = {
    "add-company-fiscal": add_company_fiscal,
    "get-company-fiscal": get_company_fiscal,
    "list-company-fiscal": list_company_fiscal,
    "add-customer-fiscal": add_customer_fiscal,
    "get-customer-fiscal": get_customer_fiscal,
    "list-customer-fiscal": list_customer_fiscal,
    "add-item-fiscal": add_item_fiscal,
    "get-item-fiscal": get_item_fiscal,
    "list-item-fiscal": list_item_fiscal,
    "migrate-fiscal-data": migrate_fiscal_data,
}
