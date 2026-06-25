# 🇧🇷 ERPClaw Region BR — Localização Fiscal Brasileira

[![Version](https://img.shields.io/badge/version-1.5.0-blue)](https://github.com/thiagoladeira/erpclaw-region-br)
[![Actions](https://img.shields.io/badge/actions-119-brightgreen)](https://github.com/thiagoladeira/erpclaw-region-br)
[![License](https://img.shields.io/badge/license-GPL%20v3-red)](LICENSE.txt)

Módulo completo de compliance fiscal brasileiro para [ERPClaw](https://github.com/avansaber/erpclaw) — o ERP open-source AI-native.

**11 domínios · 119 ações · 18.000 linhas · Tudo rodando local no seu SQLite.**

---

## 📊 Cobertura Fiscal

```
██████████████████████████████████████████████████████████████████████████████████████████░ 95%
```

| Área | Status | Ações |
|------|--------|-------|
| 🟢 **NF-e Entrada** | Completo | 8 |
| 🟢 **NF-e Saída** | Completo | 16 |
| 🟢 **NFS-e** | Completo | 8 |
| 🟢 **NF-e Avançada** | Completo | 7 |
| 🟢 **Cadastros Fiscais** | Completo | 18 |
| 🟢 **Apuração Tributária** | Completo | 15 |
| 🟢 **DCTFWeb** | Completo | 3 |
| 🟢 **REINF** | Completo | 5 |
| 🟢 **ECD** | Completo | 7 |
| 🟢 **ECF** | Completo | 8 |
| 🟡 **SPED EFD ICMS/IPI** | 85% | 8 |
| 🟡 **SPED Contribuições** | 80% | 7 |
| 🟡 **Utilitários / REPETRO** | 75% | 9 |

---

## 🚀 Instalação Rápida

### Pré-requisitos
- ERPClaw ≥ 4.3.0 instalado (`clawhub install erpclaw`)
- Python 3.10+
- `pip install lxml cryptography requests`

### Instalação

```bash
# Via GitHub
git clone https://github.com/thiagoladeira/erpclaw-region-br.git \
  ~/.openclaw/workspace/skills/erpclaw-region-br

cd ~/.openclaw/workspace/skills/erpclaw-region-br
bash install_br.sh
```

Ou via module manager:
```bash
python3 ~/.openclaw/workspace/skills/erpclaw/scripts/module_manager.py \
  --action install-module --module-name erpclaw-region-br
```

### Configuração Inicial

```bash
# Verificar status
python3 scripts/db_query.py --action br-status --company-id <ID>

# Setup completo da localização BR
python3 scripts/db_query.py --action br-setup --company-id <ID>
```

---

## 📋 Domínios

### NF-e (Nota Fiscal Eletrônica) — 31 ações

| Ciclo | Ações | Descrição |
|-------|-------|-----------|
| **Entrada** | 8 | Parse XML, importar NF-e, validar XSD, DANFE, exportar |
| **Saída** | 16 | Configurar, criar, validar, assinar (A1), transmitir SEFAZ, cancelar, inutilizar, CC-e, consultar cadastro |
| **Avançada** | 7 | Manifestação destinatário, complementar, devolução, contingência, exportação, DANFE PDF |

### NFS-e (Nota Fiscal de Serviços) — 8 ações

Ciclo completo de RPS municipal — modelo ABRASF 2.02/2.03 compatível com a maioria dos municípios brasileiros (incluindo Macaé/RJ).

### Cadastros Fiscais — 18 ações

- `company_fiscal`: CNPJ, IE, IM, CNAE, CRT com validação
- `customer_fiscal`: CNPJ/CPF, IE, ISUF com validação
- `item_fiscal`: NCM, CEST, GTIN, CSTs, alíquotas, MVA
- CFOP, CST/CSOSN, NCM com seed de dados

### Apuração Tributária — 15 ações

Cálculo real de impostos inspecionando CST, CFOP, UF de cada operação:

| Tributo | Método |
|---------|--------|
| **ICMS** | Por UF e CST real — isento, suspenso, tributado; alíquota interestadual correta (7%/12%) |
| **ICMS-ST** | MVA por NCM + UF; base dupla; FECP-ST |
| **FECP** | Taxas reais por UF (RJ 4%, SP 2%, etc.) |
| **PIS/COFINS** | Diferencia CST não-cumulativo (01-08) e cumulativo (50-56); créditos |
| **DIFAL** | De NF-es interestaduais reais; split contribuinte/não-contribuinte |
| **Simples Nacional** | Anexos I/II/III; RBT12; alíquota efetiva; DAS |
| **IRPJ/CSLL** | Lucro Real (15%+10%) e Presumido (8%/32%) |
| **ISS** | Por município com detecção de CFOP de serviço |
| **Retenções** | IR 1,5%, PIS/COFINS/CSLL 4,65%, INSS 11% |
| **DARF** | Códigos Receita Federal oficiais |
| **GNRE** | Por UF destino para DIFAL e ICMS-ST |

### Obrigações Acessórias — 38 ações

| Obrigação | Periodicidade | Blocos |
|-----------|---------------|--------|
| **SPED EFD ICMS/IPI** | Mensal | 0, C, D, E, H, K |
| **SPED EFD Contribuições** | Mensal | 0, A, C, D, F, M, P |
| **DCTFWeb** | Mensal | Débitos PIS/COFINS/IRPJ/CSLL/IPI |
| **REINF** | Mensal | R-1000, R-2010, R-2020, R-2060 |
| **ECD** | Anual | 0, I, J, K, P, 9 |
| **ECF** | Anual | 0, C, J, K, M (e-Lalur), N (e-Lacs), P, T |

### Utilitários REPETRO — 9 ações

Regime aduaneiro especial para O&G: controle de DI, equipamentos, vencimentos, inventário.

---

## 🏗️ Arquitetura

```
erpclaw-region-br/
├── README.md
├── SKILL.md                  ← Documentação completa (119 ações)
├── init_db.py                ← Schema SQLite (20 tabelas fiscais)
├── install_br.sh             ← Script de instalação
├── assets/
│   └── charts/
│       └── br_gaap.json      ← Plano de contas brasileiro (225 contas)
└── scripts/
    ├── db_query.py           ← Roteador unificado (119 ações)
    ├── nfe_parser.py         ← Parser NF-e entrada (XML → ERP)
    ├── nfe_xml_gen.py        ← Gerador NF-e saída (layout 4.00)
    ├── nfe_signer.py         ← Assinador XMLDSig (certificado A1)
    ├── sefaz_ws.py           ← Cliente SOAP SEFAZ (27 UFs)
    ├── nfe_emission.py       ← Orquestrador emissão NF-e
    ├── nfe_avancada.py       ← NF-e avançada (manifestação, complementar...)
    ├── nfse.py               ← NFS-e municipal (ABRASF)
    ├── fiscal_data.py        ← Cadastros fiscais estruturados
    ├── fiscal_catalog.py     ← CFOP, CST, NCM
    ├── tax_calc_br.py        ← Cálculo real de impostos
    ├── sped_efd.py           ← EFD ICMS/IPI
    ├── sped_contrib.py       ← EFD Contribuições
    ├── dctfweb.py            ← DCTFWeb
    ├── reinf.py              ← REINF
    ├── ecd.py                ← ECD
    ├── ecf.py                ← ECF
    ├── setup_br.py           ← Setup + REPETRO
    └── tests/
        └── ...
```

---

## 🔒 Segurança

- **Local-first**: Tudo roda no seu SQLite, nada sai da sua máquina
- **Certificado A1**: Armazenado localmente, senha ofuscada
- **XMLs fiscais**: Nunca transmitidos externamente
- **GL imutável**: Todas as operações contábeis usam invariantes ERPClaw
- **user-confirmed**: Ações que alteram lançamentos exigem confirmação

---

## 🛢️ Caso de Uso: TechForge (O&G, Macaé/RJ)

O módulo foi desenvolvido e testado com dados mockados da TechForge Engenharia Ltda:

- **Regime**: Lucro Real
- **CNAE**: 7112-0/00 (Serviços de engenharia)
- **Mix fiscal**: Serviços (ISS 5%) + Mercadorias (ICMS 18% + IPI)
- **Clientes**: Petrobras, Halliburton, Ocyan, Equinor, MODEC
- **Itens**: Engenharia de perfuração, válvulas API, bombas hidráulicas, cabos umbilicais
- **REPETRO**: Controle de importação temporária O&G

---

## 📜 Licença

GNU General Public License v3.0 — veja [LICENSE.txt](LICENSE.txt).

Parte do ecossistema [ERPClaw](https://github.com/avansaber/erpclaw).

---

## 🐇 Autor

**Morpheus / Thiago Ladeira**

*"Estou tentando libertar sua mente. Mas só posso mostrar a porta. Você é quem precisa atravessá-la."*

---

<p align="center">
  <sub>Módulo construído com ERPClaw Foundation 4.x · Python 3.10+ · SQLite WAL</sub>
</p>
