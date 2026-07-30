#!/usr/bin/env bash
# Testa restore do Postgres do Evolution PONTA-A-PONTA em cluster SCRATCH isolado.
# NÃO toca produção (dump é read-only; restore vai pra container temporário; limpa no fim).
#
# CAMINHO PRIMÁRIO (este script, roda green): restore LÓGICO (pg_dump -Fc -> pg_restore).
#   Prova o round-trip backup->restore->integridade sem privilégio de replicação.
# CAMINHO FÍSICO/PITR-WAL (documentado, gated): archive_mode já está ON (archive p/ /wal_archive).
#   Pra testar pg_basebackup + replay de WAL falta 1 linha em pg_hba.conf da prod:
#     host replication <user> <rede_docker> md5   + SELECT pg_reload_conf();
#   Depois: pg_basebackup -Fp -Xs + subir cluster com recovery_target. (mudança de prod = gate manual)
set -euo pipefail
SRC_C="${SRC_C:-evolution_postgres}"; SRC_U="${SRC_U:-evolution}"; SRC_DB="${SRC_DB:-evolution}"
SCRATCH_C="pg_restore_test_$$"; PORT="${PORT:-5434}"
cleanup(){ docker rm -f "$SCRATCH_C" >/dev/null 2>&1 || true; }
trap cleanup EXIT
DUMP=$(mktemp /tmp/evo_restore_test.XXXX.dump)
echo "== 1) Dump (READ-ONLY) de $SRC_DB @ $SRC_C =="
docker exec "$SRC_C" pg_dump -U "$SRC_U" -d "$SRC_DB" -Fc > "$DUMP"
echo "   dump: $(du -h "$DUMP" | cut -f1)"
echo "== 2) Sobe cluster SCRATCH isolado (porta $PORT) + restaura =="
docker run -d --name "$SCRATCH_C" -p "127.0.0.1:$PORT:5432" -e POSTGRES_PASSWORD=scratch postgres:15 >/dev/null
for i in $(seq 1 30); do docker exec "$SCRATCH_C" pg_isready -U postgres >/dev/null 2>&1 && break; sleep 1; done
docker exec "$SCRATCH_C" psql -U postgres -tA -c "CREATE ROLE \"$SRC_U\" LOGIN SUPERUSER;" >/dev/null 2>&1 || true
docker exec "$SCRATCH_C" psql -U postgres -tA -c "CREATE DATABASE \"$SRC_DB\" OWNER \"$SRC_U\";" >/dev/null 2>&1 || true
docker cp "$DUMP" "$SCRATCH_C:/tmp/d.dump"
docker exec "$SCRATCH_C" pg_restore -U postgres -d "$SRC_DB" --no-owner /tmp/d.dump >/dev/null 2>&1 || true
echo "== 3) Valida: contagens restauradas vs produção =="
fail=0
for T in Message Contact Chat MessageUpdate; do
  prod=$(docker exec "$SRC_C" psql -U "$SRC_U" -d "$SRC_DB" -tA -c "SELECT count(*) FROM \"$T\";" 2>/dev/null || echo "?")
  rest=$(docker exec "$SCRATCH_C" psql -U postgres -d "$SRC_DB" -tA -c "SELECT count(*) FROM \"$T\";" 2>/dev/null || echo "FALHOU")
  if [ "$prod" = "$rest" ]; then echo "   $T: $rest ✓"; else echo "   $T: prod=$prod restaurado=$rest ✗"; fail=1; fi
done
rm -f "$DUMP"
[ "$fail" = "0" ] && echo "== RESTORE OK — round-trip íntegro em cluster isolado ==" || { echo "== RESTORE DIVERGIU =="; exit 1; }
