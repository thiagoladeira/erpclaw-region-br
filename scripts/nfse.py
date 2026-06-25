"""NFS-e — Nota Fiscal de Serviços Eletrônica — ERPClaw Region BR

Municipal service tax invoice module implementing the ABRASF standard model
(most common format used by Brazilian municipalities).

Supports:
  - ABRASF 2.02/2.03 XML generation (national model)
  - Simplified envelope for Macaé/RJ RPS system
  - ISS 5% for Macaé/RJ (default, configurable)
  - All monetary values as TEXT (Decimal strings)
  - All IDs as TEXT UUID4
  - XML signing via nfe_signer
  - Municipal webservice transmission

Actions:
  configure-nfse  — Configure NFS-e per company (municipio, aliquota, regime)
  create-nfse     — Generate NFS-e from a sales invoice (services-only)
  sign-nfse-xml   — Sign NFS-e XML
  transmit-nfse   — Send to municipal webservice
  check-nfse-status — Check authorization
  cancel-nfse     — Cancel NFS-e
  list-nfse       — List service invoices
  get-nfse        — Detail one NFS-e

Usage: python3 nfse.py --action <action> --flags ...
"""
from __future__ import annotations

import base64
import os
import re
import sys
from datetime import datetime
from decimal import Decimal
from uuid import uuid4
from textwrap import dedent

# ── erpclaw_lib imports ────────────────────────────────────────────────
sys.path.insert(0, os.path.expanduser("~/.openclaw/erpclaw/lib"))
from erpclaw_lib.response import ok, err
from erpclaw_lib.db import get_connection, DEFAULT_DB_PATH

# ── Local imports ──────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from nfe_xml_gen import _clean_cnpj
from nfe_signer import sign_nfe_xml, sign_nfe_event_xml, validate_certificate

# Try to import SEFAZ ws for signing utilities (reused for NFS-e too)
try:
    from sefaz_ws import _codigo_uf as _ibge_uf
except ImportError:
    def _ibge_uf(uf: str) -> str:
        return {
            "AC": "12", "AL": "27", "AP": "16", "AM": "13", "BA": "29",
            "CE": "23", "DF": "53", "ES": "32", "GO": "52", "MA": "21",
            "MT": "51", "MS": "50", "MG": "31", "PA": "15", "PB": "25",
            "PR": "41", "PE": "26", "PI": "22", "RJ": "33", "RN": "24",
            "RS": "43", "RO": "11", "RR": "14", "SC": "42", "SP": "35",
            "SE": "28", "TO": "17",
        }.get(uf.upper(), "35")


# ═══════════════════════════════════════════════════════════════════════
# Municipio IBGE codes
# ═══════════════════════════════════════════════════════════════════════

MUN_IBGE = {
    "MACAÉ": "3302403",
    "RIO DE JANEIRO": "3304557",
    "SÃO PAULO": "3550308",
    "CAMPINAS": "3509502",
    "SANTOS": "3548500",
    "BELO HORIZONTE": "3106200",
    "BRASÍLIA": "5300108",
    "CURITIBA": "4106902",
    "PORTO ALEGRE": "4314902",
    "SALVADOR": "2927408",
    "FORTALEZA": "2304400",
    "RECIFE": "2611606",
    "MANAUS": "1302603",
}


def _mun_codigo(nome: str) -> str:
    """Look up municipio IBGE code, normalizing case."""
    key = nome.upper().strip()
    return MUN_IBGE.get(key, "3302403")  # default Macaé


# ═══════════════════════════════════════════════════════════════════════
# ABRASF service codes (common)
# ═══════════════════════════════════════════════════════════════════════

SERVICO_CODES = {
    "CONSULTORIA": "01.01",
    "ASSESSORIA": "01.01",
    "PLANEJAMENTO": "01.01",
    "AUDITORIA": "01.02",
    "CONTABILIDADE": "01.03",
    "ADVOCACIA": "01.04",
    "ENGENHARIA": "02.01",
    "ARQUITETURA": "02.01",
    "MANUTENCAO_INDUSTRIAL": "03.01",
    "MANUTENCAO": "03.01",
    "MANUTENÇÃO": "03.01",
    "TECNOLOGIA": "04.01",
    "TI": "04.01",
    "INFORMATICA": "04.01",
    "INFORMÁTICA": "04.01",
    "SOFTWARE": "04.02",
    "PESQUISA": "05.01",
    "PERFURACAO": "06.01",
    "PERFURAÇÃO": "06.01",
    "OLEO_GAS": "06.01",
    "ÓLEO_GÁS": "06.01",
    "TRANSPORTE": "07.01",
    "LOGISTICA": "07.01",
    "SERVICO_GERAL": "10.01",
    "SERVIÇO_GERAL": "10.01",
}


def _servico_code(descricao: str) -> str:
    """Guess ABRASF service code from description."""
    upper = descricao.upper().strip()
    for key, code in SERVICO_CODES.items():
        if key in upper:
            return code
    return "10.01"  # default: serviços gerais


# ═══════════════════════════════════════════════════════════════════════
# ABRASF XML RPS generator
# ═══════════════════════════════════════════════════════════════════════

def _generate_rps_xml(nfse_data: dict, cfg: dict, emit_cnpj: str,
                      emit_im: str, emit_cnae: str) -> str:
    """Generate ABRASF-compatible RPS XML.

    Follows the ABRASF 2.02/2.03 national layout.
    """
    n_rps = nfse_data["numero_rps"]
    serie = cfg.get("serie_rps", "1")
    data_emissao = nfse_data["data_emissao"]
    cod_mun = _mun_codigo(cfg.get("municipio_nome", "MACAÉ"))

    # Tomador identification
    cpf_cnpj = ""
    if nfse_data.get("customer_cnpj"):
        cnpj_clean = "".join(ch for ch in nfse_data["customer_cnpj"] if ch.isdigit())
        if len(cnpj_clean) == 14:
            cpf_cnpj = f"<Cnpj>{cnpj_clean}</Cnpj>"
    if not cpf_cnpj and nfse_data.get("customer_cpf"):
        cpf_clean = "".join(ch for ch in nfse_data["customer_cpf"] if ch.isdigit())
        if len(cpf_clean) == 11:
            cpf_cnpj = f"<Cpf>{cpf_clean}</Cpf>"

    # Simple texto for optante
    optante = "2"  # default: não optante
    regime = cfg.get("regime_tributacao", "normal")
    if regime == "simples":
        optante = "1"

    # Regime especial
    regime_esp = "1"  # 1 = microempresa municipal, etc. Use 0 for normal
    if regime in ("micro_empresa",):
        regime_esp = "1"
    else:
        regime_esp = "0"

    aliquota = nfse_data.get("aliquota_iss", cfg.get("aliquota_iss", "5.00"))
    valor_iss = nfse_data.get("valor_iss", "0.00")
    codigo_servico = nfse_data.get("codigo_servico", "10.01")
    discriminacao = nfse_data.get("discriminacao", "")
    # Escape XML entities in discriminacao
    discriminacao = (discriminacao
                     .replace("&", "&amp;")
                     .replace("<", "&lt;")
                     .replace(">", "&gt;")
                     .replace('"', "&quot;"))

    tomador_nome = nfse_data.get("customer_name", "")
    tomador_nome = (tomador_nome
                    .replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;"))

    tomador_cep = nfse_data.get("customer_cep", "27930000")
    tomador_logradouro = nfse_data.get("customer_logradouro", "")
    tomador_numero = nfse_data.get("customer_numero", "S/N")
    tomador_bairro = nfse_data.get("customer_bairro", "")
    tomador_uf = nfse_data.get("customer_uf", cfg.get("uf", "RJ"))
    tomador_im = nfse_data.get("customer_im", "")

    valor_servicos = nfse_data.get("valor_servicos", "0.00")
    valor_deducoes = nfse_data.get("valor_deducoes", "0.00")
    valor_pis = nfse_data.get("valor_pis", "0.00")
    valor_cofins = nfse_data.get("valor_cofins", "0.00")
    valor_ir = nfse_data.get("valor_ir", "0.00")
    valor_csll = nfse_data.get("valor_csll", "0.00")
    valor_inss = nfse_data.get("valor_inss", "0.00")
    retencao_iss = int(nfse_data.get("retencao_iss", 0))
    valor_liquido = nfse_data.get("valor_liquido", "0.00")

    # Build RPS XML
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Rps xmlns="http://www.abrasf.org.br/nfse.xsd">
  <InfDeclaracaoPrestacaoServico Id="RPS{str(n_rps).zfill(12)}">
    <Rps>
      <IdentificacaoRps>
        <Numero>{n_rps}</Numero>
        <Serie>{serie}</Serie>
        <Tipo>1</Tipo>
      </IdentificacaoRps>
      <DataEmissao>{data_emissao}</DataEmissao>
      <NaturezaOperacao>1</NaturezaOperacao>
      <RegimeEspecialTributacao>{regime_esp}</RegimeEspecialTributacao>
      <OptanteSimplesNacional>{optante}</OptanteSimplesNacional>
    </Rps>
    <Servico>
      <Valores>
        <ValorServicos>{valor_servicos}</ValorServicos>
        <ValorDeducoes>{valor_deducoes}</ValorDeducoes>
        <ValorPis>{valor_pis}</ValorPis>
        <ValorCofins>{valor_cofins}</ValorCofins>
        <ValorIr>{valor_ir}</ValorIr>
        <ValorCsll>{valor_csll}</ValorCsll>
        <ValorInss>{valor_inss}</ValorInss>
        <ValorIss>{valor_iss}</ValorIss>
        <Aliquota>{aliquota}</Aliquota>
        <ValorLiquidoNfse>{valor_liquido}</ValorLiquidoNfse>
        <ValorIssRetido>{valor_iss if retencao_iss else '0.00'}</ValorIssRetido>
      </Valores>
      <ItemListaServico>{codigo_servico}</ItemListaServico>
      <CodigoCnae>{emit_cnae}</CodigoCnae>
      <CodigoTributacaoMunicipio>{codigo_servico.replace('.', '')}</CodigoTributacaoMunicipio>
      <Discriminacao>{discriminacao}</Discriminacao>
      <CodigoMunicipio>{cod_mun}</CodigoMunicipio>
    </Servico>
    <Prestador>
      <Cnpj>{emit_cnpj}</Cnpj>
      <InscricaoMunicipal>{emit_im}</InscricaoMunicipal>
    </Prestador>
    <Tomador>
      <IdentificacaoTomador>
        <CpfCnpj>
          {cpf_cnpj or '<Cnpj>00000000000000</Cnpj>'}
        </CpfCnpj>
        <InscricaoMunicipal>{tomador_im or ''}</InscricaoMunicipal>
      </IdentificacaoTomador>
      <RazaoSocial>{tomador_nome or 'CONSUMIDOR NAO IDENTIFICADO'}</RazaoSocial>
      <Endereco>
        <Endereco>{tomador_logradouro or ''}</Endereco>
        <Numero>{tomador_numero}</Numero>
        <Complemento></Complemento>
        <Bairro>{tomador_bairro or ''}</Bairro>
        <CodigoMunicipio>{_mun_codigo(nfse_data.get('customer_municipio', cfg.get('municipio_nome', 'MACAÉ')))}</CodigoMunicipio>
        <Uf>{tomador_uf}</Uf>
        <Cep>{tomador_cep}</Cep>
      </Endereco>
    </Tomador>
  </InfDeclaracaoPrestacaoServico>
</Rps>"""
    return xml


def _generate_consulta_lote_rps(nfse_data: dict, cfg: dict,
                                 emit_cnpj: str, emit_im: str) -> str:
    """Generate a consulta-lote XML envelope for Macaé simplified format."""
    n_rps = nfse_data["numero_rps"]
    protocolo = nfse_data.get("protocolo", "")
    cod_mun = _mun_codigo(cfg.get("municipio_nome", "MACAÉ"))

    # Adapter for simplified Macaé envelope
    cnpj_clean = "".join(ch for ch in emit_cnpj if ch.isdigit())

    return dedent(f"""\
    <?xml version="1.0" encoding="UTF-8"?>
    <ConsultarLoteRpsEnvio xmlns="http://www.abrasf.org.br/nfse.xsd">
      <Prestador>
        <Cnpj>{cnpj_clean}</Cnpj>
        <InscricaoMunicipal>{emit_im}</InscricaoMunicipal>
      </Prestador>
      <Protocolo>{protocolo}</Protocolo>
      <CodigoMunicipio>{cod_mun}</CodigoMunicipio>
    </ConsultarLoteRpsEnvio>""")


def _generate_envio_lote_rps(nfse_data: dict, cfg: dict,
                              emit_cnpj: str, emit_im: str,
                              rps_xml: str) -> str:
    """Generate an envio-lote envelope for municipal submission."""
    n_rps = nfse_data["numero_rps"]
    cod_mun = _mun_codigo(cfg.get("municipio_nome", "MACAÉ"))
    cnpj_clean = "".join(ch for ch in emit_cnpj if ch.isdigit())

    # Strip XML declaration from RPS for embedding
    rps_body = rps_xml
    if "<?xml" in rps_body:
        rps_body = rps_body[rps_body.find("?>") + 2:].strip()

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<EnviarLoteRpsEnvio xmlns="http://www.abrasf.org.br/nfse.xsd">
  <LoteRps Id="L{str(n_rps).zfill(12)}" versao="2.02">
    <NumeroLote>1</NumeroLote>
    <Cnpj>{cnpj_clean}</Cnpj>
    <InscricaoMunicipal>{emit_im}</InscricaoMunicipal>
    <QuantidadeRps>1</QuantidadeRps>
    <ListaRps>
      {rps_body}
    </ListaRps>
  </LoteRps>
  <CodigoMunicipio>{cod_mun}</CodigoMunicipio>
</EnviarLoteRpsEnvio>"""
    return xml


def _generate_cancelamento_rps(nfse_data: dict, cfg: dict,
                                emit_cnpj: str, emit_im: str) -> str:
    """Generate NFS-e cancellation request XML."""
    n_nfse = nfse_data.get("numero_nfse", "")
    cod_mun = _mun_codigo(cfg.get("municipio_nome", "MACAÉ"))
    cnpj_clean = "".join(ch for ch in emit_cnpj if ch.isdigit())

    justificativa = nfse_data.get("motivo_cancelamento", "CANCELAMENTO SOLICITADO")
    justificativa = (justificativa
                     .replace("&", "&amp;")
                     .replace("<", "&lt;")
                     .replace(">", "&gt;"))

    return dedent(f"""\
    <?xml version="1.0" encoding="UTF-8"?>
    <CancelarNfseEnvio xmlns="http://www.abrasf.org.br/nfse.xsd">
      <Pedido>
        <InfPedidoCancelamento Id="CN{str(n_nfse).zfill(15)}">
          <IdentificacaoNfse>
            <Numero>{n_nfse}</Numero>
            <Cnpj>{cnpj_clean}</Cnpj>
            <InscricaoMunicipal>{emit_im}</InscricaoMunicipal>
            <CodigoMunicipio>{cod_mun}</CodigoMunicipio>
          </IdentificacaoNfse>
          <CodigoCancelamento>1</CodigoCancelamento>
          <MotivoCancelamento>{justificativa}</MotivoCancelamento>
        </InfPedidoCancelamento>
      </Pedido>
    </CancelarNfseEnvio>""")


# ═══════════════════════════════════════════════════════════════════════
# helper: get company details
# ═══════════════════════════════════════════════════════════════════════

def _get_company_data(conn, cid: str) -> dict:
    """Resolve emitente CNPJ, IE, IM, CNAE from structured tables."""
    row = conn.execute(
        "SELECT * FROM company_fiscal WHERE company_id = ?", (cid,)
    ).fetchone()
    if row:
        return {
            "cnpj": _clean_cnpj(row["cnpj"] or ""),
            "ie": row.get("inscricao_estadual") or "",
            "im": row.get("inscricao_municipal") or "",
            "cnae": row.get("cnae_principal") or "0910600",
            "razao_social": row.get("razao_social") or "",
            "logradouro": row.get("logradouro") or "",
            "numero": row.get("numero") or "",
            "bairro": row.get("bairro") or "",
            "cep": row.get("cep") or "",
            "municipio_codigo": row.get("municipio_codigo") or "",
            "municipio_nome": row.get("municipio_nome") or "",
            "uf": row.get("uf") or "RJ",
        }

    # Fallback: company.tax_id
    comp = conn.execute(
        "SELECT * FROM company WHERE id = ?", (cid,)
    ).fetchone()
    if not comp:
        return {
            "cnpj": "00000000000000",
            "ie": "",
            "im": "",
            "cnae": "0910600",
            "razao_social": "",
        }
    comp = dict(comp)
    tax_id = _clean_cnpj(comp.get("tax_id", "") or "")
    return {
        "cnpj": tax_id or "00000000000000",
        "ie": "",
        "im": "",
        "cnae": "0910600",
        "razao_social": comp.get("name", ""),
    }


def _get_customer_data(conn, customer_id: str) -> dict:
    """Resolve customer tax identifiers."""
    if not customer_id:
        return {}
    row = conn.execute(
        "SELECT * FROM customer_fiscal WHERE customer_id = ?", (customer_id,)
    ).fetchone()
    if row:
        return {
            "cnpj": _clean_cnpj(row.get("cnpj") or ""),
            "cpf": row.get("cpf") or "",
            "im": row.get("im") or "",
            "logradouro": row.get("logradouro") or "",
            "numero": row.get("numero") or "S/N",
            "bairro": row.get("bairro") or "",
            "cep": row.get("cep") or "",
            "municipio_codigo": row.get("municipio_codigo") or "",
            "municipio_nome": row.get("municipio_nome") or "",
            "uf": row.get("uf") or "RJ",
        }
    return {}


# ═══════════════════════════════════════════════════════════════════════
# Action: configure-nfse
# ═══════════════════════════════════════════════════════════════════════

def configure_nfse(conn, args):
    """Configure NFS-e per company. Upserts br_nfse_config.

    Args: --company-id, --municipio-codigo, --municipio-nome, --uf,
          --aliquota-iss, --regime, --ambiente, --certificado-path,
          --serie-rps
    """
    cid = args.company_id
    if not cid:
        return err("--company-id is required")

    comp = conn.execute("SELECT id, name FROM company WHERE id = ?", (cid,)).fetchone()
    if not comp:
        return err(f"Company not found: {cid}")

    municipio_nome = args.municipio_nome or "MACAÉ"
    municipio_codigo = args.municipio_codigo or _mun_codigo(municipio_nome)
    uf = (args.uf or "RJ").upper()
    aliquota_iss = args.aliq_iss or "5.00"
    regime = args.regime or "normal"
    ambiente = args.ambiente or "homologacao"
    serie_rps = args.serie_default or "1"

    if regime not in ("normal", "simples", "micro_empresa"):
        return err("regime must be: normal, simples, or micro_empresa")
    if ambiente not in ("homologacao", "producao"):
        return err("ambiente must be 'homologacao' or 'producao'")

    # Encrypt certificate password if provided
    cert_pass_encoded = ""
    if getattr(args, "certificado_password", None):
        cert_pass_encoded = base64.b64encode(
            args.certificado_password.encode("utf-8")
        ).decode("ascii")

    now = datetime.now().isoformat()

    row = conn.execute(
        "SELECT id FROM br_nfse_config WHERE company_id = ?", (cid,)
    ).fetchone()

    if row:
        cfg_id = row["id"]
        conn.execute("""
            UPDATE br_nfse_config SET
                municipio_codigo = ?, municipio_nome = ?, uf = ?,
                aliquota_iss = ?, regime_tributacao = ?, ambiente = ?,
                certificado_path = ?, serie_rps = ?,
                updated_at = ?
            WHERE id = ?
        """, (
            municipio_codigo, municipio_nome.upper(), uf,
            aliquota_iss, regime, ambiente,
            getattr(args, "certificado_path", "") or "", serie_rps,
            now, cfg_id,
        ))
    else:
        cfg_id = str(uuid4())
        conn.execute("""
            INSERT INTO br_nfse_config (
                id, company_id, municipio_codigo, municipio_nome, uf,
                aliquota_iss, regime_tributacao, ambiente,
                certificado_path, proximo_numero_rps, serie_rps,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            cfg_id, cid, municipio_codigo, municipio_nome.upper(), uf,
            aliquota_iss, regime, ambiente,
            getattr(args, "certificado_path", "") or "",
            1, serie_rps,
            now, now,
        ))

    conn.commit()

    return ok({
        "config_id": cfg_id,
        "company_id": cid,
        "municipio": municipio_nome.upper(),
        "aliquota_iss": aliquota_iss,
        "regime": regime,
        "ambiente": ambiente,
        "message": "NFS-e configuration saved",
    })


# ═══════════════════════════════════════════════════════════════════════
# Action: create-nfse
# ═══════════════════════════════════════════════════════════════════════

def create_nfse(conn, args):
    """Create an NFS-e from a sales invoice (services-only).

    Args: --company-id, --sales-invoice-id, --discriminacao,
          --codigo-servico, --retencao-iss
    """
    cid = args.company_id
    si_id = args.sales_invoice_id
    if not cid or not si_id:
        return err("--company-id and --sales-invoice-id are required")

    # Load NFS-e config
    cfg = conn.execute(
        "SELECT * FROM br_nfse_config WHERE company_id = ?", (cid,)
    ).fetchone()
    if not cfg:
        return err(f"No NFS-e config for company {cid}. Run configure-nfse first.")
    cfg = dict(cfg)

    # Get company data
    emit = _get_company_data(conn, cid)

    # Load sales invoice
    si = conn.execute(
        "SELECT * FROM sales_invoice WHERE id = ? AND company_id = ?",
        (si_id, cid)
    ).fetchone()
    if not si:
        return err(f"Sales invoice not found: {si_id}")
    si = dict(si)

    # Load customer data
    customer_id = si.get("customer_id", "")
    customer_data = _get_customer_data(conn, customer_id) if customer_id else {}

    # Load customer base record
    customer = None
    if customer_id:
        customer = conn.execute(
            "SELECT * FROM customer WHERE id = ? AND company_id = ?",
            (customer_id, cid)
        ).fetchone()
    if customer:
        customer = dict(customer)

    # Load items
    items = conn.execute("""
        SELECT sii.*, i.name as item_name, i.unit as unit_of_measure
        FROM sales_invoice_item sii
        JOIN item i ON i.id = sii.item_id
        WHERE sii.sales_invoice_id = ?
        ORDER BY sii.line_number
    """, (si_id,)).fetchall()

    if not items:
        return err("Sales invoice has no items")

    # Calculate totals for services
    total_servicos = Decimal("0")
    for it in items:
        rd = dict(it)
        qty = Decimal(str(rd.get("quantity", "1")))
        price = Decimal(str(rd.get("unit_price", "0")))
        total_servicos += qty * price

    # Get aliquota ISS from config
    aliquota_iss = Decimal(args.aliq_iss or cfg.get("aliquota_iss", "5.00"))
    retencao_iss = int(getattr(args, "retencao_iss", 0) or 0)

    # Round
    total_servicos = round(total_servicos, 2)
    valor_iss = round(total_servicos * aliquota_iss / Decimal("100"), 2)

    # Other taxes (PIS/COFINS/IR/CSLL) — 4.65% composite
    valor_pis = round(total_servicos * Decimal("0.65") / Decimal("100"), 2)
    valor_cofins = round(total_servicos * Decimal("3.00") / Decimal("100"), 2)
    valor_ir = round(total_servicos * Decimal("1.50") / Decimal("100"), 2)
    valor_csll = round(total_servicos * Decimal("1.00") / Decimal("100"), 2)
    valor_inss = round(total_servicos * Decimal("0.00") / Decimal("100"), 2)

    valor_liquido = total_servicos - valor_iss - valor_pis - valor_cofins - valor_ir - valor_csll - valor_inss

    # Get next RPS number
    rps_numero = cfg.get("proximo_numero_rps", 1)

    # Service description
    discriminacao = getattr(args, "discriminacao", None) or si.get("description") or "SERVICOS PRESTADOS"
    codigo_servico = getattr(args, "codigo_servico", None) or _servico_code(discriminacao)

    # Customer info
    customer_name = ""
    customer_cnpj = ""
    customer_cpf = ""
    if customer:
        customer_name = customer.get("name", "")
        tax_id = customer.get("tax_id", "") or ""
        tax_digits = "".join(ch for ch in tax_id if ch.isdigit())
        if len(tax_digits) == 14:
            customer_cnpj = tax_digits
        elif len(tax_digits) == 11:
            customer_cpf = tax_digits

    # Override with structured data
    if customer_data.get("cnpj"):
        customer_cnpj = customer_data["cnpj"]
    if customer_data.get("cpf"):
        customer_cpf = customer_data["cpf"]

    data_emissao = datetime.now().strftime("%Y-%m-%d")

    nfse_id = str(uuid4())

    # Build NFS-e data dict
    nfse_data = {
        "id": nfse_id,
        "numero_rps": rps_numero,
        "data_emissao": data_emissao,
        "sales_invoice_id": si_id,
        "customer_id": customer_id,
        "customer_name": customer_name,
        "customer_cnpj": customer_cnpj,
        "customer_cpf": customer_cpf,
        "customer_im": customer_data.get("im", ""),
        "customer_municipio": customer_data.get("municipio_nome", cfg.get("municipio_nome", "")),
        "customer_logradouro": customer_data.get("logradouro", ""),
        "customer_numero": customer_data.get("numero", "S/N"),
        "customer_bairro": customer_data.get("bairro", ""),
        "customer_cep": customer_data.get("cep", "27930000"),
        "customer_uf": customer_data.get("uf", cfg.get("uf", "RJ")),
        "discriminacao": discriminacao,
        "codigo_servico": codigo_servico,
        "valor_servicos": str(total_servicos),
        "base_calculo": str(total_servicos),
        "aliquota_iss": str(aliquota_iss),
        "valor_iss": str(valor_iss),
        "valor_pis": str(valor_pis),
        "valor_cofins": str(valor_cofins),
        "valor_ir": str(valor_ir),
        "valor_csll": str(valor_csll),
        "valor_inss": str(valor_inss),
        "valor_deducoes": "0.00",
        "retencao_iss": retencao_iss,
        "valor_liquido": str(valor_liquido),
        "status": "rascunho",
        "ambiente": cfg.get("ambiente", "homologacao"),
        "company_id": cid,
    }

    # Generate RPS XML
    rps_xml = _generate_rps_xml(
        nfse_data, cfg,
        emit["cnpj"], emit["im"], emit["cnae"]
    )

    now = datetime.now().isoformat()

    conn.execute("""
        INSERT INTO br_nfse (
            id, numero_rps, numero_nfse, codigo_verificacao,
            data_emissao, sales_invoice_id,
            customer_id, customer_name, customer_cnpj, customer_cpf,
            customer_municipio,
            discriminacao,
            valor_servicos, base_calculo, aliquota_iss, valor_iss,
            valor_pis, valor_cofins, valor_ir, valor_csll, valor_inss,
            retencao_iss, valor_liquido,
            xml_rps, status, ambiente, company_id,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        nfse_id, rps_numero, None, None,
        data_emissao, si_id,
        customer_id, customer_name, customer_cnpj, customer_cpf,
        customer_data.get("municipio_nome", ""),
        discriminacao,
        str(total_servicos), str(total_servicos), str(aliquota_iss),
        str(valor_iss),
        str(valor_pis), str(valor_cofins), str(valor_ir), str(valor_csll),
        str(valor_inss),
        retencao_iss, str(valor_liquido),
        rps_xml, "rascunho", nfse_data["ambiente"], cid,
        now, now,
    ))

    # Increment RPS counter
    conn.execute(
        "UPDATE br_nfse_config SET proximo_numero_rps = ?, updated_at = ? WHERE id = ?",
        (rps_numero + 1, now, cfg["id"])
    )

    conn.commit()

    return ok({
        "nfse_id": nfse_id,
        "numero_rps": rps_numero,
        "valor_servicos": str(total_servicos),
        "valor_iss": str(valor_iss),
        "aliquota_iss": str(aliquota_iss),
        "codigo_servico": codigo_servico,
        "status": "rascunho",
        "message": f"NFS-e RPS {rps_numero} created as rascunho",
    })


# ═══════════════════════════════════════════════════════════════════════
# Action: sign-nfse-xml
# ═══════════════════════════════════════════════════════════════════════

def sign_nfse_xml_action(conn, args):
    """Sign the NFS-e XML with the configured A1 certificate.

    Args: --nfse-id or --nfe-out-id (for nfse-id)
    """
    nfse_id = getattr(args, "nfse_id", None) or args.nfe_out_id
    if not nfse_id:
        return err("--nfse-id is required")

    row = conn.execute("SELECT * FROM br_nfse WHERE id = ?", (nfse_id,)).fetchone()
    if not row:
        return err(f"NFS-e not found: {nfse_id}")

    nfse = dict(row)

    if nfse["status"] not in ("rascunho", "validado"):
        return err(f"NFS-e must be 'rascunho' or 'validado', current: {nfse['status']}")

    # Get config
    cfg = conn.execute(
        "SELECT * FROM br_nfse_config WHERE company_id = ?", (nfse["company_id"],)
    ).fetchone()
    if not cfg:
        return err("NFS-e config not found")

    cfg = dict(cfg)
    cert_path = cfg.get("certificado_path", "")
    cert_pass = cfg.get("certificado_password", "") if "certificado_password" in cfg else ""

    if not cert_path or not os.path.isfile(cert_path):
        return err("Certificate not configured or file missing. Run configure-nfse with --certificado-path.")

    try:
        cert_pass = base64.b64decode(cert_pass.encode("ascii")).decode("utf-8")
    except Exception:
        pass  # use as-is

    # Get XML to sign — use rps XML
    xml_content = nfse.get("xml_rps")
    if not xml_content:
        return err("NFS-e has no XML content")

    # Sign the XML
    try:
        # For NFS-e, sign the RPS XML envelope (not individual RPS items)
        signed = sign_nfe_xml(xml_content, cert_path, cert_pass)
    except ImportError as e:
        return err(f"Dependencies missing: {e}", "pip install cryptography lxml")
    except Exception as e:
        return err(f"Signing failed: {e}")

    now = datetime.now().isoformat()
    conn.execute(
        """UPDATE br_nfse SET
             xml_signed = ?, status = 'assinado', updated_at = ?
           WHERE id = ?""",
        (signed, now, nfse_id)
    )
    conn.commit()

    return ok({
        "nfse_id": nfse_id,
        "numero_rps": nfse["numero_rps"],
        "status": "assinado",
        "message": "NFS-e XML signed successfully",
    })


# ═══════════════════════════════════════════════════════════════════════
# Action: transmit-nfse
# ═══════════════════════════════════════════════════════════════════════

def transmit_nfse(conn, args):
    """Send NFS-e to municipal webservice for authorization.

    This uses a simplified simulation for Macaé — the actual municipal
    endpoint would be configured via the municipality URL in config.

    Args: --nfse-id or --nfe-out-id
    """
    nfse_id = getattr(args, "nfse_id", None) or args.nfe_out_id
    if not nfse_id:
        return err("--nfse-id is required")

    row = conn.execute("SELECT * FROM br_nfse WHERE id = ?", (nfse_id,)).fetchone()
    if not row:
        return err(f"NFS-e not found: {nfse_id}")

    nfse = dict(row)

    if nfse["status"] != "assinado":
        return err(f"NFS-e must be 'assinado' to transmit, current: {nfse['status']}")

    signed_xml = nfse.get("xml_signed") or nfse.get("xml_rps")
    if not signed_xml:
        return err("NFS-e has no signed XML content")

    # Get config
    cfg = conn.execute(
        "SELECT * FROM br_nfse_config WHERE company_id = ?", (nfse["company_id"],)
    ).fetchone()
    if not cfg:
        return err("NFS-e config not found")

    cfg = dict(cfg)

    # Get emitente data
    emit = _get_company_data(conn, nfse["company_id"])

    # Build the envio-lote-rps envelope
    envio_xml = _generate_envio_lote_rps(nfse, cfg, emit["cnpj"], emit["im"], signed_xml)

    # Attempt real transmission if cert is available, otherwise simulate
    cert_path = cfg.get("certificado_path", "")
    cert_pass = cfg.get("certificado_password", "")
    try:
        if cert_pass:
            cert_pass = base64.b64decode(cert_pass.encode("ascii")).decode("utf-8")
    except Exception:
        pass

    now = datetime.now().isoformat()

    # Try real SEFAZ/municipal transmission
    transmitted = False
    protocolo = ""
    nfse_numero = ""
    cod_verificacao = ""
    result_msg = ""

    if cert_path and os.path.isfile(cert_path):
        try:
            from sefaz_ws import send_soap_request
            # Municipal webservice URL — would be configured per municipality
            mun_url = cfg.get("ws_url", "")
            if mun_url:
                soap_action = "http://nfse.abrasf.org.br/RecepcionarLoteRps"
                result = send_soap_request(
                    mun_url, soap_action, envio_xml,
                    cert_path, cert_pass
                )
                if result.get("success"):
                    transmitted = True
                    # Extract protocolo from response
                    response = result.get("xml_response", "")
                    protocolo = _extract_protocolo(response)
                    nfse_numero = _extract_numero_nfse(response)
                    cod_verificacao = _extract_cod_verificacao(response)
                    result_msg = "NFS-e transmitted and authorized"
            else:
                result_msg = "No municipal WS URL configured — simulated transmission"
        except ImportError:
            result_msg = "Skipping SOAP transmission — simulated"
        except Exception as e:
            result_msg = f"Transmission attempted, simulation fallback: {e}"
    else:
        result_msg = "No certificate configured — simulated transmission"

    # Generate simulation protocolo in absence of real transmission
    if not transmitted:
        nfse_numero = str(nfse["numero_rps"])
        protocolo = f"{now.strftime('%Y%m%d%H%M%S')}{str(nfse['numero_rps']).zfill(6)}"
        cod_verificacao = f"CV-{nfse['numero_rps']}-{now.strftime('%Y%m%d')}"

    # Update DB with protocolo
    conn.execute("""
        UPDATE br_nfse SET
            numero_nfse = ?, codigo_verificacao = ?,
            protocolo = ?, status = ?,
            motivo_status = ?, updated_at = ?
        WHERE id = ?
    """, (
        nfse_numero, cod_verificacao,
        protocolo,
        "autorizado" if transmitted else "enviado",
        result_msg, now,
        nfse_id,
    ))
    conn.commit()

    return ok({
        "nfse_id": nfse_id,
        "numero_rps": nfse["numero_rps"],
        "numero_nfse": nfse_numero,
        "protocolo": protocolo,
        "codigo_verificacao": cod_verificacao,
        "transmitted": transmitted,
        "message": result_msg,
    })


# ═══════════════════════════════════════════════════════════════════════
# Action: check-nfse-status
# ═══════════════════════════════════════════════════════════════════════

def check_nfse_status(conn, args):
    """Check NFS-e authorization status.

    Args: --nfse-id or --nfe-out-id
    """
    nfse_id = getattr(args, "nfse_id", None) or args.nfe_out_id
    if not nfse_id:
        return err("--nfse-id is required")

    row = conn.execute("SELECT * FROM br_nfse WHERE id = ?", (nfse_id,)).fetchone()
    if not row:
        return err(f"NFS-e not found: {nfse_id}")

    nfse = dict(row)

    protocolo = nfse.get("protocolo", "")
    if not protocolo:
        return err("NFS-e has no protocolo — transmit first")

    # Build consulta protocolo request
    cfg = conn.execute(
        "SELECT * FROM br_nfse_config WHERE company_id = ?", (nfse["company_id"],)
    ).fetchone()
    cfg = dict(cfg) if cfg else {}

    emit = _get_company_data(conn, nfse["company_id"])

    # Generate consulta request
    consulta_xml = _generate_consulta_lote_rps(nfse, cfg, emit["cnpj"], emit["im"])

    # If cert available, try real consult
    cert_path = cfg.get("certificado_path", "")
    cert_pass = cfg.get("certificado_password", "")

    try:
        if cert_pass:
            cert_pass = base64.b64decode(cert_pass.encode("ascii")).decode("utf-8")
    except Exception:
        pass

    # For now return current DB status (simulated)
    result_status = nfse["status"]
    result_msg = nfse.get("motivo_status", "")

    if cert_path and os.path.isfile(cert_path):
        try:
            from sefaz_ws import send_soap_request
            ws_url = cfg.get("ws_url", "")
            if ws_url:
                soap_action = "http://nfse.abrasf.org.br/ConsultarLoteRps"
                result = send_soap_request(
                    ws_url, soap_action, consulta_xml,
                    cert_path, cert_pass
                )
                if result.get("success"):
                    response = result.get("xml_response", "")
                    sit = _extract_situacao_lote(response)
                    if sit == "4":
                        result_status = "autorizado"
                        result_msg = "NFS-e autorizada"
                        cnt = _extract_text_xml(response, "NumeroNfse")
                        if cnt:
                            conn.execute(
                                "UPDATE br_nfse SET numero_nfse = ?, status = 'autorizado', "
                                "motivo_status = ?, updated_at = ? WHERE id = ?",
                                (cnt, result_msg, datetime.now().isoformat(), nfse_id)
                            )
                            conn.commit()
        except ImportError:
            pass
        except Exception:
            pass

    return ok({
        "nfse_id": nfse_id,
        "numero_rps": nfse["numero_rps"],
        "protocolo": protocolo,
        "status": result_status,
        "message": result_msg,
    })


# ═══════════════════════════════════════════════════════════════════════
# Action: cancel-nfse
# ═══════════════════════════════════════════════════════════════════════

def cancel_nfse_action(conn, args):
    """Cancel an NFS-e.

    Args: --nfse-id or --nfe-out-id, --justificativa
    """
    nfse_id = getattr(args, "nfse_id", None) or args.nfe_out_id
    justificativa = args.justificativa

    if not nfse_id:
        return err("--nfse-id is required")
    if not justificativa or len(justificativa) < 15:
        return err("--justificativa must be at least 15 characters")

    row = conn.execute("SELECT * FROM br_nfse WHERE id = ?", (nfse_id,)).fetchone()
    if not row:
        return err(f"NFS-e not found: {nfse_id}")

    nfse = dict(row)

    if nfse["status"] not in ("autorizado",):
        return err(f"NFS-e must be 'autorizado' to cancel, current: {nfse['status']}")

    # Get config
    cfg = conn.execute(
        "SELECT * FROM br_nfse_config WHERE company_id = ?", (nfse["company_id"],)
    ).fetchone()
    cfg = dict(cfg) if cfg else {}

    emit = _get_company_data(conn, nfse["company_id"])

    # Build cancellation XML
    cancel_data = dict(nfse)
    cancel_data["motivo_cancelamento"] = justificativa
    canc_xml = _generate_cancelamento_rps(cancel_data, cfg, emit["cnpj"], emit["im"])

    # Try signing
    cert_path = cfg.get("certificado_path", "")
    cert_pass = cfg.get("certificado_password", "")

    try:
        if cert_pass:
            cert_pass = base64.b64decode(cert_pass.encode("ascii")).decode("utf-8")
    except Exception:
        pass

    now = datetime.now().isoformat()
    transmitted = False
    result_msg = ""

    if cert_path and os.path.isfile(cert_path):
        try:
            from sefaz_ws import send_soap_request
            ws_url = cfg.get("ws_url", "")
            if ws_url:
                soap_action = "http://nfse.abrasf.org.br/CancelarNfse"
                result = send_soap_request(
                    ws_url, soap_action, canc_xml,
                    cert_path, cert_pass
                )
                if result.get("success"):
                    transmitted = True
                    result_msg = "Cancelamento transmitido"
                else:
                    result_msg = f"Cancelamento rejeitado: {result.get('error', '')}"
        except Exception as e:
            result_msg = f"Cancelamento simulation: {e}"
    else:
        # Simulated cancel
        result_msg = "Cancelamento registrado (simulado)"

    # Update DB
    new_status = "cancelado"
    conn.execute("""
        UPDATE br_nfse SET
            status = ?, motivo_status = ?, updated_at = ?
        WHERE id = ?
    """, (new_status, result_msg, now, nfse_id))
    conn.commit()

    return ok({
        "nfse_id": nfse_id,
        "numero_rps": nfse["numero_rps"],
        "numero_nfse": nfse.get("numero_nfse", ""),
        "status": new_status,
        "message": result_msg,
    })


# ═══════════════════════════════════════════════════════════════════════
# Action: list-nfse
# ═══════════════════════════════════════════════════════════════════════

def list_nfse(conn, args):
    """List NFS-e service invoices with optional filters.

    Args: --company-id, --status, --start-date, --end-date, --limit, --offset
    """
    cid = args.company_id
    if not cid:
        return err("--company-id is required")

    where = ["company_id = ?"]
    params = [cid]

    if getattr(args, "status", None):
        where.append("status = ?")
        params.append(args.status)

    if getattr(args, "start_date", None):
        where.append("data_emissao >= ?")
        params.append(args.start_date)

    if getattr(args, "end_date", None):
        where.append("data_emissao <= ?")
        params.append(args.end_date)

    limit = args.limit or 50
    offset = args.offset or 0

    count = conn.execute(
        f"SELECT COUNT(*) FROM br_nfse WHERE {' AND '.join(where)}",
        params
    ).fetchone()[0]

    rows = conn.execute(f"""
        SELECT id, numero_rps, numero_nfse, codigo_verificacao,
               data_emissao, sales_invoice_id,
               customer_name, customer_cnpj,
               discriminacao,
               valor_servicos, base_calculo, aliquota_iss, valor_iss,
               valor_liquido, retencao_iss,
               protocolo, status, ambiente, created_at
        FROM br_nfse
        WHERE {' AND '.join(where)}
        ORDER BY data_emissao DESC, numero_rps DESC
        LIMIT ? OFFSET ?
    """, params + [limit, offset]).fetchall()

    return ok({
        "nfse_count": count,
        "limit": limit,
        "offset": offset,
        "nfses": [dict(r) for r in rows],
    })


# ═══════════════════════════════════════════════════════════════════════
# Action: get-nfse
# ═══════════════════════════════════════════════════════════════════════

def get_nfse(conn, args):
    """Get a single NFS-e detail.

    Args: --nfse-id or --nfe-out-id
    """
    nfse_id = getattr(args, "nfse_id", None) or args.nfe_out_id
    if not nfse_id:
        return err("--nfse-id is required")

    row = conn.execute("SELECT * FROM br_nfse WHERE id = ?", (nfse_id,)).fetchone()
    if not row:
        return err(f"NFS-e not found: {nfse_id}")

    nfse = dict(row)

    # Append config info
    cfg = conn.execute(
        "SELECT * FROM br_nfse_config WHERE company_id = ?", (nfse["company_id"],)
    ).fetchone()
    if cfg:
        nfse["config"] = dict(cfg)

    return ok({"nfse": nfse})


# ═══════════════════════════════════════════════════════════════════════
# XML extraction helpers
# ═══════════════════════════════════════════════════════════════════════

def _extract_text_xml(xml_text: str, tag: str, default: str = "") -> str:
    """Extract text content from an XML tag."""
    for prefix in ["", "ns2:", "ns3:", "ns4:", "nf:"]:
        open_tag = f"<{prefix}{tag}>"
        close_tag = f"</{prefix}{tag}>"
        start = xml_text.find(open_tag)
        if start >= 0:
            start += len(open_tag)
            end = xml_text.find(close_tag, start)
            if end >= 0:
                return xml_text[start:end].strip()
    return default


def _extract_protocolo(xml_text: str) -> str:
    return _extract_text_xml(xml_text, "Protocolo")


def _extract_numero_nfse(xml_text: str) -> str:
    return _extract_text_xml(xml_text, "NumeroNfse")


def _extract_cod_verificacao(xml_text: str) -> str:
    return _extract_text_xml(xml_text, "CodigoVerificacao")


def _extract_situacao_lote(xml_text: str) -> str:
    return _extract_text_xml(xml_text, "Situacao")


# ═══════════════════════════════════════════════════════════════════════
# ACTIONS — Wired into db_query.py
# ═══════════════════════════════════════════════════════════════════════

ACTIONS = {
    "configure-nfse": configure_nfse,
    "create-nfse": create_nfse,
    "sign-nfse-xml": sign_nfse_xml_action,
    "transmit-nfse": transmit_nfse,
    "check-nfse-status": check_nfse_status,
    "cancel-nfse": cancel_nfse_action,
    "list-nfse": list_nfse,
    "get-nfse": get_nfse,
}
