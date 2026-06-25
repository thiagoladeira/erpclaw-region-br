"""ERPClaw Region BR — DCTFWeb

Declaração de Débitos e Créditos Tributários Federais — Monthly declaration
of federal tax debts (PIS, COFINS, IRPJ, CSLL, IPI) and credits.

Due by 15th of next month. Late fine: up to 2% of debt value.
"""
import sys
import os
from uuid import uuid4
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

sys.path.insert(0, os.path.expanduser("~/.openclaw/erpclaw/lib"))
from erpclaw_lib.response import ok, err

# ── Tax Code Mapping ───────────────────────────────────────────────────

TAX_CODES = {
    "pis_cumulativo":     {"codigo": "8109", "descricao": "PIS — Cumulativo"},
    "pis_nao_cumulativo": {"codigo": "6912", "descricao": "PIS — Não-Cumulativo"},
    "cofins_cumulativo":     {"codigo": "2172", "descricao": "COFINS — Cumulativo"},
    "cofins_nao_cumulativo": {"codigo": "5856", "descricao": "COFINS — Não-Cumulativo"},
    "irpj_lucro_real":       {"codigo": "0220", "descricao": "IRPJ — Lucro Real"},
    "irpj_lucro_presumido":  {"codigo": "2089", "descricao": "IRPJ — Lucro Presumido"},
    "csll_lucro_real":       {"codigo": "2372", "descricao": "CSLL — Lucro Real"},
    "csll_lucro_presumido":  {"codigo": "6012", "descricao": "CSLL — Lucro Presumido"},
    "ipi":               {"codigo": "1097", "descricao": "IPI — Diversos"},
    "irrf":              {"codigo": "1708", "descricao": "IRRF — Retenções"},
    "retencao_federal":  {"codigo": "5952", "descricao": "Retenção PIS/COFINS/CSLL"},
    "inss":              {"codigo": "2989", "descricao": "INSS — Contribuição Previdenciária"},
}

# ── Helpers ─────────────────────────────────────────────────────────────

def _format_dctf_line(reg, fields):
    """Format a DCTF register line with pipe delimiter."""
    parts = [str(reg)]
    for f in fields:
        parts.append(str(f) if f is not None else "")
    return "|" + "|".join(parts)

def _text_decimal(value):
    """Format value as text with two decimal places."""
    if value is None:
        return "0.00"
    if isinstance(value, str):
        try:
            value = Decimal(value)
        except Exception:
            return "0.00"
    return str(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

def _get_regime(conn, company_id):
    """Determine tax regime from company_fiscal."""
    fiscal = conn.execute(
        "SELECT crt FROM company_fiscal WHERE company_id = ?", (company_id,)
    ).fetchone()
    crt = fiscal[0] if fiscal else "3"
    # 1=Simples, 2=Lucro Presumido (simples excesso), 3=Lucro Real
    if crt == "1":
        return "simples"
    elif crt == "2":
        return "lucro_presumido"
    return "lucro_real"

# ── Actions ─────────────────────────────────────────────────────────────

def calculate_dctf_debts(conn, args):
    """Calculate federal tax debts for a period.

    Sums PIS, COFINS, IRPJ, CSLL, IPI from tax_apuration.
    Returns structured debt summary with tax codes.
    """
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatório")
    ano = args.ano or datetime.now().year
    mes = args.mes or datetime.now().month

    regime = _get_regime(conn, company_id)

    start = f"{ano}-{mes:02d}-01"
    end_month = mes + 1 if mes < 12 else 1
    end_year = ano if mes < 12 else ano + 1
    end = f"{end_year}-{end_month:02d}-01"

    debts = []
    total_debts = Decimal("0.00")
    total_credits = Decimal("0.00")

    # Fetch from tax_apuration
    tax_rows = conn.execute("""
        SELECT id, tributo, debito, credito, saldo_devedor, saldo_credor,
               valor_pagar, codigo_receita, status
        FROM tax_apuration
        WHERE company_id = ?
        ORDER BY tributo
    """, (company_id,)).fetchall()

    tax_by_tributo = {}
    for tr in tax_rows:
        if tr[1] not in tax_by_tributo or tr[7] == "pendente":
            tax_by_tributo[tr[1]] = tr

    # Process each federal tax
    tributos_to_check = [
        ("pis", "PIS", "cofins"),   # will resolve based on regime
        ("cofins", "COFINS", "pis"),
        ("irpj", "IRPJ", None),
        ("csll", "CSLL", None),
        ("ipi", "IPI", None),
    ]

    for tributo, label, related in tributos_to_check:
        row = tax_by_tributo.get(tributo)
        if row:
            debit = Decimal(row[2] or "0")
            credit = Decimal(row[3] or "0")
            valor_pagar = Decimal(row[6] or "0")
            status = row[8] or "pendente"
        else:
            # Calculate from source data
            if tributo in ("pis", "cofins"):
                revenue = conn.execute("""
                    SELECT COALESCE(SUM(CAST(total AS REAL)), 0)
                    FROM sales_invoice
                    WHERE company_id = ? AND posting_date >= ? AND posting_date < ?
                """, (company_id, start, end)).fetchone()[0]

                credits = conn.execute(f"""
                    SELECT COALESCE(SUM(CAST(valor_{tributo} AS REAL)), 0)
                    FROM nfe_import
                    WHERE company_id = ? AND data_emissao >= ? AND data_emissao < ?
                """, (company_id, start, end)).fetchone()[0]

                if regime == "lucro_presumido":
                    rate = Decimal("0.0065") if tributo == "pis" else Decimal("0.03")
                    debit = Decimal(str(revenue or 0)) * rate
                else:
                    rate = Decimal("0.0165") if tributo == "pis" else Decimal("0.076")
                    debit = Decimal(str(revenue or 0)) * rate

                credit = Decimal(str(credits or 0))
                valor_pagar = max(Decimal("0"), debit - credit)
            elif tributo in ("irpj", "csll"):
                revenue = Decimal(str(conn.execute("""
                    SELECT COALESCE(SUM(CAST(total AS REAL)), 0)
                    FROM sales_invoice
                    WHERE company_id = ? AND posting_date >= ? AND posting_date < ?
                """, (company_id, start, end)).fetchone()[0] or 0))

                if regime == "lucro_presumido":
                    presumido_pct = Decimal("0.08")  # 8% for commerce/industry
                    base = revenue * presumido_pct
                    rate = Decimal("0.15") if tributo == "irpj" else Decimal("0.09")
                    debit = base * rate
                else:
                    # Lucro Real — would need actual profit calculation
                    # Placeholder: 15% IRPJ + 9% CSLL on estimated profit
                    base = revenue * Decimal("0.10")  # 10% estimated margin
                    rate = Decimal("0.15") if tributo == "irpj" else Decimal("0.09")
                    debit = base * rate
                credit = Decimal("0")
                valor_pagar = debit
            else:  # ipi
                debit = Decimal(str(conn.execute("""
                    SELECT COALESCE(SUM(CAST(valor_ipi AS REAL)), 0)
                    FROM br_nfe_out
                    WHERE company_id = ? AND data_emissao >= ? AND data_emissao < ?
                    AND status = 'autorizado'
                """, (company_id, start, end)).fetchone()[0] or 0))

                credit = Decimal(str(conn.execute("""
                    SELECT COALESCE(SUM(CAST(valor_ipi AS REAL)), 0)
                    FROM nfe_import
                    WHERE company_id = ? AND data_emissao >= ? AND data_emissao < ?
                """, (company_id, start, end)).fetchone()[0] or 0))

                valor_pagar = max(Decimal("0"), debit - credit)

        # Determine tax code
        if tributo == "pis":
            codigo_key = "pis_cumulativo" if regime == "lucro_presumido" else "pis_nao_cumulativo"
        elif tributo == "cofins":
            codigo_key = "cofins_cumulativo" if regime == "lucro_presumido" else "cofins_nao_cumulativo"
        elif tributo == "irpj":
            codigo_key = "irpj_lucro_presumido" if regime == "lucro_presumido" else "irpj_lucro_real"
        elif tributo == "csll":
            codigo_key = "csll_lucro_presumido" if regime == "lucro_presumido" else "csll_lucro_real"
        else:
            codigo_key = "ipi"

        code_info = TAX_CODES.get(codigo_key, {"codigo": "0000", "descricao": label})

        entry = {
            "tributo": label,
            "codigo_receita": code_info["codigo"],
            "descricao_receita": code_info["descricao"],
            "debito": _text_decimal(debit),
            "credito": _text_decimal(credit),
            "valor_pagar": _text_decimal(valor_pagar),
            "regime": regime,
        }
        debts.append(entry)
        total_debts += max(Decimal("0"), debit - credit) if valor_pagar > 0 else Decimal("0")
        if credit > 0:
            total_credits += credit

    # Check for INSS on service invoices
    inss_base = Decimal(str(conn.execute("""
        SELECT COALESCE(SUM(CAST(valor_total AS REAL)), 0)
        FROM nfe_import
        WHERE company_id = ? AND data_emissao >= ? AND data_emissao < ?
        AND cfop_principal LIKE '5%'
    """, (company_id, start, end)).fetchone()[0] or 0))

    if inss_base > 0:
        inss_valor = inss_base * Decimal("0.11")
        debts.append({
            "tributo": "INSS",
            "codigo_receita": TAX_CODES["inss"]["codigo"],
            "descricao_receita": TAX_CODES["inss"]["descricao"],
            "debito": _text_decimal(inss_valor),
            "credito": "0.00",
            "valor_pagar": _text_decimal(inss_valor),
            "regime": regime,
        })
        total_debts += inss_valor

    return ok({
        "ano": ano,
        "mes": mes,
        "regime": regime,
        "total_debitos": _text_decimal(total_debts),
        "total_creditos": _text_decimal(total_credits),
        "total_pagar": _text_decimal(total_debts),
        "vencimento": f"15/{mes+1 if mes < 12 else 1:02d}/{ano}",
        "debitos": debts,
    })


def generate_dctf(conn, args):
    """Generate complete DCTF declaration for a period.

    Args: --company-id, --ano, --mes, --output-dir
    """
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatório")
    ano = args.ano or datetime.now().year
    mes = args.mes or datetime.now().month
    output_dir = args.output_dir or "."

    # Company data
    fiscal = conn.execute(
        "SELECT cnpj, razao_social FROM company_fiscal WHERE company_id = ?",
        (company_id,)
    ).fetchone()
    if not fiscal:
        return err("Dados fiscais da empresa não cadastrados — use add-company-fiscal")

    cnpj = fiscal[0]
    razao = fiscal[1] or ""
    regime = _get_regime(conn, company_id)

    # Get debt summary
    debts_result = calculate_dctf_debts(conn, args)
    if debts_result.get("status") != "ok":
        return debts_result

    debts = debts_result["data"]["debitos"]
    total_pagar = debts_result["data"]["total_pagar"]

    lines = []

    # Registro 0000 — Abertura
    lines.append(_format_dctf_line("0000", [
        "DCTF",          # TIPO_DECL
        "001",           # LAYOUT_VER
        cnpj,            # CNPJ
        razao[:100],     # NOME_EMP
        f"{mes:02d}",    # PER_MES
        str(ano),        # PER_ANO
        "1" if regime == "lucro_real" else "2",  # TIPO_DECLARACAO
        "1",             # IND_SIT_ESPECIAL — normal
        "",
    ]))

    # Bloco I — Identificação do Contribuinte
    lines.append(_format_dctf_line("I001", ["1"]))

    lines.append(_format_dctf_line("I010", [
        cnpj,
        razao[:100],
        str(ano),
        f"{mes:02d}",
        "",
    ]))

    # Bloco D — Débitos
    lines.append(_format_dctf_line("D001", ["1"]))

    for debt in debts:
        vl_pagar = debt["valor_pagar"]
        if float(vl_pagar) <= 0:
            continue

        vencimento_day = "15"
        due_month = mes + 1 if mes < 12 else 1
        due_year = ano if mes < 12 else ano + 1
        vencimento = f"{due_year}-{due_month:02d}-{vencimento_day}"

        lines.append(_format_dctf_line("D100", [
            "D",                         # NAT_DC — D=Débito
            debt["codigo_receita"],      # COD_RECEITA
            debt["descricao_receita"][:60],  # DESC_RECEITA
            vencimento,                  # DT_VENC
            debt["debito"],              # VL_DEBITO
            vl_pagar,                    # VL_PAGAR
            "0",                         # IND_SUSP — sem suspensão
            "",                          # NUM_PROC
            "",
        ]))

    # Bloco C — Créditos (compensações)
    has_credits = any(float(d["credito"]) > 0 for d in debts)
    if has_credits:
        lines.append(_format_dctf_line("C001", ["1"]))

        for debt in debts:
            credito = float(debt["credito"])
            if credito <= 0:
                continue

            lines.append(_format_dctf_line("C100", [
                "C",                         # NAT_DC — C=Crédito
                debt["codigo_receita"],      # COD_RECEITA
                debt["descricao_receita"][:60],
                "",                          # PER_REF
                debt["credito"],             # VL_CREDITO
                "0",                         # TIPO_CRED — saldo negativo
                "",
                "",
            ]))

    # Bloco S — Sumário
    lines.append(_format_dctf_line("S001", ["1"]))

    total_debts = sum(float(d["debito"]) for d in debts)
    total_credits = sum(float(d["credito"]) for d in debts)

    lines.append(_format_dctf_line("S100", [
        _text_decimal(total_debts),    # VL_TOT_DEBITOS
        _text_decimal(total_credits),  # VL_TOT_CREDITOS
        _text_decimal(total_pagar),    # VL_TOT_PAGAR
        _text_decimal(0),              # VL_TOT_SUSP
        _text_decimal(0),              # VL_TOT_COMP
        _text_decimal(total_pagar),    # VL_TOT_LIQ
        "",
    ]))

    # Registro 9999 — Encerramento
    total_lines = len(lines) + 1
    lines.append(_format_dctf_line("9999", [str(total_lines)]))

    content = "\n".join(lines)

    # Write file
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        filename = f"DCTF_{cnpj}_{ano}{mes:02d}.txt"
        filepath = os.path.join(output_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
    else:
        filepath = None

    # Log to sped_export_log
    dctf_id = str(uuid4())
    try:
        conn.execute("""
            INSERT INTO sped_export_log (id, tipo, ano, mes, arquivo_path, total_registros, status, company_id)
            VALUES (?, 'reinf', ?, ?, ?, ?, 'gerado', ?)
        """, (dctf_id, ano, mes, filepath, len(lines), company_id))
        conn.commit()
    except Exception:
        pass

    return ok({
        "dctf_id": dctf_id,
        "tipo": "dctfweb",
        "ano": ano,
        "mes": mes,
        "cnpj": cnpj,
        "regime": regime,
        "registros": len(lines),
        "total_debitos": _text_decimal(total_debts),
        "total_creditos": _text_decimal(total_credits),
        "total_pagar": _text_decimal(total_pagar),
        "vencimento": f"{mes+1 if mes < 12 else 1:02d}/{ano}",
        "debitos": debts,
        "preview": content[:500] + ("\n..." if len(content) > 500 else ""),
    })


def list_dctf_periods(conn, args):
    """List previous DCTF generations from sped_export_log."""
    company_id = args.company_id

    where = "WHERE tipo IN ('dctfweb', 'reinf')"
    params = []
    if company_id:
        where += " AND company_id = ?"
        params.append(company_id)

    rows = conn.execute(f"""
        SELECT id, tipo, ano, mes, total_registros, status, arquivo_path, created_at
        FROM sped_export_log
        {where}
        ORDER BY ano DESC, mes DESC
        LIMIT ?
    """, params + [args.limit or 50]).fetchall()

    return ok({
        "periods": [
            {
                "id": r[0],
                "tipo": r[1],
                "ano": r[2],
                "mes": r[3],
                "registros": r[4],
                "status": r[5],
                "arquivo": r[6],
                "criado_em": r[7],
            }
            for r in rows
        ]
    })


ACTIONS = {
    "calculate-dctf-debts": calculate_dctf_debts,
    "generate-dctf": generate_dctf,
    "list-dctf-periods": list_dctf_periods,
}
