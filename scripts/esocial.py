#!/usr/bin/env python3
"""ERPClaw Region BR -- eSocial (Sistema de Escrituracao Digital das Obrigacoes Fiscais,
Previdenciarias e Trabalhistas)
Brazilian unified labor, social security, and tax digital bookkeeping.
Replaces GFIP, RAIS, CAGED, SEFIP. XML events for eSocial webservice.
Actions (14): configure-esocial, get-esocial-config, generate-s1000/s1005/s1010/s1020,
generate-s2200/s2205/s2299/s2230, generate-s1200/s1299,
generate-esocial-events, list-esocial-exports
"""
import sys
import os
import json
from uuid import uuid4
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from xml.sax.saxutils import escape as xml_escape
sys.path.insert(0, os.path.expanduser("~/.openclaw/erpclaw/lib"))
from erpclaw_lib.response import ok, err

# ======================================================================
# XML Helpers
# ======================================================================

def _xml_tag(name, value=None, attrib=None, **children):
    """Build an XML element string."""
    attrs = ""
    if attrib:
        attrs = " " + " ".join('{}=\"{}\"'.format(k, xml_escape(str(v))) for k, v in attrib.items())
    if value is None and not children:
        return "<{}{}/>".format(name, attrs)
    inner = ""
    if value is not None:
        inner += xml_escape(str(value))
    for ck, cv in children.items():
        if cv is None:
            continue
        inner += _xml_tag(ck, cv)
    return "<{}{}>{}".format(name, attrs, inner) + "</{}>".format(name)

def _wrap_esocial(event_tag, ide_evento, ide_empregador, info_content):
    """Wrap event content into eSocial envelope XML."""
    tp_amb = xml_escape(str(ide_evento.get("tpAmb", "2")))
    proc_emi = xml_escape(str(ide_evento.get("procEmi", "1")))
    ver_proc = xml_escape(ide_evento.get("verProc", "erpclaw-region-br/1.7.0"))
    tp_insc = xml_escape(str(ide_empregador.get("tpInsc", "1")))
    nr_insc = xml_escape(str(ide_empregador.get("nrInsc", "")))
    xml = []
    xml.append('<?xml version="1.0" encoding="UTF-8"?>')
    xml.append('<eSocial xmlns="http://www.esocial.gov.br/schema/evt/{}/v02_05_00">'.format(event_tag))
    xml.append('  <{}>'.format(event_tag))
    xml.append('    <ideEvento>')
    xml.append('      <tpAmb>{}</tpAmb>'.format(tp_amb))
    xml.append('      <procEmi>{}</procEmi>'.format(proc_emi))
    xml.append('      <verProc>{}</verProc>'.format(ver_proc))
    xml.append('    </ideEvento>')
    xml.append('    <ideEmpregador>')
    xml.append('      <tpInsc>{}</tpInsc>'.format(tp_insc))
    xml.append('      <nrInsc>{}</nrInsc>'.format(nr_insc))
    xml.append('    </ideEmpregador>')
    xml.append(info_content)
    xml.append('  </{}>'.format(event_tag))
    xml.append('</eSocial>')
    return "\n".join(xml)

# ======================================================================
# Data Helpers
# ======================================================================

def _only_digits(text):
    """Strip non-digit characters."""
    if not text:
        return ""
    return "".join(ch for ch in str(text) if ch.isdigit())

def _format_cpf(text):
    """Format CPF as exactly 11 digits, zero-padded."""
    return _only_digits(text).zfill(11)[:11]

def _format_date(d):
    """Format date as YYYY-MM-DD."""
    if not d:
        return ""
    s = str(d).strip()
    if len(s) >= 10:
        return s[:10]
    return s

def _text_decimal(value):
    """Format Decimal as string with two decimal places."""
    if value is None:
        return "0.00"
    if isinstance(value, str):
        try:
            value = Decimal(value)
        except Exception:
            return "0.00"
    return str(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

def _format_period(ano, mes):
    """Format period as yyyy-mm."""
    return "{}-{:02d}".format(ano, mes)

def _event_id(event_code, company_cnpj, periodo=None, employee_id=None):
    """Generate unique eSocial event identifier."""
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    cnpj_base = _only_digits(company_cnpj)[:8]
    parts = ["ID1" + event_code[2:], cnpj_base, ts]
    if periodo:
        parts.append(periodo.replace("-", ""))
    if employee_id:
        parts.append(employee_id[:8])
    return "".join(parts)[:40]

# ======================================================================
# Data Fetch
# ======================================================================

def _get_company_fiscal(conn, company_id):
    """Fetch company fiscal data."""
    return conn.execute("""
        SELECT cnpj, razao_social, nome_fantasia, cnae_principal, crt,
               inscricao_estadual, inscricao_municipal, uf,
               logradouro, numero, complemento, bairro, cep,
               municipio_codigo, municipio_nome, telefone, email
        FROM company_fiscal WHERE company_id = ?
    """, (company_id,)).fetchone()

def _get_esocial_config(conn, company_id):
    """Fetch eSocial config for a company."""
    return conn.execute("""
        SELECT id, nr_insc_empregador, tp_insc, ind_sit_pj, ind_dep_fgts,
               ide_efr, ide_adicional, ide_periodicidade,
               certificado_path, ambiente
        FROM esocial_config WHERE company_id = ?
    """, (company_id,)).fetchone()

def _get_employee_data(conn, employee_id):
    """Fetch comprehensive employee data."""
    return conn.execute("""
        SELECT e.id, e.full_name, e.first_name, e.last_name,
               e.date_of_birth, e.gender, e.date_of_joining, e.date_of_exit,
               e.employment_type, e.status, e.ssn as cpf,
               e.department_id, e.designation_id,
               d.name as department_name,
               des.name as designation_name
        FROM employee e
        LEFT JOIN department d ON d.id = e.department_id
        LEFT JOIN designation des ON des.id = e.designation_id
        WHERE e.id = ?
    """, (employee_id,)).fetchone()

def _get_salary_assignment(conn, employee_id):
    """Fetch current salary assignment."""
    return conn.execute("""
        SELECT sa.id, sa.base_amount, sa.effective_from, sa.effective_to,
               sa.currency, sa.salary_structure_id,
               ss.name as salary_structure_name, ss.payroll_frequency
        FROM salary_assignment sa
        JOIN salary_structure ss ON ss.id = sa.salary_structure_id
        WHERE sa.employee_id = ?
        ORDER BY sa.effective_from DESC LIMIT 1
    """, (employee_id,)).fetchone()

def _get_shift_assignment(conn, employee_id):
    """Fetch current shift assignment."""
    return conn.execute("""
        SELECT sa.id, sa.shift_type_id, sa.start_date, sa.end_date, sa.status,
               st.name as shift_name, st.start_time, st.end_time
        FROM shift_assignment sa
        JOIN shift_type st ON st.id = sa.shift_type_id
        WHERE sa.employee_id = ?
        ORDER BY sa.start_date DESC LIMIT 1
    """, (employee_id,)).fetchone()

def _get_salary_components(conn, company_id):
    """Fetch all salary rubrics."""
    rows = conn.execute("""
        SELECT id, name, component_type, is_tax_applicable,
               is_statutory, is_pre_tax, description
        FROM salary_component ORDER BY name
    """).fetchall()
    return rows

def _store_event(conn, event_code, evento_id, periodo, employee_id,
                 xml_evento, company_id, status="rascunho"):
    """Store an eSocial event in the database."""
    event_id = str(uuid4())
    try:
        conn.execute("""
            INSERT INTO esocial_event
                (id, event_code, evento_id, periodo, employee_id,
                 xml_evento, status, company_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """, (event_id, event_code, evento_id, periodo, employee_id,
              xml_evento, status, company_id))
        conn.commit()
    except Exception:
        pass
    return event_id

def _log_export(conn, tipo, ano, mes, periodo, company_id, total_registros,
                arquivo_path=None, status="gerado"):
    """Log export to sped_export_log."""
    log_id = str(uuid4())
    try:
        conn.execute("""
            INSERT INTO sped_export_log
                (id, tipo, ano, mes, periodo, arquivo_path, total_registros,
                 status, company_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (log_id, tipo, ano, mes, periodo, arquivo_path, total_registros,
              status, company_id))
        conn.commit()
    except Exception:
        pass
    return log_id

def _determine_classificacao_tributaria(fiscal):
    """Determine tax classification from CRT."""
    crt = fiscal[4] or "3"
    if crt == "1":
        return "01"  # Simples Nacional
    elif crt == "2":
        return "02"  # Simples com excesso
    else:
        return "03"  # Lucro Real/Presumido

def _map_rubric_code(name, component_type, idx):
    """Map salary component to eSocial rubric code."""
    name_lower = (name or "").lower()
    if "salario" in name_lower or "sal" in name_lower or component_type == "earning":
        return "0100{:03d}".format(idx + 1)[-6:]
    elif "inss" in name_lower:
        return "1000{:03d}".format(idx + 1)[-6:]
    elif "irrf" in name_lower or "ir " in name_lower:
        return "2000{:03d}".format(idx + 1)[-6:]
    elif "fgts" in name_lower:
        return "3000{:03d}".format(idx + 1)[-6:]
    elif "sindic" in name_lower or "sindical" in name_lower:
        return "4000{:03d}".format(idx + 1)[-6:]
    elif component_type == "deduction":
        return "9000{:03d}".format(idx + 1)[-6:]
    else:
        return "5000{:03d}".format(idx + 1)[-6:]

def _map_natureza_rubrica(component_type, is_tax):
    """Map to natureza da rubrica."""
    ct = (component_type or "").lower()
    if ct == "earning":
        return "1800" if is_tax else "1200"
    elif ct == "deduction":
        return "9200"
    else:
        return "9900"

def _map_tipo_rubrica(component_type):
    """Map to tipo de rubrica."""
    ct = (component_type or "").lower()
    if ct == "earning":
        return "1"
    elif ct == "deduction":
        return "2"
    else:
        return "3"

def _map_leave_code(leave_type_name):
    """Map leave type to eSocial afastamento code."""
    name = (leave_type_name or "").lower()
    if "mater" in name or "matern" in name:
        return "05"  # Licenca maternidade
    elif "pater" in name or "patern" in name:
        return "04"  # Licenca paternidade
    elif "acidente" in name or "acid" in name:
        return "10"  # Acidente de trabalho
    elif "doenc" in name or "doen" in name or "sick" in name:
        return "01"  # Doenca
    elif "ferias" in name or "vacation" in name:
        return "14"  # Ferias
    elif "suspens" in name:
        return "18"  # Suspensao
    elif "sindical" in name or "sindic" in name:
        return "15"  # Mandato sindical
    else:
        return "01"  # Default: doenca

def _map_dismissal_reason(status):
    """Map employee status to eSocial dismissal code."""
    s = (status or "").lower()
    if "resig" in s or "resign" in s:
        return "03"  # Resignation
    elif "term" in s:
        return "02"  # End of contract
    elif "just" in s:
        return "01"  # Just cause
    elif "death" in s or "faleci" in s:
        return "04"  # Death
    elif "retire" in s or "aposent" in s:
        return "05"  # Retirement
    else:
        return "02"  # Default: employer initiative

# ======================================================================
# Configuration Actions
# ======================================================================

def configure_esocial(conn, args):
    """Configure company-level eSocial settings."""
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatorio")
    company = conn.execute(
        "SELECT id, name FROM company WHERE id = ?", (company_id,)).fetchone()
    if not company:
        return err("Empresa {} nao encontrada".format(company_id))
    fiscal = _get_company_fiscal(conn, company_id)
    nr_insc = getattr(args, "cnpj", None) or (_only_digits(fiscal[0]) if fiscal else "")
    if not nr_insc:
        return err("CNPJ obrigatorio -- forneca --cnpj ou cadastre company_fiscal")
    tp_insc = getattr(args, "tp_insc", 1) or 1
    existing = conn.execute(
        "SELECT id FROM esocial_config WHERE company_id = ?", (company_id,)).fetchone()
    config_id = str(uuid4()) if not existing else existing[0]
    ind_sit_pj = getattr(args, "ind_sit_pj", 0) or 0
    ind_dep_fgts = getattr(args, "ind_dep_fgts", 0) or 0
    ide_efr = getattr(args, "ide_efr", 0) or 0
    ide_adicional = getattr(args, "ide_adicional", 0) or 0
    periodicidade = getattr(args, "periodicidade", "mensal") or "mensal"
    certificado_path = getattr(args, "certificado_path", None)
    ambiente = getattr(args, "ambiente", "producao-restrita") or "producao-restrita"
    if existing:
        conn.execute("""
            UPDATE esocial_config SET
                nr_insc_empregador = ?, tp_insc = ?, ind_sit_pj = ?,
                ind_dep_fgts = ?, ide_efr = ?, ide_adicional = ?,
                ide_periodicidade = ?, certificado_path = ?,
                ambiente = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (nr_insc, int(tp_insc), int(ind_sit_pj), int(ind_dep_fgts),
              int(ide_efr), int(ide_adicional), periodicidade,
              certificado_path, ambiente, config_id))
    else:
        conn.execute("""
            INSERT INTO esocial_config
                (id, company_id, nr_insc_empregador, tp_insc, ind_sit_pj,
                 ind_dep_fgts, ide_efr, ide_adicional, ide_periodicidade,
                 certificado_path, ambiente)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (config_id, company_id, nr_insc, int(tp_insc), int(ind_sit_pj),
              int(ind_dep_fgts), int(ide_efr), int(ide_adicional),
              periodicidade, certificado_path, ambiente))
    conn.commit()
    return ok({
        "action": "configure-esocial",
        "company_id": company_id,
        "nr_insc_empregador": nr_insc,
        "tp_insc": tp_insc,
        "status": "configurado",
    })

def get_esocial_config(conn, args):
    """Get company-level eSocial configuration."""
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatorio")
    cfg = _get_esocial_config(conn, company_id)
    if not cfg:
        return err("Configuracao eSocial nao encontrada -- use configure-esocial")
    return ok({
        "id": cfg[0],
        "nr_insc_empregador": cfg[1],
        "tp_insc": cfg[2],
        "ind_sit_pj": cfg[3],
        "ind_dep_fgts": cfg[4],
        "ide_efr": cfg[5],
        "ide_adicional": cfg[6],
        "ide_periodicidade": cfg[7],
        "certificado_path": cfg[8],
        "ambiente": cfg[9],
    })

# ======================================================================
# S-1000 -- Employer Information
# ======================================================================

def generate_s1000(conn, args):
    """Generate S-1000 -- Employer Information."""
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatorio")
    cfg = _get_esocial_config(conn, company_id)
    if not cfg:
        return err("Configuracao eSocial nao encontrada -- use configure-esocial")
    fiscal = _get_company_fiscal(conn, company_id)
    if not fiscal:
        return err("Dados fiscais nao cadastrados -- use add-company-fiscal")
    cnpj_base = _only_digits(fiscal[0])[:8]
    tp_insc = cfg[2]
    nr_insc = cfg[1] if cfg[1] else cnpj_base
    ind_sit_pj = cfg[3]
    evt_id = _event_id("S1000", nr_insc)
    ide_evento = {"tpAmb": "2", "procEmi": "1", "verProc": "erpclaw-region-br/1.7.0"}
    ide_empregador = {"tpInsc": str(tp_insc), "nrInsc": nr_insc}
    hoje = datetime.now().strftime("%Y-%m")
    info_lines = []
    info_lines.append("    <infoEmpregador>")
    info_lines.append("      <inclusao>")
    info_lines.append("        <idePeriodo>")
    info_lines.append("          <iniValid>{}-01</iniValid>".format(hoje))
    info_lines.append("        </idePeriodo>")
    info_lines.append("        <infoCadastro>")
    info_lines.append("          <classTrib>{}</classTrib>".format(
            _determine_classificacao_tributaria(fiscal)))
    info_lines.append("          <indCoop>0</indCoop>")
    info_lines.append("          <indConstr>0</indConstr>")
    info_lines.append("          <indDesFolha>0</indDesFolha>")
    info_lines.append("          <indSitPJ>{}</indSitPJ>".format(ind_sit_pj))
    info_lines.append("          <natJurid>2062</natJurid>")
    info_lines.append("        </infoCadastro>")
    info_lines.append("        <softwareHouse>")
    info_lines.append("          <cnpjSoftHouse>{}0001XX</cnpjSoftHouse>".format(cnpj_base))
    info_lines.append("          <nmRazao>ERPClaw Sistemas</nmRazao>")
    info_lines.append("          <nmCont>Administrador</nmCont>")
    info_lines.append("          <telefone>+55(22)0000-0000</telefone>")
    info_lines.append("          <email>suporte@erpclaw.com.br</email>")
    info_lines.append("        </softwareHouse>")
    info_lines.append("      </inclusao>")
    info_lines.append("    </infoEmpregador>")
    info_content = "\n".join(info_lines)
    xml_evento = _wrap_esocial("evtInfoEmpregador", ide_evento, ide_empregador, info_content)
    evento_id = _store_event(conn, "S-1000", evt_id, None, None, xml_evento, company_id)
    _log_export(conn, "esocial", datetime.now().year, datetime.now().month,
                datetime.now().strftime("%Y-%m"), company_id, 1)
    return ok({
        "evento": "S-1000",
        "evento_id": evento_id,
        "evt_id": evt_id,
        "empregador": fiscal[1] or fiscal[0],
        "cnpj_base": cnpj_base,
        "xml_preview": xml_evento[:800] + ("\n..." if len(xml_evento) > 800 else ""),
    })

# ======================================================================
# S-1005 -- Establishment Table
# ======================================================================

def generate_s1005(conn, args):
    """Generate S-1005 -- Establishment table (CNAE, RAT, FAP)."""
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatorio")
    fiscal = _get_company_fiscal(conn, company_id)
    if not fiscal:
        return err("Dados fiscais nao cadastrados")
    cfg = _get_esocial_config(conn, company_id)
    nr_insc = cfg[1] if cfg else _only_digits(fiscal[0])[:8]
    tp_insc = cfg[2] if cfg else 1
    cnae = fiscal[3] or "0910600"
    evt_id = _event_id("S1005", nr_insc)
    ide_evento = {"tpAmb": "2", "procEmi": "1", "verProc": "erpclaw-region-br/1.7.0"}
    ide_empregador = {"tpInsc": str(tp_insc), "nrInsc": nr_insc}
    cnae_code = _only_digits(cnae)[:7]
    aliq_rat = "3"
    fap = "1.0000"
    aliq_rat_ajust = _text_decimal(float(aliq_rat) * float(fap))
    hoje = datetime.now().strftime("%Y-%m")
    info_lines = []
    info_lines.append("    <infoEstab>")
    info_lines.append("      <inclusao>")
    info_lines.append("        <idePeriodo>")
    info_lines.append("          <iniValid>{}-01</iniValid>".format(hoje))
    info_lines.append("        </idePeriodo>")
    info_lines.append("        <infoEstab>")
    info_lines.append("          <cnaePrep>")
    info_lines.append("            <codCNAE>{}</codCNAE>".format(cnae_code))
    info_lines.append("          </cnaePrep>")
    info_lines.append("          <aliqGilrat>")
    info_lines.append("            <aliqRat>{}</aliqRat>".format(aliq_rat))
    info_lines.append("            <fap>{}</fap>".format(fap))
    info_lines.append("            <aliqRatAjust>{}</aliqRatAjust>".format(aliq_rat_ajust))
    info_lines.append("          </aliqGilrat>")
    info_lines.append("          <infoTrab>")
    info_lines.append("            <infoApr>")
    info_lines.append("              <nrProcJud></nrProcJud>")
    info_lines.append("            </infoApr>")
    info_lines.append("          </infoTrab>")
    info_lines.append("        </infoEstab>")
    info_lines.append("      </inclusao>")
    info_lines.append("    </infoEstab>")
    info_content = "\n".join(info_lines)
    xml_evento = _wrap_esocial("evtTabEstab", ide_evento, ide_empregador, info_content)
    evento_id = _store_event(conn, "S-1005", evt_id, None, None, xml_evento, company_id)
    return ok({
        "evento": "S-1005",
        "evento_id": evento_id,
        "evt_id": evt_id,
        "cnae": cnae_code,
        "aliq_rat": aliq_rat,
        "fap": fap,
        "xml_preview": xml_evento[:800] + ("\n..." if len(xml_evento) > 800 else ""),
    })

# ======================================================================
# S-1010 -- Rubric Table
# ======================================================================

def generate_s1010(conn, args):
    """Generate S-1010 -- Rubric table (payroll rubrics)."""
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatorio")
    fiscal = _get_company_fiscal(conn, company_id)
    if not fiscal:
        return err("Dados fiscais nao cadastrados")
    cfg = _get_esocial_config(conn, company_id)
    nr_insc = cfg[1] if cfg else _only_digits(fiscal[0])[:8]
    tp_insc = cfg[2] if cfg else 1
    evt_id = _event_id("S1010", nr_insc)
    ide_evento = {"tpAmb": "2", "procEmi": "1", "verProc": "erpclaw-region-br/1.7.0"}
    ide_empregador = {"tpInsc": str(tp_insc), "nrInsc": nr_insc}
    components = _get_salary_components(conn, company_id)
    hoje = datetime.now().strftime("%Y-%m")
    info_lines = []
    info_lines.append("    <infoRubrica>")
    for idx, comp in enumerate(components):
        comp_id, comp_name, comp_type, is_tax, is_stat, is_pre_tax, desc = comp
        cod_rubr = _map_rubric_code(comp_name, comp_type, idx)
        natura_rubr = _map_natureza_rubrica(comp_type, is_tax)
        tp_rubr = _map_tipo_rubrica(comp_type)
        info_lines.append("      <inclusao>")
        info_lines.append("        <ideRubrica>")
        info_lines.append("          <codRubr>{}</codRubr>".format(cod_rubr))
        info_lines.append("          <ideTabRubr>{}</ideTabRubr>".format(
            xml_escape((comp_name or "Verba")[:50])))
        info_lines.append("          <iniValid>{}-01</iniValid>".format(hoje))
        info_lines.append("        </ideRubrica>")
        info_lines.append("        <dadosRubrica>")
        info_lines.append("          <dscRubr>{}</dscRubr>".format(
            xml_escape((comp_name or "Verba")[:100])))
        info_lines.append("          <natRubr>{}</natRubr>".format(natura_rubr))
        info_lines.append("          <tpRubr>{}</tpRubr>".format(tp_rubr))
        info_lines.append("          <codIncCP>00</codIncCP>")
        info_lines.append("          <codIncIRRF>{}</codIncIRRF>".format("11" if is_tax else "00"))
        info_lines.append("          <codIncFGTS>{}</codIncFGTS>".format("11" if is_stat else "00"))
        info_lines.append("          <codIncSIND>00</codIncSIND>")
        info_lines.append("        </dadosRubrica>")
        info_lines.append("      </inclusao>")
    info_lines.append("    </infoRubrica>")
    info_content = "\n".join(info_lines)
    xml_evento = _wrap_esocial("evtTabRubrica", ide_evento, ide_empregador, info_content)
    evento_id = _store_event(conn, "S-1010", evt_id, None, None, xml_evento, company_id)
    return ok({
        "evento": "S-1010",
        "evento_id": evento_id,
        "evt_id": evt_id,
        "rubricas": len(components),
        "xml_preview": xml_evento[:800] + ("\n..." if len(xml_evento) > 800 else ""),
    })

# ======================================================================
# S-1020 -- Work Schedule Table
# ======================================================================

def generate_s1020(conn, args):
    """Generate S-1020 -- Work schedule table."""
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatorio")
    fiscal = _get_company_fiscal(conn, company_id)
    if not fiscal:
        return err("Dados fiscais nao cadastrados")
    cfg = _get_esocial_config(conn, company_id)
    nr_insc = cfg[1] if cfg else _only_digits(fiscal[0])[:8]
    tp_insc = cfg[2] if cfg else 1
    evt_id = _event_id("S1020", nr_insc)
    ide_evento = {"tpAmb": "2", "procEmi": "1", "verProc": "erpclaw-region-br/1.7.0"}
    ide_empregador = {"tpInsc": str(tp_insc), "nrInsc": nr_insc}
    shifts = conn.execute("""
        SELECT id, name, start_time, end_time
        FROM shift_type WHERE company_id = ? ORDER BY name
    """, (company_id,)).fetchall()
    hoje = datetime.now().strftime("%Y-%m")
    info_lines = []
    info_lines.append("    <infoHorContratual>")
    for idx, shift in enumerate(shifts):
        shift_id, shift_name, start_time, end_time = shift
        cod_hor = "{:03d}".format(idx + 1)
        daily_hours = "08:00"
        if start_time and end_time:
            try:
                st_parts = str(start_time).split(":")
                et_parts = str(end_time).split(":")
                st_mins = int(st_parts[0]) * 60 + int(st_parts[1]) if len(st_parts) >= 2 else 480
                et_mins = int(et_parts[0]) * 60 + int(et_parts[1]) if len(et_parts) >= 2 else 1020
                diff = et_mins - st_mins
                if diff < 0:
                    diff += 1440
                daily_hours = "{:02d}:{:02d}".format(diff // 60, diff % 60)
            except Exception:
                pass
        info_lines.append("      <inclusao>")
        info_lines.append("        <ideHorContratual>")
        info_lines.append("          <codHorContrat>{}</codHorContrat>".format(cod_hor))
        info_lines.append("          <iniValid>{}-01</iniValid>".format(hoje))
        info_lines.append("        </ideHorContratual>")
        info_lines.append("        <dadosHorContratual>")
        info_lines.append("          <hrEnt>{}</hrEnt>".format(start_time or "08:00"))
        info_lines.append("          <hrSaida>{}</hrSaida>".format(end_time or "18:00"))
        info_lines.append("          <durJornada>")
        info_lines.append("            <tpDurJorn>1</tpDurJorn>")
        info_lines.append("            <durJornada>{}</durJornada>".format(daily_hours))
        info_lines.append("          </durJornada>")
        info_lines.append("          <perHorFlexivel>N</perHorFlexivel>")
        info_lines.append("          <dscJorn>{}</dscJorn>".format(
            xml_escape((shift_name or "")[:100])))
        info_lines.append("        </dadosHorContratual>")
        info_lines.append("      </inclusao>")
    info_lines.append("    </infoHorContratual>")
    info_content = "\n".join(info_lines)
    xml_evento = _wrap_esocial("evtTabHorTur", ide_evento, ide_empregador, info_content)
    evento_id = _store_event(conn, "S-1020", evt_id, None, None, xml_evento, company_id)
    return ok({
        "evento": "S-1020",
        "evento_id": evento_id,
        "evt_id": evt_id,
        "jornadas": len(shifts),
        "xml_preview": xml_evento[:800] + ("\n..." if len(xml_evento) > 800 else ""),
    })

# ======================================================================
# S-2200 -- Worker Admission
# ======================================================================

def generate_s2200(conn, args):
    """Generate S-2200 -- Worker Admission."""
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatorio")
    employee_id = args.employee_id
    if not employee_id:
        return err("--employee-id obrigatorio")
    fiscal = _get_company_fiscal(conn, company_id)
    if not fiscal:
        return err("Dados fiscais nao cadastrados")
    cfg = _get_esocial_config(conn, company_id)
    nr_insc = cfg[1] if cfg else _only_digits(fiscal[0])[:8]
    tp_insc = cfg[2] if cfg else 1
    emp = _get_employee_data(conn, employee_id)
    if not emp:
        return err("Funcionario {} nao encontrado".format(employee_id))
    salary_data = _get_salary_assignment(conn, employee_id)
    cpf = _format_cpf(emp[10] or "00000000000")
    evt_id = _event_id("S2200", nr_insc)
    ide_evento = {"tpAmb": "2", "procEmi": "1", "verProc": "erpclaw-region-br/1.7.0"}
    ide_empregador = {"tpInsc": str(tp_insc), "nrInsc": nr_insc}
    dt_adm = _format_date(emp[6]) or datetime.now().strftime("%Y-%m-%d")
    nome = (emp[1] or "SEM NOME")[:70]
    sexo = "F" if emp[5] == "Female" else "M"
    salario = _text_decimal(salary_data[1] if salary_data else "2000.00")
    info_lines = []
    info_lines.append("    <trabalhador>")
    info_lines.append("      <cpfTrab>{}</cpfTrab>".format(cpf))
    info_lines.append("      <nmTrab>{}</nmTrab>".format(xml_escape(nome)))
    info_lines.append("      <sexo>{}</sexo>".format(sexo))
    info_lines.append("      <racaCor>9</racaCor>")
    info_lines.append("      <estCiv>0</estCiv>")
    info_lines.append("      <grauInstr>08</grauInstr>")
    info_lines.append("      <indPriEmpr>S</indPriEmpr>")
    info_lines.append("    </trabalhador>")
    info_lines.append("    <vinculo>")
    info_lines.append("      <matricula>{}</matricula>".format(employee_id[:30]))
    info_lines.append("      <tpRegTrab>1</tpRegTrab>")
    info_lines.append("      <tpRegPrev>1</tpRegPrev>")
    info_lines.append("      <cadIni>{}</cadIni>".format(dt_adm))
    info_lines.append("      <infoRegimeTrab>")
    info_lines.append("        <infoCeletista>")
    info_lines.append("          <dtAdm>{}</dtAdm>".format(dt_adm))
    info_lines.append("          <tpAdmissao>1</tpAdmissao>")
    info_lines.append("          <indAdmissao>1</indAdmissao>")
    info_lines.append("          <tpRegJor>1</tpRegJor>")
    info_lines.append("          <natAtividade>1</natAtividade>")
    info_lines.append("          <dtBase>{}-01</dtBase>".format(dt_adm[:4]))
    info_lines.append("          <cnpjSindCategProf>00000000000000</cnpjSindCategProf>")
    info_lines.append("        </infoCeletista>")
    info_lines.append("      </infoRegimeTrab>")
    info_lines.append("      <infoContrato>")
    info_lines.append("        <codCateg>101</codCateg>")
    info_lines.append("        <undSalFixo>7</undSalFixo>")
    info_lines.append("        <tpContr>1</tpContr>")
    info_lines.append("      </infoContrato>")
    info_lines.append("    </vinculo>")
    info_lines.append("    <infoTSVInicio>")
    info_lines.append("      <codCateg>101</codCateg>")
    info_lines.append("      <remuneracao>")
    info_lines.append("        <vrSalFx>{}</vrSalFx>".format(salario))
    info_lines.append("        <undSalFixo>7</undSalFixo>")
    info_lines.append("      </remuneracao>")
    info_lines.append("      <FGTS>")
    info_lines.append("        <dtOpcFGTS>{}</dtOpcFGTS>".format(dt_adm))
    info_lines.append("      </FGTS>")
    info_lines.append("    </infoTSVInicio>")
    info_content = "\n".join(info_lines)
    xml_evento = _wrap_esocial("evtAdmissao", ide_evento, ide_empregador, info_content)
    evento_id = _store_event(conn, "S-2200", evt_id, None, employee_id,
                             xml_evento, company_id)
    return ok({
        "evento": "S-2200",
        "evento_id": evento_id,
        "evt_id": evt_id,
        "funcionario": nome,
        "cpf": cpf,
        "dt_admissao": dt_adm,
        "salario": salario,
        "xml_preview": xml_evento[:800] + ("\n..." if len(xml_evento) > 800 else ""),
    })

# ======================================================================
# S-2205 -- Worker Data Change
# ======================================================================

def generate_s2205(conn, args):
    """Generate S-2205 -- Worker data change (salary, role, hours)."""
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatorio")
    employee_id = args.employee_id
    if not employee_id:
        return err("--employee-id obrigatorio")
    fiscal = _get_company_fiscal(conn, company_id)
    if not fiscal:
        return err("Dados fiscais nao cadastrados")
    cfg = _get_esocial_config(conn, company_id)
    nr_insc = cfg[1] if cfg else _only_digits(fiscal[0])[:8]
    tp_insc = cfg[2] if cfg else 1
    emp = _get_employee_data(conn, employee_id)
    if not emp:
        return err("Funcionario {} nao encontrado".format(employee_id))
    salary_data = _get_salary_assignment(conn, employee_id)
    cpf = _format_cpf(emp[10] or "00000000000")
    evt_id = _event_id("S2205", nr_insc)
    dt_alteracao = _format_date(datetime.now())
    ide_evento = {"tpAmb": "2", "procEmi": "1", "verProc": "erpclaw-region-br/1.7.0"}
    ide_empregador = {"tpInsc": str(tp_insc), "nrInsc": nr_insc}
    nome = (emp[1] or "SEM NOME")[:70]
    salario = _text_decimal(salary_data[1] if salary_data else "2000.00")
    info_lines = []
    info_lines.append("    <cpfTrab>{}</cpfTrab>".format(cpf))
    info_lines.append("    <dtAlteracao>{}</dtAlteracao>".format(dt_alteracao))
    info_lines.append("    <alteracao>")
    info_lines.append("      <dadosTrabalhador>")
    info_lines.append("        <nmTrab>{}</nmTrab>".format(xml_escape(nome)))
    info_lines.append("        <sexo>M</sexo>")
    info_lines.append("        <racaCor>9</racaCor>")
    info_lines.append("        <estCiv>0</estCiv>")
    info_lines.append("        <grauInstr>08</grauInstr>")
    info_lines.append("      </dadosTrabalhador>")
    info_lines.append("      <infoTSVAlteracao>")
    info_lines.append("        <remuneracao>")
    info_lines.append("          <vrSalFx>{}</vrSalFx>".format(salario))
    info_lines.append("          <undSalFixo>7</undSalFixo>")
    info_lines.append("        </remuneracao>")
    info_lines.append("      </infoTSVAlteracao>")
    info_lines.append("    </alteracao>")
    info_content = "\n".join(info_lines)
    xml_evento = _wrap_esocial("evtAltCadastral", ide_evento, ide_empregador, info_content)
    evento_id = _store_event(conn, "S-2205", evt_id, None, employee_id,
                             xml_evento, company_id)
    return ok({
        "evento": "S-2205",
        "evento_id": evento_id,
        "evt_id": evt_id,
        "funcionario": nome,
        "cpf": cpf,
        "dt_alteracao": dt_alteracao,
        "salario": salario,
        "xml_preview": xml_evento[:800] + ("\n..." if len(xml_evento) > 800 else ""),
    })

# ======================================================================
# S-2230 -- Temporary Leave
# ======================================================================

def generate_s2230(conn, args):
    """Generate S-2230 -- Temporary leave (sick, maternity, accident)."""
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatorio")
    employee_id = args.employee_id
    if not employee_id:
        return err("--employee-id obrigatorio")
    fiscal = _get_company_fiscal(conn, company_id)
    if not fiscal:
        return err("Dados fiscais nao cadastrados")
    cfg = _get_esocial_config(conn, company_id)
    nr_insc = cfg[1] if cfg else _only_digits(fiscal[0])[:8]
    tp_insc = cfg[2] if cfg else 1
    emp = _get_employee_data(conn, employee_id)
    if not emp:
        return err("Funcionario {} nao encontrado".format(employee_id))
    cpf = _format_cpf(emp[10] or "00000000000")
    evt_id = _event_id("S2230", nr_insc)
    ide_evento = {"tpAmb": "2", "procEmi": "1", "verProc": "erpclaw-region-br/1.7.0"}
    ide_empregador = {"tpInsc": str(tp_insc), "nrInsc": nr_insc}
    leaves = conn.execute("""
        SELECT la.id, la.from_date, la.to_date, la.total_days, la.reason, la.status,
               lt.name as leave_type_name, lt.is_paid_leave
        FROM leave_application la
        JOIN leave_type lt ON lt.id = la.leave_type_id
        WHERE la.employee_id = ?
          AND la.status IN ("Approved", "Open")
        ORDER BY la.from_date DESC
    """, (employee_id,)).fetchall()
    info_lines = []
    info_lines.append("    <cpfTrab>{}</cpfTrab>".format(cpf))
    if leaves:
        for leave in leaves:
            leave_id, dt_ini, dt_fim, total_days, reason, status, lt_name, is_paid = leave
            cod_mot_afast = _map_leave_code(lt_name or "")
            info_lines.append("    <infoAfastamento>")
            info_lines.append("      <iniValid>{}</iniValid>".format(_format_date(dt_ini)))
            info_lines.append("      <dadosAfastamento>")
            info_lines.append("        <dtIniAfast>{}</dtIniAfast>".format(_format_date(dt_ini)))
            info_lines.append("        <codMotAfast>{}</codMotAfast>".format(cod_mot_afast))
            if is_paid:
                info_lines.append("        <infoMandSind></infoMandSind>")
            else:
                info_lines.append("        <infoRetorno>")
                info_lines.append("          <dtFimAfast>{}</dtFimAfast>".format(_format_date(dt_fim)))
                info_lines.append("        </infoRetorno>")
            info_lines.append("      </dadosAfastamento>")
            info_lines.append("    </infoAfastamento>")
    else:
        hoje = _format_date(datetime.now())
        info_lines.append("    <infoAfastamento>")
        info_lines.append("      <iniValid>{}</iniValid>".format(hoje))
        info_lines.append("      <dadosAfastamento>")
        info_lines.append("        <dtIniAfast>{}</dtIniAfast>".format(hoje))
        info_lines.append("        <codMotAfast>01</codMotAfast>")
        info_lines.append("        <infoAtestado></infoAtestado>")
        info_lines.append("      </dadosAfastamento>")
        info_lines.append("    </infoAfastamento>")
    info_content = "\n".join(info_lines)
    xml_evento = _wrap_esocial("evtAfastTemp", ide_evento, ide_empregador, info_content)
    evento_id = _store_event(conn, "S-2230", evt_id, None, employee_id,
                             xml_evento, company_id)
    return ok({
        "evento": "S-2230",
        "evento_id": evento_id,
        "evt_id": evt_id,
        "funcionario": emp[1],
        "cpf": cpf,
        "afastamentos": len(leaves),
        "xml_preview": xml_evento[:800] + ("\n..." if len(xml_evento) > 800 else ""),
    })

# ======================================================================
# S-2299 -- Dismissal
# ======================================================================

def generate_s2299(conn, args):
    """Generate S-2299 -- Dismissal (employment termination)."""
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatorio")
    employee_id = args.employee_id
    if not employee_id:
        return err("--employee-id obrigatorio")
    fiscal = _get_company_fiscal(conn, company_id)
    if not fiscal:
        return err("Dados fiscais nao cadastrados")
    cfg = _get_esocial_config(conn, company_id)
    nr_insc = cfg[1] if cfg else _only_digits(fiscal[0])[:8]
    tp_insc = cfg[2] if cfg else 1
    emp = _get_employee_data(conn, employee_id)
    if not emp:
        return err("Funcionario {} nao encontrado".format(employee_id))
    cpf = _format_cpf(emp[10] or "00000000000")
    evt_id = _event_id("S2299", nr_insc)
    dt_deslig = _format_date(emp[7]) or _format_date(datetime.now())
    ide_evento = {"tpAmb": "2", "procEmi": "1", "verProc": "erpclaw-region-br/1.7.0"}
    ide_empregador = {"tpInsc": str(tp_insc), "nrInsc": nr_insc}
    nome = (emp[1] or "SEM NOME")[:70]
    causa_deslig = _map_dismissal_reason(emp[9])
    info_lines = []
    info_lines.append("    <cpfTrab>{}</cpfTrab>".format(cpf))
    info_lines.append("    <infoDeslig>")
    info_lines.append("      <mtvDeslig>{}</mtvDeslig>".format(causa_deslig))
    info_lines.append("      <dtDeslig>{}</dtDeslig>".format(dt_deslig))
    info_lines.append("      <indPagtoAPI>N</indPagtoAPI>")
    info_lines.append("      <indCumprAviso>2</indCumprAviso>")
    info_lines.append("      <verbasResc>")
    info_lines.append("        <dmDev>")
    info_lines.append("          <ideDmDev>{}</ideDmDev>".format(evt_id[:30]))
    info_lines.append("          <infoPerApur>")
    info_lines.append("            <ideEstabLot>")
    info_lines.append("              <tpInsc>{}</tpInsc>".format(tp_insc))
    info_lines.append("              <nrInsc>{}</nrInsc>".format(nr_insc))
    info_lines.append("              <codLotacao>*</codLotacao>")
    info_lines.append("            </ideEstabLot>")
    info_lines.append("          </infoPerApur>")
    info_lines.append("        </dmDev>")
    info_lines.append("      </verbasResc>")
    info_lines.append("    </infoDeslig>")
    info_content = "\n".join(info_lines)
    xml_evento = _wrap_esocial("evtDeslig", ide_evento, ide_empregador, info_content)
    evento_id = _store_event(conn, "S-2299", evt_id, None, employee_id,
                             xml_evento, company_id)
    return ok({
        "evento": "S-2299",
        "evento_id": evento_id,
        "evt_id": evt_id,
        "funcionario": nome,
        "cpf": cpf,
        "dt_desligamento": dt_deslig,
        "causa": causa_deslig,
        "xml_preview": xml_evento[:800] + ("\n..." if len(xml_evento) > 800 else ""),
    })

# ======================================================================
# S-1200 -- Monthly Payroll
# ======================================================================

def generate_s1200(conn, args):
    """Generate S-1200 -- Monthly payroll (remuneration per worker)."""
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatorio")
    ano = args.ano or datetime.now().year
    mes = args.mes or datetime.now().month
    periodo = _format_period(ano, mes)
    fiscal = _get_company_fiscal(conn, company_id)
    if not fiscal:
        return err("Dados fiscais nao cadastrados")
    cfg = _get_esocial_config(conn, company_id)
    nr_insc = cfg[1] if cfg else _only_digits(fiscal[0])[:8]
    tp_insc = cfg[2] if cfg else 1
    period_start = "{}-{:02d}-01".format(ano, mes)
    if mes == 12:
        period_end = "{}-01-01".format(ano + 1)
    else:
        period_end = "{}-{:02d}-01".format(ano, mes + 1)
    payroll_runs = conn.execute("""
        SELECT id, period_start, period_end, total_gross, total_deductions,
               total_net, employee_count, status
        FROM payroll_run
        WHERE company_id = ?
          AND period_start >= ? AND period_start < ?
          AND status NOT IN ("Draft", "Cancelled")
        ORDER BY period_start
    """, (company_id, period_start, period_end)).fetchall()
    if not payroll_runs:
        return err("Nenhum payroll encontrado para {}".format(periodo))
    ide_evento = {"tpAmb": "2", "procEmi": "1", "verProc": "erpclaw-region-br/1.7.0"}
    ide_empregador = {"tpInsc": str(tp_insc), "nrInsc": nr_insc}
    eventos_gerados = []
    total_trabalhadores = 0
    total_remuneracao = Decimal("0")
    for pr in payroll_runs:
        pr_id = pr[0]
        evt_id = _event_id("S1200", nr_insc, periodo)
        slips = conn.execute("""
            SELECT ss.id, ss.employee_id, ss.gross_pay, ss.total_deductions,
                   ss.net_pay, e.full_name, e.ssn as cpf
            FROM salary_slip ss
            JOIN employee e ON e.id = ss.employee_id
            WHERE ss.payroll_run_id = ?
            ORDER BY e.full_name
        """, (pr_id,)).fetchall()
        info_lines = []
        info_lines.append("    <infoPerApur>")
        info_lines.append("      <ideEmpregador>")
        info_lines.append("        <tpInsc>{}</tpInsc>".format(tp_insc))
        info_lines.append("        <nrInsc>{}</nrInsc>".format(nr_insc))
        info_lines.append("      </ideEmpregador>")
        info_lines.append("      <idePeriodo>")
        info_lines.append("        <perApur>{}</perApur>".format(periodo))
        info_lines.append("      </idePeriodo>")
        info_lines.append("    </infoPerApur>")
        for slip in slips:
            ss_id, emp_id, gross, ded, net, emp_name, cpf_raw = slip
            cpf = _format_cpf(cpf_raw or "00000000000")
            gross_dec = Decimal(str(gross or 0))
            total_trabalhadores += 1
            total_remuneracao += gross_dec
            dm_dev_id = "{}_{}".format(evt_id[:30], cpf[:11])
            details = conn.execute("""
                SELECT ssd.id, ssd.salary_component_id, ssd.component_type,
                       ssd.amount, sc.name as component_name
                FROM salary_slip_detail ssd
                JOIN salary_component sc ON sc.id = ssd.salary_component_id
                WHERE ssd.salary_slip_id = ?
                ORDER BY sc.name
            """, (ss_id,)).fetchall()
            info_lines.append("    <dmDev>")
            info_lines.append("      <ideDmDev>{}</ideDmDev>".format(dm_dev_id))
            info_lines.append("      <codCateg>101</codCateg>")
            info_lines.append("      <infoPerApur>")
            info_lines.append("        <ideEstabLot>")
            info_lines.append("          <tpInsc>{}</tpInsc>".format(tp_insc))
            info_lines.append("          <nrInsc>{}</nrInsc>".format(nr_insc))
            info_lines.append("          <codLotacao>*</codLotacao>")
            info_lines.append("        </ideEstabLot>")
            info_lines.append("      </infoPerApur>")
            info_lines.append("      <infoPerAnt>")
            info_lines.append("        <ideADC>N</ideADC>")
            info_lines.append("      </infoPerAnt>")
            for detail in details:
                det_id, comp_id, comp_type, amount, comp_name = detail
                cod_rubr = _map_rubric_code(comp_name or "Verba", comp_type or "earning", 0)
                vr_rubr = _text_decimal(amount or "0.00")
                info_lines.append("      <itensRemun>")
                info_lines.append("        <codRubr>{}</codRubr>".format(cod_rubr))
                info_lines.append("        <ideTabRubr>{}</ideTabRubr>".format(
                    xml_escape((comp_name or "Verba")[:50])))
                info_lines.append("        <vrRubr>{}</vrRubr>".format(vr_rubr))
                info_lines.append("        <indApurIR>1</indApurIR>")
                info_lines.append("      </itensRemun>")
            info_lines.append("      <infoBaseFGTS>")
            info_lines.append("        <baseFGTS>{}</baseFGTS>".format(_text_decimal(gross_dec)))
            info_lines.append("        <vrFGTS>{}</vrFGTS>".format(
                _text_decimal(gross_dec * Decimal("0.08"))))
            info_lines.append("      </infoBaseFGTS>")
            info_lines.append("    </dmDev>")
        info_content = "\n".join(info_lines)
        xml_evento = _wrap_esocial("evtRemun", ide_evento, ide_empregador, info_content)
        evento_id = _store_event(conn, "S-1200", evt_id, periodo, None,
                                 xml_evento, company_id)
        eventos_gerados.append({
            "evento_id": evento_id,
            "evt_id": evt_id,
            "trabalhadores": len(slips),
        })
    _log_export(conn, "esocial", ano, mes, periodo, company_id, total_trabalhadores)
    return ok({
        "evento": "S-1200",
        "periodo": periodo,
        "total_trabalhadores": total_trabalhadores,
        "total_remuneracao": _text_decimal(total_remuneracao),
        "eventos_gerados": len(eventos_gerados),
        "detalhes": eventos_gerados,
    })

# ======================================================================
# S-1299 -- Payroll Closure
# ======================================================================

def generate_s1299(conn, args):
    """Generate S-1299 -- Payroll closure (totals INSS/FGTS)."""
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatorio")
    ano = args.ano or datetime.now().year
    mes = args.mes or datetime.now().month
    periodo = _format_period(ano, mes)
    fiscal = _get_company_fiscal(conn, company_id)
    if not fiscal:
        return err("Dados fiscais nao cadastrados")
    cfg = _get_esocial_config(conn, company_id)
    nr_insc = cfg[1] if cfg else _only_digits(fiscal[0])[:8]
    tp_insc = cfg[2] if cfg else 1
    period_start = "{}-{:02d}-01".format(ano, mes)
    if mes == 12:
        period_end = "{}-01-01".format(ano + 1)
    else:
        period_end = "{}-{:02d}-01".format(ano, mes + 1)
    agg = conn.execute("""
        SELECT COUNT(DISTINCT ss.employee_id) as total_workers,
               COALESCE(SUM(CAST(ss.gross_pay AS REAL)), 0) as total_gross,
               COALESCE(SUM(CAST(ss.net_pay AS REAL)), 0) as total_net
        FROM salary_slip ss
        JOIN payroll_run pr ON pr.id = ss.payroll_run_id
        WHERE pr.company_id = ?
          AND pr.period_start >= ? AND pr.period_start < ?
          AND pr.status NOT IN ("Draft", "Cancelled")
    """, (company_id, period_start, period_end)).fetchone()
    total_workers = agg[0] or 0
    total_gross = Decimal(str(agg[1] or 0))
    total_net = Decimal(str(agg[2] or 0))
    total_inss = total_gross * Decimal("0.31")
    total_fgts = total_gross * Decimal("0.08")
    evt_id = _event_id("S1299", nr_insc, periodo)
    ide_evento = {"tpAmb": "2", "procEmi": "1", "verProc": "erpclaw-region-br/1.7.0"}
    ide_empregador = {"tpInsc": str(tp_insc), "nrInsc": nr_insc}
    info_lines = []
    info_lines.append("    <idePeriodo>")
    info_lines.append("      <perApur>{}</perApur>".format(periodo))
    info_lines.append("    </idePeriodo>")
    info_lines.append("    <fechInfoPerApur>")
    info_lines.append("      <evtRemun>S</evtRemun>")
    info_lines.append("      <evtComProd>N</evtComProd>")
    info_lines.append("      <evtContratAvNP>N</evtContratAvNP>")
    info_lines.append("      <evtInfoComplPer>N</evtInfoComplPer>")
    info_lines.append("      <evtPgtos>S</evtPgtos>")
    info_lines.append("      <indGuia>1</indGuia>")
    info_lines.append("    </fechInfoPerApur>")
    info_lines.append("    <infoFech>")
    info_lines.append("      <ideRespInf>")
    info_lines.append("        <nmResp>{}</nmResp>".format(
            xml_escape((fiscal[1] or fiscal[0])[:70])))
    info_lines.append("        <cpfResp>{}</cpfResp>".format(_format_cpf(nr_insc)))
    info_lines.append("        <telefone>{}</telefone>".format(fiscal[15] or ""))
    info_lines.append("        <email>{}</email>".format(fiscal[16] or ""))
    info_lines.append("      </ideRespInf>")
    info_lines.append("    </infoFech>")
    info_lines.append("    <ideTransmissor>")
    info_lines.append("      <tpInsc>{}</tpInsc>".format(tp_insc))
    info_lines.append("      <nrInscTransm>{}</nrInscTransm>".format(nr_insc))
    info_lines.append("      <infoCad>")
    info_lines.append("        <classTrib>03</classTrib>")
    info_lines.append("        <indCoop>0</indCoop>")
    info_lines.append("        <indConstr>0</indConstr>")
    info_lines.append("        <indDesFolha>0</indDesFolha>")
    info_lines.append("      </infoCad>")
    info_lines.append("    </ideTransmissor>")
    info_content = "\n".join(info_lines)
    xml_evento = _wrap_esocial("evtFechaEvPer", ide_evento, ide_empregador, info_content)
    evento_id = _store_event(conn, "S-1299", evt_id, periodo, None,
                             xml_evento, company_id)
    _log_export(conn, "esocial", ano, mes, periodo, company_id, 1)
    return ok({
        "evento": "S-1299",
        "evento_id": evento_id,
        "evt_id": evt_id,
        "periodo": periodo,
        "total_trabalhadores": total_workers,
        "total_remuneracao": _text_decimal(total_gross),
        "total_liquido": _text_decimal(total_net),
        "total_inss": _text_decimal(total_inss),
        "total_fgts": _text_decimal(total_fgts),
        "xml_preview": xml_evento[:800] + ("\n..." if len(xml_evento) > 800 else ""),
    })

# ======================================================================
# Generate All Periodic Events
# ======================================================================

def generate_periodic(conn, args):
    """Generate all periodic eSocial events for a month (S-1200 + S-1299)."""
    company_id = args.company_id
    if not company_id:
        return err("--company-id obrigatorio")
    ano = args.ano or datetime.now().year
    mes = args.mes or datetime.now().month
    results = {}
    s1200_result = generate_s1200(conn, args)
    if s1200_result.get("status") == "ok":
        results["S-1200"] = {
            "periodo": s1200_result["data"]["periodo"],
            "total_trabalhadores": s1200_result["data"]["total_trabalhadores"],
            "eventos": s1200_result["data"]["eventos_gerados"],
        }
    s1299_result = generate_s1299(conn, args)
    if s1299_result.get("status") == "ok":
        results["S-1299"] = {
            "periodo": s1299_result["data"]["periodo"],
            "total_trabalhadores": s1299_result["data"]["total_trabalhadores"],
            "total_inss": s1299_result["data"]["total_inss"],
            "total_fgts": s1299_result["data"]["total_fgts"],
        }
    periodo = _format_period(ano, mes)
    _log_export(conn, "esocial", ano, mes, periodo, company_id, len(results))
    return ok({
        "modulo": "esocial",
        "periodo": periodo,
        "eventos_gerados": results,
    })

# ======================================================================
# List eSocial Exports
# ======================================================================

def list_esocial_exports(conn, args):
    """List eSocial export history."""
    company_id = args.company_id
    limit = args.limit or 50
    offset = args.offset or 0
    query = """
        SELECT id, event_code, evento_id, periodo, employee_id, status,
               protocolo, data_processamento, mensagem, created_at
        FROM esocial_event WHERE 1=1
    """
    params = []
    if company_id:
        query += " AND company_id = ?"
        params.append(company_id)
    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    rows = conn.execute(query, params).fetchall()
    results = []
    for r in rows:
        results.append({
            "id": r[0],
            "event_code": r[1],
            "evento_id": r[2],
            "periodo": r[3],
            "employee_id": r[4],
            "status": r[5],
            "protocolo": r[6],
            "data_processamento": r[7],
            "mensagem": r[8],
            "created_at": r[9],
        })
    total = conn.execute(
        "SELECT COUNT(*) FROM esocial_event" + 
        (" WHERE company_id = ?" if company_id else ""),
        params[:1] if company_id else []
    ).fetchone()[0]
    return ok({
        "total": total,
        "limit": limit,
        "offset": offset,
        "exports": results,
    })

# ======================================================================
# Actions Registry
# ======================================================================

ACTIONS = {
    # Configuration
    "configure-esocial": configure_esocial,
    "get-esocial-config": get_esocial_config,
    # Employer/Payroll Configuration Events
    "generate-s1000": generate_s1000,
    "generate-s1005": generate_s1005,
    "generate-s1010": generate_s1010,
    "generate-s1020": generate_s1020,
    # Worker Events
    "generate-s2200": generate_s2200,
    "generate-s2205": generate_s2205,
    "generate-s2299": generate_s2299,
    "generate-s2230": generate_s2230,
    # Periodic Events
    "generate-s1200": generate_s1200,
    "generate-s1299": generate_s1299,
    "generate-esocial-events": generate_periodic,
    # Utility
    "list-esocial-exports": list_esocial_exports,
}

