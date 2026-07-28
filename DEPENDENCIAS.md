# DEPENDENCIAS.md — acoplamento físico (noemi-infra)

Registro de acoplamento REAL (X hardcoded em Y; deploy de A exige restart de B).
Separado do log de decisões (memória). Atualizar toda vez que descobrir acoplamento
não documentado. Criado pós-incidente 2026-07-28.

## Deploy
- **Protocolo:** SEMPRE `git checkout <branch> -- <arquivo>` no checkout principal
  (`/root/noemi-infra`) + `systemctl restart`. **NUNCA `cp` de worktree pra produção.**
- Painel `/obs` (:8030) serve `apps/painel-operacoes/static/*` do **disco** →
  trocar arquivo + `systemctl restart noemi-painel-obs`. Não recarrega sozinho.
- `noemi-site-builder` (:8020), `noemi-motor-b` (:8010): idem, restart após trocar código.

## Acoplamentos conhecidos
- **`index.html` do painel** referenciava `go.noemi.digital` hardcoded (3 pontos:
  Site, Onboarding, card Motor Site). `go.` foi aposentado → tudo repontado pra
  `p.jpos.com.br/studio`. Lição: matar um domínio exige grep no front antes.
- **Caddy** (`/etc/caddy/Caddyfile`) agrupava `go./sites./p.jpos.com.br` no MESMO bloco.
  `p.jpos.com.br` é o único domínio vivo hoje; QG/obs/studio/widget todos nele.
- **`evolution_watchdog`** (systemd timer) depende de `infra/watchdog.env`
  (EVOLUTION_APIKEY/URL) + `packages/shared-core/notify.py` (Telegram) + `.env`
  (TELEGRAM_*). Reconecta instâncias via `POST /instance/restart/{nome}`.
- **`telegram_hub`** (timer) lê `apps/painel-operacoes/radar.py` (sys.path) + `.env`
  (TELEGRAM_BOT_TOKEN). Roda a cada ~30s lendo o arquivo fresco (sem restart).
- **LLM:** tudo passa por `packages/shared-core/ai/llm_proxy.py` → LiteLLM (:4000).
  Fallback Anthropic (`fallback-anthropic` no litellm-config) INERTE até
  `ANTHROPIC_API_KEY` estar no `.env` do app E do container `noemi-litellm`.

## Bancos (isolamento — NUNCA cruzar)
- `noemi.db` (SQLite, `data/noemi.db`): Radar, financeiro, leads, prospecção-demo. ISOLADO.
- `sdr_motor_papai` (Postgres, container): produção do SDR papai. **NÃO tocar em testes.**
  ⚠️ `sdr-motor/backend/tests/conftest.py::_limpa` TRUNCA ~20 tabelas SEM guarda de
  ambiente — rodar pytest apontado pra ele APAGA produção (incidente 2026-07-28).
