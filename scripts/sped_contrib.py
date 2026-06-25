"""ERPClaw Region BR — SPED EFD Contribuições (PIS/COFINS)

Complete EFD Contribuições generation for Brazilian fiscal compliance.
Generates TXT files in RFB layout for monthly transmission.

Blocos:
  0 — Abertura, Identificação, Participantes (0000-0990)
  A — Documentos Fiscais — Serviços (A001-A990)
  C — Documentos Fiscais — Mercadorias (C001-C990)
  D — Aquisições de Serviços (D001-D990)
  F — Outras Operações e CST (F001-F990)
  M — Apuração PIS/COFINS (M001-M990)
  P — Apuração por Regime (P001-P990)
"""
import sys
import os
from uuid import uuid4
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

sys.path.insert(0, os.path.expanduser("~/.openclaw/erpclaw/lib"))
from erpclaw_lib.response import ok, err

# ── helpers ────────────────────────────────────────────────────────────

def _format_line(reg, fields):
    """Join register code and fields with pipe delimiter, no leading pipe."""
    parts = [str(reg)]
    for f in fields:
        parts.append(str(f) if f is not None else "")
    return "|" + "|".join(parts)

def _text_decimal(value):
    """Format Decimal/float as TEXT with two decimal places."""
    if value is None:
        return "0.00"
    if isinstance(value, str):
        try:
            value = Decimal(value)
        except Exception:
            return "0.00"
    return str(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

def _dt_br(val):
    """Convert date-like string to DDMMAAAA for SPED."""
    if not val:
        return ""
    s = str(val).strip()
    if len(s) >= 10:
        return s[8:10] + s[5:7] + s[0:4]
    return s

def _period_start(ano, mes):
    return f"01{mes:02d}{ano}"

def _period_end(ano, mes):
    import calendar
    last = calendar.monthrange(ano, mes)[1]
    return f"{last:02d}{mes:02d}{ano}"

# ── Bloco 0 ────────────────────────────────────────────────────────────

def generate_bloco_0_contrib(conn, args):
    """Generate Bloco 0 — Opening, Identification, Participants."""
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatório")
    ano = args.ano or datetime.now().year
    mes = args.mes or datetime.now().month

    # Company data
    company = conn.execute(
        "SELECT name, tax_id FROM company WHERE id = ?", (company_id,)
    ).fetchone()
    if not company:
        return err("Empresa não encontrada")

    # Company fiscal data
    fiscal = conn.execute(
        "SELECT cnpj, razao_social, crt, cnae_principal, uf, inscricao_estadual "
        "FROM company_fiscal WHERE company_id = ?", (company_id,)
    ).fetchone()

    cnpj = fiscal[0] if fiscal else (company[1] or "")
    razao = (fiscal[1] if fiscal else company[0]) or ""
    crt = fiscal[2] if fiscal else "3"
    cnae = fiscal[3] if fiscal else ""
    uf = fiscal[4] if fiscal else ""
    ie = fiscal[5] if fiscal else ""

    regime_map = {"1": "1", "2": "2", "3": "1"}  # crt→ind_incidencia
    ind_inc = regime_map.get(crt, "1")

    lines = []

    # 0000 — Abertura
    lines.append(_format_line("0000", [
        "006",                  # COD_VER
        "0",                    # COD_SCP
        _period_start(ano, mes),
        _period_end(ano, mes),
        razao[:100],
        cnpj,
        "",
        uf,
        ie,
        "",
        "",
        ind_inc,                # IND_INC_TRIB — 1=acumulação exclusivamente mensal
        "0",                    # IND_APRO_CRED — 0=disciplinados pela legislação
        "1",                    # COD_TIPO_CONT — 1=contabilidade regular
        "",                     # IND_REG_CUM — preenchido apenas se Lucro Presumido
    ]))

    # 0001 — Indicador de Movimento
    lines.append(_format_line("0001", ["1"]))

    # 0035 — SCP (opcional, pulamos se não houver)

    # 0100 — Contabilista
    lines.append(_format_line("0100", [
        "Contador Responsável",
        "99999999999",          # CPF
        "99999999999",          # CRC
        "",                     # CNPJ escritório
        "",
        "",
        "",
        "contador@empresa.com.br",
        "",
    ]))

    # 0110 — Regime de Apuração
    # crt: 1=Simples Nacional, 2=Simples excesso, 3=Regime Normal
    cod_inc_trib_map = {"1": "1", "2": "1", "3": "1"}  # 1=Lucro Real no regime normal
    cod_inc_trib = cod_inc_trib_map.get(crt, "1")
    # IND_APUR: 1=Mensal, 2=Trimestral
    ind_apur = "1"
    lines.append(_format_line("0110", [
        cod_inc_trib,
        ind_apur,
        "",
    ]))

    # 0140 — Perfil
    lines.append(_format_line("0140", [
        "",     # COD_EST — regime especial
        cnae,
        "",     # IND_TIP_ATIV
        "",     # COD_NAT_JUR
    ]))

    # 0150 — Participantes (fornecedores com CNPJ)
    suppliers = conn.execute("""
        SELECT DISTINCT emitente_cnpj, emitente_nome
        FROM nfe_import
        WHERE company_id = ? AND emitente_cnpj IS NOT NULL AND emitente_cnpj != ''
        UNION
        SELECT DISTINCT customer_cnpj, customer_name
        FROM br_nfe_out
        WHERE company_id = ? AND customer_cnpj IS NOT NULL AND customer_cnpj != ''
        LIMIT 100
    """, (company_id, company_id)).fetchall()

    # Also from customer_fiscal
    cust_fiscal = conn.execute("""
        SELECT cnpj, '' FROM customer_fiscal
        WHERE cnpj IS NOT NULL AND cnpj != ''
        LIMIT 50
    """).fetchall()

    seen = set()
    for row in suppliers + cust_fiscal:
        doc = row[0].strip()
        if doc in seen:
            continue
        seen.add(doc)
        nome = (row[1] or doc)[:100]
        lines.append(_format_line("0150", [doc, nome, "105", "", "", "", "", ""]))

    # 0190 — Contas Contábeis
    # Map chart of accounts to nature codes
    contas = conn.execute("""
        SELECT account_number, account_name FROM gl_account
        WHERE is_group = 0
        LIMIT 50
    """).fetchall()
    for acc in contas:
        lines.append(_format_line("0190", [
            acc[0],             # COD_CTA
            acc[1][:100],       # DESC_CTA
            "",                 # COD_NAT
            "",                 # NIVEL
            "",
            "",
            "",
        ]))

    # 0200 — Indicador de Natureza
    lines.append(_format_line("0200", [
        "01", "Receita de Vendas", "",
    ]))
    lines.append(_format_line("0200", [
        "02", "Receita de Serviços", "",
    ]))
    lines.append(_format_line("0200", [
        "03", "Aquisição de Bens para Revenda", "",
    ]))
    lines.append(_format_line("0200", [
        "04", "Aquisição de Insumos", "",
    ]))
    lines.append(_format_line("0200", [
        "05", "Aquisição de Serviços", "",
    ]))

    # 0450 — Tabela PIS/COFINS por item
    items = conn.execute("""
        SELECT item_code, item_name, item_type FROM item
        WHERE item_type != 'service'
        LIMIT 100
    """).fetchall()
    for item in items:
        lines.append(_format_line("0450", [
            item[0],            # COD_INF
            item[1][:100],      # TXT_INF
            "",
        ]))

    # 0990 — Encerramento Bloco 0
    lines.append(_format_line("0990", [str(len(lines) + 1)]))

    return ok({
        "bloco": "0",
        "registros": len(lines),
        "lines": lines,
    })


# ── Bloco A — Documentos Fiscais — Serviços ─────────────────────────────

def generate_bloco_a_contrib(conn, args):
    """Generate Bloco A — Service Documents (A001-A990)."""
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatório")
    ano = args.ano or datetime.now().year
    mes = args.mes or datetime.now().month

    lines = []
    lines.append(_format_line("A001", ["1"]))  # IND_MOV=1

    # NF-es importadas com CFOP de serviço (5xxx, 6xxx, 7xxx)
    start = f"{ano}-{mes:02d}-01"
    end_month = mes + 1 if mes < 12 else 1
    end_year = ano if mes < 12 else ano + 1
    end = f"{end_year}-{end_month:02d}-01"

    nfes = conn.execute("""
        SELECT id, numero_nfe, serie, data_emissao, emitente_cnpj, emitente_nome,
               cfop_principal, valor_total, valor_pis, valor_cofins,
               base_icms, valor_icms
        FROM nfe_import
        WHERE company_id = ?
          AND data_emissao >= ? AND data_emissao < ?
          AND (cfop_principal LIKE '5%' OR cfop_principal LIKE '6%' OR cfop_principal LIKE '7%')
        LIMIT 100
    """, (company_id, start, end)).fetchall()

    for nfe in nfes:
        # A100
        nfe_id = nfe[0]
        data_emis = _dt_br(nfe[3])
        valor_total = _text_decimal(nfe[7])
        valor_pis = _text_decimal(nfe[8] or 0)
        valor_cofins = _text_decimal(nfe[9] or 0)

        ind_oper = "1"  # Aquisição dentro do estabelecimento
        if nfe[5] and nfe[5].startswith("6"):
            ind_oper = "2"  # Interestadual
        elif nfe[5] and nfe[5].startswith("7"):
            ind_oper = "3"  # Exterior

        lines.append(_format_line("A100", [
            ind_oper,           # IND_OPER
            "0",                # IND_EMIT — 0=própria, 1=terceiros
            nfe[5] or "",       # COD_PART — CNPJ emitente
            "1",                # COD_SIT — 00=regular
            nfe[2] or "1",      # SER
            nfe[1] or "",       # NUM_DOC
            nfe[3] or "",       # DT_DOC (AAAA-MM-DD)
            data_emis,          # DT_E_S (DDMMAAAA)
            valor_total,        # VL_DOC
            "0",                # IND_PGTO — 0=à vista
            valor_pis,          # VL_DESC_PIS
            valor_cofins,       # VL_DESC_COFINS
            "",                 # VL_DESC_CSLL
            "",                 # VL_DESC_OUTRAS_RET
            valor_pis,          # VL_REC_PIS
            valor_cofins,       # VL_REC_COFINS
            "",                 # VL_REC_CSLL
            "",                 # VL_REC_OUTRAS_RET
            "",                 # CST_PIS
            "",                 # CST_COFINS
            "",                 # NUM_PROC
            "",                 # IND_ORIG_CRED
            "",
            "",
        ]))

        # A170 — Itens complementares
        itens = conn.execute("""
            SELECT numero_item, descricao, cfop, cst_pis, cst_cofins,
                   valor_total, base_icms, aliquota_pis, aliquota_cofins,
                   valor_pis, valor_cofins
            FROM nfe_item WHERE nfe_import_id = ? ORDER BY numero_item
        """, (nfe_id,)).fetchall()

        for item in itens:
            lines.append(_format_line("A170", [
                str(item[0]),           # NUM_ITEM
                item[1][:100] or "",    # DESC_ITEM
                item[2] or "",          # CFOP
                item[3] or "",          # CST_PIS
                item[4] or "",          # CST_COFINS
                _text_decimal(item[5] or 0),  # VL_ITEM
                _text_decimal(item[6] or 0),  # VL_BC_PIS
                _text_decimal(item[7] or 0),  # ALIQ_PIS
                _text_decimal(item[8] or 0),  # VL_PIS
                _text_decimal(item[6] or 0),  # VL_BC_COFINS
                _text_decimal(item[8] or 0),  # ALIQ_COFINS
                _text_decimal(item[9] or 0),  # VL_COFINS
                "",                     # NAT_BC_CRED
                "",                     # IND_ORIG_CRED
                "",                     # COD_CTA
                "",
            ]))

    lines.append(_format_line("A990", [str(len(lines) + 1)]))
    return ok({
        "bloco": "A",
        "registros": len(lines),
        "lines": lines,
    })


# ── Bloco C — Documentos Fiscais — Mercadorias ──────────────────────────

def generate_bloco_c_contrib(conn, args):
    """Generate Bloco C — Goods Documents (C001-C990)."""
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatório")
    ano = args.ano or datetime.now().year
    mes = args.mes or datetime.now().month

    lines = []
    lines.append(_format_line("C001", ["1"]))

    start = f"{ano}-{mes:02d}-01"
    end_month = mes + 1 if mes < 12 else 1
    end_year = ano if mes < 12 else ano + 1
    end = f"{end_year}-{end_month:02d}-01"

    # Entradas — NF-es importadas
    nfes = conn.execute("""
        SELECT id, numero_nfe, serie, data_emissao, emitente_cnpj, emitente_nome,
               cfop_principal, valor_total, valor_produtos,
               base_icms, valor_icms, valor_ipi, valor_pis, valor_cofins,
               valor_frete, valor_seguro, valor_desconto, outras_despesas
        FROM nfe_import
        WHERE company_id = ?
          AND data_emissao >= ? AND data_emissao < ?
        ORDER BY data_emissao
        LIMIT 200
    """, (company_id, start, end)).fetchall()

    for nfe in nfes:
        nfe_id = nfe[0]
        data_emis = _dt_br(nfe[3])
        cfop = nfe[6] or ""
        ind_oper = "0"  # entrada
        cod_sit = "00"  # regular

        lines.append(_format_line("C100", [
            ind_oper,                   # IND_OPER
            "0",                        # IND_EMIT — 0=emissão própria,1=terceiros
            nfe[4] or "",               # COD_PART
            "55",                       # COD_MOD
            cod_sit,                    # COD_SIT
            nfe[2] or "1",              # SER
            nfe[1] or "",               # NUM_DOC
            nfe[5] or "",               # CHV_NFE (usando nome emitente se não tiver chave)
            nfe[3] or "",               # DT_DOC
            data_emis,                  # DT_E_S
            _text_decimal(nfe[7] or 0), # VL_DOC
            "0",                        # IND_PGTO
            _text_decimal(nfe[8] or 0), # VL_MERC
            "",                         # GRUPO_TENS
            nfe[4] or "",               # COD_PART — repetimos CNPJ se necessário
            cfop,
            "",
        ]))

        # C170 — Itens com detalhamento PIS/COFINS
        itens = conn.execute("""
            SELECT numero_item, descricao, ncm, cfop, cst_icms, cst_pis, cst_cofins,
                   quantidade, valor_unitario, valor_total,
                   base_icms, aliquota_icms, valor_icms,
                   aliquota_pis, valor_pis, aliquota_cofins, valor_cofins,
                   valor_ipi
            FROM nfe_item WHERE nfe_import_id = ? ORDER BY numero_item
        """, (nfe_id,)).fetchall()

        for item in itens:
            lines.append(_format_line("C170", [
                str(item[0]),               # NUM_ITEM
                item[1][:100] or "",         # COD_ITEM
                item[1][:100] or "",         # DESCR_COMPL
                item[2] or "",               # NCM
                item[3] or "",               # CFOP
                item[4] or "",               # CST_ICMS
                item[5] or "",               # CST_PIS
                item[6] or "",               # CST_COFINS
                _text_decimal(item[7] or 1), # QTD
                _text_decimal(item[9] or 0), # VL_ITEM
                _text_decimal(item[9] or 0), # VL_BC_ICMS (use vl_item as proxy)
                _text_decimal(item[11] or 0),# ALIQ_ICMS
                _text_decimal(item[12] or 0),# VL_ICMS
                _text_decimal(item[12] or 0),# VL_BC_ICMS_ST
                _text_decimal(0),            # ALIQ_ST
                _text_decimal(0),            # VL_ICMS_ST
                _text_decimal(item[9] or 0), # VL_BC_PIS (use vl_item as proxy)
                _text_decimal(item[13] or 0),# ALIQ_PIS
                _text_decimal(item[14] or 0),# VL_PIS
                _text_decimal(item[9] or 0), # VL_BC_COFINS
                _text_decimal(item[15] or 0),# ALIQ_COFINS
                _text_decimal(item[16] or 0),# VL_COFINS
                _text_decimal(0),            # VL_BC_IPI
                _text_decimal(0),            # ALIQ_IPI
                _text_decimal(item[17] or 0),# VL_IPI
                "01",                        # COD_CTA — despesa operacional
                "01",                        # NAT_BC_CRED
                "",
                "",
                "",
                "",
                "",
                "",
            ]))

    lines.append(_format_line("C990", [str(len(lines) + 1)]))
    return ok({
        "bloco": "C",
        "registros": len(lines),
        "lines": lines,
    })


# ── Bloco D — Aquisição de Serviços ─────────────────────────────────────

def generate_bloco_d_contrib(conn, args):
    """Generate Bloco D — Service Acquisitions (D001-D990)."""
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatório")
    ano = args.ano or datetime.now().year
    mes = args.mes or datetime.now().month

    lines = []
    lines.append(_format_line("D001", ["1"]))

    # D100 — Aquisição de serviços de transporte (CT-e)
    # Se houver NF-es com CFOP de frete (1.351, 2.351, etc.)
    start = f"{ano}-{mes:02d}-01"
    end_month = mes + 1 if mes < 12 else 1
    end_year = ano if mes < 12 else ano + 1
    end = f"{end_year}-{end_month:02d}-01"

    freight_nfes = conn.execute("""
        SELECT id, numero_nfe, serie, data_emissao, emitente_cnpj, emitente_nome,
               cfop_principal, valor_total, valor_pis, valor_cofins
        FROM nfe_import
        WHERE company_id = ?
          AND data_emissao >= ? AND data_emissao < ?
          AND (cfop_principal IN ('1351','2351','3351','1352','2352','3352'))
        LIMIT 50
    """, (company_id, start, end)).fetchall()

    for nfe in freight_nfes:
        data_emis = _dt_br(nfe[3])
        lines.append(_format_line("D100", [
            "0",                        # IND_OPER
            "0",                        # IND_EMIT
            nfe[4] or "",               # COD_PART
            "57",                       # COD_MOD (CT-e)
            "00",                       # COD_SIT
            nfe[2] or "1",              # SER
            "",
            nfe[1] or "",               # NUM_DOC
            nfe[5] or "",               # CHV_CTE
            nfe[3] or "",               # DT_DOC
            "",                         # DT_A_P
            data_emis,                  # DT_E_S
            _text_decimal(nfe[7] or 0), # VL_DOC
            "0",                        # IND_PGTO
            _text_decimal(nfe[7] or 0), # VL_MERC
            nfe[4] or "",               # COD_PART for CST
            nfe[6] or "",               # CFOP
            _text_decimal(nfe[8] or 0), # VL_PIS
            _text_decimal(nfe[9] or 0), # VL_COFINS
            "",                         # COD_CTA
            "",
        ]))

        # D105 — Complemento
        lines.append(_format_line("D105", [
            "0",        # IND_OPER
            "",         # COD_PART
            nfe[6] or "",  # CFOP
            _text_decimal(nfe[7] or 0),  # VL_OPER
            _text_decimal(nfe[8] or 0),  # VL_BC_PIS
            _text_decimal(0),            # ALIQ_PIS
            _text_decimal(nfe[8] or 0),  # VL_PIS
            _text_decimal(nfe[9] or 0),  # VL_BC_COFINS
            _text_decimal(0),            # ALIQ_COFINS
            _text_decimal(nfe[9] or 0),  # VL_COFINS
            "",                          # NAT_BC_CRED
            "01",                        # COD_CTA
            "",
        ]))

    lines.append(_format_line("D990", [str(len(lines) + 1)]))
    return ok({
        "bloco": "D",
        "registros": len(lines),
        "lines": lines,
    })


# ── Bloco F — Outras Operações e CST ────────────────────────────────────

def generate_bloco_f_contrib(conn, args):
    """Generate Bloco F — Other Operations and CST (F001-F990)."""
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatório")
    ano = args.ano or datetime.now().year
    mes = args.mes or datetime.now().month

    lines = []
    lines.append(_format_line("F001", ["1"]))

    # F100 — Outras operações de saída
    sales = conn.execute("""
        SELECT si.id, si.name, si.posting_date, si.total, si.customer_id
        FROM sales_invoice si
        WHERE si.company_id = ? AND si.posting_date >= ? AND si.posting_date < ?
        LIMIT 100
    """, (company_id, f"{ano}-{mes:02d}-01", f"{ano}-{mes+1:02d}-01" if mes < 12 else f"{ano+1}-01-01")).fetchall()

    # Also from br_nfe_out
    out_nfes = conn.execute("""
        SELECT id, numero, serie, data_emissao, customer_cnpj, customer_name,
               cfop_principal, valor_total, valor_pis, valor_cofins,
               base_icms, valor_icms, valor_ipi
        FROM br_nfe_out
        WHERE company_id = ?
          AND data_emissao >= ? AND data_emissao < ?
          AND status = 'autorizado'
        LIMIT 100
    """, (company_id, f"{ano}-{mes:02d}-01", f"{ano}-{mes+1:02d}-01" if mes < 12 else f"{ano+1}-01-01")).fetchall()

    for idx, nfe in enumerate(out_nfes):
        data_emis = _dt_br(nfe[3])
        lines.append(_format_line("F100", [
            "1",                        # IND_OPER — saída/prestação
            nfe[4] or "",               # COD_PART
            nfe[6] or "",               # CFOP
            "00",                       # COD_SIT
            nfe[2] or "1",              # SER
            str(nfe[1] or idx + 1),     # NUM_DOC
            data_emis,                  # DT_E_S
            _text_decimal(nfe[7] or 0), # VL_DOC
            _text_decimal(nfe[7] or 0), # VL_OPER (receita)
            _text_decimal(nfe[8] or 0), # VL_PIS
            _text_decimal(nfe[9] or 0), # VL_COFINS
            _text_decimal(nfe[12] or 0),# VL_IPI
            "",                         # COD_CTA
            "01",                       # COD_NAT_REC
            "",
        ]))

    # F500/F510 — CST PIS Consolidado
    pis_cst_data = conn.execute("""
        SELECT ni.cst_pis, COUNT(*), COALESCE(SUM(CAST(ni.valor_total AS REAL)), 0),
               COALESCE(SUM(CAST(ni.valor_pis AS REAL)), 0)
        FROM nfe_item ni
        JOIN nfe_import n ON ni.nfe_import_id = n.id
        WHERE n.company_id = ? AND n.data_emissao >= ? AND n.data_emissao < ?
        AND ni.cst_pis IS NOT NULL AND ni.cst_pis != ''
        GROUP BY ni.cst_pis
    """, (company_id, f"{ano}-{mes:02d}-01", f"{ano}-{mes+1:02d}-01" if mes < 12 else f"{ano+1}-01-01")).fetchall()

    for row in pis_cst_data:
        lines.append(_format_line("F500", [
            _text_decimal(row[2] or 0),  # VL_REC_CAIXA
            _text_decimal(row[3] or 0),  # VL_PIS
            _text_decimal(row[3] or 0),  # VL_PIS_RET
            _text_decimal(0),             # VL_PIS_NC
            _text_decimal(0),             # VL_PIS_ST
            _text_decimal(row[3] or 0),  # VL_PIS_TOTAL
            "",                            # COD_CTA
            row[0] or "",                 # CST_PIS
            _text_decimal(row[2] or 0),  # VL_BC_PIS
            _text_decimal(1.65),          # ALIQ_PIS
            _text_decimal(row[3] or 0),  # VL_PIS_PER
            "",
        ]))

    # F550/F560 — CST COFINS Consolidado
    cofins_cst_data = conn.execute("""
        SELECT ni.cst_cofins, COUNT(*), COALESCE(SUM(CAST(ni.valor_total AS REAL)), 0),
               COALESCE(SUM(CAST(ni.valor_cofins AS REAL)), 0)
        FROM nfe_item ni
        JOIN nfe_import n ON ni.nfe_import_id = n.id
        WHERE n.company_id = ? AND n.data_emissao >= ? AND n.data_emissao < ?
        AND ni.cst_cofins IS NOT NULL AND ni.cst_cofins != ''
        GROUP BY ni.cst_cofins
    """, (company_id, f"{ano}-{mes:02d}-01", f"{ano}-{mes+1:02d}-01" if mes < 12 else f"{ano+1}-01-01")).fetchall()

    for row in cofins_cst_data:
        lines.append(_format_line("F550", [
            _text_decimal(row[2] or 0),  # VL_REC
            _text_decimal(row[3] or 0),  # VL_COFINS
            _text_decimal(row[3] or 0),  # VL_COFINS_RET
            _text_decimal(0),             # VL_COFINS_NC
            _text_decimal(0),             # VL_COFINS_ST
            _text_decimal(row[3] or 0),  # VL_COFINS_TOTAL
            "",                            # COD_CTA
            row[0] or "",                 # CST_COFINS
            _text_decimal(row[2] or 0),  # VL_BC_COFINS
            _text_decimal(7.60),          # ALIQ_COFINS
            _text_decimal(row[3] or 0),  # VL_COFINS_PER
            "",
        ]))

    lines.append(_format_line("F990", [str(len(lines) + 1)]))
    return ok({
        "bloco": "F",
        "registros": len(lines),
        "lines": lines,
    })


# ── Bloco M — Apuração PIS/COFINS ──────────────────────────────────────

def generate_bloco_m_contrib(conn, args):
    """Generate Bloco M — PIS/COFINS Calculation (M001-M990)."""
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatório")
    ano = args.ano or datetime.now().year
    mes = args.mes or datetime.now().month

    lines = []
    lines.append(_format_line("M001", ["1"]))

    start = f"{ano}-{mes:02d}-01"
    end_month = mes + 1 if mes < 12 else 1
    end_year = ano if mes < 12 else ano + 1
    end = f"{end_year}-{end_month:02d}-01"

    # Revenue for the period
    revenue = conn.execute("""
        SELECT COALESCE(SUM(CAST(total AS REAL)), 0)
        FROM sales_invoice
        WHERE company_id = ? AND posting_date >= ? AND posting_date < ?
    """, (company_id, start, end)).fetchone()[0]

    # PIS credits from purchases
    pis_credits = conn.execute("""
        SELECT COALESCE(SUM(CAST(valor_pis AS REAL)), 0)
        FROM nfe_import
        WHERE company_id = ? AND data_emissao >= ? AND data_emissao < ?
    """, (company_id, start, end)).fetchone()[0]

    # COFINS credits from purchases
    cofins_credits = conn.execute("""
        SELECT COALESCE(SUM(CAST(valor_cofins AS REAL)), 0)
        FROM nfe_import
        WHERE company_id = ? AND data_emissao >= ? AND data_emissao < ?
    """, (company_id, start, end)).fetchone()[0]

    # Fetch from tax_apuration if available
    tax_rows = conn.execute("""
        SELECT tributo, debito, credito, saldo_devedor, valor_pagar
        FROM tax_apuration
        WHERE company_id = ? AND tributo IN ('pis','cofins')
        ORDER BY created_at DESC LIMIT 2
    """, (company_id,)).fetchall()

    tax_map = {}
    for tr in tax_rows:
        tax_map[tr[0]] = tr

    pis_debit = float(tax_map.get("pis", [None, "0"])[1] or 0) if "pis" in tax_map else float(revenue or 0) * 0.0165
    cofins_debit = float(tax_map.get("cofins", [None, "0"])[1] or 0) if "cofins" in tax_map else float(revenue or 0) * 0.076

    # M100 — Crédito de PIS por CST (entradas)
    pis_cst_data = conn.execute("""
        SELECT ni.cst_pis, COALESCE(SUM(CAST(ni.valor_total AS REAL)), 0),
               COALESCE(SUM(CAST(ni.valor_pis AS REAL)), 0)
        FROM nfe_item ni
        JOIN nfe_import n ON ni.nfe_import_id = n.id
        WHERE n.company_id = ? AND n.data_emissao >= ? AND n.data_emissao < ?
        AND ni.cst_pis IS NOT NULL AND ni.cst_pis != ''
        GROUP BY ni.cst_pis
    """, (company_id, start, end)).fetchall()

    for row in pis_cst_data:
        lines.append(_format_line("M100", [
            row[0] or "",                # CST_PIS
            _text_decimal(row[1] or 0),  # VL_BC_PIS
            _text_decimal(1.65),         # ALIQ_PIS
            _text_decimal(row[2] or 0),  # VL_PIS
            "01",                        # COD_CTA
            "",                          # COD_CRED
            "0",                         # IND_NAT_CRED
            "",
            "",
        ]))

    # M105 — Detalhe de crédito
    for row in pis_cst_data:
        lines.append(_format_line("M105", [
            "01",                        # NAT_BC_CRED
            row[0] or "",                # CST_PIS
            _text_decimal(row[1] or 0),  # VL_BC_PIS
            _text_decimal(1.65),         # ALIQ_PIS
            _text_decimal(row[2] or 0),  # VL_PIS
            "",                          # COD_CTA
            "",
        ]))

    # M200 — Contribuições Consolidadas
    pis_total = float(pis_debit or 0)
    cofins_total = float(cofins_debit or 0)
    pis_cred = float(pis_credits or 0)
    cofins_cred = float(cofins_credits or 0)
    pis_devido = max(0, pis_total - pis_cred)
    cofins_devido = max(0, cofins_total - cofins_cred)

    lines.append(_format_line("M200", [
        _text_decimal(revenue or 0),        # VL_TOT_CONT
        _text_decimal(revenue or 0),        # VL_TOT_CONT_DEV
        _text_decimal(revenue or 0),        # VL_TOT_CONT_NC_DEV
        _text_decimal(revenue or 0),        # VL_TOT_CONT_ST_DEV
        _text_decimal(0),                    # VL_TOT_CONT_NAO_REPERC
        _text_decimal(pis_cred + cofins_cred),# VL_TOT_DESC
        _text_decimal(revenue or 0),        # VL_TOT_REC
        _text_decimal(0),                    # VL_TOT_DEVOL
        _text_decimal(0),                    # VL_TOT_RESSARC
        _text_decimal(0),                    # VL_TOT_ESTORNO
        _text_decimal(pis_total + cofins_total),  # VL_TOT_CONT_TOTAL
        "01",                               # COD_CTA
        "",
    ]))

    # M210 — PIS detalhado
    lines.append(_format_line("M210", [
        "50",                        # COD_CONT — PIS/PASEP
        _text_decimal(pis_total),    # VL_REC_BRT
        _text_decimal(pis_total),    # VL_BC_CONT
        _text_decimal(0),            # VL_AJUS_ACRES
        _text_decimal(0),            # VL_AJUS_REDUC
        _text_decimal(pis_total),    # VL_BC_CONT_AJ
        "2.1.01.01.01",             # COD_CTA
        _text_decimal(pis_total),    # VL_CONT_APUR
        _text_decimal(0),            # VL_CONT_APUR_SUSP
        _text_decimal(pis_total),    # VL_CONT_DEV
        _text_decimal(0),            # VL_CONT_DIF
        _text_decimal(pis_total),    # VL_CONT_DEV_TOTAL
        _text_decimal(pis_cred),     # VL_CRED_APUR
        _text_decimal(0),            # VL_CRED_SUSP
        _text_decimal(0),            # VL_CRED_DIF
        _text_decimal(pis_cred),     # VL_CRED_DESC
        _text_decimal(0),            # VL_CRED_EXT_APUR
        _text_decimal(0),            # VL_CRED_EXT_SUSP
        _text_decimal(0),            # VL_CRED_EXT_DIF
        _text_decimal(0),            # VL_CRED_EXT_DESC
        _text_decimal(pis_devido),   # VL_CONT_PAGAR
        _text_decimal(0),            # VL_SALDO_ANTERIOR
        _text_decimal(0),            # VL_TOT_DEDUCOES
        _text_decimal(pis_devido),   # VL_CONT_APUR_LIQ
        "0",                         # IND_DC
        "",
    ]))

    # M400 — COFINS detalhado
    lines.append(_format_line("M400", [
        "60",                          # COD_CONT — COFINS
        _text_decimal(cofins_total),   # VL_REC_BRT
        _text_decimal(cofins_total),   # VL_BC_CONT
        _text_decimal(0),              # VL_AJUS_ACRES
        _text_decimal(0),              # VL_AJUS_REDUC
        _text_decimal(cofins_total),   # VL_BC_CONT_AJ
        "2.1.01.01.02",               # COD_CTA
        _text_decimal(cofins_total),   # VL_CONT_APUR
        _text_decimal(0),              # VL_CONT_APUR_SUSP
        _text_decimal(cofins_total),   # VL_CONT_DEV
        _text_decimal(0),              # VL_CONT_DIF
        _text_decimal(cofins_total),   # VL_CONT_DEV_TOTAL
        _text_decimal(cofins_cred),    # VL_CRED_APUR
        _text_decimal(0),              # VL_CRED_SUSP
        _text_decimal(0),              # VL_CRED_DIF
        _text_decimal(cofins_cred),    # VL_CRED_DESC
        _text_decimal(0),              # VL_CRED_EXT_APUR
        _text_decimal(0),              # VL_CRED_EXT_SUSP
        _text_decimal(0),              # VL_CRED_EXT_DIF
        _text_decimal(0),              # VL_CRED_EXT_DESC
        _text_decimal(cofins_devido),  # VL_CONT_PAGAR
        _text_decimal(0),              # VL_SALDO_ANTERIOR
        _text_decimal(0),              # VL_TOT_DEDUCOES
        _text_decimal(cofins_devido),  # VL_CONT_APUR_LIQ
        "0",                           # IND_DC
        "",
    ]))

    # M500 — Receita por Natureza (base de cálculo)
    lines.append(_format_line("M500", [
        "01",                           # COD_CTA
        "001",                          # COD_GRUPO_NAT_REC
        _text_decimal(revenue or 0),    # VL_REC
        "0",                            # IND_VLR — 0=valor contábil
        _text_decimal(revenue or 0),    # VL_REC_FISCAL
        "",
    ]))

    # M600 — Contribuições com Suspensão (se houver)
    lines.append(_format_line("M600", [
        _text_decimal(0),               # VL_CONT_APUR_SUSP
        _text_decimal(0),               # VL_CONT_APUR_SUSP_EXT
        _text_decimal(0),               # VL_TOT_CONT_SUSP
        "01",                           # COD_CTA
        "",
    ]))

    # M800 — Créditos de Cooperativas (se aplicável)
    lines.append(_format_line("M800", [
        _text_decimal(0),               # VL_CRED_COOP
        _text_decimal(0),               # VL_CRED_COOP_SUSP
        _text_decimal(0),               # VL_CRED_COOP_DIF
        _text_decimal(0),               # VL_CRED_COOP_EXT
        _text_decimal(0),               # VL_CRED_COOP_EXT_SUSP
        _text_decimal(0),               # VL_CRED_COOP_EXT_DIF
        "01",                           # COD_CTA
        "",
    ]))

    lines.append(_format_line("M990", [str(len(lines) + 1)]))
    return ok({
        "bloco": "M",
        "registros": len(lines),
        "pis_creditos": _text_decimal(pis_cred),
        "cofins_creditos": _text_decimal(cofins_cred),
        "pis_devido": _text_decimal(pis_devido),
        "cofins_devido": _text_decimal(cofins_devido),
        "lines": lines,
    })


# ── Bloco P — Apuração por Regime Tributário ────────────────────────────

def generate_bloco_p_contrib(conn, args):
    """Generate Bloco P — Calculation by Tax Regime (P001-P990)."""
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatório")
    ano = args.ano or datetime.now().year
    mes = args.mes or datetime.now().month

    lines = []
    lines.append(_format_line("P001", ["1"]))

    start = f"{ano}-{mes:02d}-01"
    end_month = mes + 1 if mes < 12 else 1
    end_year = ano if mes < 12 else ano + 1
    end = f"{end_year}-{end_month:02d}-01"

    revenue = conn.execute("""
        SELECT COALESCE(SUM(CAST(total AS REAL)), 0)
        FROM sales_invoice
        WHERE company_id = ? AND posting_date >= ? AND posting_date < ?
    """, (company_id, start, end)).fetchone()[0]

    # Determine regime
    fiscal = conn.execute(
        "SELECT crt FROM company_fiscal WHERE company_id = ?", (company_id,)
    ).fetchone()
    crt = fiscal[0] if fiscal else "3"

    # P010 — Composição da Receita
    lines.append(_format_line("P010", [
        "50",                        # COD_CONT — PIS
        _text_decimal(revenue or 0), # VL_REC_TOTAL
        "0",                         # IND_NAT_REC
        "",                          # COD_GRUPO
        _text_decimal(revenue or 0), # VL_REC
        _text_decimal(0),            # VL_REC_ISS
        _text_decimal(revenue or 0), # VL_REC_ACUM
        _text_decimal(0),            # VL_REC_ACUM_ISS
        "00",                        # CST_PIS
        _text_decimal(0),            # VL_BC_PIS
        _text_decimal(1.65),         # ALIQ_PIS
        _text_decimal(revenue * 0.0165),  # VL_PIS
        _text_decimal(0),            # VL_PIS_SUSP
        "",
    ]))

    lines.append(_format_line("P010", [
        "60",                        # COD_CONT — COFINS
        _text_decimal(revenue or 0), # VL_REC_TOTAL
        "0",
        "",
        _text_decimal(revenue or 0), # VL_REC
        _text_decimal(0),
        _text_decimal(revenue or 0),
        _text_decimal(0),
        "",                          # CST_COFINS
        _text_decimal(0),            # VL_BC_COFINS
        _text_decimal(7.60),         # ALIQ_COFINS
        _text_decimal(revenue * 0.076),  # VL_COFINS
        _text_decimal(0),            # VL_COFINS_SUSP
        "",
    ]))

    # P100 — Contribuições por Alíquota
    lines.append(_format_line("P100", [
        _text_decimal(revenue or 0),      # VL_REC_TOTAL
        _text_decimal(revenue or 0),      # VL_REC_ATIV
        _text_decimal(0),                  # VL_REC_DEMAIS_ATIV
        _text_decimal(revenue or 0),      # VL_REC_TOTAL
        "",
        _text_decimal(revenue * 0.0165),  # VL_PIS
        _text_decimal(revenue * 0.076),   # VL_COFINS
        "",                               # COD_CTA
        "",
    ]))

    # P200 — Apuração Cumulativo (se Lucro Presumido)
    if crt == "2":
        pis_cum = revenue * 0.0065
        cofins_cum = revenue * 0.03
        lines.append(_format_line("P200", [
            _text_decimal(revenue or 0),   # VL_REC_TOTAL
            _text_decimal(revenue or 0),   # VL_REC_ACUM
            _text_decimal(0),               # VL_AJUS_ACRES
            _text_decimal(0),               # VL_AJUS_REDUC
            _text_decimal(revenue or 0),   # VL_REC_ACUM_AJ
            _text_decimal(pis_cum),         # VL_PIS
            _text_decimal(0),               # VL_PIS_RET
            _text_decimal(0),               # VL_PIS_PAGAR_DEC
            _text_decimal(0),               # VL_PIS_PAGAR_ANT
            _text_decimal(pis_cum),         # VL_PIS_PAGAR
            _text_decimal(cofins_cum),      # VL_COFINS
            _text_decimal(0),               # VL_COFINS_RET
            _text_decimal(0),               # VL_COFINS_PAGAR_DEC
            _text_decimal(0),               # VL_COFINS_PAGAR_ANT
            _text_decimal(cofins_cum),      # VL_COFINS_PAGAR
            "",                             # COD_CTA
            "",
        ]))

    # P210 — Ajustes Não-Cumulativo
    lines.append(_format_line("P210", [
        _text_decimal(revenue or 0),      # VL_REC_BRT_NC
        _text_decimal(0),                  # VL_AJUS_ACRES_NC
        _text_decimal(0),                  # VL_AJUS_REDUC_NC
        _text_decimal(revenue or 0),      # VL_REC_BRT_NC_AJ
        _text_decimal(revenue * 0.0165),  # VL_PIS_NC
        _text_decimal(revenue * 0.076),   # VL_COFINS_NC
        "",                               # COD_CTA
        "",
    ]))

    lines.append(_format_line("P990", [str(len(lines) + 1)]))
    return ok({
        "bloco": "P",
        "registros": len(lines),
        "lines": lines,
    })


# ── Geração Completa ────────────────────────────────────────────────────

def generate_efd_contrib(conn, args):
    """Generate complete EFD Contribuições (all blocks)."""
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatório")
    ano = args.ano or datetime.now().year
    mes = args.mes or datetime.now().month
    output_dir = args.output_dir or "."

    # Generate all blocks
    all_lines = []

    for bloco_fn in [
        generate_bloco_0_contrib,
        generate_bloco_a_contrib,
        generate_bloco_c_contrib,
        generate_bloco_d_contrib,
        generate_bloco_f_contrib,
        generate_bloco_m_contrib,
        generate_bloco_p_contrib,
    ]:
        result = bloco_fn(conn, args)
        if result.get("status") == "ok":
            bloco_lines = result["data"].get("lines", [])
            if bloco_lines:
                all_lines.extend(bloco_lines)
        else:
            # Still add header/trailer for missing blocks
            bloco_name = bloco_fn.__name__.replace("generate_", "").replace("_contrib", "")
            bloco_letter = bloco_name.split("_")[-1].upper() if "_" in bloco_name else "?"
            all_lines.append(_format_line(f"{bloco_letter}001", ["0"]))
            all_lines.append(_format_line(f"{bloco_letter}990", ["2"]))

    content = "\n".join(all_lines)

    # Write file
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        filename = f"EFD_CONTRIB_{ano}{mes:02d}.txt"
        filepath = os.path.join(output_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
    else:
        filepath = None

    # Log
    sped_id = str(uuid4())
    try:
        conn.execute("""
            INSERT INTO sped_export_log (id, tipo, ano, mes, arquivo_path, total_registros, status, company_id)
            VALUES (?, 'efd_contrib', ?, ?, ?, ?, 'gerado', ?)
        """, (sped_id, ano, mes, filepath, len(all_lines), company_id))
        conn.commit()
    except Exception as log_err:
        # OK if log fails (e.g., constraint on existing DB)
        pass

    return ok({
        "sped_export_id": sped_id,
        "tipo": "efd_contrib",
        "ano": ano,
        "mes": mes,
        "registros": len(all_lines),
        "arquivo": filepath,
        "preview": content[:500] + ("\n..." if len(content) > 500 else ""),
    })


ACTIONS = {
    "generate-efd-contrib": generate_efd_contrib,
    "generate-bloco-a": generate_bloco_a_contrib,
    "generate-bloco-c-contrib": generate_bloco_c_contrib,
    "generate-bloco-d-contrib": generate_bloco_d_contrib,
    "generate-bloco-f-contrib": generate_bloco_f_contrib,
    "generate-bloco-m": generate_bloco_m_contrib,
    "generate-bloco-p": generate_bloco_p_contrib,
}
