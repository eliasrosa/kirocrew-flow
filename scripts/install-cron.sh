#!/usr/bin/env bash
# KiroCrew Flow — instala os crons de scan no Kiro Crew.
#
# Uso: ./scripts/install-cron.sh
#
# O que faz:
#   1. Copia deployment/deployment.py (stub de compat) E a pasta
#      deployment/flow/ inteira para ~/.kiro/crew/crons/, preservando o
#      subpath deployment/flow/ que os crons por estágio referenciam
#      (ex: ~/.kiro/crew/crons/deployment/flow/dev.py:run)
#   2. Aplica o patch de sys.path em deployment/flow/base.py (a fonte comum)
#      para que TANTO o pacote top-level flow/ QUANTO o pacote irmão
#      deployment.flow sejam importáveis quando o cron roda da pasta aninhada
#   3. Copia deployment/deployment.config.yaml se não existir ainda
#
# Depois de instalar, registre os crons por estágio no Kiro Crew (uma vez cada) —
# ver exemplos de cron_add impressos no final.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CRONS_DIR="$HOME/.kiro/crew/crons"

echo "=== KiroCrew Flow — instalando crons ==="
echo "  repo:  $REPO_ROOT"
echo "  crons: $CRONS_DIR"

mkdir -p "$CRONS_DIR/deployment"

# 1. Copia o stub de compatibilidade e a pasta flow/ inteira
cp "$REPO_ROOT/deployment/deployment.py" "$CRONS_DIR/deployment/deployment.py"
rm -rf "$CRONS_DIR/deployment/flow"
cp -R "$REPO_ROOT/deployment/flow" "$CRONS_DIR/deployment/flow"
# Marca o diretório crons como pacote-namespace raiz do deployment: garante
# que "import deployment.flow.base" resolva a partir de $CRONS_DIR no sys.path.
echo "  ✅ deployment/deployment.py + deployment/flow/ copiados"

# 2. Aplica o patch de sys.path em deployment/flow/base.py
# O cron instalado roda de ~/.kiro/crew/crons/deployment/flow/<cron>.py, onde o
# _REPO_ROOT calculado (=.../crons) não contém o pacote top-level flow/.
# Injetamos o caminho real do repo (_FLOW_ROOT) antes, mantendo _REPO_ROOT
# (=.../crons) no path para que "deployment.flow.*" também resolva.
python3 - <<PYEOF
import os, sys

path = os.path.join(
    os.path.expanduser("~"), ".kiro/crew/crons/deployment/flow/base.py"
)
repo_root = "$REPO_ROOT"

with open(path) as f:
    content = f.read()

OLD = (
    "_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))     # .../deployment/flow\n"
    "_HERE = os.path.dirname(_MODULE_DIR)                          # .../deployment\n"
    "_REPO_ROOT = os.path.dirname(_HERE)                           # .../ (raiz do repo)\n"
    "if _REPO_ROOT not in sys.path:\n"
    "    sys.path.insert(0, _REPO_ROOT)"
)
NEW = f"""_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))     # .../deployment/flow
_HERE = os.path.dirname(_MODULE_DIR)                          # .../deployment
_REPO_ROOT = os.path.dirname(_HERE)                           # .../ (raiz do repo OU .../crons)
# Quando instalado em ~/.kiro/crew/crons/deployment/flow/, _REPO_ROOT aponta
# para ~/.kiro/crew/crons/ onde o pacote top-level flow/ não existe.
# Adicionamos o caminho real do repo (para "import flow.*") e mantemos
# _REPO_ROOT no path (para "import deployment.flow.*").
_FLOW_ROOT = "{repo_root}"
if _FLOW_ROOT not in sys.path:
    sys.path.insert(0, _FLOW_ROOT)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)"""

if "_FLOW_ROOT" in content:
    print("  ✅ patch sys.path já aplicado")
elif OLD in content:
    with open(path, "w") as f:
        f.write(content.replace(OLD, NEW))
    print("  ✅ patch sys.path aplicado em deployment/flow/base.py")
else:
    print("  ⚠️  padrão sys.path não encontrado em base.py — verifique manualmente")
    sys.exit(1)
PYEOF

# 3. Copia a config se não existir
CONFIG_SRC="$REPO_ROOT/deployment/deployment.config.yaml"
CONFIG_DST="$CRONS_DIR/deployment.config.yaml"
if [ -f "$CONFIG_DST" ]; then
    echo "  ℹ️  deployment.config.yaml já existe (não sobrescrito)"
elif [ -f "$CONFIG_SRC" ]; then
    cp "$CONFIG_SRC" "$CONFIG_DST"
    echo "  ✅ deployment.config.yaml copiado"
    echo "  ⚠️  Edite $CONFIG_DST:"
    echo "       squad_config: /caminho/absoluto/para/squads/minha-squad.yaml"
    echo "       notify_chat_id: <seu chat_id>"
    echo "       dev_root: /caminho/para/seus/clones"
else
    echo "  ℹ️  deployment.config.yaml de exemplo não encontrado no repo — pulei a cópia"
fi

# 4. Grava hash de versão para detecção de script desatualizado
# deployment.py verifica este arquivo no startup e avisa quando diverge do repo.
# O hash é do deployment/deployment.py do repo — a MESMA fonte que
# _check_installed_version compara em runtime.
VERSION_FILE="$CRONS_DIR/deployment.version"
python3 - <<PYEOF
import hashlib, json, os

repo_root = "$REPO_ROOT"
crons_dir = "$CRONS_DIR"

# Hash do deployment.py do REPO (antes do patch de sys.path) — fonte comparada
# por _check_installed_version(). Continua sendo deployment/deployment.py.
src = os.path.join(repo_root, "deployment", "deployment.py")
with open(src, "rb") as f:
    repo_hash = hashlib.sha256(f.read()).hexdigest()

version_info = {
    "repo_root": repo_root,
    "repo_deployment_sha256": repo_hash,
}

version_path = os.path.join(crons_dir, "deployment.version")
with open(version_path, "w") as f:
    json.dump(version_info, f, indent=2)

print(f"  ✅ deployment.version gravado (sha256: {repo_hash[:12]}...)")
PYEOF

echo ""
echo "=== Instalação completa ==="
echo ""
echo "  Registre os crons por estágio (recomendado), no dashboard do Kiro Crew:"
echo ""
echo "    # Cron dev — implementação (issues flow:develop-waiting)"
echo "    cron_add(name=\"flow-dev\","
echo "             script=\"~/.kiro/crew/crons/deployment/flow/dev.py:run\","
echo "             every=600)"
echo ""
echo "    # Cron reviewer — code review (issues flow:review-waiting)"
echo "    cron_add(name=\"flow-reviewer\","
echo "             script=\"~/.kiro/crew/crons/deployment/flow/reviewer.py:run\","
echo "             every=300)"
echo ""
echo "    # Cron merge — merge squash (flow:review-approved + flow:qa-approved)"
echo "    cron_add(name=\"flow-merge\","
echo "             script=\"~/.kiro/crew/crons/deployment/flow/merge.py:run\","
echo "             every=120)"
echo ""
echo "    # Cron conflito — resolução de conflito (flow:merge-conflict)"
echo "    cron_add(name=\"flow-conflito\","
echo "             script=\"~/.kiro/crew/crons/deployment/flow/conflict.py:run\","
echo "             every=300)"
echo ""
echo "    # Cron rework — gate humano pós-review (flow:review-refused, notifica TL)"
echo "    cron_add(name=\"flow-rework\","
echo "             script=\"~/.kiro/crew/crons/deployment/flow/rework.py:run\","
echo "             every=300)"
echo ""
echo "    # Cron qa-notify — aviso ao QA (flow:qa-waiting)"
echo "    cron_add(name=\"flow-qa-notify\","
echo "             script=\"~/.kiro/crew/crons/deployment/flow/qa_notify.py:run\","
echo "             every=300)"
echo ""
echo "    # Cron qa-refused — gate humano pós-QA (flow:qa-refused, notifica TL+dev)"
echo "    cron_add(name=\"flow-qa-refused\","
echo "             script=\"~/.kiro/crew/crons/deployment/flow/qa_refused.py:run\","
echo "             every=300)"
echo ""
echo "  Ou, para usar o cron monolítico legado (todos os estágios em sequência):"
echo "    cron_add(name=\"flow-scan\","
echo "             script=\"~/.kiro/crew/crons/deployment/flow/base.py:run\","
echo "             every=600)"
