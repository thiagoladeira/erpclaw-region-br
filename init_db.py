#!/usr/bin/env python3
"""ERPClaw Region BR schema extension -- Brazilian fiscal tables.

Adds 13 tables: nfe_import, nfe_item, cfop, cst_csosn, ncm, 
tax_period_br, tax_apuration, sped_export_log, difal_config,
br_nfe_config, br_nfe_out, br_nfe_out_item, br_nfe_event.

Prerequisite: ERPClaw init_db.py must have run first.
Run: python3 init_db.py [db_path]
"""
import os
import sqlite3
import sys

DEFAULT_DB_PATH = os.path.expanduser("~/.openclaw/erpclaw/data.sqlite")
DISPLAY_NAME = "ERPClaw Region BR"

REQUIRED_FOUNDATION = [
    "company", "item", "stock_entry", "tax_template", "gl_entry",
]


def create_br_tables(db_path=None):
    db_path = db_path or os.environ.get("ERPCLAW_DB_PATH", DEFAULT_DB_PATH)
    conn = sqlite3.connect(db_path)
    
    # Setup pragmas
    try:
        sys.path.insert(0, os.path.expanduser("~/.openclaw/erpclaw/lib"))
        from erpclaw_lib.db import setup_pragmas
        setup_pragmas(conn)
    except ImportError:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")

    # Verify foundation exists
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()]
    missing = [t for t in REQUIRED_FOUNDATION if t not in tables]
    if missing:
        print(f"ERROR: Foundation tables missing: {', '.join(missing)}")
        print("Run ERPClaw setup first.")
        conn.close()
        sys.exit(1)

    tables_created = 0

    # ==================================================================
    # TABLE 1: nfe_import — NF-e de entrada importadas
    # ==================================================================
    conn.execute("""
        CREATE TABLE IF NOT EXISTS nfe_import (
            id                  TEXT PRIMARY KEY,
            chave_acesso        TEXT UNIQUE NOT NULL,
            numero_nfe          TEXT NOT NULL,
            serie               TEXT DEFAULT '1',
            modelo              TEXT DEFAULT '55',
            data_emissao        TEXT NOT NULL,
            data_entrada        TEXT,
            emitente_cnpj       TEXT NOT NULL,
            emitente_nome       TEXT NOT NULL,
            emitente_ie         TEXT,
            natureza_operacao   TEXT,
            cfop_principal      TEXT,
            valor_total         TEXT NOT NULL DEFAULT '0.00',
            valor_produtos      TEXT NOT NULL DEFAULT '0.00',
            base_icms           TEXT DEFAULT '0.00',
            valor_icms          TEXT DEFAULT '0.00',
            base_icms_st        TEXT DEFAULT '0.00',
            valor_icms_st       TEXT DEFAULT '0.00',
            base_ipi            TEXT DEFAULT '0.00',
            valor_ipi           TEXT DEFAULT '0.00',
            valor_pis           TEXT DEFAULT '0.00',
            valor_cofins        TEXT DEFAULT '0.00',
            valor_frete         TEXT DEFAULT '0.00',
            valor_seguro        TEXT DEFAULT '0.00',
            valor_desconto      TEXT DEFAULT '0.00',
            outras_despesas     TEXT DEFAULT '0.00',
            xml_raw             TEXT,
            supplier_id         TEXT,
            purchase_invoice_id TEXT,
            stock_entry_id      TEXT,
            gl_entries_posted   INTEGER DEFAULT 0,
            status              TEXT DEFAULT 'imported'
                                CHECK(status IN ('imported','validated','posted','error','cancelled')),
            error_message       TEXT,
            company_id          TEXT NOT NULL,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at          TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1

    conn.execute("CREATE INDEX IF NOT EXISTS idx_nfe_chave ON nfe_import(chave_acesso)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_nfe_emitente ON nfe_import(emitente_cnpj)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_nfe_company ON nfe_import(company_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_nfe_status ON nfe_import(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_nfe_data ON nfe_import(data_emissao)")

    # ==================================================================
    # TABLE 2: nfe_item — Itens da NF-e
    # ==================================================================
    conn.execute("""
        CREATE TABLE IF NOT EXISTS nfe_item (
            id                  TEXT PRIMARY KEY,
            nfe_import_id       TEXT NOT NULL REFERENCES nfe_import(id),
            numero_item         INTEGER NOT NULL,
            codigo_produto      TEXT,
            descricao           TEXT NOT NULL,
            ncm                 TEXT,
            cfop                TEXT,
            cst_icms            TEXT,
            cst_ipi             TEXT,
            cst_pis             TEXT,
            cst_cofins          TEXT,
            unidade             TEXT DEFAULT 'UN',
            quantidade          TEXT NOT NULL DEFAULT '1.0',
            valor_unitario      TEXT NOT NULL DEFAULT '0.00',
            valor_total         TEXT NOT NULL DEFAULT '0.00',
            base_icms           TEXT DEFAULT '0.00',
            aliquota_icms       TEXT DEFAULT '0.00',
            valor_icms          TEXT DEFAULT '0.00',
            base_ipi            TEXT DEFAULT '0.00',
            aliquota_ipi        TEXT DEFAULT '0.00',
            valor_ipi           TEXT DEFAULT '0.00',
            aliquota_pis        TEXT DEFAULT '0.00',
            valor_pis           TEXT DEFAULT '0.00',
            aliquota_cofins     TEXT DEFAULT '0.00',
            valor_cofins        TEXT DEFAULT '0.00',
            item_id_matched     TEXT,
            company_id          TEXT NOT NULL,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1

    conn.execute("CREATE INDEX IF NOT EXISTS idx_nfe_item_nfe ON nfe_item(nfe_import_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_nfe_item_ncm ON nfe_item(ncm)")

    # ==================================================================
    # TABLE 3: cfop — Códigos Fiscais de Operações
    # ==================================================================
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cfop (
            id                  TEXT PRIMARY KEY,
            codigo              TEXT UNIQUE NOT NULL,
            descricao           TEXT NOT NULL,
            tipo                TEXT NOT NULL
                                CHECK(tipo IN ('entrada','saida','ambos')),
            operacao            TEXT NOT NULL
                                CHECK(operacao IN ('interna','interestadual','exterior','todas')),
            is_active           INTEGER DEFAULT 1,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1

    conn.execute("CREATE INDEX IF NOT EXISTS idx_cfop_codigo ON cfop(codigo)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cfop_tipo ON cfop(tipo)")

    # ==================================================================
    # TABLE 4: cst_csosn — Códigos de Situação Tributária
    # ==================================================================
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cst_csosn (
            id                  TEXT PRIMARY KEY,
            codigo              TEXT UNIQUE NOT NULL,
            descricao           TEXT NOT NULL,
            imposto             TEXT NOT NULL
                                CHECK(imposto IN ('icms','ipi','pis','cofins','todos')),
            regime              TEXT NOT NULL
                                CHECK(regime IN ('normal','simples','ambos')),
            is_active           INTEGER DEFAULT 1,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1

    # ==================================================================
    # TABLE 5: ncm — Nomenclatura Comum do Mercosul
    # ==================================================================
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ncm (
            id                  TEXT PRIMARY KEY,
            codigo              TEXT UNIQUE NOT NULL,
            descricao           TEXT NOT NULL,
            aliquota_ii         TEXT DEFAULT '0.00',
            aliquota_ipi        TEXT DEFAULT '0.00',
            is_active           INTEGER DEFAULT 1,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1

    # ==================================================================
    # TABLE 6: tax_period_br — Períodos de apuração fiscal
    # ==================================================================
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tax_period_br (
            id                  TEXT PRIMARY KEY,
            ano                 INTEGER NOT NULL,
            mes                 INTEGER NOT NULL CHECK(mes BETWEEN 1 AND 12),
            data_inicio         TEXT NOT NULL,
            data_fim            TEXT NOT NULL,
            regime              TEXT DEFAULT 'lucro_real'
                                CHECK(regime IN ('lucro_real','lucro_presumido','simples_nacional')),
            status              TEXT DEFAULT 'aberto'
                                CHECK(status IN ('aberto','em_apuracao','fechado','retificado')),
            company_id          TEXT NOT NULL,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at          TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(ano, mes, company_id)
        )
    """)
    tables_created += 1

    # ==================================================================
    # TABLE 7: tax_apuration — Apuração de tributos
    # ==================================================================
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tax_apuration (
            id                  TEXT PRIMARY KEY,
            tax_period_br_id    TEXT NOT NULL REFERENCES tax_period_br(id),
            tributo             TEXT NOT NULL
                                CHECK(tributo IN ('icms','icms_st','ipi','pis','cofins','iss','irpj','csll','difal','simples')),
            uf                  TEXT,
            debito              TEXT DEFAULT '0.00',
            credito             TEXT DEFAULT '0.00',
            saldo_devedor       TEXT DEFAULT '0.00',
            saldo_credor        TEXT DEFAULT '0.00',
            valor_pagar         TEXT DEFAULT '0.00',
            valor_pago          TEXT DEFAULT '0.00',
            codigo_receita      TEXT,
            data_vencimento     TEXT,
            status              TEXT DEFAULT 'pendente'
                                CHECK(status IN ('pendente','pago','compensado','parcelado')),
            gl_entries_posted   INTEGER DEFAULT 0,
            company_id          TEXT NOT NULL,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at          TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1

    # ==================================================================
    # TABLE 8: sped_export_log — Histórico de exportações SPED
    # ==================================================================
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sped_export_log (
            id                  TEXT PRIMARY KEY,
            tipo                TEXT NOT NULL
                                CHECK(tipo IN ('efd_icms_ipi','efd_contrib','ecd','ecf','reinf')),
            ano                 INTEGER NOT NULL,
            mes                 INTEGER NOT NULL CHECK(mes BETWEEN 1 AND 12),
            periodo             TEXT,
            arquivo_path        TEXT,
            arquivo_hash        TEXT,
            tamanho_bytes       INTEGER,
            total_registros     INTEGER,
            status              TEXT DEFAULT 'gerado'
                                CHECK(status IN ('gerado','validado','assinado','transmitido','processado','rejeitado','erro')),
            protocolo           TEXT,
            recibo              TEXT,
            mensagem_sEFAZ      TEXT,
            company_id          TEXT NOT NULL,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at          TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1

    # ==================================================================
    # TABLE 9: difal_config — Configuração DIFAL
    # ==================================================================
    conn.execute("""
        CREATE TABLE IF NOT EXISTS difal_config (
            id                  TEXT PRIMARY KEY,
            uf_origem           TEXT NOT NULL,
            uf_destino          TEXT NOT NULL,
            aliquota_interestadual TEXT NOT NULL DEFAULT '12.00',
            aliquota_interna_destino TEXT NOT NULL,
            difal_partilha_pct  TEXT DEFAULT '100.00',
            fundo_combate_pobreza_pct TEXT DEFAULT '0.00',
            ano_vigencia        INTEGER NOT NULL,
            is_active           INTEGER DEFAULT 1,
            company_id          TEXT NOT NULL,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(uf_origem, uf_destino, ano_vigencia, company_id)
        )
    """)
    tables_created += 1

    # ==================================================================
    # TABLE 10: br_nfe_config — Configuração de emissão de NF-e
    # ==================================================================
    conn.execute("""
        CREATE TABLE IF NOT EXISTS br_nfe_config (
            id                  TEXT PRIMARY KEY,
            company_id          TEXT NOT NULL UNIQUE,
            ambiente            TEXT NOT NULL DEFAULT 'homologacao'
                                CHECK(ambiente IN ('homologacao','producao')),
            uf                  TEXT NOT NULL,
            certificado_path    TEXT,
            certificado_password TEXT,
            csc                 TEXT,
            csc_id              TEXT,
            serie_default       TEXT DEFAULT '1',
            proximo_numero      INTEGER DEFAULT 1,
            regime_tributario   TEXT DEFAULT 'normal'
                                CHECK(regime_tributario IN ('normal','simples_nacional','simples_excesso')),
            regime_isencao      TEXT,
            tipo_emissao        TEXT DEFAULT 'normal'
                                CHECK(tipo_emissao IN ('normal','contingencia_offline')),
            codigo_municipio    TEXT DEFAULT '3550308',
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at          TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1

    conn.execute("CREATE INDEX IF NOT EXISTS idx_nfe_cfg_company ON br_nfe_config(company_id)")

    # ==================================================================
    # TABLE 11: br_nfe_out — NF-e de saída (emitidas)
    # ==================================================================
    conn.execute("""
        CREATE TABLE IF NOT EXISTS br_nfe_out (
            id                  TEXT PRIMARY KEY,
            chave_acesso        TEXT UNIQUE NOT NULL,
            numero              INTEGER NOT NULL,
            serie               TEXT DEFAULT '1',
            modelo              TEXT DEFAULT '55'
                                CHECK(modelo IN ('55','65')),
            tipo_operacao       TEXT DEFAULT 'saida'
                                CHECK(tipo_operacao IN ('saida','entrada')),
            data_emissao        TEXT NOT NULL,
            data_saida          TEXT,
            hora_saida          TEXT,
            natureza_operacao   TEXT,
            cfop_principal      TEXT,
            finalidade          TEXT DEFAULT 'normal'
                                CHECK(finalidade IN ('normal','complementar','ajuste','devolucao')),
            sales_invoice_id    TEXT,
            customer_id         TEXT,
            customer_name       TEXT,
            customer_cnpj       TEXT,
            customer_cpf        TEXT,
            customer_ie         TEXT,
            customer_isuf       TEXT,
            customer_email      TEXT,
            valor_produtos      TEXT DEFAULT '0.00',
            valor_total         TEXT NOT NULL DEFAULT '0.00',
            valor_desconto      TEXT DEFAULT '0.00',
            valor_frete         TEXT DEFAULT '0.00',
            valor_seguro        TEXT DEFAULT '0.00',
            outras_despesas     TEXT DEFAULT '0.00',
            base_icms           TEXT DEFAULT '0.00',
            valor_icms          TEXT DEFAULT '0.00',
            base_icms_st        TEXT DEFAULT '0.00',
            valor_icms_st       TEXT DEFAULT '0.00',
            base_icms_uf_dest   TEXT DEFAULT '0.00',
            valor_icms_uf_dest  TEXT DEFAULT '0.00',
            valor_icms_uf_remet TEXT DEFAULT '0.00',
            valor_icms_desonerado TEXT DEFAULT '0.00',
            base_ipi            TEXT DEFAULT '0.00',
            valor_ipi           TEXT DEFAULT '0.00',
            valor_pis           TEXT DEFAULT '0.00',
            valor_cofins        TEXT DEFAULT '0.00',
            valor_ii            TEXT DEFAULT '0.00',
            valor_aproximado_tributos TEXT DEFAULT '0.00',
            info_complementar   TEXT,
            info_fisco          TEXT,
            danfe_path          TEXT,
            xml_nfe             TEXT,
            xml_signed          TEXT,
            xml_protocolado     TEXT,
            recibo              TEXT,
            protocolo           TEXT,
            data_autorizacao    TEXT,
            data_cancelamento   TEXT,
            status              TEXT DEFAULT 'rascunho'
                                CHECK(status IN ('rascunho','validado','assinado','enviado','autorizado','rejeitado','cancelado','denegado')),
            motivo_status       TEXT,
            ambiente            TEXT DEFAULT 'homologacao',
            gl_entries_posted   INTEGER DEFAULT 0,
            company_id          TEXT NOT NULL,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at          TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1

    conn.execute("CREATE INDEX IF NOT EXISTS idx_nfe_out_chave ON br_nfe_out(chave_acesso)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_nfe_out_si ON br_nfe_out(sales_invoice_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_nfe_out_cnpj ON br_nfe_out(customer_cnpj)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_nfe_out_company ON br_nfe_out(company_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_nfe_out_status ON br_nfe_out(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_nfe_out_data ON br_nfe_out(data_emissao)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_nfe_out_numero ON br_nfe_out(numero)")

    # ==================================================================
    # TABLE 12: br_nfe_out_item — Itens da NF-e de saída
    # ==================================================================
    conn.execute("""
        CREATE TABLE IF NOT EXISTS br_nfe_out_item (
            id                  TEXT PRIMARY KEY,
            nfe_out_id          TEXT NOT NULL,
            numero_item         INTEGER NOT NULL,
            codigo_produto      TEXT,
            descricao           TEXT NOT NULL,
            ncm                 TEXT,
            cfop                TEXT,
            cst_icms            TEXT,
            cst_pis             TEXT,
            cst_cofins          TEXT,
            unidade             TEXT DEFAULT 'UN',
            quantidade          TEXT NOT NULL DEFAULT '1.0',
            valor_unitario      TEXT NOT NULL DEFAULT '0.00',
            valor_total         TEXT NOT NULL DEFAULT '0.00',
            base_icms           TEXT DEFAULT '0.00',
            aliquota_icms       TEXT DEFAULT '0.00',
            valor_icms          TEXT DEFAULT '0.00',
            base_ipi            TEXT DEFAULT '0.00',
            aliquota_ipi        TEXT DEFAULT '0.00',
            valor_ipi           TEXT DEFAULT '0.00',
            aliquota_pis        TEXT DEFAULT '0.00',
            valor_pis           TEXT DEFAULT '0.00',
            aliquota_cofins     TEXT DEFAULT '0.00',
            valor_cofins        TEXT DEFAULT '0.00',
            company_id          TEXT NOT NULL,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1

    conn.execute("CREATE INDEX IF NOT EXISTS idx_nfe_out_item_nfe ON br_nfe_out_item(nfe_out_id)")

    # ==================================================================
    # TABLE 13: br_nfe_event — Eventos da NF-e (cancelamento, CC-e)
    # ==================================================================
    conn.execute("""
        CREATE TABLE IF NOT EXISTS br_nfe_event (
            id                  TEXT PRIMARY KEY,
            nfe_out_id          TEXT NOT NULL,
            tipo_evento         TEXT NOT NULL
                                CHECK(tipo_evento IN ('cancelamento','carta_correcao','manifestacao')),
            numero_sequencial   INTEGER DEFAULT 1,
            justificativa       TEXT,
            xml_evento          TEXT,
            xml_evento_signed   TEXT,
            protocolo           TEXT,
            recibo              TEXT,
            data_processamento  TEXT,
            status              TEXT DEFAULT 'pendente'
                                CHECK(status IN ('pendente','enviado','processado','rejeitado')),
            motivo_status       TEXT,
            ambiente            TEXT DEFAULT 'homologacao',
            company_id          TEXT NOT NULL,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at          TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1

    conn.execute("CREATE INDEX IF NOT EXISTS idx_nfe_event_nfe ON br_nfe_event(nfe_out_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_nfe_event_tipo ON br_nfe_event(tipo_evento)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_nfe_event_status ON br_nfe_event(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_nfe_event_company ON br_nfe_event(company_id)")

    # ==================================================================
    # Seed tabelas de catálogo fiscal (CFOP, CST, NCM)
    # ==================================================================
    _seed_fiscal_catalogs(conn)

    conn.commit()
    conn.close()

    return {
        "database": db_path,
        "display_name": DISPLAY_NAME,
        "tables": tables_created,
        "status": "ok",
    }


def _seed_fiscal_catalogs(conn):
    """Popula tabelas de catálogo com dados base."""
    from uuid import uuid4
    
    # Verifica se já existem dados
    existing = conn.execute("SELECT COUNT(*) FROM cfop").fetchone()[0]
    if existing > 0:
        return

    # CFOPs de entrada principais
    cfops = [
        ("1.101", "Compra para industrialização", "entrada", "interna"),
        ("1.102", "Compra para comercialização", "entrada", "interna"),
        ("1.111", "Compra para industrialização de mercadoria sujeita a ST", "entrada", "interna"),
        ("1.124", "Industrialização efetuada por outra empresa", "entrada", "interna"),
        ("1.151", "Transferência para industrialização", "entrada", "interna"),
        ("1.401", "Compra para industrialização em operação com mercadoria sujeita a ST", "entrada", "interna"),
        ("1.403", "Compra para comercialização em operação com mercadoria sujeita a ST", "entrada", "interna"),
        ("2.101", "Compra para industrialização", "entrada", "interestadual"),
        ("2.102", "Compra para comercialização", "entrada", "interestadual"),
        ("3.101", "Compra para industrialização", "entrada", "exterior"),
        ("3.102", "Compra para comercialização", "entrada", "exterior"),
        ("3.151", "Transferência para industrialização em operação de importação", "entrada", "exterior"),
    ]
    # CFOPs de saída principais
    cfops += [
        ("5.101", "Venda de produção do estabelecimento", "saida", "interna"),
        ("5.102", "Venda de mercadoria adquirida ou recebida de terceiros", "saida", "interna"),
        ("5.111", "Venda de produção do estabelecimento sujeita a ST", "saida", "interna"),
        ("5.151", "Transferência de produção do estabelecimento", "saida", "interna"),
        ("5.401", "Venda de produção do estabelecimento sujeita a ST", "saida", "interna"),
        ("6.101", "Venda de produção do estabelecimento", "saida", "interestadual"),
        ("6.102", "Venda de mercadoria adquirida ou recebida de terceiros", "saida", "interestadual"),
        ("7.101", "Venda de produção do estabelecimento", "saida", "exterior"),
        ("7.102", "Venda de mercadoria adquirida ou recebida de terceiros", "saida", "exterior"),
    ]
    for codigo, descricao, tipo, operacao in cfops:
        conn.execute(
            "INSERT OR IGNORE INTO cfop (id, codigo, descricao, tipo, operacao) VALUES (?, ?, ?, ?, ?)",
            (str(uuid4()), codigo, descricao, tipo, operacao)
        )

    # CSTs ICMS
    csts = [
        ("00", "Tributada integralmente", "icms", "normal", "ambos"),
        ("10", "Tributada e com cobrança do ICMS por ST", "icms", "normal", "ambos"),
        ("20", "Com redução de base de cálculo", "icms", "normal", "ambos"),
        ("30", "Isenta ou não tributada e com cobrança do ICMS por ST", "icms", "normal", "ambos"),
        ("40", "Isenta", "icms", "normal", "ambos"),
        ("41", "Não tributada", "icms", "normal", "ambos"),
        ("50", "Suspensão", "icms", "normal", "ambos"),
        ("51", "Diferimento", "icms", "normal", "ambos"),
        ("60", "ICMS cobrado anteriormente por ST", "icms", "normal", "ambos"),
        ("70", "Com redução de base de cálculo e cobrança do ICMS por ST", "icms", "normal", "ambos"),
        ("90", "Outras", "icms", "normal", "ambos"),
    ]
    for codigo, descricao, imposto, regime, _ in csts:
        conn.execute(
            "INSERT OR IGNORE INTO cst_csosn (id, codigo, descricao, imposto, regime) VALUES (?, ?, ?, ?, ?)",
            (str(uuid4()), codigo, descricao, imposto, regime)
        )

    # CSOSN (Simples Nacional)
    csosns = [
        ("101", "Tributada pelo Simples Nacional com permissão de crédito", "icms", "simples"),
        ("102", "Tributada pelo Simples Nacional sem permissão de crédito", "icms", "simples"),
        ("103", "Isenção do ICMS no Simples Nacional para faixa de receita bruta", "icms", "simples"),
        ("201", "Tributada pelo Simples Nacional com permissão de crédito e com cobrança do ICMS por ST", "icms", "simples"),
        ("202", "Tributada pelo Simples Nacional sem permissão de crédito e com cobrança do ICMS por ST", "icms", "simples"),
        ("203", "Isenção do ICMS no Simples Nacional para faixa de receita bruta e com cobrança do ICMS por ST", "icms", "simples"),
        ("300", "Imune", "icms", "simples"),
        ("400", "Não tributada pelo Simples Nacional", "icms", "simples"),
        ("500", "ICMS cobrado anteriormente por ST (substituído) ou por antecipação", "icms", "simples"),
        ("900", "Outros", "icms", "simples"),
    ]
    for codigo, descricao, imposto, regime in csosns:
        conn.execute(
            "INSERT OR IGNORE INTO cst_csosn (id, codigo, descricao, imposto, regime) VALUES (?, ?, ?, ?, ?)",
            (str(uuid4()), codigo, descricao, imposto, regime)
        )

    # NCMs comuns para O&G
    ncms = [
        ("3824.99.79", "Preparações para fluidos de perfuração"),
        ("7228.40.00", "Barras de outras ligas de aço, forjadas"),
        ("7225.40.90", "Chapas de outras ligas de aço, laminadas a quente"),
        ("4016.93.00", "Juntas, gaxetas e semelhantes, de borracha vulcanizada"),
        ("7318.15.00", "Outros parafusos e porcas, de ferro fundido, ferro ou aço"),
        ("8481.80.92", "Válvulas de gaveta"),
        ("8413.50.10", "Bombas hidráulicas de vazão variável"),
        ("8414.80.19", "Outros compressores de ar"),
        ("8502.13.11", "Grupos eletrogêneos de corrente alternada, diesel, >375kVA"),
        ("7307.99.00", "Outros acessórios para tubos, de ferro fundido, ferro ou aço"),
    ]
    for codigo, descricao in ncms:
        conn.execute(
            "INSERT OR IGNORE INTO ncm (id, codigo, descricao) VALUES (?, ?, ?)",
            (str(uuid4()), codigo, descricao)
        )


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else None
    result = create_br_tables(db)
    print(f"{DISPLAY_NAME} schema created in {result['database']}")
    print(f"  Tables: {result['tables']}")
    print(f"  Status: {result['status']}")
