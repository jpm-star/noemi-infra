# FASE 1 — Mapa de Arquitetura do Radar (read-only, antes de modificar nada)

Levantado 2026-07-30. Base factual pra qualquer evolução (Knowledge OS / Ruflo). Nada foi modificado.

## Estrutura (monorepo `noemi-infra`)
```
apps/
  painel-operacoes/   → o painel (:8030, FastAPI) — DONO do Radar (radar.py, radar_publico.py, main.py)
  motor-isca-sites/   → gerador de sites (builder_web.py :8020)
  motor-b-video/      → gerador de vídeo
  motor-imagem/       → imagem
  motor-leads/        → captação de leads (Places)
packages/shared-core/
  ai/  → llm_proxy (LiteLLM :4000), transcricao (Groq Whisper), visao (Tesseract/Gemini), local_llm
  obs/ storage/
infra/  → docker-compose (LiteLLM + Postgres), litellm-config.yaml
```

## Pipeline do Radar (a FONTE DA VERDADE — não duplicar)
```
entrada (link ou arquivo)
  → Telegram-hub (oneshot+timer 30s, deploy/telegram_hub.py)  OU  POST /api/radar/analisar (link)  OU  POST /api/radar/publico (upload, público travado)
  → radar.analisar(url)  |  radar.analisar_arquivo(caminho)
      → download (yt-dlp/Drive) [só no path por link]
      → ffmpeg (áudio) + _frames (visão)
      → transcricao.transcrever (Groq Whisper, retry rotacionando chave)
      → visao.analisar_frames (Tesseract OCR / Gemini)
      → radar._insight (prompt → llm_proxy: analise[Groq]→groq-reserva→fallback-anthropic[Claude])
          → SCHEMA NOVO 10 campos (resumo, estrutura_narrativa, tecnicas_persuasao, objecoes,
            promessa_vs_entrega, score_replicabilidade, hooks, ctas, aplicar_em, assinatura_tema)
      → processar_observacao → GRAVA em video_analises
  → UI /obs/radar
```

## Pontos de entrada (todos já convergem pro mesmo motor — bom)
- `POST /api/radar/analisar` (link, autenticado)
- `POST /api/radar/publico` (upload público — TRAVADO atrás de login até LGPD+anti-abuso)
- Telegram bot (@noemi_alert_bot) via `noemi-telegram-hub` (oneshot + timer)
- Leitura: `/api/radar/analises`, `/analise/{id}`, `/stats`, `/status`; feedback: `/api/radar/feedback`

## Persistência
- **SQLite** `data/noemi.db` → tabela `video_analises` (id, origem, url, data, transcricao, insight,
  categoria, score, tags, **detalhe**[=JSON do schema novo], feedback). `assinatura_tema` (dentro de
  detalhe) já é chave de dedup embrionária.
- Outros DBs: `leads.db` (tracker/prospecção), `leads_massa.db`.
- Postgres (docker) = só do LiteLLM (logs/models), **não** guarda conhecimento.

## Infra / serviços
- `noemi-painel-obs` (:8030, dono do Radar) · `noemi-site-builder` (:8020) · `noemi-motor-b` ·
  vários painéis Next (clinica/contabilidade/operador/papai/ps).
- **LiteLLM** em Docker (`noemi-litellm`, project **`noemiinfra`**) + Postgres. Modelos: analise,
  motor-b, groq-reserva, **fallback-anthropic** (Claude).
- Timers/workers: telegram-hub, autotune, leads, motor-b-retencao, whatsapp-watch, evolution-watchdog.

## O que NÃO existe hoje (o gap pro Knowledge OS)
- ❌ Embeddings / banco vetorial / RAG / busca semântica (zero).
- ❌ Task Queue formal (o "queue" é o timer do oneshot).
- ❌ Workspaces isolados (1 tabela única `video_analises`; roteamento só via campo `aplicar_em`).
- ❌ QA gate dedicado · versionamento/rollback formal · Supervisor/multi-agente · distribuição multi-destino.
- ❌ Ruflo (não instalado).

## Menor passo de maior valor (Fase 0 — SEM Ruflo, sem infra nova)
Os 190 registros já têm schema rico + `assinatura_tema`. **Embeddings + busca semântica sobre isso**
(sqlite-vec ou similar, local, R$0) = "Caixa de Ideias pesquisável" + dedup real, em ~1 semana, sem
os 20 agentes e sem a superfície de risco do Ruflo. É o ponto de partida recomendado.
