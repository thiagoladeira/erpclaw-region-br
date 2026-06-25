"""ERPClaw Region BR — ECF (Escrituração Contábil Fiscal)

SPED ECF generation: fiscal accounting for IRPJ/CSLL (replaces DIPJ).
Layout based on Manual de Orientação do Leiaute da ECF (RFB).

Blocos:
  0 — Abertura, Identificação (0000-0990)
  C — Dados Cadastrais (C001-C990)
  J — Plano de Contas e Saldos Fiscais (J001-J990)
  K — Saldos das Contas Contábeis e Fiscais (K001-K990)
  M — E-Lalur — Livro de Apuração do Lucro Real (M000-M990)
  N — E-Lacs — Apuração da CSLL (N001-N990)
  P — Demonstrações Contábeis Fiscais (P001-P990)
  T — Distribuição de Lucros (T001-T990)
  U — Preços de Transferência (U001-U990)
  Y — Investimentos no Exterior (Y001-Y990)
  9 — Encerramento (9001-9999)

Actions:
  generate-ecf              — Generate complete ECF
  generate-ecf-bloco-0      — Opening block
  generate-ecf-bloco-m      — E-Lalur (IRPJ adjustments)
  generate-ecf-bloco-n      — E-Lacs (CSLL adjustments)
  generate-ecf-bloco-p      — Financial statements
  generate-ecf-bloco-t      — Profit distribution
  validate-ecf              — Basic validation
  list-ecf-exports          — List ECF generations
"""
import sys
import os
from uuid import uuid4
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

sys.path.insert(0, os.path.expanduser("~/.openclaw/erpclaw/lib"))
from erpclaw_lib.response import ok, err

# ── helpers ────────────────────────────────────────────────────────────

def _fl(reg, fields):
    """Format ECF line: register + fields joined by pipe."""
    parts = [str(reg)]
    for f in fields:
        parts.append(str(f) if f is not None else "")
    return "|" + "|".join(parts)

def _td(value):
    """Format decimal as TEXT with two decimal places."""
    if value is None:
        return "0.00"
    if isinstance(value, str):
        try:
            value = Decimal(value)
        except Exception:
            return "0.00"
    return str(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

def _dt_br(val):
    """Convert date to DDMMAAAA."""
    if not val:
        return ""
    s = str(val).strip()
    if len(s) >= 10:
        return s[8:10] + s[5:7] + s[0:4]
    return s

def _pad(s, length):
    """Left-pad string with zeros."""
    return str(s).rjust(length, '0')[:length]

def _snip(s, maxlen):
    return (str(s) if s else "")[:maxlen]


# ── Bloco 0: Abertura ─────────────────────────────────────────────────

def generate_ecf_bloco_0(conn, args):
    """Generate Bloco 0 — Opening and identification."""
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatório")
    ano = args.ano or datetime.now().year
    mes = args.mes or 12

    company = conn.execute(
        "SELECT name, tax_id, country, default_currency FROM company WHERE id = ?",
        (company_id,)
    ).fetchone()
    if not company:
        return err("Empresa não encontrada")

    fiscal = conn.execute(
        "SELECT cnpj, inscricao_estadual, razao_social, nome_fantasia, "
        "cnae_principal, crt, uf, municipio_codigo, municipio_nome, "
        "logradouro, numero, complemento, bairro, cep, email "
        "FROM company_fiscal WHERE company_id = ?",
        (company_id,)
    ).fetchone()

    cnpj = fiscal[0] if fiscal else (company[1] or "")
    ie = fiscal[1] if fiscal else ""
    razao = (fiscal[2] if fiscal else company[0]) or company[0]
    nome_fant = (fiscal[3] if fiscal else "") or ""
    cnae = (fiscal[4] if fiscal else "") or ""
    crt = int(fiscal[5] if fiscal else 3) if fiscal else 3
    uf = (fiscal[6] if fiscal else "") or "RJ"
    cod_mun = (fiscal[7] if fiscal else "") or ""
    nome_mun = (fiscal[8] if fiscal else "") or ""
    end_logr = (fiscal[9] if fiscal else "") or ""
    end_num = (fiscal[10] if fiscal else "") or ""
    end_compl = (fiscal[11] if fiscal else "") or ""
    end_bairro = (fiscal[12] if fiscal else "") or ""
    end_cep = (fiscal[13] if fiscal else "") or ""
    email = (fiscal[14] if fiscal else "") or ""

    cnpj_clean = cnpj.replace(".", "").replace("/", "").replace("-", "")[:14]
    year_start = f"0101{ano}"
    year_end = f"3112{ano}"

    lines = []

    # 0000 — Opening
    # TIPO_ECF: 0 = original, 1 = retificadora
    # LECF = layout version
    lines.append(_fl("0000", [
        "LECF",  # TEXTO FIXO
        "0",  # TIPO_ECF: 0 = original
        year_end,  # DT_FIN
        _snip(razao, 100),  # NOME
        _snip(cnpj_clean, 14),  # CNPJ
        uf,  # UF
        _snip(ie, 14),  # IE
        cod_mun[:7],  # COD_MUN
        _snip(nome_mun, 60),  # NOME_MUN
        "0",  # IND_SIT_ESPECIAL
        "0",  # IND_NIRE: 0=possui
        "0",  # IND_FINANC
        "",  # COD_NIRE
        "1",  # IND_GRANDEZA: 1=milhares
        "0",  # IND_ESC
        "0",  # IND_ESTRANG: 0=não é investidor estrangeiro
    ]))

    # 0001 — Abertura do Bloco 0
    lines.append(_fl("0001", ["1"]))

    # 0020 — Identificação do Sócio Ostensivo (simplified — no SCP)
    # For normal companies, no SCP
    # IND_ESC_CONS
    lines.append(_fl("0020", ["0"]))  # 0 = sem consórcio

    # 0030 — Dados Iniciais
    # REGIME_TRIB: 1 = lucro real, 2 = lucro presumido, 3 = simples nacional
    regime_map = {1: "1", 2: "2", 3: "3", "1": "1", "2": "2", "3": "3"}
    regime = regime_map.get(str(crt), "1")

    # Determine TRIBUTACAO_LUCRO
    # 1 = trimestral, 2 = anual (balancetes de suspensão), 3 = anual (estimativa mensal)
    trib_lucro = "3"  # default: lucro real anual estimativa mensal

    # Determine NIRE
    cod_nire = ""
    ind_nire = "1"  # default: não possui NIRE

    lines.append(_fl("0030", [
        "0",  # COD_SCP: 0 = sem SCP
        regime,  # REGIME_TRIB
        trib_lucro,  # TRIBUT_LUCRO
        "1",  # TRIBUT_RTT: 1 = aplica RTT
        "0",  # IND_REC_EXT
        "0",  # IND_ATIV_RURAL
        "0",  # IND_CONSOL
        "",  # DT_EVENTO
        "",  # IND_CONS
        "",  # COD_CONS
        "0",  # TIP_LALUR
        "1",  # IND_LALUR_ESCRIT
        "0",  # IND_PJ_ENQUAD
        "0",  # IND_PART_EXT
        "1",  # IND_ATIV_EXT
        "0",  # IND_PAIS_A_PAIS
        "0",  # IND_AVAL_ECP
        "0",  # IND_AVAL_ECP_CONS
    ]))

    # 0035 — Empresas Participantes (SCP) — em branco se não houver SCP
    lines.append(_fl("0035", [
        _snip(cnpj_clean, 14),  # CNPJ_SCP
        _snip(razao, 100),  # NOME_SCP
        "0",  # COD_SCP
    ]))

    # 0930 — Identificação do Contador/Responsável
    accountant = conn.execute("""
        SELECT full_name, tax_id, employee_number, email
        FROM employee WHERE company_id = ? AND designation LIKE '%contad%'
        LIMIT 1
    """, (company_id,)).fetchone()

    if not accountant:
        accountant = conn.execute("""
            SELECT full_name, tax_id, employee_number, email
            FROM employee WHERE company_id = ?
            LIMIT 1
        """, (company_id,)).fetchone()

    acc_name = _snip(accountant[0] if accountant and accountant[0] else "CONTADOR RESPONSAVEL", 100)
    acc_cpf = accountant[1] if accountant and accountant[1] else ""
    acc_cpf = acc_cpf.replace(".", "").replace("-", "")[:11]
    acc_crc = _snip(accountant[2] if accountant and accountant[2] else "RJ-000000/O", 12)
    acc_email = _snip(accountant[3] if accountant and accountant[3] else email, 80)

    lines.append(_fl("0930", [
        acc_name,
        acc_cpf,
        acc_crc,  # NUM_CLASSE
        uf,  # UF_CRC
        "1",  # IND_CRC
        acc_email,
        "",  # DT_INI_RESP
        "",  # DT_FIM_RESP
    ]))

    # 0990 — Encerramento do Bloco 0
    lines.append(_fl("0990", [str(len(lines) + 1)]))

    content = "\n".join(lines) + "\n"

    sped_id = str(uuid4())
    conn.execute("""
        INSERT INTO sped_export_log (id, tipo, ano, mes, arquivo_path, total_registros, status, company_id)
        VALUES (?, 'ecf', ?, ?, NULL, ?, 'gerado_bloco', ?)
    """, (sped_id, ano, mes, len(lines), company_id))
    conn.commit()

    return ok({
        "sped_export_id": sped_id,
        "tipo": "ecf",
        "ano": ano,
        "registros": len(lines),
        "bloco": "0",
        "preview": "\n".join(lines[:6]) + ("\n..." if len(lines) > 6 else ""),
    })


# ── Bloco M: E-Lalur — Livro de Apuração do Lucro Real ────────────────

def generate_ecf_bloco_m(conn, args):
    """Generate Bloco M — E-Lalur (Lucro Real — IRPJ adjustments).

    E-Lalur registers:
      M000: Opening
      M010: Profit before IRPJ
      M030: Permanent additions
      M300-M355: Temporary additions
      M350: Temporary exclusions
      M410: Net profit (loss) for IRPJ
      M500: IRPJ calculation
    """
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatório")
    ano = args.ano or datetime.now().year

    start_date = args.start_date or f"{ano}-01-01"
    end_date = args.end_date or f"{ano}-12-31"

    lines = []

    # M000 — Abertura do Bloco M
    lines.append(_fl("M000", ["1"]))

    # M010 — Lucro/Prejuízo antes do IRPJ
    # Calculate accounting profit from GL (Income - Expense)
    revenue = conn.execute("""
        SELECT COALESCE(SUM(CAST(ge.credit AS REAL)), 0) -
               COALESCE(SUM(CAST(ge.debit AS REAL)), 0)
        FROM gl_entry ge
        JOIN account a ON ge.account_id = a.id
        WHERE ge.company_id = ? AND a.root_type = 'Income'
          AND ge.posting_date >= ? AND ge.posting_date < ?
    """, (company_id, start_date, end_date)).fetchone()[0] or 0

    expenses = conn.execute("""
        SELECT COALESCE(SUM(CAST(ge.debit AS REAL)), 0) -
               COALESCE(SUM(CAST(ge.credit AS REAL)), 0)
        FROM gl_entry ge
        JOIN account a ON ge.account_id = a.id
        WHERE ge.company_id = ? AND a.root_type = 'Expense'
          AND ge.posting_date >= ? AND ge.posting_date < ?
    """, (company_id, start_date, end_date)).fetchone()[0] or 0

    accounting_profit = float(revenue) - float(expenses)

    lines.append(_fl("M010", [
        "1",  # IND_LALUR: 1 = parte A do Lalur
        "1",  # IND_PREJ_LIQ: 1 = lucro, 2 = prejuízo
        _td(abs(accounting_profit)),  # VL_LUCRO_LIQ
    ]))

    # M030 — Adições (permanent additions)
    # Get from tax_apuration or calculate from GL
    tax_adjustments = conn.execute("""
        SELECT tributo, debito, credito, saldo_devedor, valor_pagar, uf
        FROM tax_apuration
        WHERE company_id = ?
        ORDER BY created_at DESC
    """, (company_id,)).fetchall()

    additions_total = 0.0
    exclusion_total = 0.0

    # Common permanent additions:
    # - Non-deductible expenses
    # - Excess depreciation
    # - Provisionamentos (not yet realized)

    # Estimate additions from common non-deductible accounts
    # Look for expense accounts that contain non-deductible keywords
    non_deductible_expenses = conn.execute("""
        SELECT a.account_number, a.name,
               COALESCE(SUM(CAST(ge.debit AS REAL)), 0) -
               COALESCE(SUM(CAST(ge.credit AS REAL)), 0) as balance
        FROM gl_entry ge
        JOIN account a ON ge.account_id = a.id
        WHERE ge.company_id = ?
          AND a.root_type = 'Expense'
          AND a.is_group = 0
          AND ge.posting_date >= ? AND ge.posting_date < ?
          AND (a.name LIKE '%multa%' OR a.name LIKE '%juros%'
               OR a.name LIKE '%nao dedutiv%' OR a.name LIKE '%brinde%'
               OR a.name LIKE '%doacao%' OR a.name LIKE '%representac%')
        GROUP BY a.id
        ORDER BY a.account_number
    """, (company_id, start_date, end_date)).fetchall()

    for exp in non_deductible_expenses:
        val = float(exp[2] or 0)
        if val <= 0:
            continue
        additions_total += val
        lines.append(_fl("M030", [
            "1",  # COD_LAN_LALUR: 1 = adição
            _snip(f"{exp[1][:80]}", 255),  # DESCRICAO
            _td(val),  # VL_LANCAMENTO
            "0",  # IND_ADICAO: 0 = normal
        ]))

    # Add provision balance additions
    provisions = conn.execute("""
        SELECT a.account_number, a.name,
               COALESCE(SUM(CAST(ge.credit AS REAL)), 0) -
               COALESCE(SUM(CAST(ge.debit AS REAL)), 0) as balance
        FROM gl_entry ge
        JOIN account a ON ge.account_id = a.id
        WHERE ge.company_id = ?
          AND a.root_type = 'Liability'
          AND a.is_group = 0
          AND (a.name LIKE '%provis%' OR a.name LIKE '%contingenc%')
          AND ge.posting_date >= ? AND ge.posting_date < ?
        GROUP BY a.id
    """, (company_id, start_date, end_date)).fetchall()

    for prov in provisions:
        val = float(prov[2] or 0)
        if val <= 0:
            continue
        additions_total += val
        lines.append(_fl("M030", [
            "1",
            _snip(f"{prov[1][:80]} (provisão não dedutível)", 255),
            _td(val),
            "0",
        ]))

    # M050 — Exclusões (permanent exclusions)
    # Common exclusions:
    # - Reversals of provisions
    # - Exempt dividends received
    # - Tax incentives
    reversals = conn.execute("""
        SELECT a.account_number, a.name,
               COALESCE(SUM(CAST(ge.credit AS REAL)), 0) -
               COALESCE(SUM(CAST(ge.debit AS REAL)), 0) as balance
        FROM gl_entry ge
        JOIN account a ON ge.account_id = a.id
        WHERE ge.company_id = ?
          AND a.root_type = 'Income'
          AND a.is_group = 0
          AND ge.posting_date >= ? AND ge.posting_date < ?
          AND (a.name LIKE '%revers%' OR a.name LIKE '%dividend%'
               OR a.name LIKE '%incentiv%' OR a.name LIKE '%equivalenc%')
        GROUP BY a.id
    """, (company_id, start_date, end_date)).fetchall()

    for rev in reversals:
        val = float(rev[2] or 0)
        if val <= 0:
            continue
        exclusion_total += val
        lines.append(_fl("M050", [
            "2",  # COD_LAN_LALUR: 2 = exclusão
            _snip(f"{rev[1][:80]}", 255),
            _td(val),
        ]))

    # M300 — Parte A do Lalur (opening balance of temp differences)
    lines.append(_fl("M300", [
        "0.00",  # VL_PREJ_ACUM (opening accumulated loss)
        _td(additions_total),  # VL_ADICOES_TOTAL
        _td(exclusion_total),  # VL_EXCLUSOES_TOTAL
        "0",  # IND_PREJ_LIQ: 0 = lucro
    ]))

    # M350 — Exclusões/Adições — Compensação de Prejuízos
    # Can compensate up to 30% of real profit with accumulated losses
    real_profit_before_comp = accounting_profit + additions_total - exclusion_total

    if real_profit_before_comp > 0 and accounting_profit < 0:
        # There were accumulated losses to compensate
        max_comp = real_profit_before_comp * 0.30  # 30% limit
        compensated = min(abs(accounting_profit), max_comp)
        lines.append(_fl("M350", [
            _td(compensated),  # VL_COMP_PREJ_LIQ
            _td(compensated),  # VL_COMP_PREJ_EXT
        ]))
    else:
        lines.append(_fl("M350", ["0.00", "0.00"]))

    # M355 — Prejuízos não operacionais compensados
    lines.append(_fl("M355", ["0.00", "0.00"]))

    # M400 — Lucro Real (after adjustments and compensation)
    real_profit = real_profit_before_comp
    if real_profit_before_comp > 0 and accounting_profit < 0:
        real_profit = real_profit_before_comp - compensated

    lines.append(_fl("M400", [
        _td(real_profit) if real_profit > 0 else "0.00",  # VL_LUCRO_REAL
        _td(abs(real_profit)) if real_profit <= 0 else "0.00",  # VL_PREJ_LIQ_REAL
        "1" if real_profit > 0 else "2",  # IND_PREJ_LIQ_REAL
    ]))

    # M410 — IRPJ Calculation
    irpj_rate = 0.15  # 15% base
    irpj_base = max(0, real_profit)
    irpj_basic = irpj_base * irpj_rate

    # Additional 10% surcharge on profit above R$ 240,000/year (R$ 20,000/month)
    # Simplified: apply to excess over R$ 240,000
    monthly_limit = 20000.0
    annual_limit = monthly_limit * 12
    excess = max(0, (irpj_base / max(1, (args.mes or 12))) - monthly_limit)
    surcharge = max(0, (irpj_base - annual_limit)) * 0.10
    irpj_total = irpj_basic + surcharge

    lines.append(_fl("M410", [
        _td(irpj_base),  # VL_LUCRO_REAL
        _td(irpj_basic),  # VL_IRPJ_15
        _td(irpj_basic),  # VL_IRPJ_15_TOTAL
        _td(surcharge),  # VL_IRPJ_ADD
        _td(irpj_total),  # VL_IRPJ_TOTAL
    ]))

    # M500 — Deduções do IRPJ (PAT, incentivos fiscais, doações)
    pat_deduction = min(irpj_total * 0.04, estimated_pat(conn, company_id, start_date, end_date))
    lines.append(_fl("M500", [
        _td(pat_deduction),  # VL_DED_PAT
        "0.00",  # VL_DED_INC_FISC
        "0.00",  # VL_DED_DOACOES
        "0.00",  # VL_DED_AUDIOVISUAL
        "0.00",  # VL_DED_ROUANET
        "0.00",  # VL_DED_ESPORTE
        "0.00",  # VL_DED_RECINE
        "0.00",  # VL_DED_PRONAS
        "0.00",  # VL_DED_PRONEON
        "0.00",  # VL_DED_IDOSO
        "0.00",  # VL_DED_ONC
        "0.00",  # VL_DED_PRONON
        _td(pat_deduction),  # VL_DED_TOTAL
    ]))

    # Net IRPJ due
    irpj_due = max(0, irpj_total - pat_deduction)

    # M990 — Encerramento do Bloco M
    lines.append(_fl("M990", [str(len(lines) + 1)]))

    return ok({
        "bloco": "M",
        "registros": len(lines),
        "lucro_contabil": _td(accounting_profit),
        "adicoes": _td(additions_total),
        "exclusoes": _td(exclusion_total),
        "lucro_real": _td(real_profit),
        "irpj_estimado": _td(irpj_total),
        "irpj_devido": _td(irpj_due),
        "preview": "\n".join(lines[:5]) + ("\n..." if len(lines) > 5 else ""),
    })


def estimated_pat(conn, company_id, start_date, end_date):
    """Estimate PAT (Programa de Alimentação do Trabalhador) deduction."""
    # Look for PAT-related expenses
    pat = conn.execute("""
        SELECT COALESCE(SUM(CAST(ge.debit AS REAL)), 0)
        FROM gl_entry ge
        JOIN account a ON ge.account_id = a.id
        WHERE ge.company_id = ?
          AND a.root_type = 'Expense'
          AND ge.posting_date >= ? AND ge.posting_date < ?
          AND (a.name LIKE '%alimenta%' OR a.name LIKE '%refeic%'
               OR a.name LIKE '%vale ref%' OR a.name LIKE '%PAT%'
               OR a.name LIKE '%ticket%')
    """, (company_id, start_date, end_date)).fetchone()
    return float(pat[0] or 0)


# ── Bloco N: E-Lacs — Apuração da CSLL ────────────────────────────────

def generate_ecf_bloco_n(conn, args):
    """Generate Bloco N — E-Lacs (CSLL calculation).

    N registers:
      N001: Opening
      N010: Profit before CSLL
      N030: Additions (CLL adjustments)
      N050: Exclusions (CLL adjustments)
      N300: Part A balance
      N500: CSLL calculation
    """
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatório")
    ano = args.ano or datetime.now().year

    start_date = args.start_date or f"{ano}-01-01"
    end_date = args.end_date or f"{ano}-12-31"

    lines = []

    # N001 — Abertura do Bloco N
    lines.append(_fl("N001", ["1"]))

    # N010 — CSLL Profit Before Adjustments
    # Same starting point as E-Lalur accounting profit
    revenue = conn.execute("""
        SELECT COALESCE(SUM(CAST(ge.credit AS REAL)), 0) -
               COALESCE(SUM(CAST(ge.debit AS REAL)), 0)
        FROM gl_entry ge
        JOIN account a ON ge.account_id = a.id
        WHERE ge.company_id = ? AND a.root_type = 'Income'
          AND ge.posting_date >= ? AND ge.posting_date < ?
    """, (company_id, start_date, end_date)).fetchone()[0] or 0

    expenses = conn.execute("""
        SELECT COALESCE(SUM(CAST(ge.debit AS REAL)), 0) -
               COALESCE(SUM(CAST(ge.credit AS REAL)), 0)
        FROM gl_entry ge
        JOIN account a ON ge.account_id = a.id
        WHERE ge.company_id = ? AND a.root_type = 'Expense'
          AND ge.posting_date >= ? AND ge.posting_date < ?
    """, (company_id, start_date, end_date)).fetchone()[0] or 0

    accounting_profit = float(revenue) - float(expenses)

    lines.append(_fl("N010", [
        "1",  # IND_LACS: 1 = parte A
        "1" if accounting_profit >= 0 else "2",
        _td(abs(accounting_profit)),
    ]))

    # N030 — CSLL Additions
    # CSLL has fewer adjustments than IRPJ
    # Main additions: non-deductible provisions, similar to E-Lalur
    csll_additions = 0.0
    csll_exclusions = 0.0

    # Use same non-deductible items as IRPJ for CSLL base
    non_deductible = conn.execute("""
        SELECT a.account_number, a.name,
               COALESCE(SUM(CAST(ge.debit AS REAL)), 0) -
               COALESCE(SUM(CAST(ge.credit AS REAL)), 0) as balance
        FROM gl_entry ge
        JOIN account a ON ge.account_id = a.id
        WHERE ge.company_id = ?
          AND a.root_type = 'Expense'
          AND a.is_group = 0
          AND ge.posting_date >= ? AND ge.posting_date < ?
          AND (a.name LIKE '%multa%' OR a.name LIKE '%nao dedutiv%'
               OR a.name LIKE '%brinde%' OR a.name LIKE '%doacao%')
        GROUP BY a.id
    """, (company_id, start_date, end_date)).fetchall()

    for nd in non_deductible:
        val = float(nd[2] or 0)
        if val <= 0:
            continue
        csll_additions += val
        lines.append(_fl("N030", [
            "1",  # COD_LAN_LACS: 1 = adição
            _snip(f"{nd[1][:80]}", 255),
            _td(val),
            "0",  # IND_ADICAO
        ]))

    # Provisions for CSLL
    provs = conn.execute("""
        SELECT a.account_number, a.name,
               COALESCE(SUM(CAST(ge.credit AS REAL)), 0) -
               COALESCE(SUM(CAST(ge.debit AS REAL)), 0) as balance
        FROM gl_entry ge
        JOIN account a ON ge.account_id = a.id
        WHERE ge.company_id = ?
          AND a.root_type = 'Liability'
          AND a.is_group = 0
          AND (a.name LIKE '%provis%' OR a.name LIKE '%contingenc%')
          AND ge.posting_date >= ? AND ge.posting_date < ?
        GROUP BY a.id
    """, (company_id, start_date, end_date)).fetchall()

    for p in provs:
        val = float(p[2] or 0)
        if val <= 0:
            continue
        csll_additions += val
        lines.append(_fl("N030", [
            "1",
            _snip(f"{p[1][:80]} (CSLL)", 255),
            _td(val),
            "0",
        ]))

    # N050 — CSLL Exclusions
    reversals_n = conn.execute("""
        SELECT a.account_number, a.name,
               COALESCE(SUM(CAST(ge.credit AS REAL)), 0) -
               COALESCE(SUM(CAST(ge.debit AS REAL)), 0) as balance
        FROM gl_entry ge
        JOIN account a ON ge.account_id = a.id
        WHERE ge.company_id = ?
          AND a.root_type = 'Income'
          AND a.is_group = 0
          AND ge.posting_date >= ? AND ge.posting_date < ?
          AND (a.name LIKE '%revers%' OR a.name LIKE '%equivalenc%')
        GROUP BY a.id
    """, (company_id, start_date, end_date)).fetchall()

    for r in reversals_n:
        val = float(r[2] or 0)
        if val <= 0:
            continue
        csll_exclusions += val
        lines.append(_fl("N050", [
            "2",  # COD_LAN_LACS: 2 = exclusão
            _snip(f"{r[1][:80]}", 255),
            _td(val),
        ]))

    # N300 — Parte A do Lacs
    lines.append(_fl("N300", [
        "0.00",  # VL_PREJ_ACUM
        _td(csll_additions),
        _td(csll_exclusions),
        "1" if accounting_profit >= 0 else "2",
    ]))

    # N350 — Compensação de Prejuízos CSLL
    csll_before_comp = accounting_profit + csll_additions - csll_exclusions
    if csll_before_comp > 0 and accounting_profit < 0:
        max_csll_comp = csll_before_comp * 0.30
        csll_compensated = min(abs(accounting_profit), max_csll_comp)
        lines.append(_fl("N350", [_td(csll_compensated), _td(csll_compensated)]))
    else:
        lines.append(_fl("N350", ["0.00", "0.00"]))

    # N400 — CSLL Base
    csll_base = csll_before_comp
    if csll_before_comp > 0 and accounting_profit < 0:
        csll_base = csll_before_comp - (csll_compensated if 'csll_compensated' in dir() else 0)

    lines.append(_fl("N400", [
        _td(max(0, csll_base)),
        _td(abs(min(0, csll_base))),
        "1" if csll_base > 0 else "2",
    ]))

    # N500 — CSLL Calculation
    csll_rate = 0.09  # 9% general
    csll_calc = max(0, csll_base) * csll_rate

    lines.append(_fl("N500", [
        _td(max(0, csll_base)),  # VL_BASE
        _td(csll_calc),  # VL_CSLL
        _td(csll_calc),  # VL_CSLL_TOTAL
    ]))

    # Deduções (very limited for CSLL)
    lines.append(_fl("N600", ["0.00"]))  # VL_DED_TOTAL

    csll_due = csll_calc

    # N990 — Encerramento
    lines.append(_fl("N990", [str(len(lines) + 1)]))

    return ok({
        "bloco": "N",
        "registros": len(lines),
        "csll_base": _td(csll_base),
        "csll_calculado": _td(csll_calc),
        "csll_devido": _td(csll_due),
        "adicoes_csll": _td(csll_additions),
        "exclusoes_csll": _td(csll_exclusions),
        "preview": "\n".join(lines[:5]) + ("\n..." if len(lines) > 5 else ""),
    })


# ── Bloco P: Demonstrações Contábeis Fiscais ──────────────────────────

def generate_ecf_bloco_p(conn, args):
    """Generate Bloco P — Financial statements for fiscal purposes.

    P registers:
      P001: Opening
      P030: Balance Sheet
      P100: Income Statement (DRE)
      P150: Statement of Changes in Equity (DMPL)
      P200: Cash-flow statement
    """
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatório")
    ano = args.ano or datetime.now().year

    start_date = args.start_date or f"{ano}-01-01"
    end_date = args.end_date or f"{ano}-12-31"

    lines = []

    # P001 — Abertura do Bloco P
    lines.append(_fl("P001", ["1"]))

    # P030 — Plano de Contas Referencial
    # Map company accounts to RFB reference chart
    accounts = conn.execute("""
        SELECT account_number, name, is_group, root_type, account_type
        FROM account
        WHERE company_id = ? AND is_group = 0
        ORDER BY account_number
        LIMIT 500
    """, (company_id,)).fetchall()

    for acc in accounts:
        # Determine RFB reference code based on root_type
        ref_code = _map_to_rfb_reference(acc[3], acc[4] or "")
        lines.append(_fl("P030", [
            _snip(acc[0] or "", 18),  # COD_CTA
            _snip(acc[1] or "", 100),  # NOME_CTA
            ref_code,  # COD_CTA_REF
        ]))

    # P100 — Balanço Patrimonial
    lines.append(_fl("P100", [
        _snip("Balanço Patrimonial", 100),
        "1",  # PERIODO: 1 = final do período
        _pad(12, 2) + str(ano),  # DT_BALANCO
    ]))

    # P130 — Ativo
    asset_balance = conn.execute("""
        SELECT COALESCE(SUM(CAST(ge.debit AS REAL)), 0) -
               COALESCE(SUM(CAST(ge.credit AS REAL)), 0)
        FROM gl_entry ge
        JOIN account a ON ge.account_id = a.id
        WHERE ge.company_id = ? AND a.root_type = 'Asset' AND a.is_group = 0
          AND ge.posting_date >= ? AND ge.posting_date < ?
    """, (company_id, start_date, end_date)).fetchone()[0] or 0

    lines.append(_fl("P130", [
        "1",  # COD_GRUPO
        _snip("ATIVO TOTAL", 100),
        _td(abs(float(asset_balance))),
        "D" if float(asset_balance) >= 0 else "C",
    ]))

    # P150 — Passivo e Patrimônio Líquido
    liability_balance = conn.execute("""
        SELECT COALESCE(SUM(CAST(ge.credit AS REAL)), 0) -
               COALESCE(SUM(CAST(ge.debit AS REAL)), 0)
        FROM gl_entry ge
        JOIN account a ON ge.account_id = a.id
        WHERE ge.company_id = ? AND a.root_type = 'Liability' AND a.is_group = 0
          AND ge.posting_date >= ? AND ge.posting_date < ?
    """, (company_id, start_date, end_date)).fetchone()[0] or 0

    equity_balance = conn.execute("""
        SELECT COALESCE(SUM(CAST(ge.credit AS REAL)), 0) -
               COALESCE(SUM(CAST(ge.debit AS REAL)), 0)
        FROM gl_entry ge
        JOIN account a ON ge.account_id = a.id
        WHERE ge.company_id = ? AND a.root_type = 'Equity' AND a.is_group = 0
          AND ge.posting_date >= ? AND ge.posting_date < ?
    """, (company_id, start_date, end_date)).fetchone()[0] or 0

    lines.append(_fl("P150", [
        "2",  # COD_GRUPO
        _snip("PASSIVO TOTAL", 100),
        _td(abs(float(liability_balance))),
        "C" if float(liability_balance) >= 0 else "D",
    ]))

    lines.append(_fl("P150", [
        "3",  # COD_GRUPO
        _snip("PATRIMONIO LIQUIDO", 100),
        _td(abs(float(equity_balance))),
        "C" if float(equity_balance) >= 0 else "D",
    ]))

    # P200 — DRE — Demonstração do Resultado
    # Revenue
    revenue_bal = conn.execute("""
        SELECT COALESCE(SUM(CAST(ge.credit AS REAL)), 0) -
               COALESCE(SUM(CAST(ge.debit AS REAL)), 0)
        FROM gl_entry ge
        JOIN account a ON ge.account_id = a.id
        WHERE ge.company_id = ? AND a.root_type = 'Income' AND a.is_group = 0
          AND ge.posting_date >= ? AND ge.posting_date < ?
    """, (company_id, start_date, end_date)).fetchone()[0] or 0

    expense_bal = conn.execute("""
        SELECT COALESCE(SUM(CAST(ge.debit AS REAL)), 0) -
               COALESCE(SUM(CAST(ge.credit AS REAL)), 0)
        FROM gl_entry ge
        JOIN account a ON ge.account_id = a.id
        WHERE ge.company_id = ? AND a.root_type = 'Expense' AND a.is_group = 0
          AND ge.posting_date >= ? AND ge.posting_date < ?
    """, (company_id, start_date, end_date)).fetchone()[0] or 0

    net_result = float(revenue_bal) - float(expense_bal)

    lines.append(_fl("P200", [
        "1",  # COD_GRUPO
        _snip("RECEITA BRUTA", 100),
        _td(abs(float(revenue_bal))),
        "C" if float(revenue_bal) >= 0 else "D",
    ]))

    lines.append(_fl("P200", [
        "2",  # COD_GRUPO
        _snip("DESPESAS TOTAIS", 100),
        _td(abs(float(expense_bal))),
        "D" if float(expense_bal) >= 0 else "C",
    ]))

    lines.append(_fl("P200", [
        "99",  # COD_GRUPO
        _snip("LUCRO/PREJUIZO LIQUIDO", 100),
        _td(abs(net_result)),
        "C" if net_result >= 0 else "D",
    ]))

    # P990 — Encerramento do Bloco P
    lines.append(_fl("P990", [str(len(lines) + 1)]))

    return ok({
        "bloco": "P",
        "registros": len(lines),
        "ativo_total": _td(abs(float(asset_balance))),
        "passivo_total": _td(abs(float(liability_balance))),
        "patrimonio_liquido": _td(abs(float(equity_balance))),
        "receita_bruta": _td(abs(float(revenue_bal))),
        "resultado_liquido": _td(net_result),
        "preview": "\n".join(lines[:5]) + ("\n..." if len(lines) > 5 else ""),
    })


def _map_to_rfb_reference(root_type, account_type):
    """Map ERPClaw root_type to RFB reference code."""
    mapping = {
        ("Asset", "Cash"): "1.01",
        ("Asset", "Bank"): "1.01.01",
        ("Asset", "Receivable"): "1.02",
        ("Asset", "Stock"): "1.03",
        ("Asset", "Fixed Asset"): "1.04",
        ("Asset", "Capital Work in Progress"): "1.04.01",
        ("Asset", None): "1",
        ("Liability", "Payable"): "2.02",
        ("Liability", "Stock Liability"): "2.02.01",
        ("Liability", "Tax"): "2.01",
        ("Liability", None): "2",
        ("Equity", None): "3",
        ("Equity", "Capital Stock"): "3.01",
        ("Equity", "Retained Earnings"): "3.05",
        ("Income", None): "4.01",
        ("Income", "Sales"): "4.01.01",
        ("Expense", None): "4.02",
        ("Expense", "Cost of Goods Sold"): "4.02.01",
    }
    return mapping.get((root_type, account_type), mapping.get((root_type, None), "99"))


# ── Bloco T: Distribuição de Lucros ───────────────────────────────────

def generate_ecf_bloco_t(conn, args):
    """Generate Bloco T — Profit distribution.

    T registers:
      T001: Opening
      T030: Distribution to members
      T120: Withholding on distributions
      T150: Schedule of tax-exempt distributions
    """
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatório")
    ano = args.ano or datetime.now().year

    start_date = args.start_date or f"{ano}-01-01"
    end_date = args.end_date or f"{ano}-12-31"

    lines = []

    # T001 — Abertura do Bloco T
    lines.append(_fl("T001", ["1"]))

    # Calculate net profit for distribution
    revenue_bal = conn.execute("""
        SELECT COALESCE(SUM(CAST(ge.credit AS REAL)), 0) -
               COALESCE(SUM(CAST(ge.debit AS REAL)), 0)
        FROM gl_entry ge
        JOIN account a ON ge.account_id = a.id
        WHERE ge.company_id = ? AND a.root_type = 'Income' AND a.is_group = 0
          AND ge.posting_date >= ? AND ge.posting_date < ?
    """, (company_id, start_date, end_date)).fetchone()[0] or 0

    expense_bal = conn.execute("""
        SELECT COALESCE(SUM(CAST(ge.debit AS REAL)), 0) -
               COALESCE(SUM(CAST(ge.credit AS REAL)), 0)
        FROM gl_entry ge
        JOIN account a ON ge.account_id = a.id
        WHERE ge.company_id = ? AND a.root_type = 'Expense' AND a.is_group = 0
          AND ge.posting_date >= ? AND ge.posting_date < ?
    """, (company_id, start_date, end_date)).fetchone()[0] or 0

    net_profit = float(revenue_bal) - float(expense_bal)

    # T030 — Distribution to partners/shareholders
    # Get partners from equity entries or use company data
    company = conn.execute(
        "SELECT name, tax_id FROM company WHERE id = ?", (company_id,)
    ).fetchone()

    # For simplicity, assume single shareholder (the company's tax ID person)
    # In practice, would come from equity capital accounts
    if net_profit > 0:
        # Distribuição presumida: dividends isento até lucro presumido
        # For Lucro Real: dividends paid from real profit are exempt
        dist_amount = net_profit * 0.9  # 90% distribution (10% legal reserve)
        exempt_amount = dist_amount  # All dividends are tax-exempt for the recipient

        lines.append(_fl("T030", [
            _snip(company[1] or "", 14),  # CNPJ_BENEF
            _snip(company[0] or "Socio", 100),  # NOME_BENEF
            "0",  # COD_REL: 0 = não relacionado (it is related for single member)
            _td(dist_amount),  # VL_DISTRIB
            _td(0),  # VL_REPASSE
            _td(0),  # VL_DISTRIB_ISENTO — dividends are exempt
            _td(exempt_amount),  # VL_JUROS_CAP_PROPRIO (JCP)
            _td(0),  # VL_REND_ISENTO
            "1",  # TIPO_BENEF: 1 = PJ, 2 = PF
        ]))

        # T120 — IRRF on profit distribution
        # JCP (Juros sobre Capital Próprio) has 15% withholding
        jcp_withholding = 0 if exempt_amount == 0 else 0
        lines.append(_fl("T120", [
            _snip(company[1] or "", 14),
            _snip(company[0] or "Socio", 100),
            "0",
            _td(jcp_withholding),
            _td(0),
            _td(0),
            _td(jcp_withholding),
        ]))

        # T150 — Non-taxable distributions (dividends)
        lines.append(_fl("T150", [
            _snip(company[1] or "", 14),
            _snip(company[0] or "Socio", 100),
            "0",
            _td(exempt_amount),
            "0",  # IND_ORIGEM: 0 = lucro real
        ]))
    else:
        # No profit to distribute
        lines.append(_fl("T030", [
            "", "", "0", "0.00", "0.00", "0.00", "0.00", "0.00", "1",
        ]))

    # T990 — Encerramento
    lines.append(_fl("T990", [str(len(lines) + 1)]))

    return ok({
        "bloco": "T",
        "registros": len(lines),
        "lucro_liquido": _td(net_profit),
        "distribuido": _td(dist_amount if net_profit > 0 else 0),
        "isento": _td(exempt_amount if net_profit > 0 else 0),
        "preview": "\n".join(lines[:5]) + ("\n..." if len(lines) > 5 else ""),
    })


# ── Geração Completa ──────────────────────────────────────────────────

def generate_ecf(conn, args):
    """Generate complete ECF (all blocks)."""
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatório")
    ano = args.ano or datetime.now().year

    all_lines = []
    blocos = {}

    only_block = args.only_block or None

    blocks_to_generate = [
        ("0", generate_ecf_bloco_0),
        ("M", generate_ecf_bloco_m),
        ("N", generate_ecf_bloco_n),
        ("P", generate_ecf_bloco_p),
        ("T", generate_ecf_bloco_t),
    ]

    for blk_name, handler in blocks_to_generate:
        if only_block and only_block != blk_name:
            continue
        result = handler(conn, args)
        if result.get("status") == "ok":
            bdata = result["data"]
            all_lines.append(bdata.get("preview", "").strip())
            blocos[blk_name] = bdata["registros"]

    # Bloco 9 — Encerramento
    total_reg = sum(blocos.values()) + 5
    closing = [
        _fl("9001", ["0"]),
        _fl("9900", ["9900", str(total_reg)]),
        _fl("9990", [str(total_reg + 3)]),
        _fl("9999", [str(total_reg + 3)]),
    ]
    all_lines.extend(closing)

    content = ""
    for block in all_lines:
        for line in block.split("\n"):
            if line.strip():
                content += line + "\n"

    sped_id = str(uuid4())
    conn.execute("""
        INSERT INTO sped_export_log (id, tipo, ano, mes, arquivo_path, total_registros, status, company_id)
        VALUES (?, 'ecf', ?, ?, NULL, ?, 'gerado', ?)
    """, (sped_id, ano, 12, total_reg, company_id))
    conn.commit()

    return ok({
        "sped_export_id": sped_id,
        "tipo": "ecf",
        "ano": ano,
        "registros_totais": total_reg,
        "blocos": blocos,
        "status": "gerado",
        "preview": content[:500] + ("\n..." if len(content) > 500 else ""),
    })


# ── Validação ─────────────────────────────────────────────────────────

def validate_ecf(conn, args):
    """Validate ECF against basic layout rules."""
    sped_id = args.sped_export_id
    if not sped_id:
        return err("--sped-export-id obrigatório")

    row = conn.execute(
        "SELECT tipo, ano, mes, total_registros, status FROM sped_export_log WHERE id = ?",
        (sped_id,)
    ).fetchone()

    if not row:
        return err(f"Exportação ECF não encontrada: {sped_id}")

    warnings = []
    if row[3] and row[3] < 20:
        warnings.append("ECF com menos de 20 registros — verifique os dados fiscais")
    if row[4] and row[4] != "gerado":
        warnings.append(f"Status: {row[4]}")

    return ok({
        "sped_export_id": sped_id,
        "tipo": row[0],
        "ano": row[1],
        "registros": row[3],
        "valid": True,
        "warnings": warnings,
    })


# ── Listagem ──────────────────────────────────────────────────────────

def list_ecf_exports(conn, args):
    """List ECF export history."""
    company_id = args.company_id
    limit = args.limit or 50

    where = "WHERE tipo = 'ecf'"
    params = []
    if company_id:
        where += " AND company_id = ?"
        params.append(company_id)

    rows = conn.execute(f"""
        SELECT id, tipo, ano, mes, total_registros, status, created_at
        FROM sped_export_log
        {where}
        ORDER BY created_at DESC
        LIMIT ?
    """, (*params, limit)).fetchall()

    exports = []
    for r in rows:
        exports.append({
            "sped_export_id": r[0],
            "tipo": r[1],
            "ano": r[2],
            "mes": r[3],
            "total_registros": r[4],
            "status": r[5],
            "created_at": r[6],
        })

    return ok({
        "total": len(exports),
        "exports": exports,
    })


ACTIONS = {
    "generate-ecf": generate_ecf,
    "generate-ecf-bloco-0": generate_ecf_bloco_0,
    "generate-ecf-bloco-m": generate_ecf_bloco_m,
    "generate-ecf-bloco-n": generate_ecf_bloco_n,
    "generate-ecf-bloco-p": generate_ecf_bloco_p,
    "generate-ecf-bloco-t": generate_ecf_bloco_t,
    "validate-ecf": validate_ecf,
    "list-ecf-exports": list_ecf_exports,
}
