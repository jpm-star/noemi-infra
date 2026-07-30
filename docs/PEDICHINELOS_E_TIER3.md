# Pé Di Chinelos (dogfood e-commerce) + Setup de Tier 3

_Pé Di NÃO é repo/projeto novo — é **cartucho/instância** dentro do motor-site/JPOS, controlado
pelo painel existente. Este doc mapeia o que já existe (reaproveitar), o modelo de preço, e o que
falta pra Tier 3 (cliente pagante externo self-serve)._

## Estado atual do Pé Di (feito, em preview)
- **Site:** `p.jpos.com.br/pe-di-chinelos/` (preview — chinelospedi.com HOLD, DNS não propagou).
- **Modo produto** (motor, aditivo, gate 8/8+37 verde): 8 produtos, grid→detalhe, preço no card/detalhe, CTA "Comprar pelo WhatsApp" (`5514991694754`).
- **Tier 2 aplicado:** `index.html` + `sitemap.xml` + `robots.txt` + JSON-LD @graph (mesmos 6 módulos do jpos.com.br).
- **Noemi isolada:** `sdr-motor/backend/cartuchos/pedichinelos.json` (validado, `ok=True`) — **config isolada, não toca a instância de prod** da prospecção de clínica.

## Modelo de preço (ESCOPO 4 — sem inventar valor)
| Item | Preço | Regra |
|---|---|---|
| Chinelo Básico | **R$ 29,99 (unidade)** | único preço fixo; atacado = sob consulta |
| Personalizado | **sob medida** | varia por arte/quantidade |
| Kits | **sob consulta** | preço PRÓPRIO (não é N×unidade) |
| Estampado / Sazonal / Sacochila / Viseira | **sob consulta** | varia por modelo/volume |
| Kits Eventos / Brindes Corporativos | **orçamento sob consulta** | categoria B2B própria |
| Brinde / amostra | (marcar onde você indicar) | prova social, não venda direta |
- **Regra de ouro de pricing:** se algum dia o painel sugerir preço automático, **nunca abaixo de
  2x o custo**. Hoje não há auto-pricing — tudo é "sob consulta" até você confirmar.
- **Editar preço/produto/foto:** pelo painel existente — `site_editor.py` (`/api/site/editar`),
  edita catálogo por comando em português. Não precisa de painel novo.

## O que REAPROVEITAR (não reconstruir)
| Necessidade | Já existe | Onde |
|---|---|---|
| Formulário de input de dados | **`/studio/combo`** (onboarding 3 perguntas) + `/studio` (form completo) | `builder_web.py` |
| Editar catálogo/preço/foto | `site_editor.py` + `/api/site/editar` | painel-operacoes |
| Gerar site | `montar_site` (motor) | motor-site |
| SDR por instância | cartucho isolado (`cartuchos/<id>.json`) | sdr-motor |
| Nova vertical de produto | campo `brief.produtos` (genérico — qualquer produto, não só chinelo) | motor-site |

**Adicionar outra vertical depois = novo cartucho com `produtos`, zero rebuild.** A estrutura já é genérica.

## Painel operador em p.chinelospedi.com — HOLD
Bloqueado no **DNS** (NS de parking `lunar/solar.dns-parking.com` ainda no GoDaddy). Além disso,
o painel de edição **já existe** (studio + site_editor) — quando o DNS limpar, é só um bloco Caddy
apontando `p.chinelospedi.com` → o painel existente (auth), não um app novo. **Não construí painel
novo** (véspera de sprint + redundante).

---

## SETUP DE TIER 3 (documentado — NÃO construído; gated atrás de Tier 2 provado)

Tier 3 = cliente pagante EXTERNO, self-serve, na conta/custo dele. O que Pé Di/JPOS fazem hoje é
**dogfood** (você opera). Pra virar Tier 3 de verdade faltam 4 peças (o SPEC trava até Tier 2 provado):

1. **Formulário self-serve do cliente** — hoje `/studio/combo` é interno (3 perguntas). Tier 3
   precisa de versão cliente-facing com: dados da marca + **lista de produtos (nome/preço/foto)** +
   cor + **upload de foto real**. Spec: estender o combo pra N produtos + upload → gera cartucho
   automático. **Esforço M.** (É o "formulário automático de input" que você pediu — a base existe.)
2. **OAuth Google por cliente** (Calendar/planilha na conta dele, não no SA da JPOS). Não construído.
3. **2 Groq keys do cliente** validadas (chamada real rejeita inválida) — a IA roda no custo dele.
4. **Isolamento de custo multi-cliente** (cada cartucho/tenant com billing próprio).

**Gate (SPEC, não-negociável):** Tier 3 só começa depois do **Tier 2 PROVADO em produção**
(GSC aceita sitemap + Rich Results OK + evento GA4 real no jpos.com.br) — que ainda depende dos
2 passos manuais (verificar domínio no GSC + criar property GA4). Ver o fluxo em
`motor-site/STATUS_TIER2.md`.

**Ordem pra habilitar Tier 3 (pós-sprint):** provar Tier 2 → estender o form (#1, reusa combo) →
gate de key Groq + OAuth (#2/#3) → isolamento (#4). Cada um é incremento sobre o que já existe.
