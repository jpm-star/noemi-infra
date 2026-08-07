# Poda da biblioteca de referência — lista e recomendação

**Data:** 2026-08-07 · **Tabela:** `templates_referencia` em `/root/noemi-infra/data/noemi.db`
**Nada foi executado.** Zero DELETE, zero UPDATE. Este arquivo é só a lista e o julgamento.

---

## 1. Retrato

| | |
|---|---|
| linhas totais | **171** medido em 2026-08-07 (as 166 originais + ids 167-171, uploads de 2026-08-07 01:53, segmento `academia`, `aprovada=0`) |
| aprovadas | 91 |
| pendentes (aprovada=0) | 75 sobre as 166 originais (80 contando os 5 uploads novos) |
| aprovadas **úteis** (segmento com receita) | 52 — clinica 28, academia 10, advocacia 9, salao 4, imobiliaria 1 |
| aprovadas **órfãs** (segmento sem receita) | **39 (42,9%)** — servicos 32, generico 6, restaurante 1 |

Órfã = `pool()` monta o pool a partir do segmento resolvido do nicho do lead. Nenhum lead
resolve para `servicos`/`generico`/`restaurante`, então essas 39 linhas estão aprovadas e
**nunca são lidas por geração nenhuma**. Não contaminam nada; só inflam o número.

Tamanho real dos pools hoje (default + aprovadas, ordens distintas):
clinica 31 · academia 11 · advocacia 11 · salao 6 · imobiliaria 3.

---

## 2. Lista completa do que seria removido (39 linhas)

Quebrei em 4 grupos porque o balde `servicos` **não é homogêneo** — a decisão é diferente
por grupo.

### GRUPO A — clínica/estética brasileira gravada em `servicos` (erro de rótulo) — 10 linhas

| id | segmento | tag | criado em | hero | ordem gravada (receita) |
|---|---|---|---|---|---|
| 17 | servicos | `clini.site/estetica-isabela` | 2026-08-05 18:57 | - | sobre > formulario > depoimentos |
| 18 | servicos | `clinicarobertaramos.com.br/` | 2026-08-05 18:57 | - | antesdepois > formulario > catalogo > sobre > depoimentos |
| 21 | servicos | `harmoniejau.com.br/` | 2026-08-05 18:57 | - | depoimentos > antesdepois > sobre > preco > catalogo_motion > formulario > catalogo |
| 22 | servicos | `dermique.com.br/` | 2026-08-05 18:57 | - | catalogo_motion > depoimentos > antesdepois > sobre > formulario |
| 23 | servicos | `sites.google.com/view/fabianaperrone/in%C3%ADcio` | 2026-08-05 18:57 | - | antesdepois > catalogo > formulario > depoimentos |
| 24 | servicos | `draisralenestrela.com/` | 2026-08-05 18:57 | - | antesdepois > sobre > depoimentos > catalogo_motion > formulario > calculadora > catalogo |
| 25 | servicos | `cybeleprovenzano.com.br/` | 2026-08-05 18:57 | - | antesdepois > catalogo > depoimentos > sobre > formulario |
| 26 | servicos | `soniaestetica.com.br/` | 2026-08-05 18:57 | - | antesdepois > sobre > catalogo > preco > depoimentos > formulario |
| 27 | servicos | `proesteticaoficial.com.br/` | 2026-08-05 18:57 | - | antesdepois > preco > depoimentos > sobre > catalogo_motion > formulario > faq |
| 28 | servicos | `esteticajulianafredericci.com.br/` | 2026-08-05 18:57 | - | faq > sobre > depoimentos > antesdepois > catalogo > preco > formulario |

### GRUPO B — lixo de scraping (nem é site de negócio) — 2 linhas

| id | segmento | tag | criado em | hero | ordem gravada (receita) |
|---|---|---|---|---|---|
| 19 | servicos | `cnes.datasus.gov.br/pages/estabelecimentos/consulta.jsp?search=2790475` | 2026-08-05 18:57 | - | catalogo > formulario > sobre > preco |
| 20 | servicos | `cnes.datasus.gov.br/` | 2026-08-05 18:57 | - | catalogo > sobre > faq > formulario > catalogo_motion > preco |

### GRUPO C — estúdio de design / SaaS estrangeiro (`servicos` + `generico`) — 26 linhas

| id | segmento | tag | criado em | hero | ordem gravada (receita) |
|---|---|---|---|---|---|
| 31 | generico | `anidachi.com` | 2026-08-05 19:51 | video | sobre > formulario > depoimentos |
| 33 | servicos | `peterhintondesign.co.uk` | 2026-08-05 19:51 | video | catalogo > catalogo_motion > sobre > formulario |
| 34 | servicos | `framer.link` | 2026-08-05 19:51 | video | faq > depoimentos > catalogo_motion > catalogo > formulario > preco |
| 37 | generico | `goodman-gallery.com` | 2026-08-05 19:51 | video | catalogo_motion > sobre > preco > formulario |
| 38 | servicos | `twelvelabs.io` | 2026-08-05 19:51 | video | preco > formulario > depoimentos > sobre > catalogo_motion |
| 39 | servicos | `freehand.ai` | 2026-08-05 19:51 | video | catalogo > formulario > sobre > faq > depoimentos > calculadora |
| 41 | servicos | `mobbin.com` | 2026-08-05 19:51 | video | preco > catalogo > formulario |
| 44 | servicos | `bymonolog.com` | 2026-08-05 19:51 | video | sobre > catalogo > formulario > depoimentos > catalogo_motion > calculadora |
| 45 | servicos | `zamp.com` | 2026-08-05 19:51 | - | catalogo > preco > sobre > formulario > depoimentos > catalogo_motion |
| 46 | servicos | `tastelabs.com` | 2026-08-05 19:51 | video | sobre > preco > faq > catalogo_motion > formulario > catalogo |
| 47 | generico | `estudioniksen.com` | 2026-08-05 19:52 | video | catalogo > depoimentos > sobre > formulario |
| 49 | servicos | `clay.com` | 2026-08-05 19:52 | video | depoimentos > catalogo_motion > preco > sobre > formulario > faq |
| 50 | servicos | `goodside.studio` | 2026-08-05 19:52 | video | sobre > formulario > catalogo |
| 51 | servicos | `okaydev.co` | 2026-08-05 19:52 | video | catalogo_motion > depoimentos > catalogo > sobre > preco > faq > formulario |
| 52 | servicos | `deadwater.fr` | 2026-08-05 19:52 | video | catalogo_motion > catalogo > formulario |
| 53 | servicos | `reducations.com` | 2026-08-05 19:52 | - | sobre > depoimentos > faq > formulario |
| 54 | servicos | `fairground.studio` | 2026-08-05 19:52 | video | sobre > formulario > catalogo |
| 55 | servicos | `tokens.studio` | 2026-08-05 19:52 | video | catalogo_motion > catalogo > preco > sobre > depoimentos > formulario |
| 56 | generico | `nuraform.com` | 2026-08-05 19:52 | video | preco > faq > formulario > sobre > catalogo_motion > depoimentos |
| 68 | servicos | `evilmartians.com` | 2026-08-05 19:58 | - | catalogo > calculadora > preco > catalogo_motion > faq > formulario |
| 69 | generico | `usefoulplay.com` | 2026-08-05 19:58 | video | catalogo > depoimentos > sobre > formulario |
| 70 | servicos | `granola.ai` | 2026-08-05 19:58 | - | depoimentos > catalogo_motion > preco > sobre > formulario |
| 84 | servicos | `shiftnudge.com` | 2026-08-05 20:00 | - | depoimentos > sobre > faq > catalogo_motion > formulario |
| 85 | servicos | `designcode.io` | 2026-08-05 20:00 | - | preco > sobre > formulario |
| 86 | generico | `offscreencanvas.com` | 2026-08-05 20:00 | - | depoimentos > catalogo_motion > sobre > faq > formulario |
| 87 | servicos | `stripe.press` | 2026-08-05 20:00 | video | catalogo_motion > sobre > catalogo > antesdepois > depoimentos > formulario > calculadora > preco |

### GRUPO D — ramo real sem receita (`restaurante`) — 1 linha

| id | segmento | tag | criado em | hero | ordem gravada (receita) |
|---|---|---|---|---|---|
| 35 | restaurante | `drinkmeli.com` | 2026-08-05 19:51 | video | catalogo > catalogo_motion > sobre > formulario > faq > depoimentos > preco |

---

## 3. Classificação, com o critério explícito

### `servicos` e `generico` = **morto de verdade** (como balde)

Critério: o rótulo não descreve um ramo de negócio. `servicos` e `generico` são o "resto"
de um classificador — não viram receita porque não há um argumento de venda comum a
"clínica de estética + agência de design + SaaS de IA". Uma receita é ordem de argumento;
sem ramo, não há argumento. Nenhum lead da base resolve para eles: `segmento_de()` só
devolve as 5 chaves vivas ou `""`.

**Mas o balde está morto, não o conteúdo.** 12 das 32 linhas de `servicos` (grupos A e B)
são **clínicas de verdade** — casei a coluna `imagem` (URL) com `leads_clinicas.website`:

| id | lead de origem | categoria |
|---|---|---|
| 17 | Estética Isabela Atanásio - Clínica Xingu | clínica de estética |
| 18 | Clínica de Estética Avançada Roberta Ramos | clínica de estética |
| 19 | CS III Martiniano Cruz de Guaicara | clínica médica |
| 20 | Estratégia da Saúde da Família Nelson Thomaz | clínica médica |
| 21 | L'Harmonie Estética Avançada | clínica de estética |
| 22 | Dermique Clínica \| Dra. Vanuire Rizzo Limeira | clínica de estética |
| 23 | Clínica Dra. Fabiana Perrone | clínica de estética |
| 24 | Dra Isralen Estrela \| Estética Facial e Corporal | clínica de estética |
| 25 | Clínica de Estética e Emagrecimento Cybele Provenzano | clínica de estética |
| 26 | Clínica Sônia Estética em Americana | clínica de estética |
| 27 | Clínica Pró Estética | clínica de estética |
| 28 | Juliana Fredericci Estética | clínica de estética |

Ou seja: **o rótulo `servicos` foi erro de classificação na ingestão, não um segmento.**
As linhas 19 e 20 caíram no grupo B porque o lead é clínica mas o `website` do lead aponta
para o **cadastro do CNES (datasus.gov.br)** — a clínica não tem site, e o coletor leu o
layout de um formulário do governo como se fosse referência de design.

### `restaurante` = **hold fraco**

É ramo real (vira receita no dia que houver lead), mas medi a base e o hold não se sustenta
hoje:

- `leads_cnpja` (37.070): segmentos existentes são **cabeleireiro 17.723, estetica 6.672,
  medico 3.874, advocacia 3.311, odontologia 1.853, imobiliaria 1.573, fisioterapia 1.058,
  academia 1.006**. Nenhum de alimentação.
- Busca por `restaur|pizzar|lanchon|food|gastron|cafeter|padari|bar` nas 3 tabelas
  (`leads_cnpja`, `leads_clinicas`, `leads_alvo`): **todos os hits são falso-positivo** —
  "Restauração Dental" (dentista), "Escobar" (sobrenome), "Clean Foods" (academia),
  "Esmalteria e Bar".

**Leads de restaurante hoje: 0.** Hold com zero lead é hold fraco: guardar 1 linha de
`drinkmeli.com` não custa nada, mas não é motivo para criar a receita `restaurante`. Fica
como semente inerte — se um dia entrar lead do ramo, essa linha é o ponto de partida.

---

## 4. Dá para reclassificar em vez de descartar?

O campo `receita` guarda `{ordem, hero}` — a **ordem das seções**, que é ordem de argumento.
Então a pergunta "essa estrutura serve a clínica?" tem resposta mensurável. Usei 3 sondas
sobre a ordem gravada:

- **sem prova** — não tem `depoimentos` nem `antesdepois` em lugar nenhum
- **preço antes da prova** — `preco` aparece antes de qualquer prova social
- **rasa** — menos de 4 blocos lidos (a visão não conseguiu ler a página)

| grupo | n | sem prova | preço antes da prova | rasa |
|---|---|---|---|---|
| aprovadas vivas (baseline) | 52 | 8 (15%) | 8 (15%) | 3 (6%) |
| **A — clínicas BR** | 10 | **0** | **0** | 1 |
| B — CNES | 2 | 2 (100%) | 2 (100%) | 0 |
| **C — design/SaaS estrangeiro** | 26 | 9 (35%) | 9 (35%) | 6 (23%) |

### Veredito por grupo

**Grupo A (10) — RECLASSIFICAR para `clinica`.** Não é aproveitamento forçado: são
literalmente sites de clínica de estética lidos de leads da base. Zero delas viola a
lógica de confiança do segmento (0 sem prova, 0 preço antes da prova), e 8 das 10 abrem
com `antesdepois` — que é exatamente o argumento de estética e hoje só existe em **1** das
3 receitas default de clínica. É o único ganho real da poda inteira.
Update seria `UPDATE templates_referencia SET segmento='clinica' WHERE id IN (17,18,21,22,23,24,25,26,27,28)`.
**Ressalva honesta:** o pool de `clinica` já tem 31 ordens distintas e a rotação é
`semente % len(pool)` — passar para 41 não melhora variedade percebida, melhora só a
*qualidade média* do que entra no sorteio. Se o objetivo é qualidade, o movimento certo é
reclassificar as 10 **e** despromover (aprovada=0) parte das 28 já lá.

**Grupo B (2) — DESCARTAR.** É o layout de um formulário do governo. Não há segmento a que
sirva. Vale mais que a poda: é um **bug do coletor** — quando `leads_clinicas.website`
aponta para diretório/registro (datasus, Google Sites, Facebook), o site não é do negócio.
Uma lista de domínios-bloqueio na ingestão evita repetir.

**Grupo C (26) — DESCARTAR como receita de estrutura.** O critério não é "é estrangeiro", é
o que a ordem codifica: são portfólios e SaaS B2B, onde `catalogo` é lista de *features* e
o formulário é "book a demo". 35% pedem contato ou preço antes de qualquer prova — para
clínica ou salão local isso é pedir o telefone antes de dar motivo. E 23% são leituras
rasas (3 blocos), sinal de que a visão não conseguiu ler a página (muitas são one-pagers
com scroll animado). Não existe regra de conversão que transporte `preco > catalogo >
formulario` (mobbin.com) para uma clínica de Bauru.
*Aproveitável de outra forma:* o valor desse grupo é **estético** (motion, tipografia,
morfismo), não estrutural — pertence à camada de tema, não a `templates_referencia`. Se o
JP quiser guardar, o lugar certo é um `tipo` novo (a coluna já existe) e **não aprovada**,
para nunca entrar em `pool()`. Descartar a *aprovação* é obrigatório; descartar a *linha* é
opcional.

**Grupo D (1) — HOLD FRACO, manter inerte.** Custa 1 linha. Não criar receita `restaurante`
enquanto houver 0 lead do ramo.

---

## 5. Decisões fechadas (2026-08-07)

1. **RECLASSIFICAR → segmento `clinica`** — 10 ids: 17, 18, 21, 22, 23, 24, 25, 26, 27, 28.
   Motivo: clínica/estética BR rotulada como `servicos` por erro da ingestão.
2. **DESCARTAR** — 2 ids: 19, 20.
   Motivo: cadastro do CNES (datasus.gov.br), não é site de cliente.
3. **DESPROMOVER (`aprovada=0`)** — 26 ids: 31, 33, 34, 37, 38, 39, 41, 44, 45, 46, 47, 49,
   50, 51, 52, 53, 54, 55, 56, 68, 69, 70, 84, 85, 86, 87.
   Motivo: estúdio de design / SaaS estrangeiro; valor é estético, não estrutural.
4. **HOLD** — 1 id: 35 (segmento `restaurante`).
   **Ressalva registrada:** existem **ZERO leads** desse ramo nos 37.070 da base `leads_cnpja`.
   A busca por `restaur|pizzar|lanchon|food|gastron|padari|bar` nas 3 tabelas de lead deu
   **só falso-positivo** ("Restauração Dental", "Escobar", "Clean Foods", "Esmalteria e Bar").
   Chamar isso de "morto por enquanto" é otimismo: não há nenhum lead a caminho. O hold é
   semente inerte, não previsão.

Efeito esperado: `pct_orfas` de `diagnostico_biblioteca()` cai de 42,9% para ~1,6% (sobra só
a linha 35), e "91 aprovadas" passa a significar o que aparenta.

---

## 6. SQL pronto — **NÃO EXECUTADO**

Banco: `/root/noemi-infra/data/noemi.db`. Nada abaixo rodou. Aprovação manual do JP antes de
qualquer execução. Backup dos sites: `/root/backup-sites-pre-regen-20260807/`.

```sql
-- ========== NÃO EXECUTADO — aguardando aprovação manual ==========

-- Ação 1 — RECLASSIFICAR clínica/estética BR (10 linhas)
-- UPDATE templates_referencia SET segmento='clinica'
--  WHERE id IN (17,18,21,22,23,24,25,26,27,28);

-- Ação 2 — DESCARTAR cadastro CNES (2 linhas)
-- DELETE FROM templates_referencia WHERE id IN (19,20);

-- Ação 3 — DESPROMOVER estúdio de design / SaaS estrangeiro (26 linhas)
-- UPDATE templates_referencia SET aprovada=0
--  WHERE id IN (31,33,34,37,38,39,41,44,45,46,47,49,50,51,52,53,54,55,56,
--               68,69,70,84,85,86,87);

-- Ação 4 — HOLD id 35: nenhum comando. Nada a executar.

-- Conferência (leitura, seguro rodar):
-- SELECT segmento, aprovada, COUNT(*) FROM templates_referencia
--  GROUP BY segmento, aprovada ORDER BY 1,2;
```
