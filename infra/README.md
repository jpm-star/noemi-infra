# infra/ — Camada de LLM (Bloco 2)

Camada única de LLM do noemi-infra via **LiteLLM Proxy**, com observabilidade de
custo/latência/modelo/erro nativa. Tudo em Docker Compose, um lugar só, cada
container com limite de memória.

## Subir
```bash
cd /root/noemi-infra/infra
cp .env.example .env   # e preencher (GROQ_API_KEY, senhas)
docker compose up -d
```

## Componentes
| Container | Imagem | Mem | Papel |
|---|---|---|---|
| `noemi-litellm` | litellm-database:main-stable | 1g | proxy OpenAI-compatível :4000 (loopback) |
| `noemi-litellm-db` | postgres:16-alpine | 256m | logs de custo/spend do proxy |

## Rotas (nomes lógicos — nunca provider cru pra cima)
- `analise` → Groq (llama-3.3-70b) — classificação/atendente
- `motor-b` → Anthropic (claude-opus-4-8) — quando `ANTHROPIC_API_KEY` existir
- fallback entre os cloud é nativo (`litellm_settings.fallbacks`)

## Ollama (fallback offline) fica FORA do proxy
Por segurança o Ollama segue em loopback (127.0.0.1); expô-lo à bridge do Docker
foi barrado. A cascata é 2 camadas: **proxy (cloud) → local_llm (Ollama) → regras**
(ver `packages/shared-core/ai/classificacao.py::_texto_do_llm`).

## Dashboard de custo
- UI: `http://127.0.0.1:4000/ui` (login `UI_USERNAME`/`UI_PASSWORD` do .env)
- API: `GET /spend/logs` com `Authorization: Bearer $LITELLM_MASTER_KEY`
- Registra por chamada: modelo, tokens, custo (USD), latência, erro.

## Langfuse (trace-UI dedicado) — plug documentado, não subido
LiteLLM manda pro Langfuse com 3 linhas no `litellm-config.yaml`:
```yaml
litellm_settings:
  success_callback: ["langfuse"]
  failure_callback: ["langfuse"]
```
+ `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY`/`LANGFUSE_HOST` no ambiente e o
stack do Langfuse (Postgres+Clickhouse+Redis+Minio) num compose próprio. Adiado
por peso/custo: o dashboard nativo do LiteLLM já entrega custo/latência/modelo/
erro que o Bloco 2 pedia. Subir Langfuse quando o trace por-span valer os +4
containers.

## Apps que consomem
Env necessário no serviço (ex. `noemi-motor-b`): `LITELLM_URL=http://127.0.0.1:4000`
e `LITELLM_MASTER_KEY=...`. Sem eles (ou proxy fora), a cascata degrada pro Ollama
local e depois regras — nunca quebra.
