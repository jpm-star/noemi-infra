# Como gastar menos token sem entregar menos

Registro do método, pra repetir. Cada regra saiu de um desperdício real observado nesta
operação — não é teoria de eficiência.

---

## 1. Scout barato antes de agente caro

Antes de abrir qualquer agente, eu rodo 2-4 comandos de shell e leio o essencial. Um `grep`
custa ~200 tokens; um agente que descobre a mesma coisa sozinho custa 20-50 mil, porque
precisa explorar, errar caminho e reler arquivo.

**Medido nesta rodada dos 3 bloqueios:**

| Bloqueio | Descoberto por scout inline | O que o agente teria gasto |
|---|---|---|
| Teto de disparo | as variáveis são **legado**, ninguém as lê; o limite real é `limite_do_dia()` | ler config.py + prospeccao.py + rastrear uso |
| Instância caída | o nome é `'joao mirandola '` **com espaço no fim** — daí o 404 | tentar a API, tomar 404, investigar rota, achar o encoding |
| Abertura reprovada | templates vivem no cartucho, chave `templates_abertura` | rastrear do QA gate até a origem |

Os três diagnósticos ficaram prontos em **6 comandos**. Os agentes receberam a resposta e
foram direto executar — que é onde eles valem o preço.

**Regra:** o agente é caro para *descobrir* e barato para *fazer*. Descubra você, delegue o
fazer.

## 2. Contexto embutido no prompt, não redescoberto

Todo prompt de agente abre com um bloco `CTX` que já entrega: caminho dos repos, como rodar
os testes, **a baseline de falhas** (558 passed / 10 failed pré-existentes), a chave da API,
e as regras do repo.

O item que mais economiza é a **baseline**. Sem ela, todo agente que roda a suíte vê 10
falhas, acha que quebrou algo e gasta uma rodada inteira investigando o que não é dele. Já
aconteceu comigo nesta sessão — precisei medir a baseline com um worktree separado para
provar que as falhas eram anteriores.

**Regra:** o que você já sabe e o agente vai precisar, escreva no prompt. Uma linha sua
economiza uma rodada de exploração dele.

## 3. Paralelizar só o que é independente

Os 3 bloqueios não se tocam: limite de disparo, instância Evolution e texto de abertura.
Rodam juntos, e o tempo total é o do mais lento em vez da soma.

O que **não** paralelizei: a verificação. É um agente só, porque as três checagens são
baratas, rodam no mesmo ambiente e precisam do resultado das três correções. Três
verificadores seriam três vezes o custo pelo mesmo veredito.

**Regra:** paralelismo economiza *tempo*, não token. Só multiplique agentes quando eles
cobrem coisas que um sozinho não cobriria.

## 4. Um verificador cético vale mais que três executores

O padrão que uso: N agentes fazem, 1 agente **cético** confere executando. O prompt dele
diz explicitamente "relato sem prova executada conta como NÃO RESOLVIDO".

Isso pega a falha mais cara que existe em orquestração: o agente que relata sucesso sem ter
verificado. Custa 1 agente e evita eu reportar a você algo que não funciona — que é o
desperdício de verdade, porque volta como retrabalho.

## 5. Cache no lugar do caminho crítico

Fora de agentes, a mesma lógica vale para LLM em produção:

- **Objeções de cold call**: eram geradas por request. A página de campo ficava minutos
  carregando. Passaram para cache em disco, geradas offline por `--aquecer`: **263 ms**.
- **Acervo de fotos**: por *segmento*, não por cliente. As 4 fotos de pet shop servem os 99
  leads de pet shop — uma rodada de visão na vida do segmento em vez de uma por site.
- **Serviços por segmento**: curadoria como fast path, LLM só para segmento novo, cache
  depois. Pet shop custa uma chamada na vida.

**Regra:** trabalho de LLM nunca no caminho de uma request. Se o resultado se repete, ele
tem cache; se o cache tem escopo maior que um cliente, melhor ainda.

## 6. Corrigir o prompt, não as saídas

Quando o juiz reprovou 27 de 33 objeções, a tentação era reescrever as 27. O que resolveu
foi **uma** mudança no prompt do gerador: dar a ele o mesmo contrato que o juiz cobrava.
Aprovação de 18% → 62%.

**Regra:** N reprovações do mesmo tipo apontam para o prompt, não para as N saídas. Um
conserto na origem em vez de N no destino.

## 7. Falha lembrada não vira avalanche

`script_call.objecoes()` re-tentava a cada lead quando o LLM falhava — 65 leads, 8
combinações, 40+ chamadas em rajada. O retry amplificava o 429 que o causou. Um `set` de
combinações já falhadas no processo resolveu.

**Regra:** cache o sucesso *e* a falha. Retry sem memória é multiplicador de custo.

---

## Resumo operacional

| Faça | Em vez de |
|---|---|
| 4 comandos de scout | 1 agente descobrindo sozinho |
| Contexto + baseline no prompt | agente re-explorando o repo |
| Paralelo só se independente | fan-out por precaução |
| 1 verificador cético | 3 executores redundantes |
| Cache offline | LLM na request |
| Consertar o prompt | consertar as saídas |
| Lembrar a falha | re-tentar sempre |
