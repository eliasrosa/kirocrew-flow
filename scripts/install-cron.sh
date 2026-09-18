#!/usr/bin/env bash
# KiroCrew Flow — instala o cron de scan no Kiro Crew.
#
# Uso: ./scripts/install-cron.sh
#
# O que faz:
#   1. Copia deployment/deployment.py para ~/.kiro/crew/crons/
#   2. Aplica o patch de sys.path para que flow/ seja importável
#      (o script é executado de ~/.kiro/crew/crons/, não do repo)
#   3. Copia deployment/deployment.config.yaml se não existir ainda
#
# Depois de instalar, o script imprime as instruções de cron_add:
#   - Sem bloco `stages:` na config → uma cron monolítica crewflow-scan → run.
#   - Com bloco `stages:` → N crons, uma por estágio (crewflow-dev/reviewer/
#     merge/conflito → deployment.py:run_<stage>), cada uma com seu interval.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CRONS_DIR="$HOME/.kiro/crew/crons"

echo "=== KiroCrew Flow — instalando cron ==="
echo "  repo:  $REPO_ROOT"
echo "  crons: $CRONS_DIR"

mkdir -p "$CRONS_DIR"

# 1. Copia o script
cp "$REPO_ROOT/deployment/deployment.py" "$CRONS_DIR/deployment.py"
echo "  ✅ deployment.py copiado"

# 2. Aplica o patch de sys.path
# O script instalado roda de ~/.kiro/crew/crons/ onde flow/ não existe.
# Precisamos injetar o caminho real do repo no sys.path.
python3 - <<PYEOF
import os, sys

path = os.path.join(os.path.expanduser("~"), ".kiro/crew/crons/deployment.py")
repo_root = "$REPO_ROOT"

with open(path) as f:
    content = f.read()

OLD = "_REPO_ROOT = os.path.dirname(_HERE)\nif _REPO_ROOT not in sys.path:\n    sys.path.insert(0, _REPO_ROOT)"
NEW = f"""_REPO_ROOT = os.path.dirname(_HERE)
# Quando instalado em ~/.kiro/crew/crons/, _REPO_ROOT aponta para ~/.kiro/crew/
# onde flow/ não existe. Adicionamos o caminho real do repo:
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
    print("  ✅ patch sys.path aplicado")
else:
    print("  ⚠️  padrão sys.path não encontrado — verifique manualmente")
    sys.exit(1)
PYEOF

# 3. Copia a config se não existir
CONFIG_SRC="$REPO_ROOT/deployment/deployment.config.yaml"
CONFIG_DST="$CRONS_DIR/deployment.config.yaml"
if [ -f "$CONFIG_DST" ]; then
    echo "  ℹ️  deployment.config.yaml já existe (não sobrescrito)"
else
    cp "$CONFIG_SRC" "$CONFIG_DST"
    echo "  ✅ deployment.config.yaml copiado"
    echo "  ⚠️  Edite $CONFIG_DST:"
    echo "       squad_config: /caminho/absoluto/para/squads/minha-squad.yaml"
    echo "       notify_chat_id: <seu chat_id>"
    echo "       dev_root: /caminho/para/seus/clones"
fi

# 4. Gera as instruções de cron_add:
#    - Se a config define um bloco `stages:`, gera N crons (uma por estágio),
#      cada uma apontando para o entrypoint deployment.py:run_<stage> com o
#      interval configurado (ou o default por estágio).
#    - Caso contrário, mantém a única cron monolítica crewflow-scan → run.
echo ""
echo "=== Instalação completa ==="
echo ""
python3 - "$CONFIG_DST" <<'PYEOF'
import sys, os, re

config_path = sys.argv[1]

# Defaults de interval por estágio (segundos). reviewer varre mais rápido.
DEFAULTS = {"dev": 600, "reviewer": 180, "merge": 300, "conflito": 900}
STAGES = ("dev", "reviewer", "merge", "conflito")

stages_cfg = {}
try:
    try:
        import yaml  # type: ignore
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}
        raw = data.get("stages")
        if isinstance(raw, dict):
            stages_cfg = raw
    except ImportError:
        # Fallback sem PyYAML: detecta um bloco `stages:` de forma simples e
        # extrai os nomes de estágio conhecidos e seus `interval:`.
        with open(config_path) as f:
            lines = f.readlines()
        in_stages = False
        current = None
        for line in lines:
            if re.match(r"^stages:\s*$", line):
                in_stages = True
                continue
            if in_stages:
                # Fim do bloco: primeira linha não-indentada não-vazia/coment.
                if line.strip() and not line.startswith((" ", "\t")) and not line.lstrip().startswith("#"):
                    break
                m = re.match(r"^\s{2}(\w+):\s*$", line)
                if m and m.group(1) in STAGES:
                    current = m.group(1)
                    stages_cfg.setdefault(current, {})
                    continue
                mi = re.match(r"^\s{4}interval:\s*(\d+)", line)
                if mi and current:
                    stages_cfg[current]["interval"] = int(mi.group(1))
except Exception as exc:
    print(f"  ⚠️  não foi possível ler {config_path} ({exc}) — usando modo monolítico")
    stages_cfg = {}

configured = [s for s in STAGES if s in stages_cfg]

if configured:
    print("  Cron por estágio detectado. Registre N crons (uma por estágio),")
    print("  no dashboard do Kiro Crew:")
    print("")
    for stage in configured:
        entry = stages_cfg.get(stage) or {}
        interval = entry.get("interval") or DEFAULTS[stage]
        print(f'    cron_add(name="crewflow-{stage}",')
        print(f'             script="~/.kiro/crew/crons/deployment.py:run_{stage}",')
        print(f'             every={interval})')
        print("")
else:
    print("  Nenhum bloco `stages:` na config — modo monolítico (cron única).")
    print("  Para registrar o cron (uma vez), no dashboard do Kiro Crew:")
    print("")
    print('    cron_add(name="crewflow-scan",')
    print('             script="~/.kiro/crew/crons/deployment.py:run",')
    print('             every=600)')
PYEOF
