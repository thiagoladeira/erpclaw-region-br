---
name: erpclaw-region-br
version: 1.7.0
description: >
  Brazilian tax compliance: ICMS/IPI/PIS/COFINS/ISS, NF-e inbound/outbound,
  NFS-e (service invoices), NF-e advanced (manifestação, complementar, devolução,
  contingência, exportação), CT-e (freight transport), Drawback/Exportação,
  DANFE PDF, SPED EFD ICMS/IPI, SPED EFD Contribuições, ECD, ECF, DIFAL,
  Simples Nacional, REPETRO, REINF, DCTFWeb, eSocial (labor/social security).
  149 actions across 14 domains.
author: Morpheus / Thiago Ladeira
source: https://github.com/avansaber/erpclaw-addons
tier: 3
category: regional
requires: [erpclaw]
database: ~/.openclaw/erpclaw/data.sqlite
user-invocable: true
tags: [brazil, brasil, icms, ipi, pis, cofins, iss, nfe, nf-e, sped, efd, ecd, ecf, difal, simples-nacional, repetro, reinf, dctfweb, esocial, xml, danfe, cfop, cst, csosn, ncm, lucro-real, lucro-presumido]
scripts:
  - scripts/db_query.py
  - scripts/nfe_xml_gen.py
  - scripts/nfe_signer.py
  - scripts/nfe_validator.py
  - scripts/sefaz_ws.py
  - scripts/nfe_emission.py
  - scripts/nfse.py
  - scripts/nfe_avancada.py
  - scripts/nfe_parser.py
  - scripts/fiscal_data.py
  - scripts/cte.py
  - scripts/drawback.py
  - scripts/sped_efd.py
  - scripts/sped_contrib.py
  - scripts/tax_calc_br.py
  - scripts/fiscal_catalog.py
  - scripts/setup_br.py
  - scripts/dctfweb.py
  - scripts/reinf.py
  - scripts/esocial.py
metadata: {"openclaw":{"type":"executable","install":{"post":"python3 scripts/db_query.py --action br-status"},"requires":{"bins":["python3"],"env":[],"optionalEnv":["ERPCLAW_DB_PATH"]},"os":["darwin","linux"]}}
---

# ERPClaw Region BR — Localização Fiscal Brasileira

Módulo de compliance fiscal brasileiro para ERPClaw. Implementa parsing de NF-e, geração de SPED,
apuração de tributos brasileiros (ICMS, IPI, PIS, COFINS, ISS), DIFAL, Simples Nacional,
CT-e, Drawback, REPETRO, XSD validation, e obrigações acessórias (EFD, ECD, ECF, REINF, DCTFWeb).

## Domínios e Ações

### NF-e (Nota Fiscal Eletrônica) — 8 ações
| Ação | Descrição |
|------|-----------|
| `parse-nfe-xml` | Parsear XML de NF-e de entrada e extrair dados fiscais |
| `import-nfe-entry` | Lançar NF-e de entrada (Stock Entry + GL + impostos) |
| `import-nfe-with-po` | Lançar NF-e de entrada vinculada a Purchase Order |
| `list-nfe-imports` | Listar histórico de NF-es importadas |
| `get-nfe-import` | Detalhar uma NF-e importada |
| `validate-nfe-xml` | Validar XML contra schema XSD da SEFAZ |
| `generate-danfe` | Gerar DANFE (PDF) a partir do XML |
| `export-nfe-data` | Exportar dados da NF-e para formato contábil |

### NF-e Emissão (Saída) — 17 ações
| Ação | Descrição |
|------|-----------|
| `configure-nfe` | Configurar emissão de NF-e para uma empresa |
| `get-nfe-config` | Consultar configuração de emissão de NF-e |
| `create-nfe-out` | Criar NF-e de saída a partir de uma fatura de venda |
| `validate-nfe-out` | Validar XML da NF-e contra estrutura SEFAZ + XSD schema |
| `sign-nfe-xml` | Assinar digitalmente o XML da NF-e (certificado A1) |
| `transmit-nfe` | Enviar NF-e assinada para autorização na SEFAZ |
| `check-nfe-status` | Consultar status de autorização na SEFAZ |
| `list-nfe-out` | Listar NF-es de saída emitidas |
| `get-nfe-out` | Detalhar uma NF-e de saída (com itens e eventos) |
| `cancel-nfe` | Cancelar uma NF-e autorizada (evento de cancelamento) |
| `inutilizar-numeracao` | Inutilizar faixa de numeração na SEFAZ |
| `generate-carta-correcao` | Emitir Carta de Correção Eletrônica (CC-e) |
| `consultar-cadastro` | Consultar cadastro de contribuinte na SEFAZ (IE) |
| `sefaz-status-servico` | Verificar status dos serviços SEFAZ |
| `generate-danfe-out` | Gerar DANFE para NF-e de saída |
| `export-nfe-out-xml` | Exportar XML autorizado da NF-e |

### NFS-e (Nota Fiscal de Serviços Eletrônica) — 8 ações

Municipal service tax invoice (ISS). Follows ABRASF national model (2.02/2.03)
compatible with most Brazilian municipalities. Targets Macaé/RJ with ISS 5% by default.

| Ação | Descrição |
|------|-----------|
| `configure-nfse` | Configurar NFS-e por empresa (município, alíquota ISS, regime) |
| `create-nfse` | Gerar NFS-e a partir de uma fatura de venda (serviços) |
| `sign-nfse-xml` | Assinar digitalmente o XML da NFS-e (certificado A1) |
| `transmit-nfse` | Enviar NFS-e para autorização no webservice municipal |
| `check-nfse-status` | Consultar status de autorização da NFS-e |
| `cancel-nfse` | Cancelar uma NFS-e autorizada |
| `list-nfse` | Listar notas fiscais de serviço emitidas |
| `get-nfse` | Detalhar uma NFS-e específica |

### NF-e Avançada — 7 ações

Advanced NF-e features: Manifestação do Destinatário, download XML from SEFAZ,
complementary/supplementary NF-e, devolução, contingência (offline), exportação (DI/RE),
and DANFE PDF generation.

| Ação | Descrição |
|------|-----------|
| `manifestar-nfe` | Enviar Manifestação do Destinatário (confirmação, ciência, desconhecimento, oper. realizada) |
| `download-nfe-xml` | Baixar XML da NF-e da SEFAZ (Distribuição DFe) |
| `create-nfe-complementar` | Criar NF-e complementar (ajuste de valores) |
| `create-nfe-devolucao` | Criar NF-e de devolução (CFOP de devolução) |
| `create-nfe-contingencia` | Criar NF-e em contingência offline (tpEmis=9) |
| `gerar-xml-nfe-exportacao` | Gerar NF-e para exportação (com DI/RE Drawback) |
| `imprimir-danfe-pdf` | Gerar DANFE como PDF (weasyprint, reportlab, ou HTML fallback) |

### CT-e (Conhecimento de Transporte Eletrônico) — 8 ações

Electronic freight transport document for companies that transport goods.
Covers the complete CT-e lifecycle from configuration to cancellation.
Reuses the same A1 certificate infrastructure as NF-e for XMLDSig signing.

| Ação | Descrição |
|------|-----------|
| `configure-cte` | Configurar emissão de CT-e por empresa (UF, certificado, ambiente) |
| `create-cte` | Gerar CT-e a partir de delivery notes ou dados manuais |
| `sign-cte-xml` | Assinar digitalmente o XML do CT-e (certificado A1) |
| `transmit-cte` | Enviar CT-e para autorização na SEFAZ |
| `check-cte-status` | Consultar status de autorização do CT-e |
| `cancel-cte` | Cancelar um CT-e autorizado |
| `list-cte` | Listar CT-es com filtros (empresa, data, destinatário) |
| `get-cte` | Detalhar um CT-e específico |

### Drawback / Exportação — 5 ações

Drawback regime management: suspension/exemption of federal taxes on imports
used to manufacture products for export. Also generates NF-e for export
with DI/RE/Drawback references.

| Ação | Descrição |
|------|-----------|
| `configure-drawback` | Registrar Ato Concessório de Drawback (modalidade, valor, vencimento) |
| `import-drawback-nfe` | Vincular NF-e de importação a um ato de Drawback |
| `generate-drawback-report` | Relatório de utilização de Drawback por ato/período |
| `list-drawback-acts` | Listar atos de Drawback com filtros |
| `create-nfe-exportacao` | Gerar NF-e para exportação (com DI/RE, Drawback) |

### Validação XSD — 1 ação

Real XSD schema validation for NF-e XML against official SEFAZ schema
(procNFe_v4.00.xsd). Downloads and caches the schema on first use.

| Ação | Descrição |
|------|-----------|
| `validate-nfe-xsd` | Validar XML de NF-e contra schema XSD oficial da SEFAZ |

### Cadastros Fiscais Estruturados — 10 ações

Tabelas estruturadas para dados fiscais brasileiros, substituindo `custom_field_value`
por tabelas com validação, constraints e integridade referencial.

| Ação | Descrição |
|------|-----------|
| `add-company-fiscal` | Cadastrar dados fiscais da empresa (CNPJ, IE, IM, CNAE, CRT) |
| `get-company-fiscal` | Consultar dados fiscais da empresa |
| `list-company-fiscal` | Listar empresas com dados fiscais cadastrados |
| `add-customer-fiscal` | Cadastrar dados fiscais do cliente (CNPJ/CPF, IE, IM, ISUF) |
| `get-customer-fiscal` | Consultar dados fiscais do cliente |
| `list-customer-fiscal` | Listar clientes com dados fiscais (filtro por UF/empresa) |
| `add-item-fiscal` | Cadastrar classificação fiscal do item (NCM, CEST, CFOP, CST, alíquotas) |
| `get-item-fiscal` | Consultar classificação fiscal do item |
| `list-item-fiscal` | Listar itens com classificação fiscal (filtro por NCM/empresa) |
| `migrate-fiscal-data` | Migrar dados de custom_field_value para tabelas estruturadas |

### SPED Fiscal (EFD ICMS/IPI) — 8 ações
| Ação | Descrição |
|------|-----------|
| `generate-efd-icms-ipi` | Gerar EFD ICMS/IPI completo (Blocos 0, C, D, E, H, K) |
| `generate-bloco-0` | Gerar Bloco 0 (Abertura, Identificação, Participantes) |
| `generate-bloco-c` | Gerar Bloco C (Documentos Fiscais - Mercadorias) |
| `generate-bloco-d` | Gerar Bloco D (Documentos de Transporte — CT-e, CF-e) |
| `generate-bloco-e` | Gerar Bloco E (Apuração ICMS/IPI — Débito/Crédito/ST) |
| `generate-bloco-h` | Gerar Bloco H (Inventário Físico) |
| `generate-bloco-k` | Gerar Bloco K (Controle da Produção e do Estoque — completo) |
| `validate-efd` | Validar arquivo EFD contra layout SEFAZ |

### SPED Contribuições (EFD Contribuições) — 7 ações
| Ação | Descrição |
|------|-----------|
| `generate-efd-contrib` | Gerar EFD Contribuições completo (Blocos 0, A, C, D, F, M, P) |
| `generate-bloco-a` | Gerar Bloco A (Documentos Fiscais — Serviços) |
| `generate-bloco-c-contrib` | Gerar Bloco C (Documentos Fiscais — Mercadorias — PIS/COFINS) |
| `generate-bloco-d-contrib` | Gerar Bloco D (Aquisição de Serviços de Transporte) |
| `generate-bloco-f-contrib` | Gerar Bloco F (Outras Operações e CST Consolidado) |
| `generate-bloco-m` | Gerar Bloco M (Apuração PIS/COFINS com créditos) |
| `generate-bloco-p` | Gerar Bloco P (Apuração por Regime Tributário) |

### ECD (Escrituração Contábil Digital) — 8 ações
| Ação | Descrição |
|------|-----------|
| `generate-ecd` | Gerar ECD completo (Blocos 0, I, J, K, 9) |
| `generate-ecd-bloco-0` | Gerar Bloco 0 (Abertura, Identificação, Participantes) |
| `generate-ecd-bloco-i` | Gerar Bloco I (Lançamentos Contábeis a partir do gl_entry) |
| `generate-ecd-bloco-j` | Gerar Bloco J (Plano de Contas e Balancetes) |
| `generate-ecd-bloco-k` | Gerar Bloco K (Demonstrações Contábeis: BP e DRE) |
| `validate-ecd` | Validar arquivo ECD contra regras básicas |
| `list-ecd-exports` | Listar histórico de exportações ECD |
| `sign-ecd` | Assinar digitalmente arquivo ECD (certificado A1, RSA-SHA256) |

### ECF (Escrituração Contábil Fiscal) — 9 ações
| Ação | Descrição |
|------|-----------|
| `generate-ecf` | Gerar ECF completo (todos os blocos fiscais) |
| `generate-ecf-bloco-0` | Gerar Bloco 0 (Abertura e Identificação do Contribuinte) |
| `generate-ecf-bloco-m` | Gerar Bloco M — E-Lalur (Apuração do Lucro Real — IRPJ) |
| `generate-ecf-bloco-n` | Gerar Bloco N — E-Lacs (Apuração da CSLL) |
| `generate-ecf-bloco-p` | Gerar Bloco P (Demonstrações Contábeis Fiscais) |
| `generate-ecf-bloco-t` | Gerar Bloco T (Distribuição de Lucros) |
| `validate-ecf` | Validar arquivo ECF contra regras básicas |
| `list-ecf-exports` | Listar histórico de exportações ECF |
| `sign-ecf` | Assinar digitalmente arquivo ECF (certificado A1, RSA-SHA256) |

### Apuração Tributária BR — 15 ações
| Ação | Descrição |
|------|-----------|
| `calculate-icms` | Apurar ICMS (débito x crédito) por UF/CST/CFOP |
| `calculate-icms-st` | Apurar ICMS Substituição Tributária com MVA por UF/NCM |
| `calculate-fecp` | Calcular FECP (Fundo de Combate à Pobreza) por UF |
| `calculate-pis-cofins` | Apurar PIS/COFINS com análise CST (não-cumulativo/cumulativo) |
| `calculate-difal` | Calcular DIFAL interestadual a partir de dados reais |
| `calculate-simples-nacional` | Calcular DAS com tabelas progressivas Anexos I/II/III |
| `calculate-irpj-csll` | Apurar IRPJ/CSLL (Lucro Real ou Presumido) |
| `calculate-ciap` | Controlar CIAP (1/48 avos ICMS Ativo Permanente) |
| `calculate-iss` | Apurar ISS municipal por código de município |
| `calculate-withholding` | Calcular retenções na fonte (IR/PIS/COFINS/CSLL/INSS/ISS) |
| `reconcile-tax-accounts` | Conciliar contas de impostos com GL |
| `generate-darf` | Gerar guia DARF com códigos de receita |
| `generate-gnre` | Gerar GNRE (ICMS interestadual + DIFAL) |
| `list-tax-periods` | Listar períodos de apuração |
| `close-tax-period` | Fechar período de apuração fiscal |

### Cadastros Fiscais — 8 ações
| Ação | Descrição |
|------|-----------|
| `add-cfop` | Cadastrar CFOP (Código Fiscal de Operações) |
| `list-cfops` | Listar CFOPs cadastrados |
| `add-cst` | Cadastrar CST/CSOSN por item |
| `list-csts` | Listar CSTs cadastrados |
| `add-ncm` | Vincular NCM a um item |
| `list-ncms` | Listar NCMs cadastrados |
| `set-item-fiscal-data` | Configurar dados fiscais completos de um item |
| `get-item-fiscal-data` | Consultar dados fiscais de um item |

### DCTFWeb — 3 ações
| Ação | Descrição |
|------|-----------|
| `calculate-dctf-debts` | Calcular débitos federais (PIS, COFINS, IRPJ, CSLL, IPI, INSS) |
| `generate-dctf` | Gerar declaração DCTFWeb (layout RFB) |
| `list-dctf-periods` | Listar períodos de DCTF gerados |

### REINF (Retenções na Fonte) — 5 ações
| Ação | Descrição |
|------|-----------|
| `generate-reinf` | Gerar REINF completo (todos os eventos) |
| `generate-reinf-r1000` | Gerar evento R-1000 (Informações do Contribuinte) |
| `generate-reinf-r2010` | Gerar evento R-2010 (Serviços Tomados com Retenção) |
| `generate-reinf-r2020` | Gerar evento R-2020 (Serviços Prestados com Retenção) |
| `generate-reinf-r2060` | Gerar evento R-2060 (INSS Retido — 11%) |

### eSocial (Escrituração Fiscal Digital Trabalhista) — 14 ações

Brazilian unified labor, social security, and tax digital bookkeeping (SPED Trabalhista).
Replaces GFIP, RAIS, CAGED, SEFIP. XML events sent to eSocial webservice.

| Ação | Descrição |
|------|-----------|
| `configure-esocial` | Configurar eSocial para uma empresa (CNPJ, periodicidade, ambiente) |
| `get-esocial-config` | Consultar configuração eSocial |
| `generate-s1000` | Gerar evento S-1000 (Informações do Empregador — classificação tributária, FPAS) |
| `generate-s1005` | Gerar evento S-1005 (Tabela de Estabelecimentos — CNAE, RAT, FAP) |
| `generate-s1010` | Gerar evento S-1010 (Tabela de Rubricas — verbas da folha, INSS, IRRF, FGTS) |
| `generate-s1020` | Gerar evento S-1020 (Tabela de Horários/Jornadas — carga diária/semanal) |
| `generate-s2200` | Gerar evento S-2200 (Admissão do Trabalhador — CPF, salário, contrato, FGTS) |
| `generate-s2205` | Gerar evento S-2205 (Alteração de Dados Cadastrais — salário, cargo) |
| `generate-s2299` | Gerar evento S-2299 (Desligamento — verbas rescisórias, aviso prévio) |
| `generate-s2230` | Gerar evento S-2230 (Afastamento Temporário — doença, maternidade) |
| `generate-s1200` | Gerar evento S-1200 (Remuneração Mensal — folha de pagamento por trabalhador) |
| `generate-s1299` | Gerar evento S-1299 (Fechamento da Folha — totais INSS/FGTS do período) |
| `generate-esocial-events` | Gerar todos os eventos periódicos do mês (S-1200 + S-1299) |
| `list-esocial-exports` | Listar histórico de eventos eSocial gerados |

### Utilitários — 13 ações
| Ação | Descrição |
|------|-----------|
| `br-status` | Status do módulo de localização BR |
| `br-setup` | Configurar localização BR (COA + tax templates + defaults) |
| `sync-coa-br` | Sincronizar plano de contas BR com template |
| `list-tax-templates-br` | Listar templates fiscais brasileiros |
| `configure-repetro` | Configurar regime REPETRO (registrar DI) |
| `repetro-status` | Verificar status REPETRO (DIs, vencimentos, equipamentos) |
| `register-repetro-equipment` | Registrar equipamento sob regime REPETRO |
| `repetro-expiry-report` | Relatório de DIs REPETRO próximas do vencimento |
| `repetro-inventory` | Inventário de equipamentos sob regime REPETRO |
| `sign-ecd` | Assinar digitalmente arquivo ECD (certificado A1, RSA-SHA256) |
| `sign-ecf` | Assinar digitalmente arquivo ECF (certificado A1, RSA-SHA256) |

### Testes Automatizados

Suite de testes unitários com pytest e SQLite em memória cobrindo:
- Validação de CNPJ/CPF (`_valida_cnpj`, `_valida_cpf`)
- CRUD de dados fiscais (company_fiscal, customer_fiscal)
- Geração de chave de acesso NF-e (`_compute_chave_acesso`, `_clean_cnpj`)
- Catálogos fiscais (CFOP, CST, NCM)
- Cálculos tributários (ICMS, PIS/COFINS, DIFAL, Simples Nacional)

Para executar:
```bash
cd scripts && python3 -m pytest tests/ -v
```

**Total: 149 ações**

## Segurança

- Local-first como toda a fundação ERPClaw
- XMLs não são transmitidos externamente
- Dados fiscais sensíveis armazenados no SQLite local
- Todas as operações de GL usam `erpclaw_lib.gl_posting` com invariantes
- `--user-confirmed` exigido para ações que alteram lançamentos contábeis

## Dependências

- `erpclaw` (fundação) >= 4.3.0
- Python 3.10+
- `lxml` (para parsing de XML NF-e)
- `xmlschema` (opcional, para validação XSD)
- `reportlab` (opcional, para geração de DANFE)
- `cryptography` (para assinatura digital de XML NF-e)

## Instalação

```bash
python3 ~/.openclaw/workspace/skills/erpclaw/scripts/module_manager.py \
  --action install-module --module-name erpclaw-region-br
```

Ou peça naturalmente: "Instalar módulo de localização brasileira"

## Estrutura de Arquivos

```
erpclaw-region-br/
├── SKILL.md              ← Este arquivo
├── init_db.py            ← Schema de tabelas fiscais BR (32 tabelas: nfe, nfse, nfse_config, cfop, cst, ncm, tax_period, tax_apuration, sped_log, difal, nfe_out, company_fiscal, customer_fiscal, item_fiscal, mva_st_config, fecp_config, iss_config, withholding_config, repetro_di, repetro_equipment, cte_config, cte, drawback_act, drawback_import, esocial_config, esocial_event)
├── assets/
│   └── charts/
│       └── br_gaap.json  ← Plano de contas brasileiro (225 contas)
└── scripts/
    ├── db_query.py       ← Roteador de ações
    ├── nfe_parser.py     ← Parser de XML NF-e (entrada)
    ├── nfe_xml_gen.py    ← Gerador de XML NF-e (Layout 4.00)
    ├── nfe_signer.py     ← Assinador digital XMLDSig (A1)
    ├── sefaz_ws.py       ← Cliente SOAP SEFAZ WebServices
    ├── nfe_emission.py   ← Orquestrador de emissão NF-e (17 ações + DANFE PDF)
    ├── nfse.py           ← NFS-e: ABRASF RPS, municipal ISS (8 ações)
    ├── nfe_avancada.py   ← NF-e Avançada: manifestação, download, compl., devol., cont., exp., DANFE PDF (7 ações)
    ├── nfe_validator.py  ← Validação XSD real contra schema oficial da SEFAZ (1 ação)
    ├── cte.py            ← CT-e: Conhecimento de Transporte Eletrônico (8 ações)
    ├── drawback.py       ← Drawback/Exportação: Ato Concessório, importações, relatórios (5 ações)
    ├── fiscal_data.py    ← Dados fiscais estruturados (10 ações)
    ├── sped_efd.py       ← Gerador EFD ICMS/IPI (Bloco K completo)
    ├── sped_contrib.py   ← Gerador EFD Contribuições
    ├── ecd.py            ← Gerador ECD (Escrituração Contábil Digital)
    ├── ecf.py            ← Gerador ECF (Escrituração Contábil Fiscal)
    ├── tax_calc_br.py    ← Cálculos tributários BR
    ├── fiscal_catalog.py ← CFOP, CST, NCM
    ├── setup_br.py       ← Configuração inicial BR + REPETRO
    ├── dctfweb.py        ← DCTFWeb (débitos federais)
    ├── reinf.py          ← REINF (retenções na fonte)
    ├── esocial.py        ← eSocial (labor/social security — 14 ações)
    └── tests/
        ├── conftest.py         ← Fixtures pytest (DB em memória, company_fiscal)
        ├── test_fiscal_data.py ← Testes de validação CNPJ/CPF e CRUD fiscal
        ├── test_fiscal_catalog.py ← Testes de CFOP, CST, NCM
        ├── test_tax_calc.py    ← Testes de cálculos tributários (ICMS, DIFAL, Simples)
        └── test_nfe_xml.py     ← Testes de geração de chave de acesso NF-e
```
