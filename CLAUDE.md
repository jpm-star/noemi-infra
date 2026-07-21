# CLAUDE.md — Regras de Ouro (monorepo noemi-infra)

## NUNCA
- NUNCA crie classes abstratas ou interfaces "genéricas" para produtos futuros que não existem ainda.
- NUNCA implemente fila complexa (Celery/Temporal) antes de ter um worker simples (asyncio/RQ) funcionando.
- NUNCA toque em fine-tuning, RLHF, LoRA, self-optimization. Se aparecer necessidade, pare e avise — não implemente.
- NUNCA crie um repositório separado por produto. Tudo em monorepo, pastas isoladas.
- NUNCA chame um provider de IA diretamente fora de `packages/shared-core/ai/`. Se algum arquivo instanciar cliente Groq/OpenRouter/Higgsfield direto, é erro de arquitetura — pare e avise.
- NUNCA implemente Market/News/Competitor Intelligence, Multi-Agent Platform, Voice Platform completa, ou qualquer módulo do "Core AI" de visão de longo prazo. Isso é roadmap de anos, não desta sessão.

## SEMPRE
- SEMPRE que for expor uma ferramenta trocável (visão, OCR, geração de vídeo/imagem), exponha via interface fixa: `vision.analyze()`, `video.generate()` — nunca o nome do provider (`qwen.detect()`, `kling.render()`). Amanhã troca o provider por baixo, nada quebra em cima.
- SEMPRE prefira função pura (recebe dict, devolve dict) a classe. Só crie classe se houver estado mutável real (ex: sessão de job em progresso).
- SEMPRE que uma etapa terminar, valide com mock antes de seguir pra próxima. Não avance sem a etapa atual funcionando de ponta a ponta.
- SEMPRE que precisar tomar decisão de arquitetura ampla (nova dependência pesada, novo serviço, nova tabela central), pare e mostre o problema antes de implementar.

## Estrutura física obrigatória
```
packages/
  shared-core/
    ai/          # client único, provider pattern, cost tracking via decorator
    obs/         # 1 função log_span(), fire-and-forget pro Langfuse
    storage/     # interface de asset (id/owner/produto/bucket/hash), mock por padrão
apps/
  motor-b-video/
  motor-isca-sites/
  motor-imagem/
  painel-operacoes/
```

## Critério de "isso pode ser Core"
Um componente só entra em `shared-core` se **já está sendo usado por 2+ produtos de verdade**, não por previsão de uso futuro. Se só um produto usa, fica dentro da pasta do produto.

## Notas de implementação (desta base)
- `packages/shared_core` é symlink pra `shared-core` (hífen não importa em Python; estrutura física preservada).
- DB: SQLite local em `data/noemi.db` (WAL). Não toca o Postgres de produção. Migrar = trocar `storage/db.py::conn()`.
- Rodar testes: `.venv/bin/python -m pytest apps/motor-b-video/tests/ -q`
