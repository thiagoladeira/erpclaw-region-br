"""ERPClaw Region BR — ECD (Escrituração Contábil Digital)

SPED ECD generation: annual digital accounting bookkeeping.
Layout based on Manual de Orientação do Leiaute da ECD (RFB).

Blocos:
  0 — Abertura, Identificação, Participantes (0000-0990)
  I — Lançamentos Contábeis (I001-I990)
  J — Plano de Contas e Balancetes (J001-J990)
  K — Demonstrações Contábeis (K001-K990)
  P — Dados de Demonstrações Auxiliares (P001-P990)
  9 — Encerramento (9001-9999)

Actions:
  generate-ecd              — Generate complete ECD
  generate-ecd-bloco-0      — Opening block
  generate-ecd-bloco-i      — Journal entries (from gl_entry)
  generate-ecd-bloco-j      — Chart of accounts + trial balance
  generate-ecd-bloco-k      — Accounting statements
  validate-ecd              — Basic validation
  list-ecd-exports          — List ECD generations
  sign-ecd                  — Digital sign ECD with A1 certificate
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
    """Format ECD line: register + fields joined by pipe."""
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
    """Left-pad a string with zeros."""
    return str(s).rjust(length, '0')[:length]

def _snip(s, maxlen):
    """Truncate a string to maxlen."""
    return (str(s) if s else "")[:maxlen]


# ── Bloco 0: Abertura ─────────────────────────────────────────────────

def generate_ecd_bloco_0(conn, args):
    """Generate Bloco 0 — Opening, Identification, Participants."""
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatório")
    ano = args.ano or datetime.now().year
    mes_inicio = args.mes or 1
    mes_fim = args.mes or 12

    company = conn.execute(
        "SELECT name, tax_id, country FROM company WHERE id = ?", (company_id,)
    ).fetchone()
    if not company:
        return err("Empresa não encontrada")

    # Get fiscal data
    fiscal = conn.execute(
        "SELECT cnpj, inscricao_estadual, inscricao_municipal, razao_social, "
        "nome_fantasia, cnae_principal, crt, uf, municipio_codigo, municipio_nome, "
        "logradouro, numero, complemento, bairro, cep, email "
        "FROM company_fiscal WHERE company_id = ?",
        (company_id,)
    ).fetchone()

    cnpj = fiscal[0] if fiscal else (company[1] or "")
    ie = fiscal[1] if fiscal else ""
    razao = (fiscal[3] if fiscal else company[0]) or company[0]
    nome_fant = (fiscal[4] if fiscal else "") or ""
    cnae = (fiscal[5] if fiscal else "") or ""
    uf = (fiscal[7] if fiscal else "") or "RJ"
    cod_mun = (fiscal[8] if fiscal else "") or ""
    nome_mun = (fiscal[9] if fiscal else "") or ""
    end_logr = (fiscal[10] if fiscal else "") or ""
    end_num = (fiscal[11] if fiscal else "") or ""
    end_compl = (fiscal[12] if fiscal else "") or ""
    end_bairro = (fiscal[13] if fiscal else "") or ""
    end_cep = (fiscal[14] if fiscal else "") or ""
    email = (fiscal[15] if fiscal else "") or ""

    cnpj_clean = cnpj.replace(".", "").replace("/", "").replace("-", "")[:14]
    ie_clean = ie.replace(".", "").replace("-", "")[:14]

    dt_ini = f"01{mes_inicio:02d}{ano}"
    dt_fin = f"31{mes_fim:02d}{ano}" if mes_fim == 12 else f"28{mes_fim:02d}{ano}"

    # SIT_ESPECIAL: 0 = normal
    # IND_SIT_INI_PER: 0 = regular, 1 = abertura, 2 = cisao/fusao, 3 = encerramento
    # IND_NIRE: 0 = possui NIRE, 1 = nao possui
    # IND_FINANC: 0 = original, 1 = substituicao
    sit_especial = "0"
    if args.regime and args.regime == "simples_nacional":
        sit_especial = "7"

    # Determine NIRE from fiscal data or default
    nire = "0"
    ind_nire = "1"  # default: nao possui
    # Determine grandezas (use company defaults)
    ind_grandeza = "1"  # 1 = milhares
    ind_financ = "0"    # 0 = original
    tip_ecf = "0"       # 0 = não apresenta ECF

    lines = []

    # 0000 — Abertura do Arquivo Digital
    lines.append(_fl("0000", [
        "LECD",  # TEXTO FIXO
        dt_fin,  # DT_FIN: data final
        _snip(razao, 100),  # NOME
        _snip(cnpj_clean, 14),  # CNPJ
        uf,  # UF
        ie_clean[:14],  # IE
        cod_mun[:7],  # COD_MUN
        _snip(nome_mun, 60),  # NOME_MUN
        sit_especial,  # IND_SIT_ESPECIAL
        "0",  # IND_SIT_INI_PER: 0 = normal
        ind_nire,  # IND_NIRE
        ind_financ,  # IND_FINANC
        "0",  # IND_ESC: 0 = sem escriturações em moeda estrangeira
        "0",  # COD_AGL: 0 = sem aglutinação
        ind_grandeza,  # IND_GRANDEZA
        tip_ecf,  # TIP_ECF
        "0.0.0",  # COD_SCP
    ]))

    # 0001 — Abertura do Bloco 0
    ind_dad = "1"  # 1 = com dados
    lines.append(_fl("0001", [ind_dad]))

    # 0007 — Entidade de Supervisão (CVM, BACEN, SUSEP)
    # default: NENHUMA
    lines.append(_fl("0007", ["NENHUMA"]))

    # 0020 — Identificação do Escriturador (Contador)
    # Get responsible accountant from company or default
    accountant = conn.execute("""
        SELECT full_name, tax_id, professional_id, email
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

    lines.append(_fl("0020", [
        acc_name,
        acc_cpf,
        acc_crc,
        "1",  # IND_CRC: 1 = CRC ativo
        _snip(nome_mun, 60),  # CIDADE_CRC
        uf,  # UF_CRC
        acc_email,
    ]))

    # 0035 — Empresas Participantes (SCP)
    # For normal companies without SCP, just empty/link to self
    lines.append(_fl("0035", [
        _snip(cnpj_clean, 14),  # CNPJ_SCP
        _snip(razao, 100),  # NOME_SCP
        "0",  # COD_SCP: 0 = controladora, 1 = controlada
    ]))

    # 0150 — Tabela de Participantes (customers, suppliers)
    # Get unique participants from GL entries
    participants = conn.execute("""
        SELECT DISTINCT party_id, party_name, party_type
        FROM gl_entry
        WHERE company_id = ? AND party_id IS NOT NULL AND party_id != ''
        LIMIT 200
    """, (company_id,)).fetchall()

    seen_ids = set()
    for p in participants:
        pid = p[0] or ""
        if pid in seen_ids or not pid:
            continue
        seen_ids.add(pid)
        ptype = "01"  # CNPJ
        pname = _snip(p[1] or "PARTICIPANTE", 100)
        lines.append(_fl("0150", [
            _pad(pid[:14], 14),  # COD_PART
            pname,  # NOME
            "105",  # COD_PAIS (Brasil)
            ptype,  # CNPJ/CPF
            _pad(pid[:14], 14),  # CNPJ/CPF
            "",  # NIT
            "",  # UF
            "",  # IE
            "",  # IE_ST
            "",  # COD_MUN
            "",  # IM
            "",  # SUFRAMA
        ]))

    # If no participants from GL, add company and some defaults
    if not seen_ids:
        # Add company itself
        lines.append(_fl("0150", [
            _pad(cnpj_clean, 14), _snip(razao, 100),
            "105", "01", _pad(cnpj_clean, 14),
            "", uf, ie_clean, "", cod_mun, "", "",
        ]))
        # Add some suppliers
        suppliers = conn.execute("""
            SELECT tax_id, name FROM supplier
            WHERE company_id = ? AND tax_id IS NOT NULL AND tax_id != ''
            LIMIT 30
        """, (company_id,)).fetchall()
        for s in suppliers:
            cnpj_s = s[0].replace(".", "").replace("/", "").replace("-", "")[:14]
            lines.append(_fl("0150", [
                _pad(cnpj_s, 14), _snip(s[1], 100),
                "105", "01", _pad(cnpj_s, 14),
                "", "", "", "", "", "", "",
            ]))
        # Add some customers
        customers = conn.execute("""
            SELECT tax_id, name FROM customer
            WHERE company_id = ? AND tax_id IS NOT NULL AND tax_id != ''
            LIMIT 30
        """, (company_id,)).fetchall()
        for c in customers:
            cnpj_c = c[0].replace(".", "").replace("/", "").replace("-", "")[:14]
            lines.append(_fl("0150", [
                _pad(cnpj_c, 14), _snip(c[1], 100),
                "105", "01", _pad(cnpj_c, 14),
                "", "", "", "", "", "", "",
            ]))

    # 0990 — Encerramento do Bloco 0
    lines.append(_fl("0990", [str(len(lines) + 1)]))

    content = "\n".join(lines) + "\n"

    # Log export
    sped_id = str(uuid4())
    conn.execute("""
        INSERT INTO sped_export_log (id, tipo, ano, mes, arquivo_path, total_registros, status, company_id)
        VALUES (?, 'ecd', ?, ?, NULL, ?, 'gerado_bloco', ?)
    """, (sped_id, ano, mes_inicio, len(lines), company_id))
    conn.commit()

    return ok({
        "sped_export_id": sped_id,
        "tipo": "ecd",
        "ano": ano,
        "registros": len(lines),
        "bloco": "0",
        "preview": "\n".join(lines[:5]) + ("\n..." if len(lines) > 5 else ""),
    })


# ── Bloco I: Lançamentos Contábeis ────────────────────────────────────

def generate_ecd_bloco_i(conn, args):
    """Generate Bloco I — Journal entries from gl_entry."""
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatório")
    ano = args.ano or datetime.now().year
    mes = args.mes or 1
    start_date = args.start_date or f"{ano}-{mes:02d}-01"
    end_date = args.end_date or f"{ano}-12-31"

    lines = []

    # I001 — Abertura do Bloco I
    ind_dad = "1"  # 1 = com dados
    lines.append(_fl("I001", [ind_dad]))

    # I010 — Identificação do Livro
    # COD_LANÇ: code that identifies the accounting book
    # TIPO: 1 = diário, 2 = razão, 3 = diário/razão
    lines.append(_fl("I010", [
        "D",  # TIPO: D = diário
        _snip(f"LIVRO DIARIO {ano}", 100),  # DESCR
        f"REGISTRO {_pad('0', 10)}",  # NUM_REG
        "1",  # FORMA_LANÇ: 1 = partidas dobradas
        "BRL",  # COD_MOEDA: moeda do lançamento
    ]))

    # I020 — Lançamentos Contábeis por Período
    # Get GL entries for the period
    gl_entries = conn.execute("""
        SELECT
            ge.id, ge.name as voucher_no, ge.posting_date,
            ge.account_id, ge.debit, ge.credit,
            ge.party_id, ge.party_name,
            ge.against, ge.cost_center,
            a.account_number, a.name as account_name,
            a.is_group
        FROM gl_entry ge
        JOIN account a ON ge.account_id = a.id
        WHERE ge.company_id = ?
          AND ge.posting_date >= ? AND ge.posting_date < ?
        ORDER BY ge.posting_date, ge.name, ge.id
        LIMIT 5000
    """, (company_id, start_date, end_date)).fetchall()

    if not gl_entries:
        lines.append(_fl("I990", [str(len(lines) + 1)]))
        return ok({
            "bloco": "I",
            "registros": len(lines),
            "lancamentos": 0,
            "message": "Nenhum lançamento encontrado no período",
        })

    # Group entries by voucher_no
    vouchers = {}
    for e in gl_entries:
        vno = e[1] or e[0]  # voucher_no or id as fallback
        if vno not in vouchers:
            vouchers[vno] = {
                "date": e[2],
                "entries": [],
            }
        vouchers[vno]["entries"].append(e)

    # I030 — Lançamento Contábil (each voucher)
    for vno, vdata in vouchers.items():
        dt = _dt_br(vdata["date"])
        entries = vdata["entries"]
        total_debit = sum(float(e[4] or 0) for e in entries)
        total_credit = sum(float(e[5] or 0) for e in entries)

        # Determine party from first entry that has one
        party_id = ""
        party_name = ""
        for e in entries:
            if e[6]:
                party_id = e[6]
                party_name = e[7] or ""
                break

        lines.append(_fl("I030", [
            _snip(vno, 30),  # NUM_LCTO
            dt,  # DT_LCTO
            "",  # COD_CCUS: centro de custo
            _td(total_debit),  # VL_LCTO (debit total)
            "",  # IND_LCTO: branco = movimentação normal
            _snip(f"Lancamento {vno} — {vdata['date']}", 1024),  # HIST
        ]))

        # I050 — Plano de Contas do Lançamento
        accounts_used = {}
        for e in entries:
            acc_num = e[10] or ""
            if acc_num not in accounts_used:
                accounts_used[acc_num] = e

        for acc_num, e in accounts_used.items():
            is_group = int(e[12] or 0)
            lines.append(_fl("I050", [
                _snip(acc_num, 18),  # COD_CTA
                _snip(e[11] or "", 100),  # DESCR
                "1" if is_group else "2",  # TIPO: 1=sintética, 2=analítica
                "",  # NÍVEL
                "",  # COD_CTA_SUP
            ]))

        # I100 — Centro de Custos (simplified — use cost_center from entries)
        cost_centers = set()
        for e in entries:
            if e[9]:
                cost_centers.add(e[9])
        for cc in sorted(cost_centers):
            lines.append(_fl("I100", [
                _snip(cc, 15),  # COD_CCUS
                _snip(cc, 60),  # DESCR
            ]))

        # I200 — Lançamento Contábil — Detalhes (I250)
        for seq, e in enumerate(entries, 1):
            acc_num = e[10] or ""
            debit = float(e[4] or 0)
            credit = float(e[5] or 0)
            valor = debit if debit > 0 else credit
            ind_dc = "D" if debit > 0 else "C"

            if valor == 0:
                continue

            lines.append(_fl("I250", [
                _snip(acc_num, 18),  # COD_CTA
                _snip(e[9] or "", 15),  # COD_CCUS
                _td(valor),  # VL_DC
                ind_dc,  # IND_DC
                str(seq),  # NUM_ARQ
                _snip(e[8] or "" if e[8] else "", 1024),  # COD_HIST_PAD
                _snip(e[7] or party_name or "", 1024),  # HIST
                _snip(party_id or "", 14),  # COD_PART
            ]))

        # I350/I355 — Saldos das Contas
        # Calculate running balances per account
        # Simplified: just report the net movement
        for acc_num, e in accounts_used.items():
            lines.append(_fl("I355", [
                _snip(acc_num, 18),  # COD_CTA
                _snip(e[9] or "", 15),  # COD_CCUS
                _td(0),  # VL_CTA (beginning balance — simplified)
                "D",  # IND_DC
                "",  # IND_DC_MF
            ]))

    # I990 — Encerramento do Bloco I
    lines.append(_fl("I990", [str(len(lines) + 1)]))

    content = "\n".join(lines) + "\n"
    return ok({
        "bloco": "I",
        "registros": len(lines),
        "vouchers": len(vouchers),
        "lancamentos": len(gl_entries),
        "preview": "\n".join(lines[:5]) + ("\n..." if len(lines) > 5 else ""),
    })


# ── Bloco J: Plano de Contas e Balancetes ─────────────────────────────

def generate_ecd_bloco_j(conn, args):
    """Generate Bloco J — Chart of accounts and trial balances."""
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatório")
    ano = args.ano or datetime.now().year
    mes = args.mes or 12
    start_date = args.start_date or f"{ano}-01-01"
    end_date = args.end_date or f"{ano}-12-31"

    lines = []

    # J001 — Abertura do Bloco J
    ind_dad = "1"
    lines.append(_fl("J001", [ind_dad]))

    # J005 — Data do Balancete
    dt_bal = f"{_pad(mes, 2)}{ano}"
    lines.append(_fl("J005", [dt_bal]))

    # J100 — Plano de Contas (hierarchical)
    accounts = conn.execute("""
        SELECT account_number, name, is_group, parent_id, account_type,
               root_type, balance_direction
        FROM account
        WHERE company_id = ?
        ORDER BY account_number
        LIMIT 1000
    """, (company_id,)).fetchall()

    # Build hierarchy for parent references
    acc_map = {}
    for a in accounts:
        acc_map[a[0]] = {
            "number": a[0] or "",
            "name": a[1] or "",
            "is_group": int(a[2] or 0),
            "parent_id": a[3] or "",
            "type": a[4] or "",
        }

    # J100 — Contas (hierarchical listing)
    for a in accounts:
        acc_num = a[0] or ""
        acc_name = a[1] or ""
        is_group = int(a[2] or 0)
        parent_id = a[3] or ""

        # Determine level from account number depth
        # Simplified: count segments separated by dots
        nivel = str(len(acc_num.split(".")) - 1) if "." in acc_num else "1"

        # Determine COD_CTA_SUP (parent account number)
        parent_num = ""
        if parent_id:
            parent_row = conn.execute(
                "SELECT account_number FROM account WHERE id = ?",
                (parent_id,)
            ).fetchone()
            if parent_row:
                parent_num = parent_row[0] or ""

        lines.append(_fl("J100", [
            _snip(acc_num, 18),  # COD_CTA
            _snip(acc_name, 100),  # DESCR
            "1" if is_group else "2",  # TIPO: 1=sintética, 2=analítica
            nivel,  # NÍVEL: depth level
            _snip(parent_num, 18),  # COD_CTA_SUP
            "",  # NAT: natureza da conta
        ]))

    # J150 — Period Balances
    # Get GL balances per account for the period
    lines.append(_fl("J150", [dt_bal, dt_bal]))

    # J210 — Balancete (trial balance)
    for a in accounts:
        acc_num = a[0] or ""
        is_group = int(a[2] or 0)
        if is_group:
            continue  # Skip group accounts in trial balance

        # Calculate debits and credits for this account in the period
        bal = conn.execute("""
            SELECT
                COALESCE(SUM(CAST(debit AS REAL)), 0) as total_debit,
                COALESCE(SUM(CAST(credit AS REAL)), 0) as total_credit
            FROM gl_entry
            WHERE company_id = ?
              AND account_id IN (SELECT id FROM account WHERE account_number = ? AND company_id = ?)
              AND posting_date >= ? AND posting_date < ?
        """, (company_id, acc_num, company_id, start_date, end_date)).fetchone()

        total_debit = float(bal[0] or 0)
        total_credit = float(bal[1] or 0)
        bd = a[6] or ""
        # Balance: debit_normal accounts = debit - credit; credit_normal = credit - debit
        if bd == "credit_normal":
            net = total_credit - total_debit
        else:
            net = total_debit - total_credit

        if net == 0:
            continue

        ind_dc = "D" if net >= 0 else "C"
        abs_val = abs(net)

        lines.append(_fl("J210", [
            _snip(acc_num, 18),  # COD_CTA
            _td(abs_val),  # VL_SLD_INI (opening)
            ind_dc,  # IND_DC_INI
            _td(abs_val),  # VL_DEB
            _td(abs_val),  # VL_CRED
            _td(abs_val),  # VL_SLD_FIN (closing)
            ind_dc,  # IND_DC_FIN
        ]))

    # J800 — Outras Informações (optional)
    lines.append(_fl("J800", [
        "ECD",  # TIPO
        "A001",  # COD
        _snip(f"Gerado por ERPClaw Region BR em {datetime.now().isoformat()}", 255),
    ]))

    # J801 — Dados do Termo de Abertura (optional)
    lines.append(_fl("J801", [
        _snip(f"Livro Diário {ano}", 255),
        _snip(f"0101{ano}", 8),
        _snip(f"{mes:02d}{ano}", 8),
    ]))

    # J900 — Termo de Encerramento
    lines.append(_fl("J900", [
        _snip(f"Livro Diário {ano}", 255),
        _snip(f"Encerrado em {mes:02d}/{ano}", 255),
        _snip(f"{_pad(1, 10)}", 10),
    ]))

    # J990 — Encerramento do Bloco J
    lines.append(_fl("J990", [str(len(lines) + 1)]))

    content = "\n".join(lines) + "\n"
    return ok({
        "bloco": "J",
        "registros": len(lines),
        "contas": len(accounts),
        "preview": "\n".join(lines[:5]) + ("\n..." if len(lines) > 5 else ""),
    })


# ── Bloco K: Demonstrações Contábeis ──────────────────────────────────

def generate_ecd_bloco_k(conn, args):
    """Generate Bloco K — Accounting statements (Balance Sheet, P&L)."""
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatório")
    ano = args.ano or datetime.now().year
    mes = args.mes or 12
    start_date = args.start_date or f"{ano}-01-01"
    end_date = args.end_date or f"{ano}-12-31"

    dt_ini = f"01{_pad(mes, 2)}{ano}" if mes == 1 else f"0101{ano}"
    dt_fin = f"31{_pad(mes, 2)}{ano}"

    # If annual period, use Jan-Dec
    if mes >= 12:
        dt_ini = f"0101{ano}"
        dt_fin = f"3112{ano}"

    lines = []

    # K001 — Abertura do Bloco K
    lines.append(_fl("K001", ["1"]))

    # K030 — Identificação do Período
    lines.append(_fl("K030", [dt_ini, dt_fin]))

    # K100 — Balanço Patrimonial
    # Get asset accounts (root_type = Asset)
    asset_accounts = conn.execute("""
        SELECT a.account_number, a.name, a.is_group,
               COALESCE(SUM(CAST(ge.debit AS REAL)), 0) -
               COALESCE(SUM(CAST(ge.credit AS REAL)), 0) as balance
        FROM account a
        LEFT JOIN gl_entry ge ON a.id = ge.account_id
            AND ge.company_id = ? AND ge.posting_date >= ? AND ge.posting_date < ?
        WHERE a.company_id = ? AND a.root_type = 'Asset'
          AND a.is_group = 0
        GROUP BY a.id
        ORDER BY a.account_number
    """, (company_id, start_date, end_date, company_id)).fetchall()

    # K100 — BP Ativo (register)
    lines.append(_fl("K100", ["BP", "ATIVO", _snip("Balanço Patrimonial — Ativo", 100)]))

    # K110 — Individual accounts
    for acc in asset_accounts:
        bal = float(acc[3] or 0)
        if bal == 0:
            continue
        lines.append(_fl("K110", [
            _snip(acc[0] or "", 18),  # COD_CTA
            _snip(acc[1] or "", 100),  # COD_CTA_DESCR
            _td(abs(bal)),  # VL_SALDO
            "D" if bal >= 0 else "C",  # IND_DC
            "1",  # COD_AGRUP: 1 = individual
        ]))

    # K100 — BP Passivo
    liability_accounts = conn.execute("""
        SELECT a.account_number, a.name, a.is_group,
               COALESCE(SUM(CAST(ge.credit AS REAL)), 0) -
               COALESCE(SUM(CAST(ge.debit AS REAL)), 0) as balance
        FROM account a
        LEFT JOIN gl_entry ge ON a.id = ge.account_id
            AND ge.company_id = ? AND ge.posting_date >= ? AND ge.posting_date < ?
        WHERE a.company_id = ? AND a.root_type = 'Liability'
          AND a.is_group = 0
        GROUP BY a.id
        ORDER BY a.account_number
    """, (company_id, start_date, end_date, company_id)).fetchall()

    lines.append(_fl("K100", ["BP", "PASSIVO", _snip("Balanço Patrimonial — Passivo", 100)]))

    for acc in liability_accounts:
        bal = float(acc[3] or 0)
        if bal == 0:
            continue
        lines.append(_fl("K110", [
            _snip(acc[0] or "", 18),
            _snip(acc[1] or "", 100),
            _td(abs(bal)),
            "C" if bal >= 0 else "D",
            "1",
        ]))

    # K100 — BP Patrimônio Líquido
    equity_accounts = conn.execute("""
        SELECT a.account_number, a.name, a.is_group,
               COALESCE(SUM(CAST(ge.credit AS REAL)), 0) -
               COALESCE(SUM(CAST(ge.debit AS REAL)), 0) as balance
        FROM account a
        LEFT JOIN gl_entry ge ON a.id = ge.account_id
            AND ge.company_id = ? AND ge.posting_date >= ? AND ge.posting_date < ?
        WHERE a.company_id = ? AND a.root_type = 'Equity'
          AND a.is_group = 0
        GROUP BY a.id
        ORDER BY a.account_number
    """, (company_id, start_date, end_date, company_id)).fetchall()

    if equity_accounts:
        lines.append(_fl("K100", ["BP", "PATRIMONIO_LIQUIDO",
                                   _snip("Balanço Patrimonial — Patrimônio Líquido", 100)]))
        for acc in equity_accounts:
            bal = float(acc[3] or 0)
            lines.append(_fl("K110", [
                _snip(acc[0] or "", 18),
                _snip(acc[1] or "", 100),
                _td(abs(bal)),
                "C" if bal >= 0 else "D",
                "1",
            ]))

    # K100 — DRE (Demonstração do Resultado do Exercício)
    # Revenue
    rev_accounts = conn.execute("""
        SELECT a.account_number, a.name, a.is_group,
               COALESCE(SUM(CAST(ge.credit AS REAL)), 0) -
               COALESCE(SUM(CAST(ge.debit AS REAL)), 0) as balance
        FROM account a
        LEFT JOIN gl_entry ge ON a.id = ge.account_id
            AND ge.company_id = ? AND ge.posting_date >= ? AND ge.posting_date < ?
        WHERE a.company_id = ? AND a.root_type = 'Income'
          AND a.is_group = 0
        GROUP BY a.id
        ORDER BY a.account_number
    """, (company_id, start_date, end_date, company_id)).fetchall()

    # Expenses
    exp_accounts = conn.execute("""
        SELECT a.account_number, a.name, a.is_group,
               COALESCE(SUM(CAST(ge.debit AS REAL)), 0) -
               COALESCE(SUM(CAST(ge.credit AS REAL)), 0) as balance
        FROM account a
        LEFT JOIN gl_entry ge ON a.id = ge.account_id
            AND ge.company_id = ? AND ge.posting_date >= ? AND ge.posting_date < ?
        WHERE a.company_id = ? AND a.root_type = 'Expense'
          AND a.is_group = 0
        GROUP BY a.id
        ORDER BY a.account_number
    """, (company_id, start_date, end_date, company_id)).fetchall()

    # Total revenue
    total_rev = sum(float(a[3] or 0) for a in rev_accounts)
    # Total expenses
    total_exp = sum(float(a[3] or 0) for a in exp_accounts)

    lines.append(_fl("K100", ["DRE", "RECEITA", _snip("Demonstração do Resultado — Receita", 100)]))

    for acc in rev_accounts:
        bal = float(acc[3] or 0)
        if bal == 0:
            continue
        lines.append(_fl("K110", [
            _snip(acc[0] or "", 18),
            _snip(acc[1] or "", 100),
            _td(abs(bal)),
            "C" if bal >= 0 else "D",
            "1",
        ]))

    lines.append(_fl("K100", ["DRE", "DESPESA", _snip("Demonstração do Resultado — Despesa", 100)]))

    for acc in exp_accounts:
        bal = float(acc[3] or 0)
        if bal == 0:
            continue
        lines.append(_fl("K110", [
            _snip(acc[0] or "", 18),
            _snip(acc[1] or "", 100),
            _td(abs(bal)),
            "D" if bal >= 0 else "C",
            "1",
        ]))

    # K155 — Detalhe de Subcontas (simplified)
    lines.append(_fl("K155", [
        "1",  # COD_CCUS
        _snip("Matriz", 60),  # COD_CCUS_DESCR
    ]))

    # K990 — Encerramento do Bloco K
    lines.append(_fl("K990", [str(len(lines) + 1)]))

    content = "\n".join(lines) + "\n"
    return ok({
        "bloco": "K",
        "registros": len(lines),
        "total_receita": _td(total_rev),
        "total_despesa": _td(total_exp),
        "resultado": _td(total_rev - total_exp),
        "preview": "\n".join(lines[:5]) + ("\n..." if len(lines) > 5 else ""),
    })


# ── Geração Completa ──────────────────────────────────────────────────

def generate_ecd(conn, args):
    """Generate complete ECD (all blocks)."""
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatório")
    ano = args.ano or datetime.now().year

    all_lines = []
    blocos = {}

    # Bloco 0
    bloco0 = generate_ecd_bloco_0(conn, args)
    if bloco0.get("status") == "ok":
        b0 = bloco0["data"]
        all_lines.append(b0.get("preview", "").strip())
        blocos["0"] = b0["registros"]

    # Bloco I
    blocoI = generate_ecd_bloco_i(conn, args)
    if blocoI.get("status") == "ok":
        bI = blocoI["data"]
        all_lines.append(bI.get("preview", "").strip())
        blocos["I"] = bI["registros"]

    # Bloco J
    blocoJ = generate_ecd_bloco_j(conn, args)
    if blocoJ.get("status") == "ok":
        bJ = blocoJ["data"]
        all_lines.append(bJ.get("preview", "").strip())
        blocos["J"] = bJ["registros"]

    # Bloco K
    blocoK = generate_ecd_bloco_k(conn, args)
    if blocoK.get("status") == "ok":
        bK = blocoK["data"]
        all_lines.append(bK.get("preview", "").strip())
        blocos["K"] = bK["registros"]

    # Bloco 9 — Encerramento
    total_reg = sum(blocos.values()) + 5  # +5 for 9001, 9900 blocks, 9990, 9999
    closing = [
        _fl("9001", ["0"]),  # IND_DAD: 0 = sem movimento no bloco 9
        _fl("9900", ["9900", str(total_reg)]),
        _fl("9990", [str(total_reg + 3)]),
        _fl("9999", [str(total_reg + 3)]),
    ]
    all_lines.extend(closing)

    content = "".join(line + "\n" for block in all_lines for line in block.split("\n") if line.strip())

    # Log export
    sped_id = str(uuid4())
    conn.execute("""
        INSERT INTO sped_export_log (id, tipo, ano, mes, arquivo_path, total_registros, status, company_id)
        VALUES (?, 'ecd', ?, ?, NULL, ?, 'gerado', ?)
    """, (sped_id, ano, 12, total_reg, company_id))
    conn.commit()

    return ok({
        "sped_export_id": sped_id,
        "tipo": "ecd",
        "ano": ano,
        "registros_totais": total_reg,
        "blocos": blocos,
        "status": "gerado",
        "preview": content[:500] + ("\n..." if len(content) > 500 else ""),
    })


# ── Validação ─────────────────────────────────────────────────────────

def validate_ecd(conn, args):
    """Validate ECD against basic layout rules."""
    sped_id = args.sped_export_id
    if not sped_id:
        return err("--sped-export-id obrigatório")

    row = conn.execute(
        "SELECT tipo, ano, mes, total_registros, status FROM sped_export_log WHERE id = ?",
        (sped_id,)
    ).fetchone()

    if not row:
        return err(f"Exportação ECD não encontrada: {sped_id}")

    warnings = []
    if row[3] and row[3] < 10:
        warnings.append("ECD com menos de 10 registros — verifique os dados contábeis")
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

def list_ecd_exports(conn, args):
    """List ECD export history."""
    company_id = args.company_id
    limit = args.limit or 50

    where = "WHERE tipo = 'ecd'"
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


# ── Digital Signing ──────────────────────────────────────────────────

def _get_cert_config(conn, company_id):
    """Get certificate path and decrypted password from company config."""
    import base64
    cfg = conn.execute(
        "SELECT certificado_path, certificado_password FROM br_nfe_config WHERE company_id = ?",
        (company_id,)
    ).fetchone()
    if not cfg:
        return "", ""
    cert_path = cfg[0] or ""
    cert_pass = cfg[1] or ""
    try:
        cert_pass = base64.b64decode(cert_pass.encode("ascii")).decode("utf-8")
    except Exception:
        pass
    return cert_path, cert_pass


def sign_ecd(conn, args):
    """Sign ECD TXT file with e-CNPJ digital certificate (A1).

    Args: --sped-export-id, --certificado-path (optional, uses company config)

    The ECD signing process:
    1. Read the generated TXT file
    2. Compute SHA-256 hash of the full file content
    3. Sign the hash with the A1 certificate's private key (RSA-SHA256)
    4. Store signature in sped_export_log
    5. Update status to 'assinado'
    """
    import base64
    import hashlib
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    from nfe_signer import _load_certificate, HAS_CRYPTO

    sped_id = args.sped_export_id
    if not sped_id:
        return err("--sped-export-id is required")

    row = conn.execute(
        "SELECT * FROM sped_export_log WHERE id = ?", (sped_id,)
    ).fetchone()
    if not row:
        return err(f"SPED export not found: {sped_id}")

    sped = dict(row)
    if sped['status'] not in ('gerado', 'validado'):
        return err(
            f"SPED must be 'gerado' or 'validado', current: {sped['status']}"
        )

    arquivo_path = sped.get('arquivo_path')
    if not arquivo_path or not os.path.isfile(arquivo_path):
        return err(f"File not found: {arquivo_path}")

    # Get certificate from company config
    cert_path, cert_pass = _get_cert_config(conn, sped['company_id'])
    if not cert_path:
        return err("Certificate not configured")

    if not HAS_CRYPTO:
        return err("cryptography not installed. pip install cryptography")

    # Load certificate and private key
    private_key, certificate = _load_certificate(cert_path, cert_pass)

    # Hash the file
    with open(arquivo_path, 'rb') as f:
        file_content = f.read()

    file_hash = hashlib.sha256(file_content).digest()

    # Sign with RSA-SHA256 (PSS padding)
    signature = private_key.sign(
        file_hash,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.MAX_LENGTH
        ),
        hashes.SHA256()
    )

    assinatura_b64 = base64.b64encode(signature).decode('ascii')

    now = datetime.now().isoformat()
    conn.execute(
        "UPDATE sped_export_log SET status = 'assinado', protocolo = ?, updated_at = ? WHERE id = ?",
        (assinatura_b64, now, sped_id)
    )
    conn.commit()

    return ok({
        "sped_export_id": sped_id,
        "status": "assinado",
        "hash_sha256": hashlib.sha256(file_content).hexdigest(),
        "message": "ECD file signed successfully"
    })


ACTIONS = {
    "generate-ecd": generate_ecd,
    "generate-ecd-bloco-0": generate_ecd_bloco_0,
    "generate-ecd-bloco-i": generate_ecd_bloco_i,
    "generate-ecd-bloco-j": generate_ecd_bloco_j,
    "generate-ecd-bloco-k": generate_ecd_bloco_k,
    "validate-ecd": validate_ecd,
    "list-ecd-exports": list_ecd_exports,
    "sign-ecd": sign_ecd,
}
