# Radar — profundidade analítica: antes/depois

Rubrica (TestFit, descrita pelo JP): (1) MECANISMO específico — por que ISSO converte, não o
que a ferramenta faz; (2) SEGMENTAÇÃO por público — dor + ângulo; (3) REPLICAÇÃO — template
concreto de COMO replicar.

## Veredito do estado atual: **RASO** — mas a culpa não é do prompt

| id | mecanismo (1) | segmentação (2) | replicação (3) |
|---|---|---|---|
| 258 | sim — 'inversão de culpa psicológica' é mecanismo real | não | **não** — `modelos` vazio |
| 257 | **não** — 'reduzir fricção aumenta conversão' serve pra qualquer produto | não | **não** — `modelos` vazio |
| 250 | **não** — descreve o QUE é (open-source, 129k stars, um clique) | não | **não** — `modelos` vazio |
| 243 | parcial — nomeia os 3 passos, não diz por que o snapback prende | não | **não** — `modelos` vazio |
| 233 | parcial — 'diagnóstico antes de apresentação' insinua o mecanismo | não | **não** — `modelos` vazio |
| 229 | parcial — 'alterna ganho e perda' é mecânica, sem o porquê | não | **não** — `modelos` vazio |
| 201 | **não** — dá o número (100x), não a causa (intenção quente / 1º a responder ancora) | não | **não** — `modelos` vazio |
| 184 | **não** — descreve o QUE é (skill grátis substitui scraper pago) | não | **não** — `modelos` vazio |

**5 de 8 falham no item (1)** — descrevem o QUE em vez do PORQUÊ. **8 de 8 falham no (3)**:
o campo `modelos` (o único que carrega template replicável) está `{}` ou `null` nos oito.
**8 de 8 falham no (2)**: `vertical` vazio, e não existe campo de ângulo-por-público.
Fora do top-8 o quadro é o mesmo: de 299 análises com score>=7, só 94 (31%) têm `modelos`.

---

## O experimento — e por que o prompt não era o problema

Editei os prompts (`_PROMPT_BASE`) pra exigir os 3 itens, reprocessei os 8, e o resultado
**piorou**. Aí rodei dois controles que mudam o diagnóstico inteiro:

| # | prompt | modelo | resultado |
|---|---|---|---|
| A | original | `analise` (llama-3.3-70b) — **hoje** | raso, pior que o que está no banco |
| B | novo (3 itens exigidos) | `analise` (llama-3.3-70b) | **muito pior** — telegráfico |
| C | **original** | `fallback-anthropic` (Haiku 4.5) | **passa na rubrica** |

Controle A é o que mata a hipótese "prompt raso": com o prompt **original**, o modelo de hoje
já produz menos que o que está gravado no banco (1-2 hooks em vez de 6, `modelos` trivial).
Ou seja — a profundidade que existe no banco veio de um modelo mais forte, não do prompt.

### O que o prompt novo fez no llama-70b (por isso foi revertido)

| id | antes (banco) | com meu prompt novo |
|---|---|---|
| 243 | O Triple Hook Method é uma fórmula de 3 passos (Context → Lean → Contrarian Snapback) que torna hooks cientificamente impossíveis de pular, baseada em | **Hipnose PORQUE Contexto, Lean e Contrarian Snapback** |
| 258 | Reativação de leads dormentes via inversão de culpa psicológica: remover toda pressão explícita e implícita, reposicionar a resposta como ato de gener | **Resposta PORQUE remoção da pressão e criação de ambiente confortável** |
| 229 | Todo anúncio/oferta cabe em 4 quadrantes (mais bom/menos bom/mais ruim/menos ruim); a persuasão eficaz alterna entre promessas de ganho e ameaças de p | **Decisão PORQUE matriz de recompensas e punições** |

O molde `"<efeito> PORQUE <mecanismo>"` virou um atrator: o 70b preencheu a forma e jogou o
conteúdo fora (`"Hipnose PORQUE Contexto, Lean e Contrarian Snapback"` — a forma da rubrica,
zero mecanismo). Pior: copiou meu placeholder literalmente em `modelos` —
`"Faça X em Y para criar um hook..."`. E os hooks caíram de 6 citações verbatim pra 1 paráfrase.
**Não foi texto mais longo e vazio: foi mais curto e mais vazio.** Revertido.

---

## ANTES / DEPOIS (depois = prompt ORIGINAL rodando no Haiku)

### id 258 — @alexfcoaches

**ANTES** (banco):

> Reativação de leads dormentes via inversão de culpa psicológica: remover toda pressão explícita e implícita, reposicionar a resposta como ato de generosidade do lead (feedback para melhorar), e fechar

- `modelos`: `{}`
- `vertical`: `''`

**DEPOIS** (mesmo prompt, Haiku):

> Lead dark responde não por chase repetido, mas por remoção de pressão + reposicionamento do feedback como valor para o vendedor aprender; inverte dinâmica de poder (de 'você me deve resposta' para 'sua honestidade me ajuda').

- `modelos`:
  - **operacao**: Lead dark: remover expectativa → oferecer saída honrosa → reposicionar feedback como valor para aprendizado do vendedor
  - **projeto**: Sequência de reativação: voicemail/SMS/email com 3 camadas psicológicas (permissão + legitimidade + benefício)
- `vertical`: `''` · hooks: 6 (antes 6)

### id 257 — @moneymindnews

**ANTES** (banco):

> Reduzir fricção e simplicidade na oferta (design, copy, CTA) aumenta conversão exponencialmente — exemplo: botão 'Continue as Guest' gerou $300M extra no Best Buy.

- `modelos`: `{}`
- `vertical`: `''`

**DEPOIS** (mesmo prompt, Haiku):

> Reduzir fricção cognitiva e física na jornada de compra (remover etapas, simplificar linguagem) converte 2.3x mais porque o cérebro escolhe a opção de menor resistência neurológica, não a melhor opção.

- `modelos`:
  - **site**: Reduzir campos obrigatórios de N para 3 (nome, telefone, serviço); capturar dados faltantes pós-conversão
  - **negocio**: Testar CTA única vs. múltiplas rotas; linguagem 5ª série vs. profissional; medir taxa de abandono
  - **operacao**: Remover uma etapa de fricção por semana; medir impacto em conversão; iterar
- `vertical`: `''` · hooks: 5 (antes 4)

### id 250 — @maxjohnscn

**ANTES** (banco):

> Agência de IA completa, open-source no GitHub com 129k stars, entregue pronta em um clique via desktop app, eliminando a necessidade de construir infraestrutura própria.

- `modelos`: `{}`
- `vertical`: `''`

**DEPOIS** (mesmo prompt, Haiku):

> Venda de acesso a ativo validado (129k stars GitHub) via especialização de agentes IA + barreira de atrito mínima (comentário público) que força comprometimento e alimenta algoritmo.

- `modelos`:
  - **video**: Abertura com número específico + inversão de expectativa + exemplos concretos + síntese de valor + CTA com barreira mínima (comentário público)
  - **negocio**: Distribuição gratuita de ativo validado via prova social (stars) + monetização indireta via engagement (comentários alimentam algoritmo) + setup guide como lead magnet
  - **operacao**: Especialização em agentes (16 departamentos) em vez de IA monolítica — cada agente otimizado para uma função específica com 'personality and processes' próprios
- `vertical`: `''` · hooks: 5 (antes 6)

### id 243 — @kallawaymarketing

**ANTES** (banco):

> O Triple Hook Method é uma fórmula de 3 passos (Context → Lean → Contrarian Snapback) que torna hooks cientificamente impossíveis de pular, baseada em dados de skip rate.

- `modelos`: `{}`
- `vertical`: `''`

**DEPOIS** (mesmo prompt, Haiku):

> O Triple Hook Method usa 3 camadas sequenciais (contexto imediato + lean com validação/dor + contrarian snapback) para forçar retenção neurológica: contexto ambíguo ativa padrão de skip em <500ms, lean abre loop de Zeigarnik (incompletude cognitiva), snapback inverte expectativa 

- `modelos`:
  - **video**: Estrutura: [Contexto imediato em áudio+visual+texto alinhados] → [Lean com proof/stat/pain point/shocking] → [Snapback contrarian invertendo expectativa]
  - **operacao**: Auditoria de hooks: verificar se primeiro frame/frase responde 'Para quem? Qual dor?' em <5 palavras; se não, reescrever com contexto + lean + snapback
- `vertical`: `''` · hooks: 6 (antes 6)

### id 233 — @brunofragaoficial

**ANTES** (banco):

> Cultura comercial (diagnóstico antes de apresentação) vence apresentação de slides; transformar atendentes em vendedores que fecham via método, não via PowerPoint.

- `modelos`: `{}`
- `vertical`: `''`

**DEPOIS** (mesmo prompt, Haiku):

> Diagnóstico antes de apresentação é o filtro que separa vendedor de amador: sem responder dor+consequência+custo de inação, a apresentação é transferência de responsabilidade do vendedor pro cliente, matando conversão em 90% dos casos.

- `modelos`:
  - **video**: Gancho de rejeição ao padrão → nomear dor específica (atendente que só responde, vendedor que espera pedido) → inversão causal (diagnóstico ANTES de apresentação) → 3 perguntas obrigatórias (dor, cons
  - **negocio**: Venda de metodologia/treinamento de cultura comercial (não ferramenta): diagnóstico → playbook → transformação de atendentes em vendedores.
  - **operacao**: Sequência de venda: 1) Pergunta dor, 2) Pergunta consequência, 3) Pergunta custo de inação, 4) Se sim em todas, apresenta solução; se não, desqualifica.
- `vertical`: `'serviços-b2b-com-time'` · hooks: 7 (antes 5)

### id 229 — @avidreadershow

**ANTES** (banco):

> Todo anúncio/oferta cabe em 4 quadrantes (mais bom/menos bom/mais ruim/menos ruim); a persuasão eficaz alterna entre promessas de ganho e ameaças de perda.

- `modelos`: `{}`
- `vertical`: `''`

**DEPOIS** (mesmo prompt, Haiku):

> Hormozi estrutura toda persuasão em 4 quadrantes (++/+-/-+/--) que sobrepõem ganho e aversão à perda simultaneamente, eliminando objeções antes de nascerem ao forçar o prospect a processar tanto o benefício da ação quanto a dor da inação.

- `modelos`:
  - **video**: Abertura com nomenclatura matemática (++/+-/-+/--) → explica cada quadrante → revela padrão oculto → exemplo concreto em camadas (corpo/ego/futuro) → ping pong rítmico
  - **negocio**: Mapear 4 quadrantes por vertical: (++) ganho imediato específico; (--) dor cumulativa futura; (+-) perda de benefício; (-+) alívio/segurança
- `vertical`: `''` · hooks: 4 (antes 4)

### id 201 — @hormozi

**ANTES** (banco):

> Responder leads em 5 minutos em vez de 30 minutos aumenta 100x a taxa de contato e permite 4x as vendas sem mudar anúncios, script ou oferta.

- `modelos`: `null`
- `vertical`: `None`

**DEPOIS** (mesmo prompt, Haiku):

> Resposta a leads em <5min vs 30min gera 100x mais contatos bem-sucedidos porque captura o pico neurológico de motivação (dopamina+comprometimento) antes da dissipação por distração, fricção mental e concorrência — é otimização operacional pura, não criatividade.

- `modelos`:
  - **operacao**: Resposta automática personalizada em <5min pós opt-in + qualificação de intenção para reter motivação neurológica
- `vertical`: `''` · hooks: 4 (antes 3)

### id 184 — @leadgenman

**ANTES** (banco):

> Substituir web scrapers pagos por um skill gratuito no Claude que automatiza extração de leads de qualquer site.

- `modelos`: `null`
- `vertical`: `None`

**DEPOIS** (mesmo prompt, Haiku):

> Destruição de modelo de custo recorrente (scrapers pagos $100-300/mês) via democratização técnica (Claude + GitHub skill em plain English), convertendo barreira cognitiva em permissão mental para experimentação imediata.

- `modelos`:
  - **video**: Abertura com negação de status quo (custo recorrente) → remoção de barreira técnica (plain English) → amplitude de casos de uso → prova técnica (adaptação automática) → CTA emocional (comentário + lea
  - **negocio**: Destruição de modelo de vendor lock-in (scrapers pagos) → democratização técnica → captura de leads via comentário + DM
  - **operacao**: Instalação de GitHub skill → input em plain English → processamento automático → output estruturado → reutilização em múltiplos sites
- `vertical`: `'arbitragem'` · hooks: 5 (antes 3)

---

## Julgamento honesto

**Aumentou profundidade, não tamanho** — mas quem aumentou foi a troca de modelo, não o prompt.
Provas de que é profundidade e não volume:

- `modelos` saiu de **0/8** pra **8/8** preenchidos, com template imperativo e parâmetro
  concreto (ex. 243: *"verificar se o primeiro frame responde 'Para quem? Qual dor?' em <5
  palavras; se não, reescrever"*) — isso é o item (3) da rubrica, que faltava em todos.
- O resumo passou a abrir pelo mecanismo sem eu pedir (243: *"contexto ambíguo ativa padrão
  de skip em <500ms"*; 250: *"barreira de atrito mínima (comentário público) que força
  comprometimento e alimenta algoritmo"* — antes era *"open-source com 129k stars, um clique"*).
- Hooks continuam verbatim e em quantidade — não houve troca de citação por prosa.

O item (2), segmentação por público, **continua não resolvido** em nenhum dos dois. Não existe
campo pro ângulo-por-segmento, e enfiar isso em `hooks` (o que tentei) destrói o valor do
campo — os hooks verbatim viram paráfrase genérica. Se o JP quiser (2), é campo novo, não
instrução nova.

## O que ficou no código

- Prompts: **revertidos**, byte a byte. Trocar prompt que funciona por prompt que o modelo
  fraco preenche como formulário é regressão.
- Única mudança mantida: `resumo` truncava em 200 chars e cortava a oração do mecanismo
  (id 258 acabava em *"e fechar"*, id 243 em *"lea"*). Agora 280. **6 dos 8** resumos novos
  passam de 200 — o cap estava decepando exatamente a parte que a rubrica cobra.

## Onde está o gargalo real

`analise` → `groq/llama-3.3-70b-versatile`. Ele consegue *estruturar*, não consegue *julgar*:
no Pass 1 ele parafraseia a transcrição e chama isso de causa raiz. Nenhum prompt conserta isso.
Opção barata e cirúrgica: rotear **só o Pass 1** (o passo de julgamento) pro Haiku e deixar o
Pass 2 (estruturar em JSON) no Groq. Custo medido nesta rodada: ~US$0,03 por vídeo nos 8
itens com os dois passos no Haiku — só o Pass 1 sai por menos. Não mexi nisso: é decisão de
custo do JP, não de código.
