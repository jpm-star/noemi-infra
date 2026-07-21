# Auditoria noemi-infra — 2026-07-21 (sessão econômica)

Escopo: análise read-only + planos. Nada instalado, nada buildado. Código do
motor-b auditado em contexto (mesma sessão que o escreveu e revisou com 67
agentes); motor-site e painel auditados por passada dirigida barata.

---

## 1. QA — achados

### motor-b-video (em produção, :8010 mock)

**Correções da Fase 1 se sustentam — verificado no serviço VIVO:**
`GET /api/jobs` (listagem que vazava cross-cliente) → **404** ✓ · asset
aleatório → **404** (uuid4 não-enumerável) ✓ · config não-dict → recusada
(guard de asset roda antes; o 422 é coberto pelo teste de unidade, suíte 8/8) ✓.

| # | Achado novo | Sev | Detalhe / fix |
|---|---|---|---|
| N1 | stderr do ffmpeg não chega ao log | média | `CalledProcessError` vira `str(e)` sem o stderr capturado → `job.erro`/obs.jsonl ficam com "exit status 1" críptico. Fix 2 linhas em `mock_video.py`: anexar `e.stderr[-300:]` ao raise. |
| N2 | disco cresce sem teto (falha silenciosa) | média | `data/buckets/` (uploads+vídeos) e `data/obs.jsonl` nunca têm GC/rotação. Com uso real, enche o KVM4 em silêncio. Fix barato: ver §5c. |
| N3 | endpoints são capability-URL sem authz | baixa (aceito) | `GET /api/assets/{id}/file` e `cancel` funcionam pra quem tiver o uuid. Não-enumerável e nada os lista publicamente — modelo aceito na Fase 1 (PENDENCIAS §5), rever com o 2º cliente. |
| N4 | retry de rede no modo real | info | Lição do crash Groq 429: o SDK `anthropic` já faz retry nativo (2x, 429/5xx) e o loop `pause_turn` tem teto 8 — cobre o básico. Backoff próprio só se a prova real mostrar 429 frequente. |
| N5 | worker único assume 1 processo | info | `requeue_orfaos()` no startup + fila FIFO pressupõem `uvicorn` sem `--workers`. A unit systemd garante isso hoje; anotado pra ninguém "escalar" com workers=4 e criar corrida. |

### motor-isca-sites (`/root/motor-site`, master deployado)
**Limpo.** 412 linhas; `LLMOrquestrador` do master é um *seam* honesto
(`NotImplementedError`, zero chamada de rede, key só via env); deploy é escrita
de arquivo puro-Python (zero `subprocess`/`os.system` → sem injeção); o que está
no ar (`/var/www/sites`, 2 sites) é estático servido pelo Caddy — superfície ~zero.
**Risco real está no futuro:** a branch `feat/site-daora` (cérebro Groq, 35
testes, não mergeada) chama LLM direto — quando mergear/migrar pro monorepo,
viola a regra "provider só em shared-core/ai". Auditar na hora do merge, não antes.

### painel-operacoes
`analista.py`: função pura hardcoded, self-check passa, **zero consumidores** —
aceito de propósito (contrato mínimo da EXECUÇÃO). Sem risco.

### Duplicação entre apps (regra: só extrai se já duplicado DE VERDADE)
Encontrada: **shim de `sys.path`** repetido 3× (motor-b main, motor-imagem main,
conftest) e a forma FastAPI mínima 2×. **Veredito: NÃO extrair.** O shim tem
paradoxo de bootstrap (precisa do path pra importar o helper que arruma o path)
e o motor-imagem é stub, não "produto de verdade" — critério de Core não
atinge 2 produtos reais. Reavaliar quando o Motor Imagem nascer de fato
(aí a solução certa é `pyproject.toml` + install editable, não helper).

---

## 2. Ferramentas — recomendação (nada instalado)

| Ferramenta | Veredito | Onde encaixaria |
|---|---|---|
| **FFmpeg** | **JÁ INSTALADO e em uso** (mock gera testsrc2; radar-reels usa) | Ver §5a — normalização na ENTRADA do upload é o item de maior ROI. Nota: "comprimir antes de mandar pro Higgsfield" ainda não se aplica — o modo real hoje é prompt-only e **não envia mídia nenhuma** (PENDENCIAS §3); a compressão entra junto com a Fase 2 do image-to-video. |
| **Docling** | adiar, mas é o único fit real | Onboarding/Modo Camaleão: cliente manda PDF (cardápio, tabela, apresentação) → markdown estruturado → cartucho-rascunho. Ganho: elimina colar-PDF-no-prompt (economia grande de tokens + menos alucinação). Só quando o fluxo de onboarding por documento existir. |
| **Unstructured** | não | Mesma categoria do Docling, mais pesada e empurra API paga. Docling cobre. |
| **Gotenberg** | não | HTML→PDF via container extra; o relatório ROI já sai do fpdf2 no sdr-motor. Ganho estético não paga +1 serviço rodando. |
| **Pagefind** | não pros tiers atuais | Sites tier 1/2 são one-pagers — busca interna não agrega. Reavaliar só se o tier 3 ganhar blog/catálogo com 30+ páginas (aí é ótimo: estático, zero backend). |
| "insta-transcribe", "OCRack", "ai-video-factory" e afins | **não instalar** | Projetos pequenos/não auditados. O pipeline da §3 usa só ferramenta madura já presente. |

---

## 3. Transcrição de vídeo Instagram — plano (não implementado)

**Descoberta que muda o plano: ~70% já existe.** `/root/radar-reels`
(radar_reels.py + teste) já faz `yt-dlp → áudio → Whisper Groq → filtro JSON →
radar_log.md`, reusando a GROQ_API_KEY do sdr-motor. yt-dlp e ffmpeg já estão
na VPS. O delta pro objetivo (hook/cortes/texto na tela) é pequeno:

```
radar-reels HOJE:  URL → yt-dlp (áudio) → Whisper Groq → JSON score/categoria
DELTA (Fase 2):    + ffmpeg -vf fps=1/3 (frames) → Groq visão (llama-4 scout)
                   → JSON {hooks, timeline_cortes, texto_on_screen}
```

- **Cabe no KVM4? Sobra.** 4 vCPU/15GB (12 livres), 154GB disco. yt-dlp+ffmpeg
  são leves; Whisper roda via API Groq (NUNCA local — CPU-only seria lento e
  ocuparia a máquina de produção).
- **Sob demanda, não cron.** Lista de concorrentes é curada à mão, Instagram
  rate-limita/pede cookie em volume, e custo Groq por vídeo é ~centavos mas
  não precisa virar fixo. Script manual: `python radar_reels.py <url>`.
- **Teste mínimo:** o próprio radar-reels já foi validado em produção (memória
  2026-07). O delta de frames é ~20 linhas no mesmo arquivo. Custo de
  implementar: ~1h de sessão. Não executado hoje (fora do escopo econômico).

---

## 4. Frontend do painel — plano de escala (nada reescrito)

**Base que já serve:** o painel de produção (sdr-motor, Next.js :3000) tem nav
**config-driven por cartucho** (`AppShell.tsx` + `useCartucho`) — adicionar área
nova = 1 entrada no CATALOGO + 1 rota + 1 chave no nav do cartucho do operador.
A arquitetura certa já existe; não inventar shell novo no monorepo.

**Estrutura proposta (quando a branch `feat/noemi-final-cleanup` estabilizar):**
```
/produtos                    ← grade de cards (Motor B, Sites, Imagem, Radar)
/produtos/video              ← status de jobs do Motor B
/produtos/sites              ← sites no ar + fila do motor-isca
/produtos/radar              ← análises de Instagram (futuro §3)
```
Regras pra não virar bagunça: **cada rota busca no SEU endpoint** (Motor B expõe
read-only na :8010 atrás do proxy Caddy `painel.noemi.digital/api/produtos/video/*`
com um token de operador no header) · **zero estado global** — fetch por página ·
produto novo = pasta nova + endpoint próprio, nunca um "superstore".
**O que precisa mudar:** nada hoje; o Motor B precisará de 1 endpoint agregado
`GET /api/interno/resumo` (contagem por estado) com token — ~15 linhas.

---

## 5. "Como eu faria" — os 3 maiores ROI

**a) Normalização FFmpeg na entrada do upload (MAIOR ROI, dá pra fazer já)**
No `worker.py`, estado `uploading`: imagem → `ffmpeg -vf scale=-2:1080` +
recomprimir (25MB → ~1-2MB); vídeo → H.264 720p. Economiza disco desde já em
mock, corta o tempo de upload futuro pro Higgsfield e resolve metade do N2.
Arquivos: `worker.py` (+~25 linhas) e 1 teste. **~1h.** Sem dependência nova.

**b) Image-to-video real — Fase 2 do provider (destrava o produto de verdade)**
Em `higgsfield_video.py::_instrucao`: incluir a URL pública do asset
(`https://video.noemi.digital/api/assets/{id}/file`) e instruir o modelo a usar
`media_import_url` antes do `generate_video`. Zero mudança de arquitetura — o
MCP faz o upload. Arquivos: só o provider (+~10 linhas) + README/PENDENCIAS.
**~1h**, mas **depende dos 2 destravas humanos**: DNS A + ANTHROPIC_API_KEY.

**c) Retention de disco + stderr do ffmpeg (mata as 2 falhas silenciosas N1/N2)**
Cron diário (systemd timer): apagar asset de ORIGEM com job completed há >30d
(vídeo final fica), truncar obs.jsonl >50MB; + anexar stderr no erro do mock.
Arquivos: `deploy/limpeza.sh` + timer + 2 linhas no `mock_video.py`. **~40min.**

Prioridade sugerida com o saldo: **(a) agora → (c) junto → (b) quando DNS+key
chegarem** (b é o único que vira receita, mas está bloqueado em ação sua).

---

*Gasto estimado desta sessão: ~R$10 (só leitura dirigida + 6 comandos read-only
+ este relatório; nenhum build, nenhuma instalação, nenhum agente paralelo).*
