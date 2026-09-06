#!/usr/bin/env bash
# kiro-esteira — aplica as 8 labels da esteira num repo (idempotente via --force).
# Uso: ./scripts/setup-labels.sh owner/repo [owner/repo ...]
set -u

if [ "$#" -lt 1 ]; then
  echo "uso: $0 owner/repo [owner/repo ...]" >&2
  exit 1
fi

# nome|cor(hex sem #)|descricao
LABELS=(
  "idea|FEF3C7|Ideia crua, nao especificada (so humano)"
  "needs-spec|FDE68A|Em especificacao/discussao (so humano)"
  "queued|FBBF24|Spec revisada, na fila aguardando liberacao (a esteira nao pega)"
  "ready|16A34A|Spec fechada, liberado - a esteira pode pegar"
  "crew: in progress|2563EB|Sessao implementando"
  "crew: needs-human|F97316|Travou, precisa de decisao humana"
  "hold|DC2626|Segura o auto-merge - humano poe quando quer revisar"
  "blocked|374151|Travado por dependencia"
)

for repo in "$@"; do
  echo "== $repo =="
  for entry in "${LABELS[@]}"; do
    IFS='|' read -r name color desc <<< "$entry"
    if gh label create "$name" --repo "$repo" --color "$color" --description "$desc" --force >/dev/null 2>&1; then
      echo "  ok: $name"
    else
      echo "  FALHOU: $name"
    fi
  done
done
echo "== done =="
