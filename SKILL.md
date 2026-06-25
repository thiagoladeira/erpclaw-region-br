---
name: erpclaw-region-br
version: 1.3.0
description: >
  Brazilian tax compliance: ICMS/IPI/PIS/COFINS/ISS, NF-e inbound/outbound, SPED EFD ICMS/IPI,
  SPED EFD Contribuições, ECD, ECF, DIFAL, Simples Nacional, REPETRO, REINF, DCTFWeb.
  83 actions across 9 domains.
author: Morpheus / Thiago Ladeira
source: https://github.com/avansaber/erpclaw-addons
tier: 3
category: regional
requires: [erpclaw]
database: ~/.openclaw/erpclaw/data.sqlite
user-invocable: true
tags: [brazil, brasil, icms, ipi, pis, cofins, iss, nfe, nf-e, sped, efd, ecd, ecf, difal, simples-nacional, repetro, reinf, dctfweb, xml, danfe, cfop, cst, csosn, ncm, lucro-real, lucro-presumido]
scripts:
  - scripts/db_query.py
  - scripts/nfe_xml_gen.py
  - scripts/nfe_signer.py
  - scripts/sefaz_ws.py
  - scripts/nfe_emission.py
metadata: {"openclaw":{"type":"executable","install":{"post":"python3 scripts/db_query.py --action br-status"},"requires":{"bins":["python3"],"env":[],"optionalEnv":["ERPCLAW_DB_PATH"]},"os":["darwin","linux"]}}
---

# ERPClaw Region BR — Localização Fiscal Brasileira

Módulo de compliance fiscal brasileiro para ERPClaw. Implementa parsing de NF-e, geração de SPED,
apuração de tributos brasileiros (ICMS, IPI, PIS, COFINS, ISS), DIFAL, Simples Nacional,
REPETRO, e obrigações acessórias (EFD, ECD, ECF, REINF, DCTFWeb).

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
| `validate-nfe-out` | Validar XML da NF-e contra estrutura SEFAZ |
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
| `generate-bloco-k` | Gerar Bloco K (Controle da Produção e do Estoque) |
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

### Apuração Tributária BR — 12 ações
| Ação | Descrição |
|------|-----------|
| `calculate-icms` | Apurar ICMS (débito x crédito) por UF e período |
| `calculate-icms-st` | Apurar ICMS Substituição Tributária |
| `calculate-pis-cofins` | Apurar PIS/COFINS (não-cumulativo) |
| `calculate-difal` | Calcular DIFAL interestadual |
| `calculate-simples-nacional` | Calcular DAS do Simples Nacional |
| `calculate-irpj-csll` | Apurar IRPJ/CSLL (Lucro Real ou Presumido) |
| `calculate-ciap` | Controlar CIAP (1/48 avos ICMS Ativo Permanente) |
| `reconcile-tax-accounts` | Conciliar contas de impostos com apuração |
| `generate-darf` | Gerar guia de recolhimento (valores) |
| `generate-gnre` | Gerar GNRE (ICMS interestadual) |
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

### Utilitários — 6 ações
| Ação | Descrição |
|------|-----------|
| `br-status` | Status do módulo de localização BR |
| `br-setup` | Configurar localização BR (COA + tax templates + defaults) |
| `sync-coa-br` | Sincronizar plano de contas BR com template |
| `list-tax-templates-br` | Listar templates fiscais brasileiros |
| `configure-repetro` | Configurar regime REPETRO |
| `repetro-status` | Verificar status REPETRO (DI, vencimentos) |

**Total: 83 ações**

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
├── init_db.py            ← Schema de tabelas fiscais BR
├── assets/
│   └── charts/
│       └── br_gaap.json  ← Plano de contas brasileiro (225 contas)
└── scripts/
    ├── db_query.py       ← Roteador de ações
    ├── nfe_parser.py     ← Parser de XML NF-e (entrada)
    ├── nfe_xml_gen.py    ← Gerador de XML NF-e (Layout 4.00)
    ├── nfe_signer.py     ← Assinador digital XMLDSig (A1)
    ├── sefaz_ws.py       ← Cliente SOAP SEFAZ WebServices
    ├── nfe_emission.py   ← Orquestrador de emissão NF-e (17 ações)
    ├── fiscal_data.py    ← Dados fiscais estruturados (10 ações)
    ├── sped_efd.py       ← Gerador EFD ICMS/IPI
    ├── sped_contrib.py   ← Gerador EFD Contribuições
    ├── tax_calc_br.py    ← Cálculos tributários BR
    ├── fiscal_catalog.py ← CFOP, CST, NCM
    ├── setup_br.py       ← Configuração inicial BR
    └── tests/
        ├── conftest.py
        └── test_nfe.py
```
