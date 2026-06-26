"""ERPClaw Region BR — Tax Calculation (Phase 3)

Real tax calculations with CST/CFOP/UF analysis, MVA tables,
Simples Nacional annexes, DARF/GNRE generation.

15 actions: ICMS, ICMS-ST, FECP, PIS/COFINS, DIFAL, Simples Nacional,
IRPJ/CSLL, CIAP, ISS, Withholding, Reconcile, DARF, GNRE,
list/close tax periods.
"""
import sys
import os
from uuid import uuid4
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

sys.path.insert(0, os.path.expanduser("~/.openclaw/erpclaw/lib"))
from erpclaw_lib.response import ok, err

# ═══════════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════════

# Interstate ICMS rates (Resolução Senado 22/89, updated 13/2012)
# 7%: products from Sul/Sudeste to other regions
# 12%: all other interstate transactions
_UF_REGIAO = {
    "AC": "NORTE", "AP": "NORTE", "AM": "NORTE", "PA": "NORTE", "RO": "NORTE", "RR": "NORTE", "TO": "NORTE",
    "AL": "NORDESTE", "BA": "NORDESTE", "CE": "NORDESTE", "MA": "NORDESTE",
    "PB": "NORDESTE", "PE": "NORDESTE", "PI": "NORDESTE", "RN": "NORDESTE", "SE": "NORDESTE",
    "DF": "CENTRO-OESTE", "GO": "CENTRO-OESTE", "MT": "CENTRO-OESTE", "MS": "CENTRO-OESTE",
    "ES": "SUDESTE", "MG": "SUDESTE", "RJ": "SUDESTE", "SP": "SUDESTE",
    "PR": "SUL", "RS": "SUL", "SC": "SUL",
}

# ICMS internal rates per UF (typical — actual rates vary)
_ICMS_INTERNO = {
    "SP": Decimal("18.00"), "RJ": Decimal("20.00"), "MG": Decimal("18.00"),
    "ES": Decimal("17.00"), "RS": Decimal("18.00"), "SC": Decimal("17.00"),
    "PR": Decimal("18.00"), "BA": Decimal("18.00"), "CE": Decimal("18.00"),
    "PE": Decimal("18.00"), "MA": Decimal("18.00"), "PI": Decimal("18.00"),
    "PB": Decimal("18.00"), "RN": Decimal("18.00"), "AL": Decimal("18.00"),
    "SE": Decimal("18.00"), "GO": Decimal("17.00"), "MT": Decimal("17.00"),
    "MS": Decimal("17.00"), "DF": Decimal("18.00"), "AM": Decimal("18.00"),
    "PA": Decimal("17.00"), "RO": Decimal("17.50"), "AC": Decimal("17.00"),
    "RR": Decimal("17.00"), "AP": Decimal("18.00"), "TO": Decimal("18.00"),
}

# PIS/COFINS non-cumulative rates
PIS_NAO_CUMULATIVO = Decimal("1.65")
COFINS_NAO_CUMULATIVO = Decimal("7.60")
# PIS/COFINS cumulative rates
PIS_CUMULATIVO = Decimal("0.65")
COFINS_CUMULATIVO = Decimal("3.00")

# IRPJ rates
IRPJ_BASE = Decimal("15.00")
IRPJ_ADICIONAL = Decimal("10.00")  # on excess above R$20k/month
IRPJ_ADICIONAL_LIMITE = Decimal("20000.00")
CSLL_BASE = Decimal("9.00")

# DARF codes
DARF_CODES = {
    "irpj": {"lucro_real_mensal": "0220", "lucro_presumido": "2089", "simples": "3373"},
    "csll": {"lucro_real_mensal": "2372", "lucro_presumido": "6012"},
    "pis_cumulativo": "8109",
    "pis_nao_cumulativo": "6912",
    "cofins_cumulativo": "2172",
    "cofins_nao_cumulativo": "5856",
    "ipi": "1097",
    "irrf": "1708",
    "retencoes": "5952",
}

# Simples Nacional Annex I (Commerce) — progressive rates
SIMPLES_ANEXO_I = [
    # (rbt12_max, aliquota, parcela_deduzir)
    (Decimal("180000.00"), Decimal("4.00"), Decimal("0.00")),
    (Decimal("360000.00"), Decimal("7.30"), Decimal("5940.00")),
    (Decimal("720000.00"), Decimal("9.50"), Decimal("13860.00")),
    (Decimal("1800000.00"), Decimal("10.70"), Decimal("22500.00")),
    (Decimal("3600000.00"), Decimal("14.30"), Decimal("87300.00")),
    (Decimal("4800000.00"), Decimal("19.00"), Decimal("378000.00")),
]

# Simples Nacional Annex II (Industry)
SIMPLES_ANEXO_II = [
    (Decimal("180000.00"), Decimal("4.50"), Decimal("0.00")),
    (Decimal("360000.00"), Decimal("7.80"), Decimal("5940.00")),
    (Decimal("720000.00"), Decimal("10.00"), Decimal("13860.00")),
    (Decimal("1800000.00"), Decimal("11.20"), Decimal("22500.00")),
    (Decimal("3600000.00"), Decimal("14.70"), Decimal("85500.00")),
    (Decimal("4800000.00"), Decimal("30.00"), Decimal("720000.00")),
]

# Simples Nacional Annex III (Services)
SIMPLES_ANEXO_III = [
    (Decimal("180000.00"), Decimal("6.00"), Decimal("0.00")),
    (Decimal("360000.00"), Decimal("11.20"), Decimal("9360.00")),
    (Decimal("720000.00"), Decimal("13.50"), Decimal("17640.00")),
    (Decimal("1800000.00"), Decimal("16.00"), Decimal("35640.00")),
    (Decimal("3600000.00"), Decimal("21.00"), Decimal("125640.00")),
    (Decimal("4800000.00"), Decimal("33.00"), Decimal("648000.00")),
]

# Tax breakdown percentages within each Simples annex bracket
SIMPLES_BREAKDOWN = {
    # annex -> [irpj, csll, cofins, pis, cpp, icms, ipi, iss]
    "I": [Decimal("5.50"), Decimal("3.50"), Decimal("12.74"), Decimal("2.76"), Decimal("41.50"), Decimal("34.00"), Decimal("0.00"), Decimal("0.00")],
    "II": [Decimal("5.50"), Decimal("3.50"), Decimal("11.51"), Decimal("2.49"), Decimal("37.50"), Decimal("39.50"), Decimal("0.00"), Decimal("0.00")],
    "III": [Decimal("4.00"), Decimal("3.50"), Decimal("12.82"), Decimal("2.78"), Decimal("43.40"), Decimal("0.00"), Decimal("0.00"), Decimal("33.50")],
}


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════

def _d(val) -> Decimal:
    """Convert to Decimal, defaulting to 0."""
    if val is None or val == "":
        return Decimal("0.00")
    try:
        return Decimal(str(val))
    except Exception:
        return Decimal("0.00")


def _fmt(val) -> str:
    """Format Decimal as string with 2 decimal places."""
    if isinstance(val, Decimal):
        return str(val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    return str(Decimal(str(val or "0")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _ensure_period(conn, company_id, ano, mes, regime="lucro_real") -> str:
    """Ensure a tax_period_br row exists and return its id."""
    data_inicio = f"{ano}-{mes:02d}-01"
    # Determine last day of month
    if mes == 12:
        data_fim = f"{ano}-12-31"
    else:
        next_month = datetime(ano, mes + 1, 1)
        last_day = (next_month.replace(month=next_month.month % 12 + 1, day=1) if mes < 11
                    else datetime(ano + 1, 1, 1)) - datetime.resolution
        import calendar
        data_fim = f"{ano}-{mes:02d}-{calendar.monthrange(ano, mes)[1]}"

    existing = conn.execute(
        "SELECT id FROM tax_period_br WHERE ano = ? AND mes = ? AND company_id = ?",
        (ano, mes, company_id)
    ).fetchone()
    if existing:
        return existing["id"]

    period_id = str(uuid4())
    conn.execute(
        """INSERT INTO tax_period_br (id, ano, mes, data_inicio, data_fim, regime, status, company_id)
           VALUES (?, ?, ?, ?, ?, ?, 'aberto', ?)""",
        (period_id, ano, mes, data_inicio, data_fim, regime, company_id)
    )
    return period_id


def _store_tax_apuration(conn, tax_period_id, tributo, uf, debito, credito, company_id,
                         saldo_devedor=None, saldo_credor=None, valor_pagar=None,
                         codigo_receita=None, extra_data=None) -> str:
    """Store a tax apuration row and return its id."""
    d, c = Decimal(str(debito)), Decimal(str(credito))
    saldo = d - c
    sd = saldo_devedor if saldo_devedor is not None else str(d - c) if d >= c else "0.00"
    sc = saldo_credor if saldo_credor is not None else str(c - d) if c > d else "0.00"
    vp = valor_pagar if valor_pagar is not None else str(max(Decimal("0.00"), d - c))

    apur_id = str(uuid4())
    conn.execute(
        """INSERT INTO tax_apuration
           (id, tax_period_br_id, tributo, uf, debito, credito, saldo_devedor, saldo_credor,
            valor_pagar, codigo_receita, status, company_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pendente', ?)""",
        (apur_id, tax_period_id, tributo, uf, _fmt(d), _fmt(c), _fmt(sd), _fmt(sc),
         _fmt(vp), codigo_receita, company_id)
    )
    return apur_id


def _get_item_fiscal(conn, item_id: str) -> dict:
    """Get item fiscal data from item_fiscal table."""
    row = conn.execute(
        "SELECT * FROM item_fiscal WHERE item_id = ?", (item_id,)
    ).fetchone()
    if row:
        return dict(row)
    return None


def _get_customer_uf(conn, customer_id: str) -> str:
    """Get customer's UF from customer_fiscal."""
    row = conn.execute(
        "SELECT uf FROM customer_fiscal WHERE customer_id = ?", (customer_id,)
    ).fetchone()
    if row and row["uf"]:
        return row["uf"].upper().strip()
    return None


def _get_company_uf(conn, company_id: str) -> str:
    """Get company's UF from company_fiscal."""
    row = conn.execute(
        "SELECT uf FROM company_fiscal WHERE company_id = ?", (company_id,)
    ).fetchone()
    if row and row["uf"]:
        return row["uf"].upper().strip()
    return None


def _get_mva(conn, uf: str, ncm: str, company_id: str) -> Decimal:
    """Look up MVA for ICMS ST by UF and NCM prefix (best match)."""
    if not ncm:
        return Decimal("0.00")
    ncm_clean = "".join(ch for ch in ncm if ch.isdigit())
    # Try exact 6-digit prefix, then 4-digit, then 2-digit
    for prefix_len in [6, 4, 2]:
        prefix = ncm_clean[:prefix_len]
        row = conn.execute(
            """SELECT mva_padrao FROM mva_st_config
               WHERE uf = ? AND ncm_prefix = ? AND is_active = 1 AND company_id = ?
               ORDER BY length(ncm_prefix) DESC LIMIT 1""",
            (uf, prefix, company_id)
        ).fetchone()
        if row:
            return _d(row["mva_padrao"])
    return Decimal("0.00")


def _get_fecp(conn, uf: str, company_id: str) -> Decimal:
    """Get FECP rate for a given UF."""
    row = conn.execute(
        "SELECT aliquota FROM fecp_config WHERE uf = ? AND is_active = 1 AND (company_id = ? OR company_id = '*')",
        (uf, company_id)
    ).fetchone()
    if row:
        return _d(row["aliquota"])
    # Fallback: default 2%
    return Decimal("2.00")


def _is_contribuinte(conn, customer_id: str) -> bool:
    """Check if customer is ICMS taxpayer (contribuinte_icms = 1)."""
    row = conn.execute(
        "SELECT contribuinte_icms FROM customer_fiscal WHERE customer_id = ?",
        (customer_id,)
    ).fetchone()
    if row and row["contribuinte_icms"] is not None:
        return int(row["contribuinte_icms"]) == 1
    # Default: assume contributor if has IE
    return True


def _get_aliq_interestadual(uf_origem: str, uf_destino: str) -> Decimal:
    """Return interstate ICMS rate based on origin/destination regions.

    7%: products from Sul/Sudeste (except ES) to other regions
    12%: all other interstate operations
    """
    reg_origem = _UF_REGIAO.get(uf_origem, "")
    reg_destino = _UF_REGIAO.get(uf_destino, "")

    if reg_origem in ("SUL", "SUDESTE") and reg_destino not in ("SUL", "SUDESTE"):
        # Sul/Sudeste → other regions
        return Decimal("7.00")
    return Decimal("12.00")


def _icms_por_dentro(base: Decimal, aliquota: Decimal) -> Decimal:
    """Calculate ICMS with gross-up: base = valor / (1 - aliquota/100)."""
    if aliquota >= Decimal("100") or aliquota <= Decimal("0"):
        return base
    taxa = aliquota / Decimal("100")
    return base / (Decimal("1") - taxa)


def _get_internal_aliquota(uf: str) -> Decimal:
    """Get internal ICMS rate for a given UF."""
    return _ICMS_INTERNO.get(uf, Decimal("18.00"))


# ═══════════════════════════════════════════════════════════════════════
# Action 1: calculate-icms — Real ICMS per UF/CFOP/CST
# ═══════════════════════════════════════════════════════════════════════

def calculate_icms(conn, args):
    """Apura ICMS (débito x crédito) por UF e período com análise CST/CFOP.

    Args: --company-id, --ano, --mes, --uf (optional)
    """
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatório")

    ano = args.ano or datetime.now().year
    mes = args.mes or (datetime.now().month - 1 if datetime.now().month > 1 else 12)
    filtro_uf = (args.uf or "").upper().strip() or None

    company_uf = _get_company_uf(conn, company_id) or "SP"
    period_id = _ensure_period(conn, company_id, ano, mes)
    data_prefix = f"{ano}-{mes:02d}"

    resultados = {}
    total_debit = Decimal("0.00")
    total_credit = Decimal("0.00")

    # ── Débito ICMS: NF-e de saída ──
    nfe_rows = conn.execute(
        """SELECT n.id, n.customer_id, n.valor_total, n.base_icms, n.valor_icms,
                  n.valor_icms_uf_dest, n.valor_icms_uf_remet, n.cfop_principal
           FROM br_nfe_out n
           WHERE n.company_id = ? AND n.data_emissao LIKE ?
           AND n.status IN ('autorizado','enviado')""",
        (company_id, f"{data_prefix}%")
    ).fetchall()

    for nfe in nfe_rows:
        customer_uf = _get_customer_uf(conn, nfe["customer_id"])
        if not customer_uf:
            customer_uf = company_uf  # assume local

        if filtro_uf and customer_uf != filtro_uf:
            continue

        # Get items to determine CST
        items = conn.execute(
            """SELECT ni.ncm, ni.cst_icms, ni.valor_total, ni.valor_icms, ni.base_icms,
                      i.item_id
               FROM br_nfe_out_item ni
               LEFT JOIN item_fiscal i ON i.item_id = ni.codigo_produto
               WHERE ni.nfe_out_id = ?""",
            (nfe["id"],)
        ).fetchall()

        for item in items:
            cst = (item["cst_icms"] or "").strip()
            # Skip exempt/non-taxed operations
            if cst in ("40", "41", "50", "51"):
                continue
            # Skip CSOSN immune/not-taxed
            if cst in ("300", "400", "500"):
                continue

            valor_item = _d(item["valor_total"])
            is_same_uf = (customer_uf == company_uf)

            if is_same_uf:
                aliquota = _get_internal_aliquota(company_uf)
                debito = valor_item * (aliquota / Decimal("100"))
            else:
                aliquota = _get_aliq_interestadual(company_uf, customer_uf)
                debito = valor_item * (aliquota / Decimal("100"))

            uf_key = company_uf if is_same_uf else f"{company_uf}→{customer_uf}"
            if customer_uf not in resultados:
                resultados[customer_uf] = {"debit": Decimal("0.00"), "difal_origem": Decimal("0.00"),
                                           "difal_destino": Decimal("0.00"), "credit": Decimal("0.00")}
            resultados[customer_uf]["debit"] += debito
            total_debit += debito

            # DIFAL contribuinte
            if not is_same_uf and _is_contribuinte(conn, nfe["customer_id"]):
                aliq_interna_dest = _get_internal_aliquota(customer_uf)
                difal_rate = aliq_interna_dest - aliquota
                # Split: transition rule — shared between origin and destination
                difal_total = valor_item * (difal_rate / Decimal("100"))
                resultados[customer_uf]["difal_origem"] += difal_total * Decimal("0.2")
                resultados[customer_uf]["difal_destino"] += difal_total * Decimal("0.8")

    # ── Crédito ICMS: NF-e de entrada ──
    credit_rows = conn.execute(
        """SELECT nfe.valor_icms, nfe.base_icms
           FROM nfe_import nfe
           WHERE nfe.company_id = ? AND nfe.data_emissao LIKE ?
           AND nfe.status IN ('imported','validated','posted')""",
        (company_id, f"{data_prefix}%")
    ).fetchall()

    for row in credit_rows:
        credito = _d(row["valor_icms"])
        if company_uf not in resultados:
            resultados[company_uf] = {"debit": Decimal("0.00"), "difal_origem": Decimal("0.00"),
                                      "difal_destino": Decimal("0.00"), "credit": Decimal("0.00")}
        resultados[company_uf]["credit"] += credito
        total_credit += credito

    # ── Store results per UF ──
    stored = []
    for uf_oper, vals in resultados.items():
        debit_v = vals["debit"]
        credit_v = vals["credit"]
        saldo = debit_v - credit_v
        apur_id = _store_tax_apuration(
            conn, period_id, "icms", uf_oper, debit_v, credit_v, company_id,
            valor_pagar=max(Decimal("0.00"), saldo)
        )
        stored.append({
            "uf": uf_oper,
            "debito": _fmt(debit_v),
            "credito": _fmt(credit_v),
            "saldo": _fmt(saldo),
            "situacao": "devedor" if saldo > 0 else "credor",
            "tax_apuration_id": apur_id,
        })

    conn.commit()
    return ok({
        "tributo": "ICMS",
        "ano": ano, "mes": mes,
        "total_debito": _fmt(total_debit),
        "total_credito": _fmt(total_credit),
        "saldo_total": _fmt(total_debit - total_credit),
        "por_uf": stored,
    })


# ═══════════════════════════════════════════════════════════════════════
# Action 2: calculate-icms-st — ICMS Substituição Tributária
# ═══════════════════════════════════════════════════════════════════════

def calculate_icms_st(conn, args):
    """Apura ICMS Substituição Tributária com MVA por UF/NCM.

    Args: --company-id, --ano, --mes
    """
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatório")

    ano = args.ano or datetime.now().year
    mes = args.mes or (datetime.now().month - 1 if datetime.now().month > 1 else 12)

    company_uf = _get_company_uf(conn, company_id) or "SP"
    period_id = _ensure_period(conn, company_id, ano, mes)
    data_prefix = f"{ano}-{mes:02d}"

    st_por_uf = {}
    total_st = Decimal("0.00")

    # Get NF-e saída (authorized)
    nfe_rows = conn.execute(
        """SELECT n.id, n.customer_id, n.valor_total
           FROM br_nfe_out n
           WHERE n.company_id = ? AND n.data_emissao LIKE ?
           AND n.status IN ('autorizado','enviado')""",
        (company_id, f"{data_prefix}%")
    ).fetchall()

    for nfe in nfe_rows:
        customer_uf = _get_customer_uf(conn, nfe["customer_id"])
        if not customer_uf or customer_uf == company_uf:
            continue  # ST applies to interstate operations to contributor customers

        if not _is_contribuinte(conn, nfe["customer_id"]):
            continue

        # Get items with NCM
        items = conn.execute(
            """SELECT ni.ncm, ni.valor_total, ni.cst_icms
               FROM br_nfe_out_item ni
               WHERE ni.nfe_out_id = ?""",
            (nfe["id"],)
        ).fetchall()

        for item in items:
            cst = (item["cst_icms"] or "").strip()
            # ST applicable: CST 10, 30, 70 or CSOSN 201, 202, 203
            if cst not in ("10", "30", "70", "201", "202", "203"):
                # Check CFOP for ST (51xx)
                cfop_rows = conn.execute(
                    "SELECT cfop FROM br_nfe_out_item WHERE nfe_out_id = ? AND cfop LIKE '5.%'",
                    (nfe["id"],)
                ).fetchall()
                if not cfop_rows:
                    continue

            ncm = (item["ncm"] or "").strip()
            if not ncm:
                continue

            valor = _d(item["valor_total"])
            mva = _get_mva(conn, customer_uf, ncm, company_id)

            if mva <= Decimal("0"):
                mva = Decimal("0.40")  # default 40% MVA

            # ST base: valor_mercadoria × (1 + MVA)
            mva_factor = Decimal("1") + (mva / Decimal("100"))
            st_base = valor * mva_factor

            # ST tax: ST_base × aliq_interna_destino - ICMS próprio
            aliq_interna = _get_internal_aliquota(customer_uf)
            aliq_interest = _get_aliq_interestadual(company_uf, customer_uf)

            st_bruto = st_base * (aliq_interna / Decimal("100"))
            icms_proprio = valor * (aliq_interest / Decimal("100"))
            st_devido = max(Decimal("0.00"), st_bruto - icms_proprio)

            if customer_uf not in st_por_uf:
                st_por_uf[customer_uf] = {"st_devido": Decimal("0.00"), "mva_aplicada": _fmt(mva),
                                          "base_st": Decimal("0.00")}
            st_por_uf[customer_uf]["st_devido"] += st_devido
            st_por_uf[customer_uf]["base_st"] += st_base
            total_st += st_devido

    # Store results
    stored = []
    for uf_dest, vals in st_por_uf.items():
        apur_id = _store_tax_apuration(
            conn, period_id, "icms_st", uf_dest, vals["st_devido"], Decimal("0.00"), company_id,
            valor_pagar=vals["st_devido"]
        )
        stored.append({
            "uf_destino": uf_dest,
            "base_st": _fmt(vals["base_st"]),
            "mva_aplicada": vals["mva_aplicada"],
            "st_devido": _fmt(vals["st_devido"]),
            "tax_apuration_id": apur_id,
        })

    conn.commit()
    return ok({
        "tributo": "ICMS-ST",
        "ano": ano, "mes": mes,
        "total_st_devido": _fmt(total_st),
        "por_uf": stored,
    })


# ═══════════════════════════════════════════════════════════════════════
# Action 3: calculate-fecp — Fundo de Combate à Pobreza
# ═══════════════════════════════════════════════════════════════════════

def calculate_fecp(conn, args):
    """Calcula FECP (Fundo de Combate à Pobreza) por UF.

    Args: --company-id, --ano, --mes, --uf
    """
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatório")

    ano = args.ano or datetime.now().year
    mes = args.mes or (datetime.now().month - 1 if datetime.now().month > 1 else 12)
    uf_alvo = (args.uf or "").upper().strip()

    if not uf_alvo:
        return err("--uf obrigatório para FECP")

    company_uf = _get_company_uf(conn, company_id) or "SP"
    period_id = _ensure_period(conn, company_id, ano, mes)
    data_prefix = f"{ano}-{mes:02d}"

    fecp_rate = _get_fecp(conn, uf_alvo, company_id)
    total_fecp = Decimal("0.00")
    total_fecp_st = Decimal("0.00")

    # FECP on regular ICMS operations
    icms_apur = conn.execute(
        """SELECT id, debito FROM tax_apuration
           WHERE company_id = ? AND tributo = 'icms' AND uf = ? AND status = 'pendente'""",
        (company_id, uf_alvo)
    ).fetchone()

    if icms_apur:
        icms_debit = _d(icms_apur["debito"])
        fecp = icms_debit * (fecp_rate / Decimal("100"))
        total_fecp += fecp

    # FECP-ST on ICMS ST operations
    st_rows = conn.execute(
        """SELECT id, debito FROM tax_apuration
           WHERE company_id = ? AND tributo = 'icms_st' AND uf = ? AND status = 'pendente'""",
        (company_id, uf_alvo)
    ).fetchall()

    for st in st_rows:
        st_debit = _d(st["debito"])
        fecp_st = st_debit * (fecp_rate / Decimal("100"))
        total_fecp_st += fecp_st

    # Store FECP
    fecp_id = _store_tax_apuration(
        conn, period_id, "icms_st", f"{uf_alvo}_FECP", total_fecp, Decimal("0.00"), company_id,
        valor_pagar=total_fecp
    )

    # Store FECP-ST (stored under same category, different uf)
    if total_fecp_st > 0:
        _store_tax_apuration(
            conn, period_id, "icms_st", f"{uf_alvo}_FECP-ST", total_fecp_st, Decimal("0.00"), company_id,
            valor_pagar=total_fecp_st
        )

    conn.commit()
    return ok({
        "tributo": "FECP",
        "uf": uf_alvo,
        "ano": ano, "mes": mes,
        "aliquota_fecp": _fmt(fecp_rate),
        "fecp_devido": _fmt(total_fecp),
        "fecp_st_devido": _fmt(total_fecp_st),
        "total": _fmt(total_fecp + total_fecp_st),
        "tax_apuration_id": fecp_id,
    })


# ═══════════════════════════════════════════════════════════════════════
# Action 4: calculate-pis-cofins — Real PIS/COFINS with CST analysis
# ═══════════════════════════════════════════════════════════════════════

def calculate_pis_cofins(conn, args):
    """Apura PIS/COFINS com análise de CST por regime.

    Args: --company-id, --ano, --mes
    """
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatório")

    ano = args.ano or datetime.now().year
    mes = args.mes or (datetime.now().month - 1 if datetime.now().month > 1 else 12)

    period_id = _ensure_period(conn, company_id, ano, mes)
    data_prefix = f"{ano}-{mes:02d}"

    # ── Revenue (debits) from NF-e out ──
    nfe_rows = conn.execute(
        """SELECT n.id
           FROM br_nfe_out n
           WHERE n.company_id = ? AND n.data_emissao LIKE ?
           AND n.status IN ('autorizado','enviado')""",
        (company_id, f"{data_prefix}%")
    ).fetchall()

    # Track by CST group
    pis_por_cst = {}  # {cst_group: {"receita", "debito"}}
    cofins_por_cst = {}

    def _cst_grupo(cst: str) -> str:
        """Map PIS/COFINS CST to regime group."""
        if not cst:
            return "01"
        cst = cst.strip()
        # Não-cumulativo: 01-05
        if cst in ("01", "02", "03", "04", "05"):
            return "nao_cumulativo"
        # Isento/não tributado/suspenso: 06-08
        if cst in ("06", "07", "08", "09"):
            return "isento"
        # Cumulativo regime (50-56)
        first_digit = cst[:1]
        if first_digit == "5":
            return "cumulativo"
        # Outros: 49, 99
        if cst in ("49", "99"):
            return "outros"
        return "nao_cumulativo"

    total_receita = Decimal("0.00")
    total_pis_debit = Decimal("0.00")
    total_cofins_debit = Decimal("0.00")

    for nfe in nfe_rows:
        items = conn.execute(
            """SELECT ni.valor_total, ni.cst_pis, ni.cst_cofins, ni.aliquota_pis,
                      ni.aliquota_cofins
               FROM br_nfe_out_item ni
               WHERE ni.nfe_out_id = ?""",
            (nfe["id"],)
        ).fetchall()

        for item in items:
            valor = _d(item["valor_total"])
            if valor <= Decimal("0"):
                continue
            total_receita += valor

            pis_cst = (item["cst_pis"] or "").strip()
            cofins_cst = (item["cst_cofins"] or "").strip()

            # PIS
            g = _cst_grupo(pis_cst)
            if g not in pis_por_cst:
                pis_por_cst[g] = {"receita": Decimal("0.00"), "debito": Decimal("0.00")}
            pis_por_cst[g]["receita"] += valor

            if g == "nao_cumulativo":
                pis_debito = valor * (PIS_NAO_CUMULATIVO / Decimal("100"))
            elif g == "cumulativo":
                pis_debito = valor * (PIS_CUMULATIVO / Decimal("100"))
            else:
                pis_debito = Decimal("0.00")  # isento/outros

            pis_por_cst[g]["debito"] += pis_debito
            total_pis_debit += pis_debito

            # COFINS
            g = _cst_grupo(cofins_cst)
            if g not in cofins_por_cst:
                cofins_por_cst[g] = {"receita": Decimal("0.00"), "debito": Decimal("0.00")}
            cofins_por_cst[g]["receita"] += valor

            if g == "nao_cumulativo":
                cofins_debito = valor * (COFINS_NAO_CUMULATIVO / Decimal("100"))
            elif g == "cumulativo":
                cofins_debito = valor * (COFINS_CUMULATIVO / Decimal("100"))
            else:
                cofins_debito = Decimal("0.00")

            cofins_por_cst[g]["debito"] += cofins_debito
            total_cofins_debit += cofins_debito

    # ── Credits from purchases ──
    credit_rows = conn.execute(
        """SELECT ni.valor_total, ni.cst_pis, ni.cst_cofins, ni.valor_pis, ni.valor_cofins
           FROM nfe_item ni
           JOIN nfe_import n ON ni.nfe_import_id = n.id
           WHERE n.company_id = ? AND n.data_emissao LIKE ?
           AND n.status IN ('imported','validated','posted')""",
        (company_id, f"{data_prefix}%")
    ).fetchall()

    total_pis_credit = Decimal("0.00")
    total_cofins_credit = Decimal("0.00")

    for row in credit_rows:
        valor = _d(row["valor_total"])
        pis_cst = (row["cst_pis"] or "").strip()
        cofins_cst = (row["cst_cofins"] or "").strip()

        # PIS credit — only for não-cumulativo CSTs
        if _cst_grupo(pis_cst) == "nao_cumulativo":
            pis_cred = valor * (PIS_NAO_CUMULATIVO / Decimal("100"))
        else:
            pis_cred = Decimal("0.00")
        total_pis_credit += pis_cred

        # COFINS credit
        if _cst_grupo(cofins_cst) == "nao_cumulativo":
            cofins_cred = valor * (COFINS_NAO_CUMULATIVO / Decimal("100"))
        else:
            cofins_cred = Decimal("0.00")
        total_cofins_credit += cofins_cred

    # ── Store results ──
    pis_saldo = max(Decimal("0.00"), total_pis_debit - total_pis_credit)
    cofins_saldo = max(Decimal("0.00"), total_cofins_debit - total_cofins_credit)

    pis_id = _store_tax_apuration(
        conn, period_id, "pis", None,
        total_pis_debit, total_pis_credit, company_id,
        valor_pagar=pis_saldo, codigo_receita=DARF_CODES["pis_nao_cumulativo"]
    )
    cofins_id = _store_tax_apuration(
        conn, period_id, "cofins", None,
        total_cofins_debit, total_cofins_credit, company_id,
        valor_pagar=cofins_saldo, codigo_receita=DARF_CODES["cofins_nao_cumulativo"]
    )

    conn.commit()
    return ok({
        "periodo": f"{mes:02d}/{ano}",
        "receita_bruta": _fmt(total_receita),
        "pis": {
            "debito": _fmt(total_pis_debit),
            "credito": _fmt(total_pis_credit),
            "pagar": _fmt(pis_saldo),
            "por_regime": {k: {"receita": _fmt(v["receita"]), "debito": _fmt(v["debito"])}
                           for k, v in pis_por_cst.items()},
            "tax_apuration_id": pis_id,
        },
        "cofins": {
            "debito": _fmt(total_cofins_debit),
            "credito": _fmt(total_cofins_credit),
            "pagar": _fmt(cofins_saldo),
            "por_regime": {k: {"receita": _fmt(v["receita"]), "debito": _fmt(v["debito"])}
                           for k, v in cofins_por_cst.items()},
            "tax_apuration_id": cofins_id,
        },
    })


# ═══════════════════════════════════════════════════════════════════════
# Action 5: calculate-difal — DIFAL from real interstate sales
# ═══════════════════════════════════════════════════════════════════════

def calculate_difal(conn, args):
    """Calcula DIFAL interestadual a partir de vendas reais.

    Args: --company-id, --ano, --mes
    """
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatório")

    ano = args.ano or datetime.now().year
    mes = args.mes or (datetime.now().month - 1 if datetime.now().month > 1 else 12)

    company_uf = _get_company_uf(conn, company_id) or "SP"
    period_id = _ensure_period(conn, company_id, ano, mes)
    data_prefix = f"{ano}-{mes:02d}"

    difal_por_uf = {}
    total_difal = Decimal("0.00")

    nfe_rows = conn.execute(
        """SELECT n.id, n.customer_id, n.valor_total
           FROM br_nfe_out n
           WHERE n.company_id = ? AND n.data_emissao LIKE ?
           AND n.status IN ('autorizado','enviado')""",
        (company_id, f"{data_prefix}%")
    ).fetchall()

    for nfe in nfe_rows:
        customer_uf = _get_customer_uf(conn, nfe["customer_id"])
        if not customer_uf or customer_uf == company_uf:
            continue  # DIFAL only for interstate

        is_contrib = _is_contribuinte(conn, nfe["customer_id"])
        aliq_inter = _get_aliq_interestadual(company_uf, customer_uf)
        aliq_interna = _get_internal_aliquota(customer_uf)

        difal_pct = aliq_interna - aliq_inter
        if difal_pct <= Decimal("0"):
            continue

        valor_total = _d(nfe["valor_total"])
        difal_valor = valor_total * (difal_pct / Decimal("100"))

        if customer_uf not in difal_por_uf:
            difal_por_uf[customer_uf] = {
                "difal_origem": Decimal("0.00"), "difal_destino": Decimal("0.00"),
                "aliq_inter": _fmt(aliq_inter), "aliq_interna": _fmt(aliq_interna),
            }

        if is_contrib:
            # Transition rule: shared. Currently 100% to destination since EC 87/2015
            # (gradual phase-out of origin share)
            difal_por_uf[customer_uf]["difal_destino"] += difal_valor
        else:
            # Non-contributor: full DIFAL to destination
            difal_por_uf[customer_uf]["difal_destino"] += difal_valor

        total_difal += difal_valor

    stored = []
    for uf_dest, vals in difal_por_uf.items():
        apur_id = _store_tax_apuration(
            conn, period_id, "difal", uf_dest,
            vals["difal_destino"], Decimal("0.00"), company_id,
            valor_pagar=vals["difal_destino"]
        )
        stored.append({
            "uf_destino": uf_dest,
            "aliq_inter": vals["aliq_inter"],
            "aliq_interna": vals["aliq_interna"],
            "difal_devido": _fmt(vals["difal_destino"]),
            "tax_apuration_id": apur_id,
        })

    conn.commit()
    return ok({
        "tributo": "DIFAL",
        "ano": ano, "mes": mes,
        "total_difal": _fmt(total_difal),
        "por_uf": stored,
    })


# ═══════════════════════════════════════════════════════════════════════
# Action 6: calculate-simples-nacional — Full Simples Nacional
# ═══════════════════════════════════════════════════════════════════════

def calculate_simples_nacional(conn, args):
    """Calcula DAS do Simples Nacional com tabelas progressivas.

    Args: --company-id, --ano, --mes
    """
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatório")

    ano = args.ano or datetime.now().year
    mes = args.mes or (datetime.now().month - 1 if datetime.now().month > 1 else 12)

    period_id = _ensure_period(conn, company_id, ano, mes, regime="simples_nacional")
    data_prefix = f"{ano}-{mes:02d}"

    # Determine annex from company CNAE and activity
    cnae = None
    row = conn.execute("SELECT cnae_principal FROM company_fiscal WHERE company_id = ?",
                       (company_id,)).fetchone()
    if row:
        cnae = (row["cnae_principal"] or "").strip()

    # Rough annex determination by CNAE section
    annex_key = "III"  # default services
    if cnae:
        cnae_prefix = cnae[:2]
        if cnae_prefix in ("45", "46", "47"):
            annex_key = "I"  # commerce
        elif cnae_prefix in ("10", "11", "12", "13", "14", "15", "16", "17", "18",
                             "19", "20", "21", "22", "23", "24", "25", "26", "27",
                             "28", "29", "30", "31", "32", "33"):
            annex_key = "II"  # industry

    annex = {"I": SIMPLES_ANEXO_I, "II": SIMPLES_ANEXO_II, "III": SIMPLES_ANEXO_III}[annex_key]

    # ── Revenue in last 12 months (RBT12) ──
    rbt12 = Decimal("0.00")
    for m_offset in range(1, 13):
        m = mes - m_offset
        a = ano
        while m <= 0:
            m += 12
            a -= 1
        rev = conn.execute(
            """SELECT COALESCE(SUM(CAST(valor_total AS REAL)), 0) as total
               FROM br_nfe_out
               WHERE company_id = ? AND data_emissao LIKE ? AND status != 'cancelado'""",
            (company_id, f"{a}-{m:02d}%")
        ).fetchone()
        rbt12 += _d(rev["total"] if rev else 0)

    # ── Revenue in current month ──
    receita_mes = conn.execute(
        """SELECT COALESCE(SUM(CAST(valor_total AS REAL)), 0) as total
           FROM br_nfe_out
           WHERE company_id = ? AND data_emissao LIKE ? AND status != 'cancelado'""",
        (company_id, f"{data_prefix}%")
    ).fetchone()
    receita_mes = _d(receita_mes["total"] if receita_mes else 0)

    # ── Find applicable bracket ──
    bracket_aliq = Decimal("0.00")
    bracket_pd = Decimal("0.00")
    rbt12_k = rbt12 / Decimal("1000.00")

    for rbt_max, aliq, pd in annex:
        if rbt12 <= rbt_max:
            bracket_aliq = aliq
            bracket_pd = pd
            break
    else:
        # Last bracket (above 4.8M)
        bracket_aliq = annex[-1][1]
        bracket_pd = annex[-1][2]

    # ── Effective rate ──
    if rbt12 > Decimal("0"):
        aliq_efetiva = ((rbt12 * bracket_aliq / Decimal("100")) - bracket_pd) / rbt12 * Decimal("100")
    else:
        aliq_efetiva = bracket_aliq

    # Cap effective rate at nominal rate
    aliq_efetiva = min(aliq_efetiva, bracket_aliq)

    # ── DAS value ──
    das_valor = receita_mes * (aliq_efetiva / Decimal("100"))

    # ── Breakdown by tax ──
    breakdown = SIMPLES_BREAKDOWN[annex_key]
    tax_names = ["IRPJ", "CSLL", "COFINS", "PIS", "INSS", "ICMS", "IPI", "ISS"]
    tax_breakdown = {}
    for i, name in enumerate(tax_names):
        share = breakdown[i] / Decimal("100.00")
        tax_val = das_valor * share
        if tax_val > Decimal("0"):
            tax_breakdown[name] = _fmt(tax_val)

    # Store
    apur_id = _store_tax_apuration(
        conn, period_id, "simples", None,
        das_valor, Decimal("0.00"), company_id,
        valor_pagar=das_valor, codigo_receita=DARF_CODES["irpj"]["simples"]
    )

    conn.commit()
    return ok({
        "tributo": "Simples Nacional",
        "ano": ano, "mes": mes,
        "anexo": annex_key,
        "rbt12": _fmt(rbt12),
        "receita_mes": _fmt(receita_mes),
        "aliq_nominal": _fmt(bracket_aliq),
        "aliq_efetiva": _fmt(aliq_efetiva),
        "das_valor": _fmt(das_valor),
        "breakdown": tax_breakdown,
        "tax_apuration_id": apur_id,
    })


# ═══════════════════════════════════════════════════════════════════════
# Action 7: calculate-irpj-csll — IRPJ/CSLL Lucro Real or Presumido
# ═══════════════════════════════════════════════════════════════════════

def calculate_irpj_csll(conn, args):
    """Apura IRPJ/CSLL por regime (Lucro Real ou Presumido).

    Args: --company-id, --ano, --mes, --regime (lucro_real|lucro_presumido)
    """
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatório")

    ano = args.ano or datetime.now().year
    mes = args.mes or (datetime.now().month - 1 if datetime.now().month > 1 else 12)
    regime = (getattr(args, "regime", None) or "lucro_real").lower()

    period_id = _ensure_period(conn, company_id, ano, mes, regime=regime)
    data_prefix = f"{ano}-{mes:02d}"

    # ── Gross revenue ──
    receita = _d(conn.execute(
        """SELECT COALESCE(SUM(CAST(valor_total AS REAL)), 0) as total
           FROM br_nfe_out
           WHERE company_id = ? AND data_emissao LIKE ? AND status != 'cancelado'""",
        (company_id, f"{data_prefix}%")
    ).fetchone()["total"])

    # ── Deductions (purchases, expenses from GL) ──
    # Sum purchase invoices and nfe_import
    compras = _d(conn.execute(
        """SELECT COALESCE(SUM(CAST(valor_produtos AS REAL)), 0)
           FROM nfe_import
           WHERE company_id = ? AND data_emissao LIKE ?
           AND status IN ('imported','validated','posted')""",
        (company_id, f"{data_prefix}%")
    ).fetchone()[0] or 0)

    if regime == "lucro_presumido":
        # Lucro Presumido
        cnae_row = conn.execute(
            "SELECT cnae_principal FROM company_fiscal WHERE company_id = ?",
            (company_id,)
        ).fetchone()
        cnae = (cnae_row["cnae_principal"] if cnae_row else "") or ""

        is_service = cnae[:2] in (
            "41", "42", "43",  # construction
            "49", "50", "51", "52", "53",  # transport
            "55", "56",  # hospitality
            "58", "59", "60", "61", "62", "63",  # IT/media
            "64", "65", "66",  # finance
            "68",  # real estate
            "69", "70", "71", "72", "73", "74", "75",  # professional/tech
            "77", "78", "79", "80", "81", "82",  # admin/support
            "85",  # education
            "86", "87", "88",  # health/social
            "90", "91", "92", "93", "94", "95", "96",  # arts/other services
        )

        if is_service:
            pres_base_irpj = receita * Decimal("0.32")
            pres_base_csll = receita * Decimal("0.32")
        else:
            pres_base_irpj = receita * Decimal("0.08")
            pres_base_csll = receita * Decimal("0.12")

        irpj_valor = pres_base_irpj * (IRPJ_BASE / Decimal("100"))
        # Additional 10% IRPJ if presumptive base > R$20k/month
        if pres_base_irpj > IRPJ_ADICIONAL_LIMITE:
            irpj_valor += (pres_base_irpj - IRPJ_ADICIONAL_LIMITE) * (IRPJ_ADICIONAL / Decimal("100"))

        csll_valor = pres_base_csll * (CSLL_BASE / Decimal("100"))

        apur_desc = "Lucro Presumido"

    else:
        # Lucro Real
        desp_op = _d(conn.execute(
            """SELECT COALESCE(SUM(ABS(CAST(credit AS REAL))), 0)
               FROM gl_entry
               WHERE company_id = ? AND posting_date LIKE ?
               AND account LIKE '4%'""",
            (company_id, f"{data_prefix}%")
        ).fetchone()[0] or 0)

        lucro_real = receita - compras - desp_op
        lucro_tributavel = max(Decimal("0.00"), lucro_real)

        irpj_valor = lucro_tributavel * (IRPJ_BASE / Decimal("100"))
        if lucro_tributavel > IRPJ_ADICIONAL_LIMITE:
            irpj_valor += (lucro_tributavel - IRPJ_ADICIONAL_LIMITE) * (IRPJ_ADICIONAL / Decimal("100"))

        csll_valor = lucro_tributavel * (CSLL_BASE / Decimal("100"))
        apur_desc = "Lucro Real"

    # Store
    irpj_id = _store_tax_apuration(
        conn, period_id, "irpj", None,
        irpj_valor, Decimal("0.00"), company_id,
        valor_pagar=irpj_valor,
        codigo_receita=(
            DARF_CODES["irpj"]["lucro_real_mensal"] if regime == "lucro_real"
            else DARF_CODES["irpj"]["lucro_presumido"]
        )
    )
    csll_id = _store_tax_apuration(
        conn, period_id, "csll", None,
        csll_valor, Decimal("0.00"), company_id,
        valor_pagar=csll_valor,
        codigo_receita=(
            DARF_CODES["csll"]["lucro_real_mensal"] if regime == "lucro_real"
            else DARF_CODES["csll"]["lucro_presumido"]
        )
    )

    conn.commit()
    return ok({
        "tributo": "IRPJ/CSLL",
        "regime": apur_desc,
        "ano": ano, "mes": mes,
        "receita_bruta": _fmt(receita),
        "irpj": {
            "valor": _fmt(irpj_valor),
            "tax_apuration_id": irpj_id,
        },
        "csll": {
            "valor": _fmt(csll_valor),
            "tax_apuration_id": csll_id,
        },
    })


# ═══════════════════════════════════════════════════════════════════════
# Action 8: calculate-ciap — CIAP 1/48 credit control
# ═══════════════════════════════════════════════════════════════════════

def calculate_ciap(conn, args):
    """CIAP — Controle de Crédito de ICMS Ativo Permanente (1/48 avos).

    Args: --company-id, --ano, --mes
    """
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatório")

    ano = args.ano or datetime.now().year
    mes = args.mes or (datetime.now().month - 1 if datetime.now().month > 1 else 12)

    period_id = _ensure_period(conn, company_id, ano, mes)

    # ── Find fixed asset purchases with ICMS ──
    # Look for nfe_import with fixed asset CFOPs (1.551, 2.551, 3.551)
    asset_nfes = conn.execute(
        """SELECT n.id, n.valor_icms, n.valor_produtos, n.data_emissao,
                  n.chave_acesso
           FROM nfe_import n
           WHERE n.company_id = ?
           AND (n.cfop_principal LIKE '1.551%' OR n.cfop_principal LIKE '2.551%'
                OR n.cfop_principal LIKE '3.551%')
           AND n.status != 'error'
           ORDER BY n.data_emissao DESC""",
        (company_id,)
    ).fetchall()

    total_credit_mes = Decimal("0.00")
    ciap_entries = []

    for nfe in asset_nfes:
        icms_total = _d(nfe["valor_icms"])
        if icms_total <= Decimal("0"):
            continue

        # 1/48 monthly credit
        credito_mensal = (icms_total / Decimal("48")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        # Count months already credited
        data_emissao = nfe["data_emissao"]
        # Parse acquisition date; if before/outside period, check if in current period
        try:
            parts = data_emissao.split("-")
            aquis_ano = int(parts[0])
            aquis_mes = int(parts[1])
        except (ValueError, IndexError):
            aquis_ano, aquis_mes = ano, mes

        months_elapsed = (ano - aquis_ano) * 12 + (mes - aquis_mes)
        if months_elapsed < 0:
            months_elapsed = 0
        if months_elapsed >= 48:
            continue  # fully amortized

        months_remaining = 48 - months_elapsed
        total_credited = credito_mensal * Decimal(str(months_elapsed))
        total_remaining = credito_mensal * Decimal(str(months_remaining))

        total_credit_mes += credito_mensal

        ciap_entries.append({
            "chave_acesso": nfe["chave_acesso"],
            "data_aquisicao": data_emissao,
            "icms_total": _fmt(icms_total),
            "credito_mensal_1_48": _fmt(credito_mensal),
            "meses_ja_creditados": months_elapsed,
            "meses_restantes": months_remaining,
            "total_ja_creditado": _fmt(total_credited),
            "saldo_a_creditar": _fmt(total_remaining),
        })

    # Store CIAP credit
    apur_id = None
    if total_credit_mes > Decimal("0"):
        apur_id = _store_tax_apuration(
            conn, period_id, "icms", "CIAP",
            Decimal("0.00"), total_credit_mes, company_id
        )

    conn.commit()
    return ok({
        "tributo": "CIAP (1/48 avos ICMS)",
        "ano": ano, "mes": mes,
        "credito_mensal_total": _fmt(total_credit_mes),
        "ativos": ciap_entries,
        "tax_apuration_id": apur_id,
    })


# ═══════════════════════════════════════════════════════════════════════
# Action 9: calculate-iss — ISS municipal service tax
# ═══════════════════════════════════════════════════════════════════════

def calculate_iss(conn, args):
    """Calcula ISS (Imposto Sobre Serviços) municipal.

    Args: --company-id, --ano, --mes
    """
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatório")

    ano = args.ano or datetime.now().year
    mes = args.mes or (datetime.now().month - 1 if datetime.now().month > 1 else 12)

    period_id = _ensure_period(conn, company_id, ano, mes)
    data_prefix = f"{ano}-{mes:02d}"

    # ISS applies to service operations — CFOP starting with 5.9xx (service sales)
    # or items with ISS rate > 0
    iss_por_muni = {}
    total_iss = Decimal("0.00")

    nfe_rows = conn.execute(
        """SELECT n.id, n.customer_id, n.valor_total
           FROM br_nfe_out n
           WHERE n.company_id = ? AND n.data_emissao LIKE ?
           AND n.status IN ('autorizado','enviado')""",
        (company_id, f"{data_prefix}%")
    ).fetchall()

    for nfe in nfe_rows:
        items = conn.execute(
            """SELECT ni.valor_total, ni.cfop,
                      COALESCE(i.aliq_iss, '0.00') as aliq_iss
               FROM br_nfe_out_item ni
               LEFT JOIN item_fiscal i ON i.item_id = ni.codigo_produto
               WHERE ni.nfe_out_id = ?""",
            (nfe["id"],)
        ).fetchall()

        for item in items:
            cfop = (item["cfop"] or "").strip()
            # Service CFOPs: 5.9xx, 6.9xx (venda de serviço / interestadual)
            is_service = cfop.startswith("5.9") or cfop.startswith("6.9")
            aliq_iss = _d(item["aliq_iss"])

            if not is_service and aliq_iss <= Decimal("0"):
                continue

            valor_servico = _d(item["valor_total"])

            # Determine municipality where ISS is due (service provision location)
            # For local services, use company's municipality
            customer_uf = _get_customer_uf(conn, nfe["customer_id"])
            if customer_uf and customer_uf != _get_company_uf(conn, company_id):
                # Interstate service — ISS to company's municipality (general rule)
                row = conn.execute(
                    "SELECT municipio_codigo, municipio_nome, uf FROM company_fiscal WHERE company_id = ?",
                    (company_id,)
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT municipio_codigo, municipio_nome, uf FROM company_fiscal WHERE company_id = ?",
                    (company_id,)
                ).fetchone()

            mun_codigo = row["municipio_codigo"] if row else "0000000"
            mun_nome = row["municipio_nome"] if row else "DESCONHECIDO"

            # Get ISS rate from config
            iss_config_row = conn.execute(
                """SELECT aliquota FROM iss_config
                   WHERE municipio_codigo = ? AND is_active = 1
                   AND (company_id = ? OR company_id = '*')
                   ORDER BY company_id DESC LIMIT 1""",
                (mun_codigo, company_id)
            ).fetchone()

            if iss_config_row:
                iss_rate = _d(iss_config_row["aliquota"])
            elif aliq_iss > Decimal("0"):
                iss_rate = aliq_iss
            else:
                iss_rate = Decimal("5.00")  # default municipal rate

            iss_valor = valor_servico * (iss_rate / Decimal("100"))

            mun_key = f"{mun_codigo} - {mun_nome}"
            if mun_key not in iss_por_muni:
                iss_por_muni[mun_key] = Decimal("0.00")
            iss_por_muni[mun_key] += iss_valor
            total_iss += iss_valor

    stored = []
    for mun_key, iss_val in iss_por_muni.items():
        apur_id = _store_tax_apuration(
            conn, period_id, "iss", mun_key,
            iss_val, Decimal("0.00"), company_id,
            valor_pagar=iss_val
        )
        stored.append({
            "municipio": mun_key,
            "iss_devido": _fmt(iss_val),
            "tax_apuration_id": apur_id,
        })

    conn.commit()
    return ok({
        "tributo": "ISS",
        "ano": ano, "mes": mes,
        "total_iss": _fmt(total_iss),
        "por_municipio": stored,
    })


# ═══════════════════════════════════════════════════════════════════════
# Action 10: calculate-withholding — Retenções na Fonte
# ═══════════════════════════════════════════════════════════════════════

def calculate_withholding(conn, args):
    """Calcula retenções na fonte (IR, PIS/COFINS/CSLL, INSS, ISS).

    Args: --company-id, --ano, --mes
    """
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatório")

    ano = args.ano or datetime.now().year
    mes = args.mes or (datetime.now().month - 1 if datetime.now().month > 1 else 12)

    period_id = _ensure_period(conn, company_id, ano, mes)
    data_prefix = f"{ano}-{mes:02d}"

    withholding = {
        "ir": {"base": Decimal("0.00"), "valor": Decimal("0.00"), "aliq": Decimal("1.50")},
        "pis": {"base": Decimal("0.00"), "valor": Decimal("0.00"), "aliq": Decimal("0.65")},
        "cofins": {"base": Decimal("0.00"), "valor": Decimal("0.00"), "aliq": Decimal("3.00")},
        "csll": {"base": Decimal("0.00"), "valor": Decimal("0.00"), "aliq": Decimal("1.00")},
        "inss": {"base": Decimal("0.00"), "valor": Decimal("0.00"), "aliq": Decimal("11.00")},
        "iss": {"base": Decimal("0.00"), "valor": Decimal("0.00"), "aliq": Decimal("5.00")},
    }

    # Load configured rates
    config_rows = conn.execute(
        """SELECT tributo, aliquota, base_minima FROM withholding_config
           WHERE is_active = 1 AND (company_id = ? OR company_id = '*')""",
        (company_id,)
    ).fetchall()
    for row in config_rows:
        t = row["tributo"]
        if t in withholding:
            withholding[t]["aliq"] = _d(row["aliquota"])
            withholding[t]["base_minima"] = _d(row["base_minima"])

    # ── Purchase invoices with services from nfe_import ──
    purchase_rows = conn.execute(
        """SELECT n.id, n.valor_total, n.valor_produtos, n.emitente_cnpj, n.emitente_nome,
                  n.natureza_operacao
           FROM nfe_import n
           WHERE n.company_id = ? AND n.data_emissao LIKE ?
           AND n.status IN ('imported','validated','posted')""",
        (company_id, f"{data_prefix}%")
    ).fetchall()

    for pur in purchase_rows:
        # For each purchase, check items for services
        valor_total = _d(pur["valor_total"])
        if valor_total <= Decimal("0"):
            continue

        items = conn.execute(
            """SELECT ni.valor_total, ni.cfop
               FROM nfe_item ni
               WHERE ni.nfe_import_id = ?""",
            (pur["id"],)
        ).fetchall()

        for item in items:
            cfop = (item["cfop"] or "").strip()
            if not cfop:
                continue
            cfop_prefix = cfop[:1] if cfop else ""
            valor = _d(item["valor_total"])

            # Service CFOPs: 1.xxx (entrada), 2.xxx (interestadual), 3.xxx (exterior)
            # Services are typically identified by nature_operacao or CFOP
            is_service = cfop_prefix in ("1", "2", "3") and any(
                k in (pur["natureza_operacao"] or "").lower()
                for k in ("servi", "frete", "transporte", "comunicação", "consult")
            )

            if not is_service:
                continue

            # Service portion: typically 100% of value for pure services
            # For mixed, use a service fraction
            svc_fraction = Decimal("1.00")

            # IR withholding: 1.5% on labor/services portion
            ir_base = valor * svc_fraction * Decimal("0.40")  # 40% presumed labor
            if ir_base > withholding["ir"].get("base_minima", Decimal("0.00")):
                withholding["ir"]["base"] += ir_base
                withholding["ir"]["valor"] += ir_base * (withholding["ir"]["aliq"] / Decimal("100"))

            # PIS/COFINS/CSLL: 4.65% combined
            pis_base = valor * svc_fraction
            withholding["pis"]["base"] += pis_base
            withholding["pis"]["valor"] += pis_base * (withholding["pis"]["aliq"] / Decimal("100"))
            withholding["cofins"]["base"] += pis_base
            withholding["cofins"]["valor"] += pis_base * (withholding["cofins"]["aliq"] / Decimal("100"))
            withholding["csll"]["base"] += pis_base
            withholding["csll"]["valor"] += pis_base * (withholding["csll"]["aliq"] / Decimal("100"))

            # INSS: 11% on labor portion
            inss_base = valor * svc_fraction * Decimal("0.60")  # 60% presumed labor
            withholding["inss"]["base"] += inss_base
            withholding["inss"]["valor"] += inss_base * (withholding["inss"]["aliq"] / Decimal("100"))

    # Store results
    stored = []
    total_valor = Decimal("0.00")
    for tributo, vals in withholding.items():
        if vals["valor"] > Decimal("0"):
            total_valor += vals["valor"]
            apur_id = _store_tax_apuration(
                conn, period_id, tributo, "RETENCAO",
                vals["valor"], Decimal("0.00"), company_id,
                valor_pagar=vals["valor"]
            )
            stored.append({
                "tributo": tributo.upper(),
                "base_calculo": _fmt(vals["base"]),
                "aliquota": _fmt(vals["aliq"]),
                "valor_reter": _fmt(vals["valor"]),
                "tax_apuration_id": apur_id,
            })

    conn.commit()
    return ok({
        "tributo": "Retenções na Fonte",
        "ano": ano, "mes": mes,
        "total_reter": _fmt(total_valor),
        "retencoes": stored,
    })


# ═══════════════════════════════════════════════════════════════════════
# Action 11: reconcile-tax-accounts — Real reconciliation with GL
# ═══════════════════════════════════════════════════════════════════════

def reconcile_tax_accounts(conn, args):
    """Concilia contas de impostos com apuração e GL.

    Args: --company-id, --ano, --mes
    """
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatório")

    ano = args.ano or datetime.now().year
    mes = args.mes or (datetime.now().month - 1 if datetime.now().month > 1 else 12)

    data_prefix = f"{ano}-{mes:02d}"

    reconciliations = []
    differences_found = 0

    # Tax GL accounts mapping (typical BR chart of accounts)
    tax_gl_map = {
        "icms": ("1.1.2.01.001", "2.1.1.01.001"),   # ICMS a recuperar, ICMS a recolher
        "pis": ("1.1.2.02.001", "2.1.1.02.001"),     # PIS a recuperar, PIS a recolher
        "cofins": ("1.1.2.02.002", "2.1.1.02.002"),  # COFINS a recuperar, COFINS a recolher
        "ipi": ("1.1.2.03.001", "2.1.1.03.001"),     # IPI a recuperar, IPI a recolher
        "iss": ("1.1.2.04.001", "2.1.1.04.001"),     # ISS a recolher
        "irpj": (None, "2.1.1.05.001"),               # IRPJ a recolher
        "csll": (None, "2.1.1.05.002"),               # CSLL a recolher
    }

    for tributo, (account_rec, account_pay) in tax_gl_map.items():
        # Get calculated value from tax_apuration
        calc_row = conn.execute(
            """SELECT COALESCE(SUM(CAST(valor_pagar AS REAL)), 0) as total_calc,
                      COALESCE(SUM(CAST(debito AS REAL)), 0) as total_debit,
                      COALESCE(SUM(CAST(credito AS REAL)), 0) as total_credit
               FROM tax_apuration
               WHERE company_id = ? AND tributo = ?""",
            (company_id, tributo)
        ).fetchone()

        calc_pagar = _d(calc_row["total_calc"] if calc_row else 0)

        # Get GL balance for payable account
        gl_row = conn.execute(
            """SELECT COALESCE(SUM(CAST(credit AS REAL)), 0) -
                      COALESCE(SUM(CAST(debit AS REAL)), 0) as balance
               FROM gl_entry
               WHERE company_id = ? AND account = ? AND posting_date LIKE ?""",
            (company_id, account_pay, f"{data_prefix}%")
        ).fetchone()

        gl_balance = _d(gl_row["balance"] if gl_row else 0)

        diff = calc_pagar - gl_balance
        if abs(diff) > Decimal("0.01"):
            status = "divergente"
            differences_found += 1
        else:
            status = "conciliado"

        reconciliations.append({
            "tributo": tributo.upper(),
            "conta_gl": account_pay,
            "apurado": _fmt(calc_pagar),
            "gl_balance": _fmt(gl_balance),
            "diferenca": _fmt(diff),
            "status": status,
        })

    conn.commit()
    return ok({
        "tributo": "Conciliação Fiscal",
        "ano": ano, "mes": mes,
        "total_divergencias": differences_found,
        "conciliacoes": reconciliations,
    })


# ═══════════════════════════════════════════════════════════════════════
# Action 12: generate-darf — DARF generation
# ═══════════════════════════════════════════════════════════════════════

def generate_darf(conn, args):
    """Gera guias DARF (Documento de Arrecadação de Receitas Federais).

    Args: --company-id, --ano, --mes
    """
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatório")

    ano = args.ano or datetime.now().year
    mes = args.mes or (datetime.now().month - 1 if datetime.now().month > 1 else 12)

    # Get company CNPJ
    row = conn.execute(
        "SELECT cnpj, razao_social FROM company_fiscal WHERE company_id = ?",
        (company_id,)
    ).fetchone()
    if not row:
        return err("Dados fiscais da empresa não cadastrados (company_fiscal)")

    cnpj = row["cnpj"]
    razao = row["razao_social"] or ""

    # Get all pending tax_apuration entries for the period
    entries = conn.execute(
        """SELECT id, tributo, uf, valor_pagar, codigo_receita
           FROM tax_apuration
           WHERE company_id = ? AND status = 'pendente'
           ORDER BY tributo""",
        (company_id,)
    ).fetchall()

    darfs = []
    total_geral = Decimal("0.00")

    for entry in entries:
        valor = _d(entry["valor_pagar"])
        if valor <= Decimal("0"):
            continue

        tributo = entry["tributo"]
        cod_receita = entry["codigo_receita"]

        # Determine DARF code if not already set
        if not cod_receita:
            if tributo == "irpj":
                cod_receita = DARF_CODES["irpj"]["lucro_real_mensal"]
            elif tributo == "csll":
                cod_receita = DARF_CODES["csll"]["lucro_real_mensal"]
            elif tributo == "pis":
                cod_receita = DARF_CODES["pis_nao_cumulativo"]
            elif tributo == "cofins":
                cod_receita = DARF_CODES["cofins_nao_cumulativo"]
            elif tributo == "ipi":
                cod_receita = DARF_CODES["ipi"]
            elif tributo in ("ir", "pis", "cofins", "csll") and entry["uf"] == "RETENCAO":
                cod_receita = DARF_CODES["retencoes"]
            elif tributo == "simples":
                cod_receita = DARF_CODES["irpj"]["simples"]
            else:
                cod_receita = "9999"  # unknown

        darfs.append({
            "tributo": tributo.upper(),
            "codigo_receita": cod_receita,
            "periodo_apuracao": f"{mes:02d}/{ano}",
            "cnpj": cnpj,
            "contribuinte": razao,
            "valor_principal": _fmt(valor),
            "tax_apuration_id": entry["id"],
        })
        total_geral += valor

    return ok({
        "documento": "DARF",
        "ano": ano, "mes": mes,
        "cnpj": cnpj,
        "total_darf": _fmt(total_geral),
        "guias": darfs,
        "darf_codes_reference": DARF_CODES,
    })


# ═══════════════════════════════════════════════════════════════════════
# Action 13: generate-gnre — GNRE for interstate ICMS
# ═══════════════════════════════════════════════════════════════════════

def generate_gnre(conn, args):
    """Gera GNRE (Guia Nacional de Recolhimento Estadual).

    Args: --company-id, --ano, --mes, --uf-destino (optional)
    """
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatório")

    ano = args.ano or datetime.now().year
    mes = args.mes or (datetime.now().month - 1 if datetime.now().month > 1 else 12)
    uf_dest = (getattr(args, "uf_destino", None) or "").upper().strip() or None

    # Get company data
    row = conn.execute(
        "SELECT cnpj, razao_social, uf FROM company_fiscal WHERE company_id = ?",
        (company_id,)
    ).fetchone()
    if not row:
        return err("Dados fiscais da empresa não cadastrados")

    cnpj_emit = row["cnpj"]
    razao = row["razao_social"] or ""
    uf_origem = row["uf"]

    # Get DIFAL entries for interstate operations
    query = """SELECT uf, COALESCE(SUM(CAST(valor_pagar AS REAL)), 0) as total_difal
               FROM tax_apuration
               WHERE company_id = ? AND tributo = 'difal'
               AND uf != ? AND status = 'pendente'"""
    params = [company_id, uf_origem]

    if uf_dest:
        query += " AND uf = ?"
        params.append(uf_dest)

    query += " GROUP BY uf"

    entries = conn.execute(query, params).fetchall()

    gnres = []
    total_gnre = Decimal("0.00")

    # GNRE receipt codes
    GNRE_CODES = {
        "ICMS": "100006",       # ICMS interestadual
        "ICMS_ST": "100010",    # ICMS ST
        "DIFAL": "100099",      # DIFAL
        "FECP": "100021",       # FECP
    }

    for entry in entries:
        uf = entry["uf"]
        valor = _d(entry["total_difal"])
        if valor <= Decimal("0"):
            continue

        # Also get ICMS ST for this destination
        st_row = conn.execute(
            """SELECT COALESCE(SUM(CAST(valor_pagar AS REAL)), 0)
               FROM tax_apuration
               WHERE company_id = ? AND tributo = 'icms_st' AND uf = ? AND status = 'pendente'""",
            (company_id, uf)
        ).fetchone()
        st_valor = _d(st_row[0] if st_row else 0)

        gnres.append({
            "uf_destino": uf,
            "uf_origem": uf_origem,
            "cnpj_emitente": cnpj_emit,
            "razao_social": razao,
            "periodo_referencia": f"{mes:02d}/{ano}",
            "vencimento": f"{ano}-{mes+1:02d}-15" if mes < 12 else f"{ano+1}-01-15",
            "icms_difal": {
                "codigo_receita": GNRE_CODES["DIFAL"],
                "valor": _fmt(valor),
            },
        })

        if st_valor > Decimal("0"):
            gnres[-1]["icms_st"] = {
                "codigo_receita": GNRE_CODES["ICMS_ST"],
                "valor": _fmt(st_valor),
            }

        total_gnre += valor + st_valor

    return ok({
        "documento": "GNRE",
        "ano": ano, "mes": mes,
        "uf_origem": uf_origem,
        "total_gnre": _fmt(total_gnre),
        "guias": gnres,
    })


# ═══════════════════════════════════════════════════════════════════════
# Action 14: list-tax-periods
# ═══════════════════════════════════════════════════════════════════════

def list_tax_periods(conn, args):
    """Lista períodos de apuração fiscal.

    Args: --company-id, --limit
    """
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatório")

    limit = min(getattr(args, "limit", 50) or 50, 200)

    rows = conn.execute(
        """SELECT tp.id, tp.ano, tp.mes, tp.regime, tp.status,
                  COUNT(ta.id) as total_apuracoes,
                  COALESCE(SUM(CAST(ta.valor_pagar AS REAL)), 0) as total_impostos
           FROM tax_period_br tp
           LEFT JOIN tax_apuration ta ON ta.tax_period_br_id = tp.id
           WHERE tp.company_id = ?
           GROUP BY tp.id
           ORDER BY tp.ano DESC, tp.mes DESC LIMIT ?""",
        (company_id, limit)
    ).fetchall()

    return ok({
        "periods": [{
            "id": r[0], "ano": r[1], "mes": r[2], "regime": r[3], "status": r[4],
            "total_apuracoes": r[5], "total_impostos": f"{r[6]:.2f}" if r[6] else "0.00"
        } for r in rows]
    })


# ═══════════════════════════════════════════════════════════════════════
# Action 15: close-tax-period
# ═══════════════════════════════════════════════════════════════════════

def close_tax_period(conn, args):
    """Fecha período de apuração fiscal.

    Args: --tax-period-id
    """
    tax_id = args.tax_period_id
    if not tax_id:
        return err("--tax-period-id obrigatório")

    # Check if period exists
    existing = conn.execute(
        "SELECT id, ano, mes, status FROM tax_period_br WHERE id = ?",
        (tax_id,)
    ).fetchone()
    if not existing:
        return err(f"Período {tax_id} não encontrado")

    if existing["status"] == "fechado":
        return err(f"Período {existing['ano']}/{existing['mes']:02d} já está fechado")

    conn.execute(
        "UPDATE tax_period_br SET status = 'fechado', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (tax_id,)
    )

    # Mark related tax_apuration as finalized
    conn.execute(
        "UPDATE tax_apuration SET status = 'pago' WHERE tax_period_br_id = ? AND status = 'pendente'",
        (tax_id,)
    )

    conn.commit()
    return ok({
        "tax_period_id": tax_id,
        "ano": existing["ano"],
        "mes": f"{existing['mes']:02d}",
        "status": "fechado",
        "apuracoes_finalizadas": conn.execute(
            "SELECT COUNT(*) FROM tax_apuration WHERE tax_period_br_id = ? AND status = 'pago'",
            (tax_id,)
        ).fetchone()[0],
    })


# ═══════════════════════════════════════════════════════════════════════
# Action Registry — 15 actions
# ═══════════════════════════════════════════════════════════════════════

ACTIONS = {
    "calculate-icms": calculate_icms,
    "calculate-icms-st": calculate_icms_st,
    "calculate-fecp": calculate_fecp,
    "calculate-pis-cofins": calculate_pis_cofins,
    "calculate-difal": calculate_difal,
    "calculate-simples-nacional": calculate_simples_nacional,
    "calculate-irpj-csll": calculate_irpj_csll,
    "calculate-ciap": calculate_ciap,
    "calculate-iss": calculate_iss,
    "calculate-withholding": calculate_withholding,
    "reconcile-tax-accounts": reconcile_tax_accounts,
    "generate-darf": generate_darf,
    "generate-gnre": generate_gnre,
    "list-tax-periods": list_tax_periods,
    "close-tax-period": close_tax_period,
}
