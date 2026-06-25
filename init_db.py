#!/usr/bin/env python3
"""ERPClaw Region BR schema extension -- Brazilian fiscal tables.

Adds 24 tables: nfe_import, nfe_item, cfop, cst_csosn, ncm, 
tax_period_br, tax_apuration, sped_export_log, difal_config,
br_nfe_config, br_nfe_out, br_nfe_out_item, br_nfe_event,
company_fiscal, customer_fiscal, item_fiscal, mva_st_config,
fecp_config, iss_config, withholding_config, repetro_di,
repetro_equipment,
br_nfse_config, br_nfse (NFS-e — service invoices).

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
                                CHECK(tipo IN ('efd_icms_ipi','efd_contrib','ecd','ecf','dctfweb','reinf')),
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
                                CHECK(tipo_evento IN ('cancelamento','carta_correcao','manifestacao','confirmacao','ciencia','desconhecimento','operacao_realizada')),
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
    # TABLE 14: br_nfse_config — Configuração de emissão de NFS-e
    # ==================================================================
    conn.execute("""
        CREATE TABLE IF NOT EXISTS br_nfse_config (
            id TEXT PRIMARY KEY,
            company_id TEXT NOT NULL UNIQUE REFERENCES company(id),
            municipio_codigo TEXT NOT NULL,
            municipio_nome TEXT NOT NULL,
            uf TEXT NOT NULL,
            aliquota_iss TEXT DEFAULT '5.00',
            regime_tributacao TEXT DEFAULT 'normal',
            ambiente TEXT DEFAULT 'homologacao',
            certificado_path TEXT,
            proximo_numero_rps INTEGER DEFAULT 1,
            serie_rps TEXT DEFAULT '1',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1

    conn.execute("CREATE INDEX IF NOT EXISTS idx_nfse_cfg_company ON br_nfse_config(company_id)")

    # ==================================================================
    # TABLE 15: br_nfse — Nota Fiscal de Serviços Eletrônica
    # ==================================================================
    conn.execute("""
        CREATE TABLE IF NOT EXISTS br_nfse (
            id TEXT PRIMARY KEY,
            numero_rps INTEGER NOT NULL,
            numero_nfse TEXT,
            codigo_verificacao TEXT,
            data_emissao TEXT NOT NULL,
            sales_invoice_id TEXT,
            customer_id TEXT,
            customer_name TEXT,
            customer_cnpj TEXT,
            customer_cpf TEXT,
            customer_municipio TEXT,
            discriminacao TEXT,
            valor_servicos TEXT DEFAULT '0.00',
            base_calculo TEXT DEFAULT '0.00',
            aliquota_iss TEXT DEFAULT '5.00',
            valor_iss TEXT DEFAULT '0.00',
            valor_pis TEXT DEFAULT '0.00',
            valor_cofins TEXT DEFAULT '0.00',
            valor_ir TEXT DEFAULT '0.00',
            valor_csll TEXT DEFAULT '0.00',
            valor_inss TEXT DEFAULT '0.00',
            retencao_iss INTEGER DEFAULT 0,
            valor_liquido TEXT DEFAULT '0.00',
            xml_rps TEXT,
            xml_nfse TEXT,
            xml_signed TEXT,
            protocolo TEXT,
            status TEXT DEFAULT 'rascunho'
                CHECK(status IN ('rascunho','validado','assinado','enviado','autorizado','rejeitado','cancelado')),
            motivo_status TEXT,
            ambiente TEXT DEFAULT 'homologacao',
            company_id TEXT NOT NULL REFERENCES company(id),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1

    conn.execute("CREATE INDEX IF NOT EXISTS idx_nfse_company ON br_nfse(company_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_nfse_rps ON br_nfse(numero_rps)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_nfse_status ON br_nfse(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_nfse_data ON br_nfse(data_emissao)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_nfse_si ON br_nfse(sales_invoice_id)")

    # ==================================================================
    # TABLE 16: company_fiscal — Brazilian tax identifiers for the company
    # ==================================================================
    conn.execute("""
        CREATE TABLE IF NOT EXISTS company_fiscal (
            id                  TEXT PRIMARY KEY,
            company_id          TEXT NOT NULL UNIQUE REFERENCES company(id),
            cnpj                TEXT NOT NULL UNIQUE,
            inscricao_estadual  TEXT,
            inscricao_municipal TEXT,
            inscricao_suframa   TEXT,
            razao_social        TEXT,
            nome_fantasia       TEXT,
            cnae_principal      TEXT,
            crt                 TEXT DEFAULT '3' CHECK(crt IN ('1','2','3')),
            regime_isencao      TEXT,
            logradouro          TEXT,
            numero              TEXT,
            complemento         TEXT,
            bairro              TEXT,
            cep                 TEXT,
            municipio_codigo    TEXT,
            municipio_nome      TEXT,
            uf                  TEXT,
            telefone            TEXT,
            email               TEXT,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at          TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1

    conn.execute("CREATE INDEX IF NOT EXISTS idx_company_fiscal_cnpj ON company_fiscal(cnpj)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_company_fiscal_company ON company_fiscal(company_id)")

    # ==================================================================
    # TABLE 17: customer_fiscal — Brazilian tax identifiers for customers
    # ==================================================================
    conn.execute("""
        CREATE TABLE IF NOT EXISTS customer_fiscal (
            id                  TEXT PRIMARY KEY,
            customer_id         TEXT NOT NULL UNIQUE REFERENCES customer(id),
            cnpj                TEXT,
            cpf                 TEXT,
            ie                  TEXT,
            isuf                TEXT,
            im                  TEXT,
            contribuinte_icms   INTEGER DEFAULT 1 CHECK(contribuinte_icms IN (0,1,2)),
            crt                 TEXT DEFAULT '3' CHECK(crt IN ('1','2','3')),
            logradouro          TEXT,
            numero              TEXT,
            complemento         TEXT,
            bairro              TEXT,
            cep                 TEXT,
            municipio_codigo    TEXT,
            municipio_nome      TEXT,
            uf                  TEXT,
            telefone            TEXT,
            email_nfe           TEXT,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at          TEXT DEFAULT CURRENT_TIMESTAMP,
            CHECK(cnpj IS NOT NULL OR cpf IS NOT NULL)
        )
    """)
    tables_created += 1

    conn.execute("CREATE INDEX IF NOT EXISTS idx_customer_fiscal_cnpj ON customer_fiscal(cnpj)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_customer_fiscal_cpf ON customer_fiscal(cpf)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_customer_fiscal_customer ON customer_fiscal(customer_id)")

    # ==================================================================
    # TABLE 18: item_fiscal — Brazilian tax classification for items
    # ==================================================================
    conn.execute("""
        CREATE TABLE IF NOT EXISTS item_fiscal (
            id                  TEXT PRIMARY KEY,
            item_id             TEXT NOT NULL UNIQUE REFERENCES item(id),
            ncm                 TEXT,
            cest                TEXT,
            gtin                TEXT,
            gtin_trib           TEXT,
            origem              TEXT DEFAULT '0' CHECK(origem IN ('0','1','2','3','4','5','6','7','8')),
            ex_tipi             TEXT,
            cfop_saida_interna          TEXT,
            cfop_saida_interestadual    TEXT,
            cfop_saida_exterior         TEXT,
            cfop_entrada_interna        TEXT,
            cfop_entrada_interestadual  TEXT,
            cfop_entrada_exterior       TEXT,
            icms_cst            TEXT,
            pis_cst             TEXT,
            cofins_cst          TEXT,
            ipi_cst             TEXT,
            aliq_icms           TEXT DEFAULT '18.00',
            aliq_icms_st        TEXT DEFAULT '0.00',
            aliq_pis            TEXT DEFAULT '1.65',
            aliq_cofins         TEXT DEFAULT '7.60',
            aliq_ipi            TEXT DEFAULT '0.00',
            aliq_iss            TEXT DEFAULT '0.00',
            mva_st              TEXT DEFAULT '0.00',
            reducao_base_icms   TEXT DEFAULT '0.00',
            reducao_base_icms_st TEXT DEFAULT '0.00',
            company_id          TEXT NOT NULL REFERENCES company(id),
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at          TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1

    conn.execute("CREATE INDEX IF NOT EXISTS idx_item_fiscal_ncm ON item_fiscal(ncm)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_item_fiscal_item ON item_fiscal(item_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_item_fiscal_company ON item_fiscal(company_id)")

    # ==================================================================
    # TABLE 19: mva_st_config — MVA (Margem de Valor Agregado) for ICMS ST per UF/produto
    # ==================================================================
    conn.execute("""
        CREATE TABLE IF NOT EXISTS mva_st_config (
            id TEXT PRIMARY KEY,
            uf TEXT NOT NULL,
            ncm_prefix TEXT NOT NULL,
            mva_original TEXT NOT NULL DEFAULT '0.00',
            mva_padrao TEXT NOT NULL DEFAULT '0.00',
            is_active INTEGER DEFAULT 1,
            company_id TEXT NOT NULL REFERENCES company(id),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(uf, ncm_prefix, company_id)
        )
    """)
    tables_created += 1
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mva_st_uf ON mva_st_config(uf)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mva_st_ncm ON mva_st_config(ncm_prefix)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mva_st_company ON mva_st_config(company_id)")

    # ==================================================================
    # TABLE 20: fecp_config — FECP rates per UF
    # ==================================================================
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fecp_config (
            id TEXT PRIMARY KEY,
            uf TEXT NOT NULL UNIQUE,
            aliquota TEXT NOT NULL DEFAULT '2.00',
            is_active INTEGER DEFAULT 1,
            company_id TEXT NOT NULL REFERENCES company(id),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1
    conn.execute("CREATE INDEX IF NOT EXISTS idx_fecp_config_uf ON fecp_config(uf)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_fecp_config_company ON fecp_config(company_id)")

    # ==================================================================
    # TABLE 21: iss_config — ISS municipal rates
    # ==================================================================
    conn.execute("""
        CREATE TABLE IF NOT EXISTS iss_config (
            id TEXT PRIMARY KEY,
            municipio_codigo TEXT NOT NULL,
            municipio_nome TEXT NOT NULL,
            uf TEXT NOT NULL,
            aliquota TEXT NOT NULL DEFAULT '5.00',
            cnae TEXT,
            is_active INTEGER DEFAULT 1,
            company_id TEXT NOT NULL REFERENCES company(id),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(municipio_codigo, cnae, company_id)
        )
    """)
    tables_created += 1
    conn.execute("CREATE INDEX IF NOT EXISTS idx_iss_config_mun ON iss_config(municipio_codigo)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_iss_config_company ON iss_config(company_id)")

    # ==================================================================
    # TABLE 22: withholding_config — Tax withholding rates
    # ==================================================================
    conn.execute("""
        CREATE TABLE IF NOT EXISTS withholding_config (
            id TEXT PRIMARY KEY,
            tributo TEXT NOT NULL CHECK(tributo IN ('ir','pis','cofins','csll','inss','iss')),
            base_minima TEXT DEFAULT '0.00',
            aliquota TEXT NOT NULL,
            descricao TEXT,
            is_active INTEGER DEFAULT 1,
            company_id TEXT NOT NULL REFERENCES company(id),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1
    conn.execute("CREATE INDEX IF NOT EXISTS idx_withholding_config_tributo ON withholding_config(tributo)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_withholding_config_company ON withholding_config(company_id)")

    # ==================================================================
    # TABLE 21: repetro_di — REPETRO Declaração de Importação
    # ==================================================================
    conn.execute("""
        CREATE TABLE IF NOT EXISTS repetro_di (
            id TEXT PRIMARY KEY,
            di_numero TEXT NOT NULL,
            di_data TEXT NOT NULL,
            di_vencimento TEXT,
            cnpj_beneficiario TEXT NOT NULL,
            uf_despacho TEXT,
            status TEXT DEFAULT 'ativo'
                CHECK(status IN ('ativo','prorrogado','encerrado','vencido')),
            observacoes TEXT,
            company_id TEXT NOT NULL REFERENCES company(id),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1
    conn.execute("CREATE INDEX IF NOT EXISTS idx_repetro_di_numero ON repetro_di(di_numero)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_repetro_di_cnpj ON repetro_di(cnpj_beneficiario)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_repetro_di_status ON repetro_di(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_repetro_di_company ON repetro_di(company_id)")

    # ==================================================================
    # TABLE 22: repetro_equipment — REPETRO Equipment Tracking
    # ==================================================================
    conn.execute("""
        CREATE TABLE IF NOT EXISTS repetro_equipment (
            id TEXT PRIMARY KEY,
            repetro_di_id TEXT NOT NULL REFERENCES repetro_di(id),
            item_id TEXT REFERENCES item(id),
            descricao TEXT NOT NULL,
            ncm TEXT,
            quantidade TEXT DEFAULT '1',
            valor_unitario TEXT DEFAULT '0.00',
            data_entrada TEXT,
            data_saida TEXT,
            status TEXT DEFAULT 'ativo'
                CHECK(status IN ('ativo','exportado','transferido','baixado')),
            company_id TEXT NOT NULL REFERENCES company(id),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1
    conn.execute("CREATE INDEX IF NOT EXISTS idx_repetro_eq_di ON repetro_equipment(repetro_di_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_repetro_eq_item ON repetro_equipment(item_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_repetro_eq_status ON repetro_equipment(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_repetro_eq_company ON repetro_equipment(company_id)")

    # ==================================================================
    # Seed tabelas de catálogo fiscal (CFOP, CST, NCM)
    # ==================================================================
    _seed_fiscal_catalogs(conn)

    # Migration: add 'dctfweb' to sped_export_log CHECK if table already existed
    _migrate_sped_export_log_check(conn)

    # Migration: add manifestação subtypes to br_nfe_event CHECK constraint
    _migrate_nfe_event_check(conn)

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

    # FECP rates for all 27 UFs
    fecp_rates = [
        ("SP", "2.00"), ("RJ", "4.00"), ("MG", "2.00"), ("ES", "2.00"),
        ("RS", "2.00"), ("SC", "2.00"), ("PR", "2.00"), ("BA", "2.00"),
        ("CE", "2.00"), ("PE", "2.00"), ("MA", "2.00"), ("PI", "2.00"),
        ("PB", "2.00"), ("RN", "2.00"), ("AL", "2.00"), ("SE", "2.00"),
        ("GO", "2.00"), ("MT", "2.00"), ("MS", "2.00"), ("DF", "2.00"),
        ("AM", "2.00"), ("PA", "2.00"), ("RO", "2.00"), ("AC", "2.00"),
        ("RR", "2.00"), ("AP", "2.00"), ("TO", "2.00"),
    ]
    # Use a dummy company_id for catalog seed (these are reference rates)
    for uf, aliquota in fecp_rates:
        conn.execute(
            "INSERT OR IGNORE INTO fecp_config (id, uf, aliquota, company_id) VALUES (?, ?, ?, ?)",
            (str(uuid4()), uf, aliquota, "*")
        )

    # Withholding defaults
    withholding_defaults = [
        ("ir", "10.00", "1.50", "IR retido na fonte — serviços (base reduzida 40%)"),
        ("pis", "10.00", "0.65", "PIS retido na fonte — 4.65% composto"),
        ("cofins", "10.00", "3.00", "COFINS retido na fonte — 4.65% composto"),
        ("csll", "10.00", "1.00", "CSLL retida na fonte — 4.65% composto"),
        ("inss", "10.00", "11.00", "INSS retido na fonte — serviços"),
        ("iss", "10.00", "5.00", "ISS retido na fonte — padrão municipal"),
    ]
    for tributo, base_min, aliquota, descricao in withholding_defaults:
        conn.execute(
            "INSERT OR IGNORE INTO withholding_config (id, tributo, base_minima, aliquota, descricao, company_id) VALUES (?, ?, ?, ?, ?, ?)",
            (str(uuid4()), tributo, base_min, aliquota, descricao, "*")
        )


def _migrate_sped_export_log_check(conn):
    """Add 'dctfweb' to sped_export_log tipo CHECK constraint.

    SQLite does not support ALTER TABLE ... ALTER CHECK, so we rebuild
    the table if the constraint is missing the new value. This is safe
    because the table is small (export metadata, not financial data).
    """
    try:
        # Test if 'dctfweb' is valid by trying to insert with it
        # If it fails, the constraint needs updating
        test_id = str(uuid4())
        conn.execute("""
            INSERT INTO sped_export_log (id, tipo, ano, mes, total_registros, status, company_id)
            VALUES (?, 'dctfweb', 2026, 6, 0, 'gerado', 'test')
        """, (test_id,))
        # It worked — clean up test row
        conn.execute("DELETE FROM sped_export_log WHERE id = ?", (test_id,))
        return  # Constraint already includes 'dctfweb'
    except Exception:
        pass  # Constraint needs updating

    try:
        # Attempt ALTER TABLE to drop and recreate with new constraint
        # Strategy: rename, create new, copy data, drop old
        conn.execute("PRAGMA foreign_keys=OFF")

        # 1. Rename existing table
        conn.execute("ALTER TABLE sped_export_log RENAME TO sped_export_log_old")

        # 2. Create new table with updated CHECK
        conn.execute("""
            CREATE TABLE sped_export_log (
                id                  TEXT PRIMARY KEY,
                tipo                TEXT NOT NULL
                                    CHECK(tipo IN ('efd_icms_ipi','efd_contrib','ecd','ecf','dctfweb','reinf')),
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

        # 3. Copy data
        conn.execute("""
            INSERT INTO sped_export_log
            SELECT * FROM sped_export_log_old
        """)

        # 4. Drop old table
        conn.execute("DROP TABLE sped_export_log_old")

        # 5. Recreate indexes
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sped_log_tipo ON sped_export_log(tipo)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sped_log_periodo ON sped_export_log(ano, mes)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sped_log_company ON sped_export_log(company_id)")

        conn.execute("PRAGMA foreign_keys=ON")
        print("  ✓ sped_export_log migrated: added 'dctfweb' to tipo constraint")
    except Exception as e:
        # Already migrated or nothing to migrate
        try:
            conn.execute("PRAGMA foreign_keys=ON")
        except Exception:
            pass
        print(f"  ℹ sped_export_log migration skipped: {e}")


def _migrate_nfe_event_check(conn):
    """Add manifestação subtypes to br_nfe_event tipo_evento CHECK.

    SQLite does not support ALTER TABLE ... ALTER CHECK, so we rebuild
    the table if the constraint is missing the new values.
    """
    from uuid import uuid4
    try:
        # Test if 'confirmacao' is valid by trying to insert with it
        test_id = str(uuid4())
        conn.execute("""
            INSERT INTO br_nfe_event (id, nfe_out_id, tipo_evento, xml_evento, status, company_id)
            VALUES (?, 'test', 'confirmacao', '<evento/>', 'pendente', 'test')
        """, (test_id,))
        conn.execute("DELETE FROM br_nfe_event WHERE id = ?", (test_id,))
        return  # Constraint already includes 'confirmacao'
    except Exception:
        pass  # Constraint needs updating

    try:
        conn.execute("PRAGMA foreign_keys=OFF")

        conn.execute("ALTER TABLE br_nfe_event RENAME TO br_nfe_event_old")

        conn.execute("""
            CREATE TABLE br_nfe_event (
                id                  TEXT PRIMARY KEY,
                nfe_out_id          TEXT NOT NULL,
                tipo_evento         TEXT NOT NULL
                                    CHECK(tipo_evento IN ('cancelamento','carta_correcao','manifestacao','confirmacao','ciencia','desconhecimento','operacao_realizada')),
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

        conn.execute("""
            INSERT INTO br_nfe_event
            SELECT * FROM br_nfe_event_old
        """)

        conn.execute("DROP TABLE br_nfe_event_old")

        conn.execute("CREATE INDEX IF NOT EXISTS idx_nfe_event_nfe ON br_nfe_event(nfe_out_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_nfe_event_tipo ON br_nfe_event(tipo_evento)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_nfe_event_status ON br_nfe_event(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_nfe_event_company ON br_nfe_event(company_id)")

        conn.execute("PRAGMA foreign_keys=ON")
        print("  ✓ br_nfe_event migrated: added manifestação subtypes to tipo_evento constraint")
    except Exception as e:
        try:
            conn.execute("PRAGMA foreign_keys=ON")
        except Exception:
            pass
        print(f"  ℹ br_nfe_event migration skipped: {e}")


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else None
    result = create_br_tables(db)
    print(f"{DISPLAY_NAME} schema created in {result['database']}")
    print(f"  Tables: {result['tables']}")
    print(f"  Status: {result['status']}")
