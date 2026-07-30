# VISÃO — Radar como Sistema Operacional de Conhecimento do JPOS

> Capturado do brief do JP (2026-07-30). **É visão/roadmap, NÃO construído.** Iniciativa de semanas.
> Gated atrás dos itens de risco do `BACKLOG_JPOS.md` + decisão sobre Ruflo (hoje travado).

## O norte
Transformar qualquer entrada (vídeo/texto/URL/PDF/imagem) em **conhecimento estruturado**, com QA,
enriquecido, relacionado ao existente, distribuído automaticamente pro Workspace certo, indexado pra
RAG e versionado. Sem depender do usuário pra classificar/distribuir.

## Arquitetura alvo
- **Supervisor** (não faz trabalho pesado): recebe → planeja → delega → revisa → QA → integra.
- **Agentes** abaixo dele: Knowledge Router (classifica/dedup), Knowledge Analyst (extração profunda),
  Knowledge QA (gate obrigatório), + Research/Video/OCR/Whisper/Crawler/Embedding/Relationship/
  Template/Task-Gen/Docs/Database/Notification/UI-Sync/Search/Dedup/Insight (~20 no total).
- **Workspaces isolados** (sem compartilhar embeddings/contexto/memória): Pessoal, JPOS, Noemi, Radar,
  Motor Sites, Motor Vídeo, SDR, CRM, Marketing, Produto, Engenharia, Infra, Financeiro. Cada um com
  KB próprio, Caixa de Ideias, RAG, tags, templates, embeddings, histórico, insights, score, conexões.
- **Pipelines por tipo** (vídeo/texto/URL/PDF/imagem) → Analyst → Router → QA → persistência →
  UI → relacionamento → notificação.
- **Memória por entrada:** embeddings, resumo executivo+técnico, keywords, relacionamentos, scores
  (importância/reutilização/impacto), categorias, origem, autor, data, projeto, tipo.
- **Distribuição automática** pós-QA: Caixa de Ideias, KB, Templates, Playbooks, Roadmap, Backlog,
  Docs, RAG, banco vetorial, Tarefas, CRM, Dashboard.
- **Automações:** ao detectar oportunidade → cria tarefas/issues/roadmap/prompts/templates/agentes.
- **Regras:** nunca perder info; versionar; histórico; justificar classificação; logar decisão/erro/confiança.

## O que JÁ existe hoje (base pra não reconstruir)
- **Ingestão de vídeo/link:** Telegram-hub (oneshot+timer) → yt-dlp/Drive → ffmpeg → OCR (Tesseract) +
  Whisper (Groq, com retry rotacionando chave) + visão (Gemini) → insight.
- **Extração estruturada:** `radar._insight` — HOJE com o **schema novo de 10 campos** (resumo,
  estrutura_narrativa, tecnicas_persuasao [taxonomia fixa], objecoes, promessa_vs_entrega,
  score_replicabilidade, hooks, ctas, aplicar_em, assinatura_tema/anti-dup). Fallback Groq→Claude.
- **Persistência:** `video_analises` (SQLite noemi.db) + `assinatura_tema` já serve de chave de dedup.
- **Roteamento embrionário:** campo `aplicar_em`/`motores` (arbitragem/motor-site/motor-b/noemi) +
  `verticais` — é um proto-"Workspace routing".
- **UI:** `/obs/radar` no painel.

## O gap (o que a visão pede e não existe)
- Supervisor + orquestração multi-agente (hoje é 1 pipeline linear, sem QA dedicado).
- Workspaces isolados de verdade (hoje 1 tabela única, sem RAG/vetorial por projeto).
- Embeddings / banco vetorial / busca semântica (não existe).
- Distribuição automática pra múltiplos destinos (Caixa de Ideias/CRM/Dashboard/etc).
- Versionamento formal + QA gate.
- Ruflo (233 ferramentas + shell) — **travado por decisão de risco**.

## Caminho faseado sugerido (quando desbloquear — NÃO agora)
1. **Fase 0 (barato, alto valor):** embeddings + busca semântica sobre `video_analises` que JÁ tem o
   schema rico. Só isso já vira "Caixa de Ideias pesquisável" sem reescrever nada.
2. **Fase 1:** QA gate + versionamento na escrita do radar.
3. **Fase 2:** roteamento por Workspace (usar `aplicar_em` pra separar KBs).
4. **Fase 3+:** multi-agente (Supervisor + Analyst/Router/QA separados), demais pipelines, Ruflo (se
   os riscos do backlog estiverem fechados).

> Recomendação: começar pela **Fase 0** (embeddings sobre o que já existe) — prova o valor com 1 semana
> de trabalho, sem o peso dos 20 agentes. O resto é roadmap.
