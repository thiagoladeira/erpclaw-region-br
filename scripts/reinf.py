"""ERPClaw Region BR — REINF (Escrituração Fiscal Digital de Retenções)

Monthly declaration of tax withholdings at source.
Due by 15th of next month. Late fine: up to R$500/month.

Events:
  R-1000: Taxpayer information (company registration)
  R-2010: Services taken with PIS/COFINS/CSLL withholding
  R-2020: Services provided with IR/CSLL/COFINS/PIS withholding
  R-2060: INSS contribution on services (11% retention)
"""
import sys
import os
import json
from uuid import uuid4
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

sys.path.insert(0, os.path.expanduser("~/.openclaw/erpclaw/lib"))
from erpclaw_lib.response import ok, err

# ── Helpers ─────────────────────────────────────────────────────────────

def _format_reinf_line(reg, fields):
    """Format REINF register line with pipe delimiter."""
    parts = [str(reg)]
    for f in fields:
        parts.append(str(f) if f is not None else "")
    return "|" + "|".join(parts)

def _text_decimal(value):
    """Format decimal as text with two decimal places."""
    if value is None:
        return "0.00"
    if isinstance(value, str):
        try:
            value = Decimal(value)
        except Exception:
            return "0.00"
    return str(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

def _only_digits(text):
    """Strip non-digit characters."""
    if not text:
        return ""
    return "".join(ch for ch in str(text) if ch.isdigit())

# ── Shared Data Fetch ──────────────────────────────────────────────────

def _get_company_fiscal(conn, company_id):
    """Fetch company fiscal data."""
    return conn.execute("""
        SELECT cnpj, razao_social, nome_fantasia, cnae_principal, crt,
               inscricao_estadual, inscricao_municipal, uf,
               logradouro, numero, complemento, bairro, cep,
               municipio_codigo, municipio_nome, telefone, email
        FROM company_fiscal WHERE company_id = ?
    """, (company_id,)).fetchone()

# ── R-1000: Taxpayer Information ──────────────────────────────────────

def generate_reinf_r1000(conn, args):
    """Generate R-1000 — Taxpayer Information event."""
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatório")

    fiscal = _get_company_fiscal(conn, company_id)
    if not fiscal:
        return err("Dados fiscais da empresa não cadastrados — use add-company-fiscal")

    cnpj = _only_digits(fiscal[0])
    razao = fiscal[1] or ""
    nome_fantasia = fiscal[2] or razao
    cnae = fiscal[3] or ""
    crt = fiscal[4] or "3"

    lines = []
    lines.append(_format_reinf_line("R1000", [
        "R-1000",               # EVT
        "1.00.00",              # VERSAO
        "1",                    # TP_INSC — 1=CNPJ
        cnpj,                   # NR_INSC
        razao[:100],            # NM_RAZAO
        crt,                    # IND_SIT_PJ
        "1",                    # IND_NAT_PJ — 1=for-profit
        cnae,                   # CNAE
        fiscal[8] or "",        # LOGRADOURO
        fiscal[9] or "",        # NUMERO
        fiscal[10] or "",       # COMPLEMENTO
        fiscal[11] or "",       # BAIRRO
        fiscal[13] or "",       # COD_MUN
        fiscal[14] or "",       # NM_MUN
        fiscal[7] or "",        # UF
        fiscal[12] or "",       # CEP
        fiscal[15] or "",       # TELEFONE
        fiscal[16] or "",       # EMAIL
        nome_fantasia[:100],    # NM_FANTASIA
        "",
    ]))

    return ok({
        "evento": "R-1000",
        "cnpj": cnpj,
        "razao_social": razao,
        "registros": len(lines),
        "lines": lines,
    })


# ── R-2010: Services Taken with Withholding ───────────────────────────

def generate_reinf_r2010(conn, args):
    """Generate R-2010 — Services Taken with PIS/COFINS/CSLL withholding.

    For purchase/service invoices where taxes were withheld at source.
    """
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatório")
    ano = args.ano or datetime.now().year
    mes = args.mes or datetime.now().month

    fiscal = _get_company_fiscal(conn, company_id)
    if not fiscal:
        return err("Dados fiscais da empresa não cadastrados")

    cnpj = _only_digits(fiscal[0])

    lines = []
    lines.append(_format_reinf_line("R2010", [
        "R-2010",               # EVT
        "1.00.00",              # VERSAO
        "1",                    # TP_INSC — 1=CNPJ
        cnpj,                   # NR_INSC
        str(ano),               # PER_APUR_ANO
        f"{mes:02d}",           # PER_APUR_MES
        "1",                    # IND_RETIF
        "",
    ]))

    # Look for service NF-es (CFOP 5xxx, 6xxx entries)
    start = f"{ano}-{mes:02d}-01"
    end_month = mes + 1 if mes < 12 else 1
    end_year = ano if mes < 12 else ano + 1
    end = f"{end_year}-{end_month:02d}-01"

    service_nfes = conn.execute("""
        SELECT id, numero_nfe, serie, data_emissao, emitente_cnpj, emitente_nome,
               cfop_principal, valor_total, valor_pis, valor_cofins,
               base_icms, valor_icms
        FROM nfe_import
        WHERE company_id = ?
          AND data_emissao >= ? AND data_emissao < ?
          AND (cfop_principal LIKE '5%' OR cfop_principal LIKE '6%')
        LIMIT 100
    """, (company_id, start, end)).fetchall()

    if not service_nfes:
        lines.append(_format_reinf_line("R2010_INFO", [
            "Nenhum serviço tomado com retenção no período",
        ]))
        return ok({
            "evento": "R-2010",
            "prestadores": 0,
            "registros": len(lines),
            "lines": lines,
        })

    prestadores = {}
    for nfe in service_nfes:
        provider_cnpj = _only_digits(nfe[4])
        if not provider_cnpj:
            continue

        if provider_cnpj not in prestadores:
            prestadores[provider_cnpj] = {
                "nome": nfe[5] or "",
                "nfes": [],
                "total_bruto": Decimal("0"),
                "total_pis_ret": Decimal("0"),
                "total_cofins_ret": Decimal("0"),
                "total_csll_ret": Decimal("0"),
            }

        vl_bruto = Decimal(str(nfe[7] or 0))
        pis_ret = vl_bruto * Decimal("0.0065")  # 0.65% retenção padrão serviços
        cofins_ret = vl_bruto * Decimal("0.03")  # 3% retenção padrão
        csll_ret = vl_bruto * Decimal("0.01")    # 1% retenção padrão

        prestadores[provider_cnpj]["nfes"].append({
            "serie": nfe[2] or "1",
            "numero": nfe[1] or "",
            "data": nfe[3],
            "cfop": nfe[6] or "",
            "vl_bruto": nfe[7] or "0.00",
            "pis_ret": _text_decimal(pis_ret),
            "cofins_ret": _text_decimal(cofins_ret),
            "csll_ret": _text_decimal(csll_ret),
        })
        prestadores[provider_cnpj]["total_bruto"] += vl_bruto
        prestadores[provider_cnpj]["total_pis_ret"] += pis_ret
        prestadores[provider_cnpj]["total_cofins_ret"] += cofins_ret
        prestadores[provider_cnpj]["total_csll_ret"] += csll_ret

    total_bruto = Decimal("0")
    total_pis = Decimal("0")
    total_cofins = Decimal("0")
    total_csll = Decimal("0")

    for prov_cnpj, data in prestadores.items():
        lines.append(_format_reinf_line("R2010_TOM", [
            "1",                    # TP_INSC_TOM — 1=CNPJ
            prov_cnpj,              # NR_INSC_TOM
            data["nome"][:100],     # NM_TOM
            _text_decimal(data["total_bruto"]),
            _text_decimal(data["total_pis_ret"]),
            _text_decimal(data["total_cofins_ret"]),
            _text_decimal(data["total_csll_ret"]),
            str(len(data["nfes"])),
            "",
        ]))

        total_bruto += data["total_bruto"]
        total_pis += data["total_pis_ret"]
        total_cofins += data["total_cofins_ret"]
        total_csll += data["total_csll_ret"]

        # NFS detail per provider
        for nf in data["nfes"]:
            lines.append(_format_reinf_line("R2010_NFS", [
                nf["serie"],
                nf["numero"],
                nf["data"],
                nf["cfop"],
                nf["vl_bruto"],
                nf["pis_ret"],
                nf["cofins_ret"],
                nf["csll_ret"],
                "",
            ]))

    # Summary
    lines.append(_format_reinf_line("R2010_TOT", [
        str(len(prestadores)),
        _text_decimal(total_bruto),
        _text_decimal(total_pis),
        _text_decimal(total_cofins),
        _text_decimal(total_csll),
    ]))

    return ok({
        "evento": "R-2010",
        "prestadores": len(prestadores),
        "total_bruto": _text_decimal(total_bruto),
        "total_retencoes": _text_decimal(total_pis + total_cofins + total_csll),
        "registros": len(lines),
        "lines": lines,
    })


# ── R-2020: Services Provided with Withholding ────────────────────────

def generate_reinf_r2020(conn, args):
    """Generate R-2020 — Services Provided with IR/CSLL/COFINS/PIS withholding.

    For sales invoices where the client withheld taxes at source.
    """
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatório")
    ano = args.ano or datetime.now().year
    mes = args.mes or datetime.now().month

    fiscal = _get_company_fiscal(conn, company_id)
    if not fiscal:
        return err("Dados fiscais da empresa não cadastrados")

    cnpj = _only_digits(fiscal[0])

    lines = []
    lines.append(_format_reinf_line("R2020", [
        "R-2020",               # EVT
        "1.00.00",              # VERSAO
        "1",                    # TP_INSC
        cnpj,                   # NR_INSC
        str(ano),
        f"{mes:02d}",
        "1",
        "",
    ]))

    start = f"{ano}-{mes:02d}-01"
    end_month = mes + 1 if mes < 12 else 1
    end_year = ano if mes < 12 else ano + 1
    end = f"{end_year}-{end_month:02d}-01"

    out_nfes = conn.execute("""
        SELECT id, numero, serie, data_emissao, customer_cnpj, customer_name,
               cfop_principal, valor_total, valor_pis, valor_cofins,
               base_icms, valor_icms, valor_ipi
        FROM br_nfe_out
        WHERE company_id = ?
          AND data_emissao >= ? AND data_emissao < ?
          AND (cfop_principal LIKE '5%' OR cfop_principal LIKE '6%')
          AND status = 'autorizado'
        LIMIT 100
    """, (company_id, start, end)).fetchall()

    if not out_nfes:
        lines.append(_format_reinf_line("R2020_INFO", [
            "Nenhum serviço prestado com retenção no período",
        ]))
        return ok({
            "evento": "R-2020",
            "tomadores": 0,
            "registros": len(lines),
            "lines": lines,
        })

    tomadores = {}
    for nfe in out_nfes:
        taker_cnpj = _only_digits(nfe[4]) if nfe[4] else ""
        if not taker_cnpj:
            continue

        if taker_cnpj not in tomadores:
            tomadores[taker_cnpj] = {
                "nome": nfe[5] or "",
                "nfes": [],
                "total_bruto": Decimal("0"),
                "total_ir_ret": Decimal("0"),
                "total_csll_ret": Decimal("0"),
                "total_cofins_ret": Decimal("0"),
                "total_pis_ret": Decimal("0"),
            }

        vl_bruto = Decimal(str(nfe[7] or 0))
        ir_ret = vl_bruto * Decimal("0.015")     # 1.5% IRRF serviços
        pis_ret = vl_bruto * Decimal("0.0065")   # 0.65%
        cofins_ret = vl_bruto * Decimal("0.03")  # 3%
        csll_ret = vl_bruto * Decimal("0.01")    # 1%

        tomadores[taker_cnpj]["nfes"].append({
            "serie": nfe[2] or "1",
            "numero": str(nfe[1] or ""),
            "data": nfe[3],
            "cfop": nfe[6] or "",
            "vl_bruto": _text_decimal(vl_bruto),
            "ir_ret": _text_decimal(ir_ret),
            "pis_ret": _text_decimal(pis_ret),
            "cofins_ret": _text_decimal(cofins_ret),
            "csll_ret": _text_decimal(csll_ret),
        })
        tomadores[taker_cnpj]["total_bruto"] += vl_bruto
        tomadores[taker_cnpj]["total_ir_ret"] += ir_ret
        tomadores[taker_cnpj]["total_csll_ret"] += csll_ret
        tomadores[taker_cnpj]["total_cofins_ret"] += cofins_ret
        tomadores[taker_cnpj]["total_pis_ret"] += pis_ret

    total_bruto = Decimal("0")
    total_ir = Decimal("0")
    total_pis = Decimal("0")
    total_cofins = Decimal("0")
    total_csll = Decimal("0")

    for tak_cnpj, data in tomadores.items():
        lines.append(_format_reinf_line("R2020_PRE", [
            "1",                        # TP_INSC_PRE — 1=CNPJ
            tak_cnpj,                   # NR_INSC_PRE
            data["nome"][:100],
            _text_decimal(data["total_bruto"]),
            _text_decimal(data["total_ir_ret"]),
            _text_decimal(data["total_csll_ret"]),
            _text_decimal(data["total_cofins_ret"]),
            _text_decimal(data["total_pis_ret"]),
            str(len(data["nfes"])),
            "",
        ]))

        total_bruto += data["total_bruto"]
        total_ir += data["total_ir_ret"]
        total_csll += data["total_csll_ret"]
        total_cofins += data["total_cofins_ret"]
        total_pis += data["total_pis_ret"]

        for nf in data["nfes"]:
            lines.append(_format_reinf_line("R2020_NFS", [
                nf["serie"],
                nf["numero"],
                nf["data"],
                nf["cfop"],
                nf["vl_bruto"],
                nf["ir_ret"],
                nf["csll_ret"],
                nf["cofins_ret"],
                nf["pis_ret"],
                "",
            ]))

    lines.append(_format_reinf_line("R2020_TOT", [
        str(len(tomadores)),
        _text_decimal(total_bruto),
        _text_decimal(total_ir),
        _text_decimal(total_csll),
        _text_decimal(total_cofins),
        _text_decimal(total_pis),
    ]))

    return ok({
        "evento": "R-2020",
        "tomadores": len(tomadores),
        "total_bruto": _text_decimal(total_bruto),
        "total_retencoes": _text_decimal(total_ir + total_csll + total_cofins + total_pis),
        "registros": len(lines),
        "lines": lines,
    })


# ── R-2060: INSS Contribution on Services ─────────────────────────────

def generate_reinf_r2060(conn, args):
    """Generate R-2060 — INSS contribution on services (11% retention).

    CNPJ of provider, NF, gross amount, INSS base, INSS retained.
    """
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatório")
    ano = args.ano or datetime.now().year
    mes = args.mes or datetime.now().month

    fiscal = _get_company_fiscal(conn, company_id)
    if not fiscal:
        return err("Dados fiscais da empresa não cadastrados")

    cnpj = _only_digits(fiscal[0])

    lines = []
    lines.append(_format_reinf_line("R2060", [
        "R-2060",               # EVT
        "1.00.00",              # VERSAO
        "1",                    # TP_INSC
        cnpj,                   # NR_INSC
        str(ano),               # PER_APUR_ANO
        f"{mes:02d}",           # PER_APUR_MES
        "1",                    # IND_RETIF
        "",
    ]))

    start = f"{ano}-{mes:02d}-01"
    end_month = mes + 1 if mes < 12 else 1
    end_year = ano if mes < 12 else ano + 1
    end = f"{end_year}-{end_month:02d}-01"

    service_nfes = conn.execute("""
        SELECT id, numero_nfe, serie, data_emissao, emitente_cnpj, emitente_nome,
               cfop_principal, valor_total, valor_pis, valor_cofins,
               base_icms, valor_icms
        FROM nfe_import
        WHERE company_id = ?
          AND data_emissao >= ? AND data_emissao < ?
          AND (cfop_principal LIKE '5%' OR cfop_principal LIKE '6%')
        LIMIT 100
    """, (company_id, start, end)).fetchall()

    if not service_nfes:
        lines.append(_format_reinf_line("R2060_INFO", [
            "Nenhuma NF de serviço com INSS retido no período",
        ]))
        return ok({
            "evento": "R-2060",
            "prestadores": 0,
            "registros": len(lines),
            "lines": lines,
        })

    prestadores = {}
    for nfe in service_nfes:
        prov_cnpj = _only_digits(nfe[4])
        if not prov_cnpj:
            continue

        if prov_cnpj not in prestadores:
            prestadores[prov_cnpj] = {
                "nome": nfe[5] or "",
                "nfes": [],
                "total_bruto": Decimal("0"),
                "total_base_inss": Decimal("0"),
                "total_inss_ret": Decimal("0"),
            }

        vl_bruto = Decimal(str(nfe[7] or 0))
        # INSS 11% on service invoices (Lei 8.212/91)
        inss_base = vl_bruto  # Full value as base for services
        inss_ret = vl_bruto * Decimal("0.11")

        prestadores[prov_cnpj]["nfes"].append({
            "serie": nfe[2] or "1",
            "numero": nfe[1] or "",
            "data": nfe[3],
            "cfop": nfe[6] or "",
            "vl_bruto": _text_decimal(vl_bruto),
            "inss_base": _text_decimal(inss_base),
            "inss_ret": _text_decimal(inss_ret),
        })
        prestadores[prov_cnpj]["total_bruto"] += vl_bruto
        prestadores[prov_cnpj]["total_base_inss"] += inss_base
        prestadores[prov_cnpj]["total_inss_ret"] += inss_ret

    total_bruto = Decimal("0")
    total_base = Decimal("0")
    total_inss = Decimal("0")

    for prov_cnpj, data in prestadores.items():
        lines.append(_format_reinf_line("R2060_TOM", [
            "1",                        # TP_INSC_TOM
            prov_cnpj,
            data["nome"][:100],
            _text_decimal(data["total_bruto"]),
            _text_decimal(data["total_base_inss"]),
            _text_decimal(data["total_inss_ret"]),
            "11.00",                    # ALIQ_RET — 11%
            str(len(data["nfes"])),
            "",
        ]))

        total_bruto += data["total_bruto"]
        total_base += data["total_base_inss"]
        total_inss += data["total_inss_ret"]

        for nf in data["nfes"]:
            lines.append(_format_reinf_line("R2060_NFS", [
                nf["serie"],
                nf["numero"],
                nf["data"],
                nf["cfop"],
                nf["vl_bruto"],
                nf["inss_base"],
                nf["inss_ret"],
                "11.00",
                "",
            ]))

    lines.append(_format_reinf_line("R2060_TOT", [
        str(len(prestadores)),
        _text_decimal(total_bruto),
        _text_decimal(total_base),
        _text_decimal(total_inss),
    ]))

    return ok({
        "evento": "R-2060",
        "prestadores": len(prestadores),
        "total_bruto": _text_decimal(total_bruto),
        "total_base_inss": _text_decimal(total_base),
        "total_inss_retido": _text_decimal(total_inss),
        "registros": len(lines),
        "lines": lines,
    })


# ── Complete REINF Generation ──────────────────────────────────────────

def generate_reinf(conn, args):
    """Generate complete REINF (all events combined)."""
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatório")
    ano = args.ano or datetime.now().year
    mes = args.mes or datetime.now().month
    output_dir = args.output_dir or "."

    fiscal = _get_company_fiscal(conn, company_id)
    if not fiscal:
        return err("Dados fiscais da empresa não cadastrados")

    all_lines = []
    events_summary = {}

    # Generate each event
    for event_fn in [
        generate_reinf_r1000,
        generate_reinf_r2010,
        generate_reinf_r2020,
        generate_reinf_r2060,
    ]:
        result = event_fn(conn, args)
        if result.get("status") == "ok":
            event_lines = result["data"].get("lines", [])
            if event_lines:
                all_lines.extend(event_lines)
            events_summary[result["data"]["evento"]] = {
                "registros": result["data"].get("registros", 0)
            }

    content = "\n".join(all_lines)

    # Write file
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        cnpj = _only_digits(fiscal[0])
        filename = f"REINF_{cnpj}_{ano}{mes:02d}.txt"
        filepath = os.path.join(output_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
    else:
        filepath = None

    # Log
    reinf_id = str(uuid4())
    try:
        conn.execute("""
            INSERT INTO sped_export_log (id, tipo, ano, mes, arquivo_path, total_registros, status, company_id)
            VALUES (?, 'reinf', ?, ?, ?, ?, 'gerado', ?)
        """, (reinf_id, ano, mes, filepath, len(all_lines), company_id))
        conn.commit()
    except Exception:
        pass

    return ok({
        "reinf_id": reinf_id,
        "tipo": "reinf",
        "ano": ano,
        "mes": mes,
        "registros": len(all_lines),
        "eventos": events_summary,
        "preview": content[:500] + ("\n..." if len(content) > 500 else ""),
    })


ACTIONS = {
    "generate-reinf": generate_reinf,
    "generate-reinf-r1000": generate_reinf_r1000,
    "generate-reinf-r2010": generate_reinf_r2010,
    "generate-reinf-r2020": generate_reinf_r2020,
    "generate-reinf-r2060": generate_reinf_r2060,
}
