#!/usr/bin/env bash
# ===========================================================================
# ERPClaw Region BR — Instalação Rápida
# ===========================================================================
# Instala o módulo de localização brasileira em uma instância existente do ERPClaw.
#
# Uso:
#   bash install_br.sh
#
# Pré-requisitos:
#   - ERPClaw já instalado (clawhub install erpclaw)
#   - Python 3.10+
#   - pip install lxml cryptography requests (para NF-e, assinatura digital e SEFAZ)
# ===========================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ERPCLAW_SKILLS_DIR="${HOME}/.openclaw/workspace/skills"
MODULE_NAME="erpclaw-region-br"
MODULE_DIR="${ERPCLAW_SKILLS_DIR}/${MODULE_NAME}"

echo "╔══════════════════════════════════════════╗"
echo "║  ERPClaw Region BR — Instalação         ║"
echo "║  Localização Fiscal Brasileira          ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# STEP 1: Verificar ERPClaw
echo "📋 [1/5] Verificando ERPClaw..."
if [ ! -d "${HOME}/.openclaw/erpclaw/lib" ]; then
    echo "❌ ERPClaw não encontrado. Instale primeiro:"
    echo "   clawhub install erpclaw"
    exit 1
fi
echo "   ✅ ERPClaw encontrado"

# STEP 2: Instalar módulo
echo "📦 [2/5] Instalando módulo ${MODULE_NAME}..."
if [ -d "${MODULE_DIR}" ]; then
    echo "   ⚠️  Módulo já existe, atualizando..."
    cp -r "${SCRIPT_DIR}/"* "${MODULE_DIR}/"
else
    mkdir -p "${MODULE_DIR}"
    cp -r "${SCRIPT_DIR}/"* "${MODULE_DIR}/"
fi
echo "   ✅ Módulo copiado para ${MODULE_DIR}"

# STEP 3: Instalar dependências Python
echo "🐍 [3/5] Instalando dependências Python..."
if ! python3 -c "import lxml" 2>/dev/null; then
    echo "   Instalando lxml..."
    pip install lxml --quiet
fi
if ! python3 -c "import cryptography" 2>/dev/null; then
    echo "   Instalando cryptography..."
    pip install cryptography --quiet
fi
if ! python3 -c "import requests" 2>/dev/null; then
    echo "   Instalando requests..."
    pip install requests --quiet
fi
echo "   ✅ Dependências OK"

# STEP 4: Inicializar schema
echo "🗄️  [4/5] Inicializando tabelas fiscais..."
python3 "${MODULE_DIR}/init_db.py"
echo "   ✅ Schema criado"

# STEP 5: Adicionar ao registry
echo "📝 [5/5] Registrando módulo..."
python3 -c "
import json, os
registry_path = os.path.expanduser('${HOME}/.openclaw/workspace/skills/erpclaw/scripts/module_registry.json')
if os.path.exists(registry_path):
    with open(registry_path) as f:
        reg = json.load(f)
    if 'erpclaw-region-br' not in reg.get('modules', {}):
        reg['modules']['erpclaw-region-br'] = {
            'action_count': 119,
            'category': 'regional',
            'description': 'Brazilian full fiscal compliance: NF-e in/out, NFS-e, SPED EFD ICMS/IPI & Contribuições, DCTFWeb, REINF, ECD, ECF, REPETRO, ISS, DIFAL, Simples Nacional. 119 actions across 11 domains.',
            'repo': 'thiagoladeira/erpclaw-region-br',
            'source': 'https://github.com/thiagoladeira/erpclaw-region-br',
            'tags': ['brazil','nfe','nfse','sped','ecd','ecf','dctfweb','reinf','icms','pis','cofins','iss','ipi','repetro','simples-nacional','difal','lucro-real'],
            'install_type': 'git',
            'requires': ['erpclaw'],
            'version': '1.5.0'
        }
        with open(registry_path, 'w') as f:
            json.dump(reg, f, indent=2)
        print('   ✅ Módulo registrado')
    else:
        print('   ✅ Já registrado')
"
echo ""

echo "╔══════════════════════════════════════════╗"
echo "║  ✅ Instalação concluída!                ║"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "Próximos passos:"
echo ""
echo "  1. Configure a empresa:"
echo "     Diga: 'Configurar localização brasileira para <nome da empresa>'"
echo ""
echo "  2. Verifique o status:"
echo "     Diga: 'Qual o status da localização BR?'"
echo ""
echo "  3. Importe uma NF-e:"
echo "     Envie um arquivo XML e diga: 'Importar essa NF-e'"
echo ""
echo "  4. Gere o SPED:"
echo "     Diga: 'Gerar EFD ICMS/IPI de janeiro/2025'"
echo ""
