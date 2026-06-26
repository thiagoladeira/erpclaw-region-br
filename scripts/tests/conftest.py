"""Test fixtures for erpclaw-region-br."""
import os
import sqlite3
import sys
import pytest
from uuid import uuid4

sys.path.insert(0, os.path.expanduser("~/.openclaw/erpclaw/lib"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def db():
    """Create in-memory test database with all BR tables."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")

    # Create minimal foundation tables needed
    _create_foundation_tables(conn)

    # Create all BR tables
    _create_br_tables_memory(conn)

    yield conn
    conn.close()


def _create_foundation_tables(conn):
    """Create minimal ERPClaw tables needed by BR module."""
    tables = [
        """CREATE TABLE IF NOT EXISTS company (
            id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE,
            abbr TEXT NOT NULL UNIQUE, default_currency TEXT DEFAULT 'USD',
            country TEXT DEFAULT 'United States', tax_id TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS customer (
            id TEXT PRIMARY KEY, name TEXT,
            customer_type TEXT DEFAULT 'company', default_currency TEXT,
            tax_id TEXT, email TEXT, status TEXT DEFAULT 'active',
            company_id TEXT REFERENCES company(id)
        )""",
        """CREATE TABLE IF NOT EXISTS supplier (
            id TEXT PRIMARY KEY, name TEXT, tax_id TEXT, company_id TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS item (
            id TEXT PRIMARY KEY, item_code TEXT, item_name TEXT,
            item_type TEXT DEFAULT 'stock', stock_uom TEXT, description TEXT,
            is_purchase_item INTEGER DEFAULT 1, is_sales_item INTEGER DEFAULT 1,
            is_stock_item INTEGER DEFAULT 1, standard_rate TEXT,
            status TEXT DEFAULT 'active'
        )""",
        """CREATE TABLE IF NOT EXISTS sales_invoice (
            id TEXT PRIMARY KEY, customer_id TEXT, posting_date TEXT,
            due_date TEXT, total_amount TEXT DEFAULT '0',
            tax_amount TEXT DEFAULT '0', grand_total TEXT DEFAULT '0',
            outstanding_amount TEXT DEFAULT '0', status TEXT DEFAULT 'draft',
            company_id TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS sales_invoice_item (
            id TEXT PRIMARY KEY, sales_invoice_id TEXT, item_id TEXT,
            quantity TEXT DEFAULT '0', rate TEXT DEFAULT '0',
            amount TEXT DEFAULT '0'
        )""",
        """CREATE TABLE IF NOT EXISTS purchase_invoice (
            id TEXT PRIMARY KEY, supplier_id TEXT, posting_date TEXT,
            total_amount TEXT DEFAULT '0', tax_amount TEXT DEFAULT '0',
            grand_total TEXT DEFAULT '0', status TEXT DEFAULT 'draft',
            company_id TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS gl_entry (
            id TEXT PRIMARY KEY, name TEXT, account_id TEXT, account TEXT,
            debit TEXT DEFAULT '0', credit TEXT DEFAULT '0',
            posting_date TEXT, voucher_type TEXT, voucher_no TEXT,
            party_id TEXT, party_name TEXT, party_type TEXT,
            against TEXT, cost_center TEXT, company_id TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS account (
            id TEXT PRIMARY KEY, account_number TEXT, account_name TEXT,
            account_type TEXT, is_group INTEGER DEFAULT 0,
            parent_account_id TEXT, parent_id TEXT,
            root_type TEXT, balance_direction TEXT, company_id TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS tax_template (
            id TEXT PRIMARY KEY, name TEXT, company_id TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS tax_category (
            id TEXT PRIMARY KEY, name TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS custom_field (
            id TEXT PRIMARY KEY, table_name TEXT, field_name TEXT,
            field_type TEXT, label TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS custom_field_value (
            table_name TEXT, doc_id TEXT, field_name TEXT, value TEXT,
            created_at TEXT, PRIMARY KEY(table_name, doc_id, field_name)
        )""",
        """CREATE TABLE IF NOT EXISTS employee (
            id TEXT PRIMARY KEY, employee_id TEXT, first_name TEXT,
            last_name TEXT, full_name TEXT, cpf TEXT, nis TEXT,
            employee_number TEXT, designation TEXT,
            date_of_joining TEXT, status TEXT DEFAULT 'active',
            company_id TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS salary_structure (
            id TEXT PRIMARY KEY, name TEXT, company_id TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS salary_assignment (
            id TEXT PRIMARY KEY, employee_id TEXT,
            salary_structure_id TEXT, base_salary TEXT DEFAULT '0',
            company_id TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS payroll_run (
            id TEXT PRIMARY KEY, period_start TEXT, period_end TEXT,
            status TEXT DEFAULT 'draft', company_id TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS salary_slip (
            id TEXT PRIMARY KEY, employee_id TEXT, payroll_run_id TEXT,
            gross_pay TEXT DEFAULT '0', net_pay TEXT DEFAULT '0',
            company_id TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS salary_slip_detail (
            id TEXT PRIMARY KEY, salary_slip_id TEXT, component_id TEXT,
            amount TEXT DEFAULT '0'
        )""",
        """CREATE TABLE IF NOT EXISTS salary_component (
            id TEXT PRIMARY KEY, name TEXT,
            component_type TEXT DEFAULT 'earning'
        )""",
        """CREATE TABLE IF NOT EXISTS stock_ledger_entry (
            id TEXT PRIMARY KEY, item_id TEXT, warehouse_id TEXT,
            qty_change TEXT DEFAULT '0', valuation_rate TEXT DEFAULT '0',
            posting_date TEXT, company_id TEXT
        )""",
    ]
    for sql in tables:
        try:
            conn.execute(sql)
        except Exception:
            pass


def _create_br_tables_memory(conn):
    """Create all 22 BR fiscal tables in the in-memory database."""
    # nfe_import
    conn.execute("""CREATE TABLE IF NOT EXISTS nfe_import (
        id TEXT PRIMARY KEY, chave_acesso TEXT UNIQUE NOT NULL,
        numero_nfe TEXT NOT NULL, serie TEXT DEFAULT '1', modelo TEXT DEFAULT '55',
        data_emissao TEXT NOT NULL, data_entrada TEXT,
        emitente_cnpj TEXT NOT NULL, emitente_nome TEXT NOT NULL, emitente_ie TEXT,
        natureza_operacao TEXT, cfop_principal TEXT,
        valor_total TEXT NOT NULL DEFAULT '0.00', valor_produtos TEXT NOT NULL DEFAULT '0.00',
        base_icms TEXT DEFAULT '0.00', valor_icms TEXT DEFAULT '0.00',
        base_icms_st TEXT DEFAULT '0.00', valor_icms_st TEXT DEFAULT '0.00',
        base_ipi TEXT DEFAULT '0.00', valor_ipi TEXT DEFAULT '0.00',
        valor_pis TEXT DEFAULT '0.00', valor_cofins TEXT DEFAULT '0.00',
        valor_frete TEXT DEFAULT '0.00', valor_seguro TEXT DEFAULT '0.00',
        valor_desconto TEXT DEFAULT '0.00', outras_despesas TEXT DEFAULT '0.00',
        xml_raw TEXT, supplier_id TEXT, purchase_invoice_id TEXT,
        stock_entry_id TEXT, gl_entries_posted INTEGER DEFAULT 0,
        status TEXT DEFAULT 'imported', error_message TEXT,
        company_id TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")

    # nfe_item
    conn.execute("""CREATE TABLE IF NOT EXISTS nfe_item (
        id TEXT PRIMARY KEY, nfe_import_id TEXT NOT NULL, numero_item INTEGER NOT NULL,
        codigo_produto TEXT, descricao TEXT NOT NULL, ncm TEXT, cfop TEXT,
        cst_icms TEXT, cst_ipi TEXT, cst_pis TEXT, cst_cofins TEXT,
        unidade TEXT DEFAULT 'UN', quantidade TEXT NOT NULL DEFAULT '1.0',
        valor_unitario TEXT NOT NULL DEFAULT '0.00', valor_total TEXT NOT NULL DEFAULT '0.00',
        base_icms TEXT DEFAULT '0.00', aliquota_icms TEXT DEFAULT '0.00',
        valor_icms TEXT DEFAULT '0.00', base_ipi TEXT DEFAULT '0.00',
        aliquota_ipi TEXT DEFAULT '0.00', valor_ipi TEXT DEFAULT '0.00',
        aliquota_pis TEXT DEFAULT '0.00', valor_pis TEXT DEFAULT '0.00',
        aliquota_cofins TEXT DEFAULT '0.00', valor_cofins TEXT DEFAULT '0.00',
        item_id_matched TEXT, company_id TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")

    # cfop
    conn.execute("""CREATE TABLE IF NOT EXISTS cfop (
        id TEXT PRIMARY KEY, codigo TEXT UNIQUE NOT NULL, descricao TEXT NOT NULL,
        tipo TEXT NOT NULL, operacao TEXT NOT NULL,
        is_active INTEGER DEFAULT 1, created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")

    # cst_csosn
    conn.execute("""CREATE TABLE IF NOT EXISTS cst_csosn (
        id TEXT PRIMARY KEY, codigo TEXT UNIQUE NOT NULL, descricao TEXT NOT NULL,
        imposto TEXT NOT NULL, regime TEXT NOT NULL,
        is_active INTEGER DEFAULT 1, created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")

    # ncm
    conn.execute("""CREATE TABLE IF NOT EXISTS ncm (
        id TEXT PRIMARY KEY, codigo TEXT UNIQUE NOT NULL, descricao TEXT NOT NULL,
        aliquota_ii TEXT DEFAULT '0.00', aliquota_ipi TEXT DEFAULT '0.00',
        is_active INTEGER DEFAULT 1, created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")

    # tax_period_br
    conn.execute("""CREATE TABLE IF NOT EXISTS tax_period_br (
        id TEXT PRIMARY KEY, ano INTEGER NOT NULL, mes INTEGER NOT NULL,
        data_inicio TEXT NOT NULL, data_fim TEXT NOT NULL,
        regime TEXT DEFAULT 'lucro_real', status TEXT DEFAULT 'aberto',
        company_id TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(ano, mes, company_id)
    )""")

    # tax_apuration
    conn.execute("""CREATE TABLE IF NOT EXISTS tax_apuration (
        id TEXT PRIMARY KEY, tax_period_br_id TEXT NOT NULL,
        tributo TEXT NOT NULL, uf TEXT,
        debito TEXT DEFAULT '0.00', credito TEXT DEFAULT '0.00',
        saldo_devedor TEXT DEFAULT '0.00', saldo_credor TEXT DEFAULT '0.00',
        valor_pagar TEXT DEFAULT '0.00', valor_pago TEXT DEFAULT '0.00',
        codigo_receita TEXT, data_vencimento TEXT,
        status TEXT DEFAULT 'pendente', gl_entries_posted INTEGER DEFAULT 0,
        company_id TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")

    # sped_export_log
    conn.execute("""CREATE TABLE IF NOT EXISTS sped_export_log (
        id TEXT PRIMARY KEY,
        tipo TEXT NOT NULL,
        ano INTEGER NOT NULL, mes INTEGER NOT NULL, periodo TEXT,
        arquivo_path TEXT, arquivo_hash TEXT, tamanho_bytes INTEGER,
        total_registros INTEGER,
        status TEXT DEFAULT 'gerado',
        protocolo TEXT, recibo TEXT, mensagem_sEFAZ TEXT,
        company_id TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")

    # difal_config
    conn.execute("""CREATE TABLE IF NOT EXISTS difal_config (
        id TEXT PRIMARY KEY, uf_origem TEXT NOT NULL, uf_destino TEXT NOT NULL,
        aliquota_interestadual TEXT NOT NULL DEFAULT '12.00',
        aliquota_interna_destino TEXT NOT NULL,
        difal_partilha_pct TEXT DEFAULT '100.00',
        fundo_combate_pobreza_pct TEXT DEFAULT '0.00',
        ano_vigencia INTEGER NOT NULL, is_active INTEGER DEFAULT 1,
        company_id TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(uf_origem, uf_destino, ano_vigencia, company_id)
    )""")

    # br_nfe_config
    conn.execute("""CREATE TABLE IF NOT EXISTS br_nfe_config (
        id TEXT PRIMARY KEY, company_id TEXT NOT NULL UNIQUE,
        ambiente TEXT NOT NULL DEFAULT 'homologacao', uf TEXT NOT NULL,
        certificado_path TEXT, certificado_password TEXT,
        csc TEXT, csc_id TEXT,
        serie_default TEXT DEFAULT '1', proximo_numero INTEGER DEFAULT 1,
        regime_tributario TEXT DEFAULT 'normal', regime_isencao TEXT,
        tipo_emissao TEXT DEFAULT 'normal', codigo_municipio TEXT DEFAULT '3550308',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")

    # br_nfe_out
    conn.execute("""CREATE TABLE IF NOT EXISTS br_nfe_out (
        id TEXT PRIMARY KEY, chave_acesso TEXT UNIQUE NOT NULL,
        numero INTEGER NOT NULL, serie TEXT DEFAULT '1', modelo TEXT DEFAULT '55',
        tipo_operacao TEXT DEFAULT 'saida', data_emissao TEXT NOT NULL,
        data_saida TEXT, hora_saida TEXT, natureza_operacao TEXT,
        cfop_principal TEXT, finalidade TEXT DEFAULT 'normal',
        sales_invoice_id TEXT, customer_id TEXT, customer_name TEXT,
        customer_cnpj TEXT, customer_cpf TEXT, customer_ie TEXT,
        customer_isuf TEXT, customer_email TEXT,
        valor_produtos TEXT DEFAULT '0.00', valor_total TEXT NOT NULL DEFAULT '0.00',
        valor_desconto TEXT DEFAULT '0.00', valor_frete TEXT DEFAULT '0.00',
        valor_seguro TEXT DEFAULT '0.00', outras_despesas TEXT DEFAULT '0.00',
        base_icms TEXT DEFAULT '0.00', valor_icms TEXT DEFAULT '0.00',
        base_icms_st TEXT DEFAULT '0.00', valor_icms_st TEXT DEFAULT '0.00',
        base_icms_uf_dest TEXT DEFAULT '0.00', valor_icms_uf_dest TEXT DEFAULT '0.00',
        valor_icms_uf_remet TEXT DEFAULT '0.00', valor_icms_desonerado TEXT DEFAULT '0.00',
        base_ipi TEXT DEFAULT '0.00', valor_ipi TEXT DEFAULT '0.00',
        valor_pis TEXT DEFAULT '0.00', valor_cofins TEXT DEFAULT '0.00',
        valor_ii TEXT DEFAULT '0.00', valor_aproximado_tributos TEXT DEFAULT '0.00',
        info_complementar TEXT, info_fisco TEXT,
        danfe_path TEXT, xml_nfe TEXT, xml_signed TEXT, xml_protocolado TEXT,
        recibo TEXT, protocolo TEXT, data_autorizacao TEXT, data_cancelamento TEXT,
        status TEXT DEFAULT 'rascunho', motivo_status TEXT,
        ambiente TEXT DEFAULT 'homologacao', gl_entries_posted INTEGER DEFAULT 0,
        company_id TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")

    # br_nfe_out_item
    conn.execute("""CREATE TABLE IF NOT EXISTS br_nfe_out_item (
        id TEXT PRIMARY KEY, nfe_out_id TEXT NOT NULL, numero_item INTEGER NOT NULL,
        codigo_produto TEXT, descricao TEXT NOT NULL, ncm TEXT, cfop TEXT,
        cst_icms TEXT, cst_pis TEXT, cst_cofins TEXT,
        unidade TEXT DEFAULT 'UN', quantidade TEXT NOT NULL DEFAULT '1.0',
        valor_unitario TEXT NOT NULL DEFAULT '0.00', valor_total TEXT NOT NULL DEFAULT '0.00',
        base_icms TEXT DEFAULT '0.00', aliquota_icms TEXT DEFAULT '0.00',
        valor_icms TEXT DEFAULT '0.00', base_ipi TEXT DEFAULT '0.00',
        aliquota_ipi TEXT DEFAULT '0.00', valor_ipi TEXT DEFAULT '0.00',
        aliquota_pis TEXT DEFAULT '0.00', valor_pis TEXT DEFAULT '0.00',
        aliquota_cofins TEXT DEFAULT '0.00', valor_cofins TEXT DEFAULT '0.00',
        company_id TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")

    # br_nfe_event
    conn.execute("""CREATE TABLE IF NOT EXISTS br_nfe_event (
        id TEXT PRIMARY KEY, nfe_out_id TEXT NOT NULL,
        tipo_evento TEXT NOT NULL, numero_sequencial INTEGER DEFAULT 1,
        justificativa TEXT, xml_evento TEXT, xml_evento_signed TEXT,
        protocolo TEXT, recibo TEXT, data_processamento TEXT,
        status TEXT DEFAULT 'pendente', motivo_status TEXT,
        ambiente TEXT DEFAULT 'homologacao', company_id TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")

    # br_nfse_config
    conn.execute("""CREATE TABLE IF NOT EXISTS br_nfse_config (
        id TEXT PRIMARY KEY, company_id TEXT NOT NULL UNIQUE,
        municipio_codigo TEXT NOT NULL, municipio_nome TEXT NOT NULL,
        uf TEXT NOT NULL, aliquota_iss TEXT DEFAULT '5.00',
        regime_tributacao TEXT DEFAULT 'normal', ambiente TEXT DEFAULT 'homologacao',
        certificado_path TEXT, proximo_numero_rps INTEGER DEFAULT 1,
        serie_rps TEXT DEFAULT '1',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")

    # br_nfse
    conn.execute("""CREATE TABLE IF NOT EXISTS br_nfse (
        id TEXT PRIMARY KEY, numero_rps INTEGER NOT NULL,
        numero_nfse TEXT, codigo_verificacao TEXT, data_emissao TEXT NOT NULL,
        sales_invoice_id TEXT, customer_id TEXT, customer_name TEXT,
        customer_cnpj TEXT, customer_cpf TEXT, customer_municipio TEXT,
        discriminacao TEXT, valor_servicos TEXT DEFAULT '0.00',
        base_calculo TEXT DEFAULT '0.00', aliquota_iss TEXT DEFAULT '5.00',
        valor_iss TEXT DEFAULT '0.00', valor_pis TEXT DEFAULT '0.00',
        valor_cofins TEXT DEFAULT '0.00', valor_ir TEXT DEFAULT '0.00',
        valor_csll TEXT DEFAULT '0.00', valor_inss TEXT DEFAULT '0.00',
        retencao_iss INTEGER DEFAULT 0, valor_liquido TEXT DEFAULT '0.00',
        xml_rps TEXT, xml_nfse TEXT, xml_signed TEXT, protocolo TEXT,
        status TEXT DEFAULT 'rascunho', motivo_status TEXT,
        ambiente TEXT DEFAULT 'homologacao', company_id TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")

    # company_fiscal
    conn.execute("""CREATE TABLE IF NOT EXISTS company_fiscal (
        id TEXT PRIMARY KEY, company_id TEXT NOT NULL UNIQUE,
        cnpj TEXT NOT NULL UNIQUE, inscricao_estadual TEXT,
        inscricao_municipal TEXT, inscricao_suframa TEXT,
        razao_social TEXT, nome_fantasia TEXT, cnae_principal TEXT,
        crt TEXT DEFAULT '3', regime_isencao TEXT,
        logradouro TEXT, numero TEXT, complemento TEXT, bairro TEXT,
        cep TEXT, municipio_codigo TEXT, municipio_nome TEXT, uf TEXT,
        telefone TEXT, email TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")

    # customer_fiscal
    conn.execute("""CREATE TABLE IF NOT EXISTS customer_fiscal (
        id TEXT PRIMARY KEY, customer_id TEXT NOT NULL UNIQUE,
        cnpj TEXT, cpf TEXT, ie TEXT, isuf TEXT, im TEXT,
        contribuinte_icms INTEGER DEFAULT 1, crt TEXT DEFAULT '3',
        logradouro TEXT, numero TEXT, complemento TEXT, bairro TEXT,
        cep TEXT, municipio_codigo TEXT, municipio_nome TEXT, uf TEXT,
        telefone TEXT, email_nfe TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")

    # item_fiscal
    conn.execute("""CREATE TABLE IF NOT EXISTS item_fiscal (
        id TEXT PRIMARY KEY, item_id TEXT NOT NULL UNIQUE,
        ncm TEXT, cest TEXT, gtin TEXT, gtin_trib TEXT,
        origem TEXT DEFAULT '0', ex_tipi TEXT,
        cfop_saida_interna TEXT, cfop_saida_interestadual TEXT,
        cfop_saida_exterior TEXT, cfop_entrada_interna TEXT,
        cfop_entrada_interestadual TEXT, cfop_entrada_exterior TEXT,
        icms_cst TEXT, pis_cst TEXT, cofins_cst TEXT, ipi_cst TEXT,
        aliq_icms TEXT DEFAULT '18.00', aliq_icms_st TEXT DEFAULT '0.00',
        aliq_pis TEXT DEFAULT '1.65', aliq_cofins TEXT DEFAULT '7.60',
        aliq_ipi TEXT DEFAULT '0.00', aliq_iss TEXT DEFAULT '0.00',
        mva_st TEXT DEFAULT '0.00', reducao_base_icms TEXT DEFAULT '0.00',
        reducao_base_icms_st TEXT DEFAULT '0.00',
        company_id TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")

    # mva_st_config
    conn.execute("""CREATE TABLE IF NOT EXISTS mva_st_config (
        id TEXT PRIMARY KEY, uf TEXT NOT NULL, ncm_prefix TEXT NOT NULL,
        mva_original TEXT NOT NULL DEFAULT '0.00', mva_padrao TEXT NOT NULL DEFAULT '0.00',
        is_active INTEGER DEFAULT 1, company_id TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(uf, ncm_prefix, company_id)
    )""")

    # fecp_config
    conn.execute("""CREATE TABLE IF NOT EXISTS fecp_config (
        id TEXT PRIMARY KEY, uf TEXT NOT NULL UNIQUE,
        aliquota TEXT NOT NULL DEFAULT '2.00', is_active INTEGER DEFAULT 1,
        company_id TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")

    # iss_config
    conn.execute("""CREATE TABLE IF NOT EXISTS iss_config (
        id TEXT PRIMARY KEY, municipio_codigo TEXT NOT NULL,
        municipio_nome TEXT NOT NULL, uf TEXT NOT NULL,
        aliquota TEXT NOT NULL DEFAULT '5.00', cnae TEXT,
        is_active INTEGER DEFAULT 1, company_id TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(municipio_codigo, cnae, company_id)
    )""")

    # withholding_config
    conn.execute("""CREATE TABLE IF NOT EXISTS withholding_config (
        id TEXT PRIMARY KEY, tributo TEXT NOT NULL,
        base_minima TEXT DEFAULT '0.00', aliquota TEXT NOT NULL,
        descricao TEXT, is_active INTEGER DEFAULT 1,
        company_id TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")

    # repetro_di
    conn.execute("""CREATE TABLE IF NOT EXISTS repetro_di (
        id TEXT PRIMARY KEY, di_numero TEXT NOT NULL, di_data TEXT NOT NULL,
        di_vencimento TEXT, cnpj_beneficiario TEXT NOT NULL, uf_despacho TEXT,
        status TEXT DEFAULT 'ativo', observacoes TEXT,
        company_id TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")

    # repetro_equipment
    conn.execute("""CREATE TABLE IF NOT EXISTS repetro_equipment (
        id TEXT PRIMARY KEY, repetro_di_id TEXT NOT NULL,
        item_id TEXT, descricao TEXT NOT NULL, ncm TEXT,
        quantidade TEXT DEFAULT '1', valor_unitario TEXT DEFAULT '0.00',
        data_entrada TEXT, data_saida TEXT,
        status TEXT DEFAULT 'ativo',
        company_id TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")

    conn.commit()

    # Seed fiscal catalogs for tests
    _seed_fiscal_catalogs(conn)


def _seed_fiscal_catalogs(conn):
    """Seed CFOP, CST, NCM tables for tests."""
    existing = conn.execute("SELECT COUNT(*) FROM cfop").fetchone()[0]
    if existing > 0:
        return

    cfops = [
        ("1.101", "Compra para industrialização", "entrada", "interna"),
        ("1.102", "Compra para comercialização", "entrada", "interna"),
        ("5.101", "Venda de produção do estabelecimento", "saida", "interna"),
        ("5.102", "Venda de mercadoria adquirida ou recebida de terceiros", "saida", "interna"),
        ("6.101", "Venda de produção do estabelecimento", "saida", "interestadual"),
    ]
    for codigo, descricao, tipo, operacao in cfops:
        conn.execute(
            "INSERT INTO cfop (id, codigo, descricao, tipo, operacao) VALUES (?, ?, ?, ?, ?)",
            (str(uuid4()), codigo, descricao, tipo, operacao)
        )

    csts = [
        ("00", "Tributada integralmente", "icms", "normal"),
        ("10", "Tributada e com cobrança do ICMS por ST", "icms", "normal"),
        ("40", "Isenta", "icms", "normal"),
        ("60", "ICMS cobrado anteriormente por ST", "icms", "normal"),
    ]
    for codigo, descricao, imposto, regime in csts:
        conn.execute(
            "INSERT INTO cst_csosn (id, codigo, descricao, imposto, regime) VALUES (?, ?, ?, ?, ?)",
            (str(uuid4()), codigo, descricao, imposto, regime)
        )

    ncms = [
        ("3824.99.79", "Preparações para fluidos de perfuração"),
        ("7228.40.00", "Barras de outras ligas de aço, forjadas"),
    ]
    for codigo, descricao in ncms:
        conn.execute(
            "INSERT INTO ncm (id, codigo, descricao) VALUES (?, ?, ?)",
            (str(uuid4()), codigo, descricao)
        )

    conn.commit()


@pytest.fixture
def company_fiscal(db):
    """Create a test company with fiscal data."""
    cid = str(uuid4())
    db.execute(
        "INSERT INTO company (id, name, abbr, default_currency, country) "
        "VALUES (?, 'TestCo', 'TC', 'BRL', 'Brazil')",
        (cid,)
    )
    db.execute(
        """INSERT INTO company_fiscal (id, company_id, cnpj, inscricao_estadual,
           cnae_principal, crt, uf, municipio_nome, municipio_codigo)
           VALUES (?, ?, '32478156000179', '38740890', '7112000', '3',
           'RJ', 'Macaé', '3302403')""",
        (str(uuid4()), cid)
    )
    db.commit()
    return cid
