# noemi-infra — monorepo dos produtos Noemi

| Produto | Onde | URL | Status |
|---|---|---|---|
| 🎥 Motor B — Vídeo IA | `apps/motor-b-video/` (porta **8010**) | video.noemi.digital | funcional em MOCK |
| 🌐 Sites (motor-isca) | ponteiro → `/root/motor-site` | videoshiggs.noemi.digital (+ alias sites.) | ativo (fora do monorepo) |
| 🖼️ Motor Imagem | `apps/motor-imagem/` (porta 8011 reservada) | imagem.noemi.digital | stub/placeholder |
| 👁️ Análise (Analista) | `apps/painel-operacoes/analista.py` | — | contrato mínimo (hardcoded Motor B) |

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

## Deploy / operação

```bash
uv venv .venv && uv pip install -p .venv/bin/python -r requirements.txt
cp deploy/noemi-motor-b.service /etc/systemd/system/ && systemctl daemon-reload
systemctl enable --now noemi-motor-b        # sobe na 127.0.0.1:8010 (Caddy → video.noemi.digital)
.venv/bin/python -m pytest apps/motor-b-video/tests/ -q   # suíte (6 testes)
```

Pendência externa: DNS A de `video.` / `imagem.` / `sites.noemi.digital` → 2.24.120.204
(Caddy já configurado; certs emitem sozinhos quando o DNS chegar).
