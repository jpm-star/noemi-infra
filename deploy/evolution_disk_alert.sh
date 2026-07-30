#!/usr/bin/env bash
# Alerta de disco + tamanho do Evolution DB. READ-ONLY. Notifica no Telegram se > limite.
set -euo pipefail
DISK_LIMIT="${DISK_LIMIT:-80}"; DB_LIMIT_MB="${DB_LIMIT_MB:-3000}"
C="${EVO_PG_CONTAINER:-evolution_postgres}"; U="${EVO_PG_USER:-evolution}"; DB="${EVO_PG_DB:-evolution}"
used=$(df / --output=pcent 2>/dev/null | tail -1 | tr -dc '0-9'); used="${used:-0}"
dbmb=$(docker exec "$C" psql -U "$U" -d "$DB" -tA -c "SELECT round(pg_database_size('${DB}')/1024/1024);" 2>/dev/null || echo 0)
msg=""
[ "$used" -ge "$DISK_LIMIT" ] && msg="⚠️ Disco ${used}% (>=${DISK_LIMIT}%). "
[ "${dbmb:-0}" -ge "$DB_LIMIT_MB" ] && msg="${msg}⚠️ Evolution DB ${dbmb}MB (>=${DB_LIMIT_MB}MB — rodar retenção). "
if [ -n "$msg" ]; then
  echo "ALERTA: ${msg}"
  /root/noemi-infra/.venv/bin/python -c "import sys;sys.path.insert(0,'/root/noemi-infra/packages');from shared_core import notify;notify.telegram('''${msg}''')" 2>/dev/null || true
  exit 1
fi
echo "OK: disco ${used}%, Evolution DB ${dbmb}MB (limites ${DISK_LIMIT}% / ${DB_LIMIT_MB}MB)"
