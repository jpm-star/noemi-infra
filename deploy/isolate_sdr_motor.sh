#!/usr/bin/env bash
# Isola os bancos sdr_motor_* do cluster do Evolution -> instância dedicada.
# SEGURO: só faz DUMP (read-only) da origem. NÃO apaga a origem, NÃO faz cutover.
# O restore + cutover é manual (runbook impresso no fim), com janela.
set -euo pipefail
SRC_C="${SRC_C:-evolution_postgres}"; SRC_U="${SRC_U:-evolution}"
DBS="${DBS:-sdr_motor_papai sdr_motor_operador sdr_motor_contabilidade sdr_motor_clinica sdr_motor_ps sdr_motor}"
DUMPDIR="${DUMPDIR:-/root/noemi-infra/data/sdr_motor_dumps}"; mkdir -p "$DUMPDIR"
echo "== Dump (read-only) dos bancos SDR Motor da origem ${SRC_C} =="
for DB in $DBS; do
  if docker exec "$SRC_C" pg_dump -U "$SRC_U" -d "$DB" -Fc > "$DUMPDIR/$DB.dump" 2>/dev/null; then
    rows=$(docker exec "$SRC_C" psql -U "$SRC_U" -d "$DB" -tA -c "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';" 2>/dev/null || echo "?")
    echo "  ${DB}: dump ok ($(du -h "$DUMPDIR/$DB.dump" | cut -f1), ${rows} tabelas)"
  else echo "  ${DB}: FALHOU (existe?)"; fi
done
cat <<RUN

== RUNBOOK DE CUTOVER (manual, com janela — NÃO automatizado de propósito) ==
1. Suba a instância dedicada:  docker compose -f infra/sdr-motor-postgres.compose.yml -p sdrmotor up -d
2. Restaure cada dump:  for f in ${DUMPDIR}/*.dump; do db=\$(basename \$f .dump);
     PGPASSWORD=\$SDR_PG_PASSWORD createdb -h 127.0.0.1 -p 5433 -U sdrmotor \$db;
     PGPASSWORD=\$SDR_PG_PASSWORD pg_restore -h 127.0.0.1 -p 5433 -U sdrmotor -d \$db \$f; done
3. Valide contagens (novo vs origem) antes de repontar.
4. Repointe DATABASE_URL: /root/sdr-motor/deploy/papai.env (+ operador/clinica/etc) -> host 127.0.0.1:5433.
5. Reinicie os serviços SDR + valide funcionamento.
6. SÓ ENTÃO dropar os bancos da origem Evolution (libera o disco compartilhado).
RUN
