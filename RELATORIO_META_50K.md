# Meta R$50.000 / 27 dias úteis — o que foi construído e o que os números dizem

Data: 2026-08-06 · branch `feat/caixa-ideias-item2` (noemi-infra) + `feat/jpos-tier1`
(motor-site) + `feat/refundacao-noemi-jpos` (sdr-motor). **Nada foi deployado nem
disparado.** O kill switch de prospecção segue como estava.

---

## 0. Antes das tarefas: três números que mudam o plano

### 0.1 O funil não tem 1.100 leads de cold call — tem 65

| Tier | Leads | Canal |
|---|---:|---|
| T1 | 414 | WhatsApp (Noemi) |
| T2 | 1.032 | WhatsApp (Noemi) |
| **T3** | **55** | **cold call / porta-a-porta** |
| **T4** | **10** | **cold call / porta-a-porta** |

Os "1.100 números" da especificação são os **1.446 T1/T2**, do canal automático.
O cold call tem **65**. Isso é bom pra Tarefa 2 (65 scripts com carinho é viável;
1.100 não seria) e é o dado que muda a conta da meta.

### 0.2 A meta pede 42 fechamentos, e o T3/T4 sozinho não chega lá

O contador (Tarefa 4) calcula, com a janela 07/08 → 15/09:

- **R$ 1.851,85 por dia útil**
- na premissa de R$1.200/cliente: **42 fechamentos**

Com 65 leads de cold call, 42 seriam **65% de conversão** — não acontece. A meta
depende do canal WhatsApp (1.446 leads → 42 é ~3%, agressivo mas possível), ou de
ticket maior que R$1.200, ou dos dois. **Esse é o número pra decidir agora, não no dia 20.**
O widget mostra ele subindo a cada dia sem venda.

### 0.3 Duas ferramentas que a especificação assume não existem no servidor

- **Gemini**: a chave em `noemi-infra/.env` responde `429 — "prepayment credits are
  depleted"`. Construí a camada de variação (Tarefa 3) preferindo o Gemini e caindo no
  pool Groq: quando você puser uma chave com saldo, ela passa a ser usada sem trocar
  código.
- **DeepSeek**: não há chave em lugar nenhum. O auditor tem o slot pronto
  (`DEEPSEEK_API_KEY` no `.env` liga sozinho). Enquanto isso o juiz é `gpt-oss-120b`, que
  é o que importa: **arquitetura diferente da do modelo que escreve**.
- **Higgsfield**: a conta conectada por MCP tem **10 créditos, plano free** — não os 860.
  Por isso as fotos não são geradas; são buscadas e julgadas (ver §1).

---

## 1. Demo Rações & Cia — https://p.jpos.com.br/racoes-e-cia/

### O que estava errado (e por quê)

O site saiu com os serviços **"Atendimento / Orçamento / Acompanhamento"** ilustrados por
`service,professional` — foto de reunião de escritório num pet shop.

A causa não era a palavra-chave: era um **dicionário fechado de 5 segmentos**
(odonto/estética/fisio/salão/psico) dentro do motor. Todo o resto casava com o genérico.
Corrigir só o pet shop deixaria o mesmo bug esperando academia, imobiliária e oficina.

### O que mudou

1. **`motor-site/app/servicos.py`** — catálogo por segmento: 11 curados à mão (os 5
   antigos + os 6 com mais leads na base) e **LLM + cache pro resto**. Segmento novo custa
   uma chamada de LLM na vida, não uma por site.
   O casamento é por início de palavra — com substring solta, "clínica do coração" virava
   pet shop (co-**ração**), e uma cardiologia receberia um site de banho e tosa. Isso foi
   pego por um teste, não por leitura.

2. **`acervo_fotos.py`** (novo) — as fotos deixaram de vir de banco aleatório.
   Openverse (busca real, licença comercial, sem chave) traz candidatas; **a visão que já
   roda em produção julga cada uma** e reprova o que não serve. Amostra real do log:

   > `Banho e Tosa: reprovada — "Cão na praia, não banho"`
   > `Consulta Veterinária: reprovada — "Cachorro vestido não ilustra consulta"`
   > `Acessórios: reprovada — "Foco na fachada, não nos produtos"`
   > `Banho e Tosa: APROVADA — "Cão na mesa de tosa profissional"`

   O acervo é **por segmento, não por cliente**: as 4 fotos de pet shop servem os 99 leads
   de pet shop. Da segunda demo em diante é leitura de disco.

3. **Sem foto aprovada, o card vira placa** (gradiente do tema + inicial), nunca foto
   aleatória. O fallback pro `loremflickr` tinha publicado uma **estátua de urso**
   ilustrando "Acessórios e Higiene" — o erro só aparece depois de no ar, na frente do dono.

4. **Transições ligadas ao scroll** (referência lusion.co): `animation-timeline: view()`,
   CSS nativo, dentro de `@supports`. Cortina por `clip-path`, parallax do hero, título
   entrando palavra a palavra, tilt nos cards. Navegador sem suporte fica com a camada
   anterior — nada degrada.

**Resultado:** serviços certos (Banho e Tosa · Ração e Alimentação · Consulta Veterinária ·
Acessórios), 2 fotos reais julgadas + 2 placas sóbrias. Sem estátua de urso.

---

## 2. Tarefa 1 — cartucho de oferta (canal WhatsApp)

`sdr-motor/backend/cartuchos/jpos_prospeccao.json` ganhou o bloco `oferta`, renderizado
por `cerebro.bloco_oferta()`:

- demo grátis, sem cartão;
- **15% pra quem fechar até a sexta desta semana** — com a data escrita;
- handoff: ao sinal de compra real (pergunta de preço, "pode ligar", "manda proposta"),
  a Noemi entrega `wa.me/5514998745847` e **não tenta fechar**;
- objeção fora do escopo → mesma regra, conecta com você.

**A data é calculada a cada conversa, não escrita no arquivo.** Data em JSON envelhece
sozinha e vira promessa vencida dentro da mensagem. Depois de sexta ao meio-dia o prazo já
pula pra semana seguinte — prometer "até hoje" numa sexta à tarde não dá tempo de fechar.

Uma divergência que achei e **não** resolvi por conta própria: o cartucho tem
`whatsapp_dono = 5514991978607` (canal de alerta interno, usado por lembretes/notificações)
e você me passou `5514998745847` como contato. São papéis diferentes, então o link público
usa o seu contato e o alerta interno ficou intocado. Se os dois deviam ser o mesmo número,
me diga qual.

Cartucho sem bloco `oferta` continua exatamente como antes — nenhum cliente ganha oferta
da JPOS por tabela.

---

## 3. Tarefa 2 — script de cold call / porta-a-porta (T3/T4)

`script_call.py` + página **`/obs/campo`** (feita pra imprimir e levar no carro).

Por lead: **abertura de 15 segundos** (com o nome do decisor do QSA quando existe, e o
nome da empresa limpo da cauda de SEO — falar "DVI Radiologia: Radiologia, Exames, Lins SP"
em voz alta entrega que é lista comprada), **3 objeções do segmento com resposta**, e a
**mesma oferta do WhatsApp** (a data vem da mesma regra; se divergir entre canais, quem
ouviu os dois percebe).

**A ordem é o que economiza o dia:** cidades encadeadas por vizinho mais próximo saindo de
Marília, e o score de fit decide só dentro da cidade. Saída real:

```
Marília (0 km) → Garça (+30) → Lins (+63) → Birigui (+110) → Araçatuba (+122) → Tupã
65 leads · 30 cidades
```

Score de fit: T4 vale mais que T3 (oferta maior), e ter o nome do decisor pesa 20 pontos —
é o que muda "posso falar com o responsável?" para "o Wagner está?".

---

## 4. Tarefa 3 — orquestração multi-LLM

| Papel | Modelo | Estado |
|---|---|---|
| Conversa ao vivo (Noemi) | Groq/Llama, pool dedicado | intocado, como você pediu |
| Variação de copy em lote | Gemini → **pool de 10 chaves** | Gemini 429, cai no pool |
| Auditoria adversarial | DeepSeek → **`juiz`** (gpt-oss-120b × 10 chaves) | sem chave DeepSeek |
| Arquitetura + QA | eu | este relatório |

**O achado grande desta tarefa não estava no pedido.** Ao ligar a variação no gateway,
descobri que a infraestrutura de "nunca ter rate limit" estava montada e **desligada**:

1. `docker-compose.yml` declarava as variáveis **uma a uma**, e as 10 `GROQ_POOL_*` nunca
   foram declaradas. Estavam no `.env`, mapeadas no `litellm-config.yaml`, e **o container
   não as via**. `pool-groq` e metade da cascata de fallback estavam mortos. Corrigido com
   `env_file: .env` — o pool respondeu na primeira tentativa depois disso.
2. O painel e o motor-site não exportam `LITELLM_MASTER_KEY`, então **o gateway devolvia
   401 e toda geração de site caía no Groq cru**, onde estourava 429. A cascata existia e
   nunca era usada.
3. **A visão do sistema estava muda.** `qwen3.6-27b` é modelo de raciocínio: gastava os 900
   tokens de teto inteiros dentro do `<think>` e a limpeza (correta) devolvia string vazia.
   A cascata lia "" como "não respondeu", caía pro OCR e virava `sem_visao` — sem erro, sem
   log. Isso afetava também o OCR de fotos na aba Criação. Corrigido com teto de 6000 e
   `reasoning_effort=none`, e agora há um `log.warning` para o caso não voltar calado.

Config que existe no arquivo e não chega no processo é pior que config ausente: parece feita.

---

## 5. Tarefa 4 — contador de ritmo (`/obs/campo`)

Meta, dias úteis restantes (regressiva, com os feriados nacionais da janela), R$ fechado, e
o número que muda decisão: **quanto precisa sair por dia útil**.

Enquanto não houver venda, ele se declara **estimada** com aviso na cara e mostra a
premissa (R$1.200/cliente → 42 fechamentos). Vira **calibrada** sozinho depois de 10
contatos reais no `prospeccao_log`. Um painel que mostra estimativa com cara de fato dá
confiança onde não há informação.

Para sair da estimativa: `POST /api/campo/fechamento {prospect_id, valor}`.

---

## 6. Tarefa 5 — QA gate (o relatório que você pediu antes de autorizar)

`qa_gate.py` roda **três ângulos independentes** (compliance, comercial, realismo) sobre
uma amostra **espalhada** de 12 — não as 12 primeiras, que seriam todas do mesmo segmento
e da mesma cidade.

**Veredito da amostra: ⛔ BLOQUEADO.** Os três ângulos discordaram entre si (prova de que
não são o mesmo teste três vezes):

| Ângulo | ok / reprovados | tipos |
|---|---|---|
| compliance | 5 / 3 | `promessa` ×3 |
| comercial | 4 / 4 | `promessa` ×3, `tom_robotico` ×1 |
| realismo | 5 / 3 | `promessa` ×3 |

Exemplos reprovados:

> "Noemi da JPOS aqui, vocês precisam de um site para aparecer no Google, tenho uma demo
> para te mostrar" → *promessa: promete resultado sem prova*
>
> "Sem um site, a {nome} perde clientes que procuram no Google, quero te mostrar uma
> solução" → *promessa: oferta vaga, falta de clareza*

**O padrão é claro: `promessa` em todos os ângulos.** Pelo próprio critério do gate, isso
manda corrigir o *prompt*, não as frases. Fiz isso nas objeções do cold call e a taxa foi
de ~18% para 2 em 3 com nota 9 — a mesma correção precisa passar pela mensagem de abertura
antes de qualquer disparo.

**Nada é disparado até você olhar isto.** É o gate funcionando, não uma falha.

Duas decisões de projeto que valem citar, porque parecem defeito e são intencionais:
- **Sem veredito é reprovação.** Se o juiz cai, o texto não passa. Um gate que libera
  quando o verificador falha não é gate.
- **O veredito vem dos problemas listados, não do campo `aprovado`** — o modelo às vezes
  lista três defeitos e se marca aprovado no mesmo JSON.

---

## 7. Provas executadas

| O quê | Resultado |
|---|---|
| `motor-site` | **45 testes verdes** (39 + 6 de regressão do pet shop e da placa) |
| `sdr-motor` (`make test`) | **551 passed, 10 failed** |
| Baseline sem minhas mudanças | **551 passed, 10 failed — as mesmas 10** |
| Demo regerada | 3× no ar, com print a cada rodada |
| Rotas do painel | `/obs/campo`, `/api/campo/ritmo`, `/api/campo/script` → 200, console sem erro |
| Acervo pet shop | 2/4 fotos julgadas e aprovadas, 2 posições em placa |

As 10 falhas do sdr-motor são **pré-existentes** na branch `feat/refundacao-noemi-jpos`
(medidas guardando minhas mudanças e rodando a suíte limpa). Não são minhas e não as
consertei — não estavam no escopo e mexer nelas às cegas seria pior.

---

## 8. O que depende de você

1. **Autorizar (ou não) o disparo** depois de olhar §6. Recomendo corrigir o prompt da
   mensagem de abertura primeiro — o gate diz exatamente o quê.
2. **`whatsapp_dono` vs contato público** (§2): são dois números diferentes hoje.
3. **Chaves**: Gemini com saldo e/ou `DEEPSEEK_API_KEY`. Nenhuma das duas bloqueia nada —
   ambas têm slot e caem no pool.
4. **Deploy**: nada disto está no ar. O painel em produção roda de `/root/noemi-infra`, e
   estas mudanças estão no worktree.
5. **A conta da meta** (§0.2). É a decisão mais cara da lista.

## 9. Comandos

```bash
# gerar/auditar as objeções (offline, minutos — NUNCA no caminho de uma request)
python apps/painel-operacoes/script_call.py --aquecer

# popular o acervo de fotos de um segmento (uma vez por segmento na vida)
python apps/painel-operacoes/acervo_fotos.py "clínica odontológica"

# rodar o gate antes de qualquer disparo
python apps/painel-operacoes/qa_gate.py
```
