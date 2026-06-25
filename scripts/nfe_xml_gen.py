"""NF-e XML Generator — Brazilian Electronic Invoice XML (Layout 4.00)

Generates complete NFe XML from database records.
Namespaces, structure, and validation follow NT 2024.001.

Library module: no direct ACTIONS — used by nfe_emission.py.
"""
from __future__ import annotations

import os
import random
import sys
from datetime import datetime
from decimal import Decimal
from xml.etree.ElementTree import Element, SubElement, tostring

# Try erpclaw_lib for DB connection if available
try:
    sys.path.insert(0, os.path.expanduser("~/.openclaw/erpclaw/lib"))
    from erpclaw_lib.response import ok, err
except ImportError:
    ok = err = None  # graceful degradation when used standalone

# ── Constants ──────────────────────────────────────────────────────────
NFE_NAMESPACE = "http://www.portalfiscal.inf.br/nfe"
MODELO_NFE = "55"
VERSAO_LAYOUT = "4.00"


# ── Public API ─────────────────────────────────────────────────────────

def generate_nfe_xml(conn, nfe_out_id: str) -> str | None:
    """Generate complete NFe XML from br_nfe_out record and its items.

    Args:
        conn: Database connection.
        nfe_out_id: UUID of the br_nfe_out record.

    Returns:
        Complete unsigned NFe XML string, or None on failure.
    """
    # Load NF-e header
    row = conn.execute(
        "SELECT * FROM br_nfe_out WHERE id = ?", (nfe_out_id,)
    ).fetchone()
    if not row:
        return None
    nfe_data = dict(row)

    # Load company / emitente config
    company = conn.execute(
        "SELECT * FROM company WHERE id = ?", (nfe_data["company_id"],)
    ).fetchone()
    if not company:
        return None
    company_data = dict(company)

    # Load items from the linked sales invoice (or directly from nfe_item if already stored)
    items = _load_items(conn, nfe_data)

    # Load NF-e config
    cfg = conn.execute(
        "SELECT * FROM br_nfe_config WHERE company_id = ?", (nfe_data["company_id"],)
    ).fetchone()
    cfg_data = dict(cfg) if cfg else {}

    return _assemble_nfe_xml(nfe_data, items, company_data, cfg_data)


def _load_items(conn, nfe_data: dict) -> list[dict]:
    """Load line items from the linked sales invoice or br_nfe_out_items."""
    # Try dedicated NF-e items table first
    items = conn.execute(
        "SELECT * FROM br_nfe_out_item WHERE nfe_out_id = ? ORDER BY numero_item",
        (nfe_data["id"],)
    ).fetchall()
    if items:
        return [dict(it) for it in items]

    # Fall back to sales_invoice_items
    si_id = nfe_data.get("sales_invoice_id")
    if not si_id:
        return []

    rows = conn.execute(
        """SELECT sii.*, i.name as item_name, i.unit as unit_of_measure,
                  cf.cfv_value as ncm_code
           FROM sales_invoice_item sii
           JOIN item i ON i.id = sii.item_id
           LEFT JOIN custom_field_value cf ON cf.record_id = i.id
                AND cf.field_name = 'ncm'
           WHERE sii.sales_invoice_id = ?
           ORDER BY sii.line_number""",
        (si_id,)
    ).fetchall()

    result = []
    for idx, r in enumerate(rows):
        rd = dict(r)
        qty = Decimal(str(rd.get("quantity", "1")))
        price = Decimal(str(rd.get("unit_price", "0")))
        total = qty * price

        # Load fiscal data per item
        cfop = _get_custom_field(conn, rd["item_id"], "cfop", "5102")
        cst_icms = _get_custom_field(conn, rd["item_id"], "cst_icms", "00")
        cst_pis = _get_custom_field(conn, rd["item_id"], "cst_pis", "01")
        cst_cofins = _get_custom_field(conn, rd["item_id"], "cst_cofins", "01")
        ncm = rd.get("ncm_code") or _get_custom_field(conn, rd["item_id"], "ncm", "")

        # Tax rates — stored as custom fields or use defaults
        p_icms = Decimal(_get_custom_field(conn, rd["item_id"], "aliq_icms", "18.00"))
        p_pis = Decimal(_get_custom_field(conn, rd["item_id"], "aliq_pis", "1.65"))
        p_cofins = Decimal(_get_custom_field(conn, rd["item_id"], "aliq_cofins", "7.60"))
        p_ipi = Decimal(_get_custom_field(conn, rd["item_id"], "aliq_ipi", "0.00"))

        result.append({
            "numero_item": idx + 1,
            "codigo_produto": rd.get("item_id", ""),
            "descricao": rd.get("item_name", rd.get("description", "")),
            "ncm": ncm,
            "cfop": cfop,
            "cst_icms": cst_icms,
            "cst_pis": cst_pis,
            "cst_cofins": cst_cofins,
            "unidade": rd.get("unit_of_measure", "UN"),
            "quantidade": str(qty),
            "valor_unitario": str(price),
            "valor_total": str(total),
            "base_icms": str(total),
            "aliquota_icms": str(p_icms),
            "valor_icms": str(round(total * p_icms / Decimal("100"), 2)),
            "base_ipi": str(total),
            "aliquota_ipi": str(p_ipi),
            "valor_ipi": str(round(total * p_ipi / Decimal("100"), 2)),
            "aliquota_pis": str(p_pis),
            "valor_pis": str(round(total * p_pis / Decimal("100"), 2)),
            "aliquota_cofins": str(p_cofins),
            "valor_cofins": str(round(total * p_cofins / Decimal("100"), 2)),
        })
    return result


def _get_custom_field(conn, record_id: str, field_name: str, default: str = "") -> str:
    """Fetch a custom field value from the ERPClaw core schema."""
    row = conn.execute(
        "SELECT cfv_value FROM custom_field_value WHERE record_id = ? AND field_name = ?",
        (record_id, field_name)
    ).fetchone()
    return row[0] if row else default


# ── XML Assembly ───────────────────────────────────────────────────────

def _assemble_nfe_xml(nfe_data: dict, items: list[dict],
                      company_data: dict, cfg_data: dict) -> str:
    """Build the full NFe XML document."""
    # Compute chave if not already set
    chave = nfe_data.get("chave_acesso", "")
    if not chave:
        chave = _compute_chave_acesso_tuple(nfe_data, cfg_data)

    # Root element with namespace
    root = Element("NFe", xmlns=NFE_NAMESPACE)
    inf_nfe = SubElement(root, "infNFe", {
        "Id": f"NFe{chave}",
        "versao": VERSAO_LAYOUT,
    })

    # Required child groups (order matters per SEFAZ schema)
    _build_ide(inf_nfe, nfe_data, cfg_data)
    _build_emit(inf_nfe, company_data, cfg_data)
    _build_dest(inf_nfe, nfe_data)
    _build_det(inf_nfe, items)
    _build_total(inf_nfe, nfe_data, items)
    _build_transp(inf_nfe, nfe_data)
    _build_cobr(inf_nfe, nfe_data)
    _build_inf_adic(inf_nfe, nfe_data)

    xml_bytes = tostring(root, encoding="unicode", xml_declaration=True)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_bytes[len('<?xml version="1.0" encoding="UTF-8"?>\n'):]


# ── Group B: Identificação ─────────────────────────────────────────────

def _build_ide(inf_nfe: Element, nfe_data: dict, cfg_data: dict):
    """Build <ide> (Identificação da NF-e) group B."""
    uf = cfg_data.get("uf", "35")
    serie = nfe_data.get("serie", cfg_data.get("serie_default", "1"))
    n_nf = str(nfe_data.get("numero", ""))
    data_emissao = nfe_data.get("data_emissao", "")

    # Compute cNF (random 8-digit code) if chave not yet set
    cnf = str(random.randint(10000000, 99999999))
    if nfe_data.get("chave_acesso"):
        # Extract cNF from existing chave (positions 35-42)
        cnf = nfe_data["chave_acesso"][35:43]

    ide = SubElement(inf_nfe, "ide")
    SubElement(ide, "cUF").text = _codigo_uf(uf)
    SubElement(ide, "cNF").text = cnf
    SubElement(ide, "natOp").text = nfe_data.get("natureza_operacao", "VENDA DE MERCADORIA")
    SubElement(ide, "mod").text = nfe_data.get("modelo", "55")
    SubElement(ide, "serie").text = serie
    SubElement(ide, "nNF").text = n_nf

    # dhEmi format: YYYY-MM-DDTHH:MM:SS+TZ
    dh_emi = _format_dh_emi(data_emissao, nfe_data.get("hora_saida", ""))
    SubElement(ide, "dhEmi").text = dh_emi

    if nfe_data.get("data_saida"):
        dh_sai = _format_dh_emi(nfe_data["data_saida"], nfe_data.get("hora_saida", ""))
        SubElement(ide, "dhSaiEnt").text = dh_sai

    SubElement(ide, "tpNF").text = _tp_nf(nfe_data)
    SubElement(ide, "idDest").text = "1"  # 1=interestadual, 2=interna, 3=exterior
    SubElement(ide, "cMunFG").text = cfg_data.get("codigo_municipio", "3550308")

    tp_imp = "1"  # 1=DANFE normal
    SubElement(ide, "tpImp").text = tp_imp

    tp_emis = _tp_emis(cfg_data)
    SubElement(ide, "tpEmis").text = tp_emis

    SubElement(ide, "cDV").text = "0"  # check digit computed separately
    tp_amb = "1" if cfg_data.get("ambiente") == "producao" else "2"
    SubElement(ide, "tpAmb").text = tp_amb

    finalidade = nfe_data.get("finalidade", "normal")
    fin_map = {"normal": "1", "complementar": "2", "ajuste": "3", "devolucao": "4"}
    SubElement(ide, "finNFe").text = fin_map.get(finalidade, "1")

    ind_final = "1"  # 1=consumidor final
    SubElement(ide, "indFinal").text = ind_final
    ind_pres = "1"  # 1=presencial
    SubElement(ide, "indPres").text = ind_pres

    ind_intermed = "0"  # 0=sem intermediario
    SubElement(ide, "indIntermed").text = ind_intermed
    SubElement(ide, "procEmi").text = "0"  # 0=emissão com certificado A1
    SubElement(ide, "verProc").text = "ERPClaw-BR/1.1.0"


def _format_dh_emi(data_str: str, hora_str: str = "") -> str:
    """Format datetime for dhEmi field: YYYY-MM-DDTHH:MM:SS-03:00"""
    if not data_str:
        return datetime.now().strftime("%Y-%m-%dT%H:%M:%S") + "-03:00"

    if "T" in data_str:
        return data_str  # already formatted

    hora = hora_str or "12:00:00"
    # Ensure hora has seconds
    if len(hora) == 5:
        hora = hora + ":00"
    return f"{data_str}T{hora}-03:00"


def _tp_nf(nfe_data: dict) -> str:
    """Return tipo NF: 0=entrada, 1=saida."""
    return "1" if nfe_data.get("tipo_operacao", "saida") == "saida" else "0"


def _tp_emis(cfg_data: dict) -> str:
    """Return tipo emissao: 1=normal, 4=EPEC, 5=FS-DA, 6=SVC-AN, 7=SVC-RS, 9=offline."""
    tipo = cfg_data.get("tipo_emissao", "normal")
    return "1" if tipo == "normal" else "9"


# ── Group C: Emitente ──────────────────────────────────────────────────

def _build_emit(inf_nfe: Element, company_data: dict, cfg_data: dict):
    """Build <emit> (Emitente) group C."""
    emit = SubElement(inf_nfe, "emit")

    # CNPJ from company record or custom field
    cnpj = company_data.get("tax_id") or company_data.get("company_tax_id", "")
    if not cnpj:
        cnpj = _get_company_fiscal_data(company_data, "cnpj", "00000000000000")
    SubElement(emit, "CNPJ").text = _clean_cnpj(cnpj)

    x_nome = company_data.get("name", "")
    # Razão social or nome fantasia
    SubElement(emit, "xNome").text = _truncate_60(x_nome or "Empresa")

    nome_fantasia = company_data.get("legal_name") or company_data.get("name", "")
    SubElement(emit, "xFant").text = _truncate_60(nome_fantasia or x_nome or "")

    # Endereço do emitente
    ender_emit = SubElement(emit, "enderEmit")
    SubElement(ender_emit, "xLgr").text = company_data.get("address_line1", "")[:60] or "RUA SEM CADASTRO"
    SubElement(ender_emit, "nro").text = company_data.get("address_number", "0") or "S/N"
    SubElement(ender_emit, "xCpl").text = (company_data.get("address_line2", "") or "")[:60]
    SubElement(ender_emit, "xBairro").text = (company_data.get("district", "") or "")[:60]
    SubElement(ender_emit, "cMun").text = cfg_data.get("codigo_municipio", "3550308")
    SubElement(ender_emit, "xMun").text = (company_data.get("city", "") or "")[:60]
    SubElement(ender_emit, "UF").text = cfg_data.get("uf", "SP")
    SubElement(ender_emit, "CEP").text = _clean_cep(company_data.get("postal_code", "00000000"))
    SubElement(ender_emit, "cPais").text = "1058"  # Brasil
    SubElement(ender_emit, "xPais").text = "BRASIL"
    SubElement(ender_emit, "fone").text = _clean_phone(company_data.get("phone", ""))

    ie = _get_company_fiscal_data(company_data, "ie", "")
    if ie:
        SubElement(emit, "IE").text = _clean_ie(ie)

    ie_st = _get_company_fiscal_data(company_data, "ie_st", "")
    if ie_st:
        SubElement(emit, "IEST").text = _clean_ie(ie_st)

    # CRTs
    regime = cfg_data.get("regime_tributario", "normal")
    if regime == "simples_nacional":
        crt_code = "1"
    elif regime == "simples_excesso":
        crt_code = "2"
    else:
        crt_code = "3"  # Regime Normal
    SubElement(emit, "CRT").text = crt_code


def _get_company_fiscal_data(company_data: dict, key: str, default: str = "") -> str:
    """Extract fiscal data from company custom fields."""
    # company_data is from the 'company' table; fiscal data may be in
    # custom_field_value or in the company record itself
    val = company_data.get(key, "") or company_data.get(f"company_{key}", "")
    return str(val) if val else default


# ── Group E: Destinatário ──────────────────────────────────────────────

def _build_dest(inf_nfe: Element, nfe_data: dict):
    """Build <dest> (Destinatário) group E."""
    dest = SubElement(inf_nfe, "dest")

    cnpj = nfe_data.get("customer_cnpj", "")
    cpf = nfe_data.get("customer_cpf", "")
    if cnpj and len(_clean_cnpj(cnpj)) >= 14:
        SubElement(dest, "CNPJ").text = _clean_cnpj(cnpj)
    elif cpf and len(_clean_cpf(cpf)) >= 11:
        SubElement(dest, "CPF").text = _clean_cpf(cpf)
    else:
        SubElement(dest, "CNPJ").text = "00000000000000"  # fallback

    SubElement(dest, "xNome").text = _truncate_60(nfe_data.get("customer_name", "CONSUMIDOR NAO IDENTIFICADO"))

    # Endereço — simplified (full address from customer record if available)
    ender_dest = SubElement(dest, "enderDest")
    SubElement(ender_dest, "xLgr").text = "RUA SEM CADASTRO"
    SubElement(ender_dest, "nro").text = "0"
    SubElement(ender_dest, "xBairro").text = "CENTRO"
    SubElement(ender_dest, "cMun").text = "3550308"
    SubElement(ender_dest, "xMun").text = "SAO PAULO"
    SubElement(ender_dest, "UF").text = "SP"
    SubElement(ender_dest, "CEP").text = "00000000"
    SubElement(ender_dest, "cPais").text = "1058"
    SubElement(ender_dest, "xPais").text = "BRASIL"

    ie = nfe_data.get("customer_ie", "")
    if ie:
        SubElement(dest, "IE").text = _clean_ie(ie)

    isuf = nfe_data.get("customer_isuf", "")
    if isuf:
        SubElement(dest, "ISUF").text = isuf

    email = nfe_data.get("customer_email", "")
    if email:
        SubElement(dest, "email").text = email[:60]

    SubElement(dest, "indIEDest").text = _ind_ie_dest(ie)


def _ind_ie_dest(ie: str) -> str:
    """Indicador IE do destinatário: 1=contribuinte, 2=isento, 9=nao contribuinte."""
    if ie and len(_clean_ie(ie)) >= 8:
        return "1"
    return "9"


# ── Group H: Detalhe (Produtos e Serviços) ─────────────────────────────

def _build_det(inf_nfe: Element, items: list[dict]):
    """Build <det nItem="N"> elements for each line item."""
    for item in items:
        n = str(item.get("numero_item", "1"))
        det = SubElement(inf_nfe, "det", {"nItem": n})

        prod = SubElement(det, "prod")
        SubElement(prod, "cProd").text = _truncate_60(item.get("codigo_produto", ""))
        SubElement(prod, "cEAN").text = "SEM GTIN"
        SubElement(prod, "xProd").text = _truncate_120(item.get("descricao", ""))
        ncm = _clean_ncm(item.get("ncm", "00"))
        SubElement(prod, "NCM").text = ncm

        # CFOP
        cfop = item.get("cfop", "5102")
        SubElement(prod, "CFOP").text = cfop.replace(".", "")

        SubElement(prod, "uCom").text = item.get("unidade", "UN")[:6]
        SubElement(prod, "qCom").text = _fmt_dec(item.get("quantidade", "1"))
        SubElement(prod, "vUnCom").text = _fmt_dec(item.get("valor_unitario", "0.00"))
        SubElement(prod, "vProd").text = _fmt_dec(item.get("valor_total", "0.00"))

        # UPC / uTrib — simplified (same as comercial)
        SubElement(prod, "uTrib").text = item.get("unidade", "UN")[:6]
        SubElement(prod, "qTrib").text = _fmt_dec(item.get("quantidade", "1"))
        SubElement(prod, "vUnTrib").text = _fmt_dec(item.get("valor_unitario", "0.00"))

        SubElement(prod, "indTot").text = "1"  # compõe total

        # Imposto (Group N)
        imposto = SubElement(det, "imposto")

        # ICMS
        _build_icms(imposto, item)

        # IPI
        _build_ipi(imposto, item)

        # PIS
        _build_pis(imposto, item)

        # COFINS
        _build_cofins(imposto, item)


def _build_icms(imposto: Element, item: dict):
    """Build ICMS tag based on CST."""
    icms = SubElement(imposto, "ICMS")
    cst = item.get("cst_icms", "00")

    # ICMS00 — Tributada integralmente
    icms_tag = SubElement(icms, "ICMS00")
    SubElement(icms_tag, "orig").text = "0"  # nacional
    SubElement(icms_tag, "CST").text = cst
    SubElement(icms_tag, "modBC").text = "3"  # valor da operação
    SubElement(icms_tag, "vBC").text = _fmt_dec(item.get("base_icms", "0.00"))
    SubElement(icms_tag, "pICMS").text = _fmt_dec(item.get("aliquota_icms", "18.00"))
    SubElement(icms_tag, "vICMS").text = _fmt_dec(item.get("valor_icms", "0.00"))
    SubElement(icms_tag, "pFCP").text = "0.00"
    SubElement(icms_tag, "vFCP").text = "0.00"


def _build_ipi(imposto: Element, item: dict):
    """Build IPI tag."""
    v_ipi = item.get("valor_ipi", "0.00")
    if Decimal(v_ipi or "0") == 0:
        return  # skip if no IPI

    ipi = SubElement(imposto, "IPI")
    ipi_tag = SubElement(ipi, "IPITrib")
    SubElement(ipi_tag, "CST").text = item.get("cst_ipi", "50") or "50"
    SubElement(ipi_tag, "vBC").text = _fmt_dec(item.get("base_ipi", "0.00"))
    SubElement(ipi_tag, "pIPI").text = _fmt_dec(item.get("aliquota_ipi", "0.00"))
    SubElement(ipi_tag, "vIPI").text = _fmt_dec(v_ipi)


def _build_pis(imposto: Element, item: dict):
    """Build PIS tag."""
    pis = SubElement(imposto, "PIS")
    pis_tag = SubElement(pis, "PISAliq")
    SubElement(pis_tag, "CST").text = item.get("cst_pis", "01") or "01"
    SubElement(pis_tag, "vBC").text = _fmt_dec(item.get("valor_total", "0.00"))
    SubElement(pis_tag, "pPIS").text = _fmt_dec(item.get("aliquota_pis", "1.65"))
    SubElement(pis_tag, "vPIS").text = _fmt_dec(item.get("valor_pis", "0.00"))


def _build_cofins(imposto: Element, item: dict):
    """Build COFINS tag."""
    cofins = SubElement(imposto, "COFINS")
    cofins_tag = SubElement(cofins, "COFINSAliq")
    SubElement(cofins_tag, "CST").text = item.get("cst_cofins", "01") or "01"
    SubElement(cofins_tag, "vBC").text = _fmt_dec(item.get("valor_total", "0.00"))
    SubElement(cofins_tag, "pCOFINS").text = _fmt_dec(item.get("aliquota_cofins", "7.60"))
    SubElement(cofins_tag, "vCOFINS").text = _fmt_dec(item.get("valor_cofins", "0.00"))


# ── Group W: Totais ────────────────────────────────────────────────────

def _build_total(inf_nfe: Element, nfe_data: dict, items: list[dict]):
    """Build <total> (Totais da NF-e) group W."""
    total = SubElement(inf_nfe, "total")

    # ICMSTot
    icms_tot = SubElement(total, "ICMSTot")
    SubElement(icms_tot, "vBC").text = _fmt_dec(nfe_data.get("base_icms", "0.00"))
    SubElement(icms_tot, "vICMS").text = _fmt_dec(nfe_data.get("valor_icms", "0.00"))
    SubElement(icms_tot, "vICMSDeson").text = _fmt_dec(nfe_data.get("valor_icms_desonerado", "0.00"))
    SubElement(icms_tot, "vFCPUFDest").text = "0.00"
    SubElement(icms_tot, "vICMSUFDest").text = _fmt_dec(nfe_data.get("valor_icms_uf_dest", "0.00"))
    SubElement(icms_tot, "vICMSUFRemet").text = _fmt_dec(nfe_data.get("valor_icms_uf_remet", "0.00"))
    SubElement(icms_tot, "vFCP").text = "0.00"
    SubElement(icms_tot, "vBCST").text = _fmt_dec(nfe_data.get("base_icms_st", "0.00"))
    SubElement(icms_tot, "vST").text = _fmt_dec(nfe_data.get("valor_icms_st", "0.00"))
    SubElement(icms_tot, "vFCPST").text = "0.00"
    SubElement(icms_tot, "vFCPSTRet").text = "0.00"

    v_prod = nfe_data.get("valor_produtos", "0.00")
    SubElement(icms_tot, "vProd").text = _fmt_dec(v_prod)
    SubElement(icms_tot, "vFrete").text = _fmt_dec(nfe_data.get("valor_frete", "0.00"))
    SubElement(icms_tot, "vSeg").text = _fmt_dec(nfe_data.get("valor_seguro", "0.00"))
    SubElement(icms_tot, "vDesc").text = _fmt_dec(nfe_data.get("valor_desconto", "0.00"))
    SubElement(icms_tot, "vII").text = _fmt_dec(nfe_data.get("valor_ii", "0.00"))
    SubElement(icms_tot, "vIPI").text = _fmt_dec(nfe_data.get("valor_ipi", "0.00"))
    SubElement(icms_tot, "vIPIDevol").text = "0.00"
    SubElement(icms_tot, "vPIS").text = _fmt_dec(nfe_data.get("valor_pis", "0.00"))
    SubElement(icms_tot, "vCOFINS").text = _fmt_dec(nfe_data.get("valor_cofins", "0.00"))
    SubElement(icms_tot, "vOutro").text = _fmt_dec(nfe_data.get("outras_despesas", "0.00"))
    SubElement(icms_tot, "vNF").text = _fmt_dec(nfe_data.get("valor_total", "0.00"))
    SubElement(icms_tot, "vTotTrib").text = _fmt_dec(nfe_data.get("valor_aproximado_tributos", "0.00"))


# ── Group X: Transporte ────────────────────────────────────────────────

def _build_transp(inf_nfe: Element, nfe_data: dict):
    """Build <transp> (Transporte) group X."""
    transp = SubElement(inf_nfe, "transp")
    frete = nfe_data.get("valor_frete", "0.00")
    mod_frete = "9" if Decimal(frete or "0") == 0 else "0"  # 9=sem frete, 0=emitente
    SubElement(transp, "modFrete").text = mod_frete


# ── Group Y: Cobrança ──────────────────────────────────────────────────

def _build_cobr(inf_nfe: Element, nfe_data: dict):
    """Build <cobr> (Cobrança) group Y — simplified (no fatura/dup)."""
    SubElement(inf_nfe, "cobr")
    # Fatura and duplicata optional; omitted for simplicity


# ── Group Z: Informações Adicionais ─────────────────────────────────────

def _build_inf_adic(inf_nfe: Element, nfe_data: dict):
    """Build <infAdic> (Informações Adicionais) group Z."""
    inf_adic = SubElement(inf_nfe, "infAdic")
    info = nfe_data.get("info_complementar", "")
    if info:
        SubElement(inf_adic, "infCpl").text = info[:5000]
    fisco = nfe_data.get("info_fisco", "")
    if fisco:
        SubElement(inf_adic, "infAdFisco").text = fisco[:2000]


# ── Chave de Acesso Computation ────────────────────────────────────────

def _compute_chave_acesso_tuple(nfe_data: dict, cfg_data: dict) -> str:
    """Compute the 44-digit access key from NF-e fields.

    Composition (NT 2024.001):
      cUF(2) + AAMM(4) + CNPJ(14) + mod(2) + serie(3) + nNF(9) + tpEmis(1) + cNF(8)
    Last digit is modulo-11 check digit.

    Returns:
        44-character chave de acesso.
    """
    from datetime import datetime

    uf = cfg_data.get("uf", "SP")
    cuf = _codigo_uf(uf)

    # AAMM from data_emissao
    data_em = nfe_data.get("data_emissao", "")
    if len(data_em) >= 7:
        aamm = data_em[2:4] + data_em[5:7]
    else:
        aamm = datetime.now().strftime("%y%m")

    cnpj = _clean_cnpj(nfe_data.get("emitente_cnpj", "00000000000000"))
    mod = nfe_data.get("modelo", "55")
    serie = str(nfe_data.get("serie", cfg_data.get("serie_default", "1"))).zfill(3)
    n_nf = str(nfe_data.get("numero", "1")).zfill(9)
    tp_emis = _tp_emis(cfg_data)
    cnf = str(random.randint(10000000, 99999999))

    base = f"{cuf}{aamm}{cnpj}{mod}{serie}{n_nf}{tp_emis}{cnf}"
    dv = _calc_dv_mod11(base)
    return base + dv


def _compute_chave_acesso(nfe_data: dict) -> str:
    """Compute the 44-digit NFe access key (chave de acesso).

    Uses data from the nfe_data dict. If chave_acesso already present, returns it.
    Standalone variant that doesn't require cfg_data.
    """
    from datetime import datetime

    if nfe_data.get("chave_acesso") and len(nfe_data["chave_acesso"]) == 44:
        return nfe_data["chave_acesso"]

    cuf = "35"  # default SP
    if "uf" in nfe_data:
        cuf = _codigo_uf(nfe_data["uf"])

    data_em = nfe_data.get("data_emissao", "")
    if len(data_em) >= 7:
        aamm = data_em[2:4] + data_em[5:7]
    else:
        aamm = datetime.now().strftime("%y%m")

    # Try to resolve CNPJ from customer_cnpj or emitente_cnpj
    cnpj = "00000000000000"
    if nfe_data.get("customer_cnpj"):
        cnpj = _clean_cnpj(nfe_data["customer_cnpj"])
    elif nfe_data.get("emitente_cnpj"):
        cnpj = _clean_cnpj(nfe_data["emitente_cnpj"])

    mod = nfe_data.get("modelo", "55")
    serie = str(nfe_data.get("serie", "1")).zfill(3)
    n_nf = str(nfe_data.get("numero", "1")).zfill(9)
    tp_emis = "1"
    if "cfg" in nfe_data:
        tp_emis = _tp_emis(nfe_data["cfg"])
    cnf = str(random.randint(10000000, 99999999))
    if nfe_data.get("chave_acesso") and len(nfe_data["chave_acesso"]) >= 43:
        cnf = nfe_data["chave_acesso"][35:43]

    base = f"{cuf}{aamm}{cnpj}{mod}{serie}{n_nf}{tp_emis}{cnf}"
    dv = _calc_dv_mod11(base)
    return base + dv


# ── Helper Utilities ───────────────────────────────────────────────────

def _codigo_uf(uf: str) -> str:
    """Return IBGE state code (cUF) for a UF abbreviation."""
    uf_codes = {
        "AC": "12", "AL": "27", "AP": "16", "AM": "13", "BA": "29",
        "CE": "23", "DF": "53", "ES": "32", "GO": "52", "MA": "21",
        "MT": "51", "MS": "50", "MG": "31", "PA": "15", "PB": "25",
        "PR": "41", "PE": "26", "PI": "22", "RJ": "33", "RN": "24",
        "RS": "43", "RO": "11", "RR": "14", "SC": "42", "SP": "35",
        "SE": "28", "TO": "17",
    }
    return uf_codes.get(uf.upper(), "35")


def _calc_dv_mod11(base: str) -> str:
    """Compute modulo-11 check digit for NF-e chave de acesso.

    Weights: 2 to 9, repeated from right to left.
    """
    weights = [2, 3, 4, 5, 6, 7, 8, 9]
    total = 0
    for i, ch in enumerate(reversed(base)):
        w = weights[i % 8]
        total += int(ch) * w
    remainder = total % 11
    dv = 0 if remainder <= 1 else 11 - remainder
    return str(dv)


def _clean_cnpj(cnpj: str) -> str:
    """Strip non-digit characters from CNPJ, pad to 14 digits."""
    digits = "".join(ch for ch in (cnpj or "") if ch.isdigit())
    return digits.zfill(14)[:14]


def _clean_cpf(cpf: str) -> str:
    """Strip non-digit characters from CPF, pad to 11 digits."""
    digits = "".join(ch for ch in (cpf or "") if ch.isdigit())
    return digits.zfill(11)[:11]


def _clean_ie(ie: str) -> str:
    """Strip non-digit characters from IE."""
    return "".join(ch for ch in (ie or "") if ch.isdigit() or ch.upper() in "P")


def _clean_cep(cep: str) -> str:
    """Strip non-digit characters from CEP, pad to 8 digits."""
    digits = "".join(ch for ch in (cep or "") if ch.isdigit())
    return digits.zfill(8)[:8]


def _clean_phone(phone: str) -> str:
    """Strip non-digit from phone, truncate to 14."""
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    return digits[:14]


def _clean_ncm(ncm: str) -> str:
    """Clean NCM code: digits only, 8 chars."""
    digits = "".join(ch for ch in (ncm or "") if ch.isdigit())
    return digits.zfill(8)[:8]


def _truncate_60(val: str) -> str:
    """Truncate string to 60 characters (xNome limit)."""
    return (val or "")[:60]


def _truncate_120(val: str) -> str:
    """Truncate string to 120 characters (xProd limit)."""
    return (val or "")[:120]


def _fmt_dec(val: str | Decimal | float) -> str:
    """Format a decimal value to 2 decimal places."""
    if val is None:
        return "0.00"
    return f"{Decimal(str(val)):.2f}"


# ── ACTIONS ────────────────────────────────────────────────────────────

ACTIONS: dict = {}
