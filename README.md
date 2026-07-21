# noemi-infra — monorepo dos produtos Noemi

| Produto | Onde | URL | Status |
|---|---|---|---|
| 🎥 Motor B — Vídeo IA | `apps/motor-b-video/` (porta **8010**) | **videoshiggs.noemi.digital** (tem DNS) | funcional em MOCK, no ar |
| 🌐 Sites (motor-isca) | ponteiro → `/root/motor-site` | **go.noemi.digital** (+ alias sites.) | ativo (fora do monorepo) |
| 🧪 Site Builder (teste) | `apps/motor-isca-sites/builder_web.py` (porta **8020**) | localhost (túnel SSH) | ferramenta interna |
| 🖼️ Motor Imagem | `apps/motor-imagem/` (porta 8011 reservada) | imagem.noemi.digital (sem DNS ainda) | stub/placeholder |
| 👁️ Análise (Analista) | `apps/painel-operacoes/analista.py` | — | contrato mínimo (hardcoded Motor B) |

### Camada 2 (LiteLLM + Langfuse) — ADIADA de propósito (2026-07-21)
Gateway LLM único + observabilidade **não** foram construídos: a premissa ("2 produtos já
chamam Groq") é falsa aqui — `motor-b-video` usa Anthropic (vídeo, não Groq) e o orquestrador
do `motor-isca` é stub sem chamada real. Rotear "os 2 apps" hoje = rotear nada; Langfuse (4+
contêineres, vários GB) observaria zero chamadas. Fica no mapa (Core AI §Camada 2), fora do
backlog ativo. **Ligar quando UMA destas acontecer de verdade — não antes:**
1. o orquestrador do motor-isca sair de stub e fazer a 1ª chamada real a qualquer LLM;
2. o Motor B ganhar um 2º provider real (hoje só Anthropic);
3. existir chamada de LLM em produção em 2 lugares diferentes do monorepo ao mesmo tempo.
Quando ligar: LiteLLM (leve, ~200MB) primeiro como gateway; Langfuse (pesado) só se custo/
latência real virar dor. Nota: o que já chama Groq em prod (`sdr-motor`, `radar-reels`) vive
FORA deste monorepo — talvez o alvo certo da Camada 2 nem seja aqui.

### Subdomínios (decisão final 2026-07-21)
DNS existente aponta pra `2.24.120.204`. Escolhas dentro do que já existe, sem pedir DNS novo:
- **`videoshiggs` → Motor B** (o nome já casa com vídeo/Higgsfield). `video.noemi.digital`
  fica no mesmo bloco Caddy, pronto pra quando/se ganhar DNS.
- **`go` → motor-isca-sites** (único livre da lista). Isca migrou de videoshiggs pra cá;
  os sites em `/var/www/sites` agora servem em `go.noemi.digital/<slug>/`.
- **`motor` e `api` NÃO estão livres** — `motor`→motor-arbitragem (:8082), `api`→evolution
  (:8080). Verificado com `curl -I`/`dig`; não tocados.
- **Motor Imagem** ficou sem DNS dedicado (só `go` era livre, foi pro isca) — segue no
  placeholder do Caddy até o JP provisionar um subdomínio.
- Intocados por serem de outros projetos: `garimp`, `n8n`, `painel`, `contabilidade`, `influia`.

### Site Studio — ferramenta de produção do JP (com login)
`apps/motor-isca-sites/builder_web.py` (systemd `noemi-site-builder`, 127.0.0.1:8020,
exposto via Caddy). **URL: `https://go.noemi.digital/studio`** (HTTPS, autenticado).
Formulário de briefing → pipeline REAL do motor-site (`stub→template→local`, sem LLM)
→ publica em `go.noemi.digital/<slug>/`, com **preview em iframe + histórico** dos
sites gerados (tabela `sites_gerados`). Frontend com identidade própria (dark/roxo),
não admin genérico. Preview por screenshot foi omitido (headless browser ~400MB — o
iframe do site real cobre melhor e de graça).

**Auth** (`auth.py`, single-user, stdlib): senha `pbkdf2_hmac` + cookie de sessão
`hmac`-assinado (30d, httponly/secure/samesite=lax). Só o hash mora em
`data/builder_auth.json` (chmod 600) — nunca texto puro. Trocar a senha:
`BUILDER_PASSWORD=nova .venv/bin/python apps/motor-isca-sites/auth.py set-password`.
Usuário: `joaop`. Rotas todas sob `/studio` (Caddy encaminha o prefixo; app segue
em localhost, Caddy é a borda TLS). `/studio` sem login → 303 pra `/studio/login`.

Camadas compartilhadas em `packages/shared-core/`: `ai/` (interface fixa `video.generate(asset, config)` + cost tracking), `storage/` (Asset: id/owner/produto/bucket/mime/hash/metadata, SQLite + bucket em disco), `obs/` (`log_span()` fire-and-forget → `data/obs.jsonl`).

## Motor B — fluxo

```
POST /api/upload (multipart)  → asset_id            # valida mime + tamanho
POST /api/jobs {asset_id}     → job_id (queued)
GET  /api/jobs/{id}           → estado: queued → uploading → processing → completed
                                          (retry até 3x → failed; cancel a qualquer momento)
GET  /api/assets/{id}/file    → mp4 final
GET  /                        → front (upload + progresso + player)
```

Worker: asyncio in-process (1 job por vez). Vínculo persistido: job → asset origem → asset vídeo (`metadata.asset_origem` / `metadata.job`).

## ⚠️ PONTO DE TROCA mock → Higgsfield real (1 função, zero refactor)

O roteamento está em **`packages/shared-core/ai/video.py`** (~5 linhas): `MOCK_MODE`
decide entre `providers/mock_video.generate` e `providers/higgsfield_video.generate`.

A função que passa a rodar é **`packages/shared-core/ai/providers/higgsfield_video.py::generate`**
— já implementada com o padrão provado no `/root/motor-video` (Anthropic Messages API +
MCP connector da Higgsfield, loop `pause_turn`, download do mp4 pro bucket local).

Pra ligar o real:
```bash
cd /root/noemi-infra
cp .env.example .env   # e edite:
#   MOCK_MODE=false
#   ANTHROPIC_API_KEY=sk-ant-...     ← único item ainda pendente na VPS
#   HIGGSFIELD_MCP_TOKEN=...         ← OAuth concluído 2026-07-21 (plano plus, 1010 cr)
uv pip install -p .venv/bin/python anthropic   # SDK só é preciso no modo real
systemctl restart noemi-motor-b
```
Nenhum arquivo de app muda. Front, fila, storage e painel não sabem qual provider roda.

**Limite honesto da Fase 1:** o modo real é **prompt-only** — gera vídeo a partir da
descrição (`config.prompt`), mas a mídia enviada pelo cliente ainda NÃO é anexada à
geração. Image-to-video de verdade (foto do imóvel → vídeo) é a Fase 2:
`media_upload`/`media_import_url` do MCP antes do `generate_video` (PENDENCIAS §4).

## Normalização da mídia de entrada

No estado `uploading`, o worker normaliza a mídia de origem **in-place** (mesmo
asset id/URL) via FFmpeg: imagem → JPEG ≤1080px (lado maior), vídeo → H.264 720p
/ AAC / faststart. Encolhe disco desde já e é o que a Fase 2 (image-to-video)
enviará ao Higgsfield. **Best-effort**: se o FFmpeg não decodifica o formato, o
job segue com o original (`metadata.normalizado=false` + erro estruturado) —
normalização é otimização, nunca condição de correção. Código: `media.py` +
`worker._normalizar_origem`.

## Política de retenção de disco

`apps/motor-b-video/retention.py` (systemd timer diário):
- Asset de **ORIGEM** de job terminal (completed/failed/cancelled) mais velho que
  `RETENTION_DIAS` (default **30**) tem o **arquivo** purgado; o **vídeo final é
  preservado**. A linha do asset fica (proveniência + FK `jobs.asset_origem`).
- `data/obs.jsonl` acima de `OBS_MAX_MB` (default **50**) rotaciona pra `obs.jsonl.1`.

Rodar manual: `.venv/bin/python apps/motor-b-video/retention.py`

## Logging de interação real (fundação pra tuning futuro — NÃO é tuning)

Tabela `interacoes` (SQLite `data/noemi.db`): `ts, produto, cliente, segmento,
input, output, modelo, handoff_whatsapp`. `storage.registrar_interacao(...)` grava
UMA interação **real**. O worker do Motor B só registra quando o modelo **não é
mock** (`out["modelo"]` não começa com `mock`) — então a tabela fica **vazia até a
1ª geração Higgsfield de verdade** (`MOCK_MODE=false`). É fire-and-forget: falha de
log nunca reverte um job concluído. Objetivo único: quando houver volume pra decidir
tuning, o histórico já existe — sem reconstruir.

- **Motor B** loga na SQLite própria (não no Postgres de prod — CLAUDE.md proíbe tocá-lo).
- **Assistente Virtual** (sdr-motor): quando integrar, loga no Postgres dele que já
  existe, com o mesmo shape + `handoff_whatsapp` preenchido (Camada 2 segue adiada).
- Sem ClickHouse, sem Langfuse (Camada 2 adiada, gatilhos documentados acima).

## Deploy / operação

```bash
uv venv .venv && uv pip install -p .venv/bin/python -r requirements.txt
cp deploy/noemi-motor-b.service /etc/systemd/system/ && systemctl daemon-reload
systemctl enable --now noemi-motor-b        # sobe na 127.0.0.1:8010 (Caddy → video.noemi.digital)
# retenção diária:
cp deploy/noemi-motor-b-retencao.{service,timer} /etc/systemd/system/ && systemctl daemon-reload
systemctl enable --now noemi-motor-b-retencao.timer
.venv/bin/python -m pytest apps/motor-b-video/tests/ -q   # suíte (15 testes)
```

Pendência externa: DNS A de `video.` / `imagem.` / `sites.noemi.digital` → 2.24.120.204
(Caddy já configurado; certs emitem sozinhos quando o DNS chegar).
