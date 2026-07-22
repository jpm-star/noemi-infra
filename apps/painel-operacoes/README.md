# Painel de observabilidade (read-only) — :8030

Tela única do estado real dos 3 motores da Noemi OS, sem terminal. Agrega 4 fontes
(health dos serviços, LiteLLM /spend/logs, SQLite jobs, obs.jsonl) + VPS via /proc.
**Zero escrita/ação** — só leitura e diagnóstico.

- `agg.py`: coleta pura, best-effort por fonte (uma cai, o resto segue).
- `main.py`: FastAPI serve `/api/painel` (JSON) e `/painel` (HTML dark, auto-refresh 4s).
- `static/index.html`: dashboard (status, custo/latência/P95, cache, ranking, fila,
  cascata de fallback, falhas agrupadas, CPU/RAM/disco).

Subir: `systemctl enable --now noemi-painel` (unit em `deploy/noemi-painel.service`).
Env: `LITELLM_MASTER_KEY` (do `infra/.env`), `NOEMI_DB`, `NOEMI_OBS`.
Acesso remoto: atrás do Caddy com basicauth (interno). Localhost por padrão.

Cortado de propósito (sem fonte de dado / infra nova): Next.js/shadcn/SSE (o padrão
do monorepo é FastAPI+HTML), trace_id correlation (não há trace ids), uptime%/SLA
histórico e forecast (exigiria um poller gravando histórico — próximo passo natural),
deploy history, temperatura da CPU.
