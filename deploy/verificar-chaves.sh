#!/usr/bin/env bash
# Guarda de segredos — roda ANTES do deploy e FALHA se a config está mentindo.
#
# Pega a CLASSE de erro, não um caso: o incidente de 2026-08-04 (Radar com 45 análises
# "score 0") veio de duas configs que pareciam certas e não eram —
#   (a) GROQ_KEY_1 == KEY_2 == KEY_3 em 2 deploys: o round-robin acha que soma 3x o teto
#       e na verdade bate na mesma cota (1/3 da capacidade que o código pensa ter);
#   (b) a MESMA chave servindo 6 serviços: o Radar consumia o TPD do atendimento.
# Nenhum valor de segredo é impresso — só o sha256 curto, que permite comparar sem expor.
#
# Uso:  bash deploy/verificar-chaves.sh [dir...]     (default: os .env conhecidos)
# Saída: 0 = ok | 1 = erro (bloqueia deploy) | avisos não bloqueiam.
set -uo pipefail

ERROS=0; AVISOS=0
sha() { printf '%s' "$1" | sha256sum | cut -c1-8; }
val() { grep -m1 -E "^$2=" "$1" 2>/dev/null | cut -d= -f2- | tr -d '"'"'"' \r'; }
erro()  { echo "  ❌ $*"; ERROS=$((ERROS+1)); }
aviso() { echo "  ⚠️  $*"; AVISOS=$((AVISOS+1)); }

ARQS=()
if [ $# -gt 0 ]; then
  for d in "$@"; do while IFS= read -r f; do ARQS+=("$f"); done < <(find "$d" -name '*.env' -not -path '*/node_modules/*' -not -path '*/.claude/*' 2>/dev/null); done
else
  while IFS= read -r f; do ARQS+=("$f"); done < <(
    find /root/sdr-motor /root/noemi-infra -name '*.env' \
         -not -path '*/node_modules/*' -not -path '*/.claude/*' 2>/dev/null)
fi
echo "🔑 verificando ${#ARQS[@]} arquivo(s) .env"
echo

# ── 1) pool de chaves FALSO (o bug 2.2): KEY_1/2/3 com o mesmo valor ──────────
echo "1) pool Groq: as KEY_1/2/3 são mesmo distintas?"
for f in "${ARQS[@]}"; do
  k1=$(val "$f" GROQ_KEY_1); k2=$(val "$f" GROQ_KEY_2); k3=$(val "$f" GROQ_KEY_3)
  [ -z "$k1$k2$k3" ] && continue
  n=0; declare -A vistos=()
  for k in "$k1" "$k2" "$k3"; do [ -n "$k" ] && { vistos["$(sha "$k")"]=1; n=$((n+1)); }; done
  if [ "$n" -gt 1 ] && [ "${#vistos[@]}" -lt "$n" ]; then
    erro "$(basename "$f"): $n slots de pool, só ${#vistos[@]} chave(s) distinta(s) — o round-robin NÃO multiplica a cota"
  fi
  unset vistos
done
[ "$ERROS" -eq 0 ] && echo "  ✅ nenhum pool falso"
echo

# ── 2) slot obrigatório vazio (a cascata cai calada) ──────────────────────────
echo "2) slots que, vazios, derrubam a cascata em silêncio:"
for f in "${ARQS[@]}"; do
  case "$f" in */noemi-infra/infra/.env)
    for v in GROQ_API_KEY; do
      [ -z "$(val "$f" "$v")" ] && erro "$(basename "$f"): $v vazia (o Radar/painel não analisa nada)"
    done
    [ -z "$(val "$f" GROQ_API_KEY_RESERVA)" ] && aviso "infra/.env: GROQ_API_KEY_RESERVA vazia — nível 2 da cascata inerte"
  ;; esac
done
echo

# ── 3) chave espalhada demais (o bug 2.1: Radar derruba o atendimento) ────────
echo "3) a mesma chave servindo serviços demais:"
TMP=$(mktemp)
for f in "${ARQS[@]}"; do
  while IFS= read -r ln; do
    case "$ln" in \#*|"") continue;; esac
    k=${ln%%=*}; v=${ln#*=}; v=$(printf '%s' "$v" | tr -d '"'"'"' \r')
    case "$k" in *KEY*|*TOKEN*|*SECRET*|*APIKEY*) [ -n "$v" ] && echo "$(sha "$v") $f" >> "$TMP";; esac
  done < "$f"
done
LIMITE=${MAX_ARQUIVOS_POR_CHAVE:-4}
while read -r n h; do
  [ "$n" -gt "$LIMITE" ] && aviso "sha:$h em $n arquivos (>$LIMITE) — um serviço pesado consome a cota do outro"
done < <(sort "$TMP" | uniq | awk '{print $1}' | sort | uniq -c | sort -rn)
rm -f "$TMP"
echo

echo "──────────────────────────────"
echo "erros: $ERROS · avisos: $AVISOS"
[ "$ERROS" -gt 0 ] && { echo "DEPLOY BLOQUEADO — corrija os ❌ acima."; exit 1; }
echo "OK pra deploy."
exit 0
