#!/usr/bin/env bash
# Retenção do Evolution — remove mensagens antigas pra o Message não crescer sem limite.
# SEGURANÇA: DRY-RUN por padrão. Só apaga com APPLY=1. NUNCA roda DELETE sozinho no cron.
set -euo pipefail
DAYS="${RETENTION_DAYS:-90}"
C="${EVO_PG_CONTAINER:-evolution_postgres}"; U="${EVO_PG_USER:-evolution}"; DB="${EVO_PG_DB:-evolution}"
CUT=$(( $(date +%s) - DAYS*86400 ))   # unix seconds
q(){ docker exec "$C" psql -U "$U" -d "$DB" -tA -c "$1"; }
echo "== Retenção Evolution (> ${DAYS} dias · corte messageTimestamp < ${CUT}) =="
for T in Message MessageUpdate; do
  n=$(q "SELECT count(*) FROM \"$T\" WHERE \"messageTimestamp\" < ${CUT};" 2>/dev/null || echo "n/a (sem messageTimestamp?)")
  tot=$(q "SELECT count(*) FROM \"$T\";" 2>/dev/null || echo "?")
  echo "  ${T}: ${n} de ${tot} candidatos"
done
if [ "${APPLY:-0}" = "1" ]; then
  echo ">> APPLY=1 — apagando + VACUUM..."
  for T in Message MessageUpdate; do q "DELETE FROM \"$T\" WHERE \"messageTimestamp\" < ${CUT};" || true; done
  q "VACUUM (ANALYZE) \"Message\";" || true
  echo "feito."
else
  echo ">> DRY-RUN (nada apagado). Rode 'APPLY=1 bash deploy/evolution_retention.sh' pra executar."
fi
