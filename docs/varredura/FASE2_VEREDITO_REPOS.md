# Fase 2 — veredito por repositório

_Avaliação em sandbox (`/root/.claude/jobs/.../sandbox`), nada em produção. 13/08/2026._

Cada veredito é **ADOTA / NÃO ADOTA / USO PONTUAL**, com o número que sustenta a
decisão. Onde não medi, está escrito que não medi.

---

## 1. public-apis · **USO PONTUAL — e rendeu na primeira busca**

Catálogo de consulta. Procurei contra gaps que esta sessão **mediu**, não contra
categorias genéricas, e um único achado cobre quatro deles.

### BrasilAPI (`brasilapi.com.br`) — sem chave, sem cadastro, HTTPS

Testado ao vivo, com o tempo de resposta real:

| Gap medido no JPOS | Endpoint | Resposta | Serve porque |
|---|---|---|---|
| Antipadrão "não gerar mapa sem CEP e número" | `/cep/v2/{cep}` | 46 ms | devolve rua, bairro, cidade **e lat/long** — valida o briefing e ainda dá o geocoding de graça |
| Estrutura nova "aberto agora" | `/feriados/v1/2026` | 61 ms | 14 feriados nacionais; sem isso o selo diz "aberto" em 25/12 |
| Enriquecimento de lead | `/cnpj/v1/{cnpj}` | 55 ms | razão social, CNAE, município, situação — hoje o JPOS usa `cnpja`, que exige chave |
| Estrutura nova "atendemos toda a região" | `/ddd/v1/14` | 365 ms | 100 cidades reais do DDD 14, em vez de lista chutada |

**O que isso destrava, concretamente:** três das quinze estruturas brasileiras que
entraram no vocabulário na Fase 1 (`aberto-agora`, `regiao-atendida`, e o endereço
estruturado que o antipadrão `endereco-texto` exige) deixam de depender de dado que
o cliente teria que digitar. E o `cnpj` abre a possibilidade de reduzir dependência
de uma API paga — **não medi** o quanto o BrasilAPI cobre em relação ao `cnpja`;
isso é comparação para outra rodada.

> Ressalva honesta: BrasilAPI é comunitária e sem SLA. Serve para enriquecer no
> momento da **geração** (offline, com cache), não como dependência de request de
> visitante. Cair não pode derrubar site de cliente.

---

## 2. free-for-dev · **USO PONTUAL — consulta, sem achado urgente**

Lista de camadas gratuitas. Vale como referência quando um custo aparecer. Não
encontrei nada que resolva gap medido melhor que o que já roda (Caddy, SQLite,
Groq free tier, Resend). **Não é motivo de trabalho agora.**

---

## 3. awesome-mcp-servers · **NÃO ADOTA agora — reavaliar quando houver cliente**

Catálogo de servidores MCP. A stack já tem MCP em uso (Higgsfield, Playwright,
Semgrep, Google). O que faria diferença — um MCP que ligasse o painel a um CRM
externo — não faz sentido com **zero clientes pagantes**: seria integração para
um fluxo que não existe. Reavaliar quando o primeiro cliente fechar.

---

## 4. Scrapling · **USO PONTUAL, OFFLINE — nunca em produção**

Testado (v0.4.14), só contra `jpos.com.br`. O escopo está cravado **no código** do
teste, não só na conversa: uma lista de domínios permitidos que levanta antes de
tocar a rede, para o script não virar ferramenta de raspagem de terceiro quando
alguém copiar daqui.

### O gap é real e está medido

`referencias_vistas` tem 141 tentativas de colheita:

| resultado | n | % | o que é |
|---|---|---|---|
| salva | 96 | 68% | funcionou |
| **rasa** | **25** | **18%** | menos de 3 blocos — assinatura de página renderizada por JS que o fetch estático vê como casca |
| erro:HTTPError | 18 | 13% | bloqueado (anti-bot) |
| erro:URLError | 2 | 1% | rede |

**32% das colheitas falham.** O `de_url` usa `ingestao._buscar`, um GET simples: não
executa JavaScript.

### O que o teste mediu

| | tempo | conteúdo | seções |
|---|---|---|---|
| fetch atual do motor | **179 ms** | 46.183 chars | 5 |
| Scrapling `Fetcher` (HTTP) | 142 ms | 46.099 chars | — |
| Scrapling `DynamicFetcher` (navegador) | **2.094 ms** | 46.475 chars | 5 |

Peso da dependência: **17 MB → 339 MB** (20×, por causa de curl_cffi + navegador).

### Veredito

O modo dinâmico **funciona e renderia as 25 páginas rasas**. Mas em site estático
entrega exatamente as mesmas 5 seções por **11,7× o tempo** — ou seja, não há ganho
onde não há JS, e o custo é permanente.

**Decisão: não entra no caminho de produção.** Vale como **job offline de uma vez**
para re-colher as 25 referências rasas e aposentar. 322 MB e 12× de latência
instalados para sempre, em troca de um ganho único de 25 itens, é troca ruim.

**As 18 bloqueadas ficam fora por decisão sua**, não por limitação técnica: contornar
proteção de site de terceiro é exatamente a parte do Scrapling que o escopo excluiu.

---

## 5. Ollama · **NÃO ADOTA para qualidade — reavaliar só como válvula de TPM**

Medido nesta VPS: **10 GB de RAM disponíveis** (de 15), com 14 containers e 10
serviços systemd já rodando, carga 1.65.

Contra: o stack já tem Groq (gratuito), Gemini, Anthropic e um gateway `litellm` de
pé. Um modelo que caiba em 10 GB é menor e mais lento que o `llama-3.3-70b` que o
Groq entrega de graça em ~50 ms. Rodar local seria pagar RAM para ter menos.

A favor, e é o único argumento real: o **TPM do Groq é 8.000 por organização** —
medido nesta sessão, e é o teto que derrubou o ensemble. Trabalho de volume e baixa
exigência (classificar segmento, etiquetar lead) poderia sair do orçamento do Groq
e ir para um 8B local, deixando o teto livre para o que precisa de qualidade.

**Não agora.** Vira decisão real quando o volume de classificação bater no teto de
forma recorrente — e aí a métrica que justifica já existe.

---

## 6. Langflow · **NÃO ADOTA — concorre com o que já roda**

Construtor visual de fluxo de LLM. O `n8n` já está no Caddy (`n8n.noemi.digital`) e
o `litellm` já centraliza chave e roteamento. Adicionar Langflow é uma terceira
camada de orquestração para os mesmos fluxos, com mais um serviço para manter numa
máquina que já tem 24 processos do projeto.

O motor do JPOS não é fluxo visual: é Python com decisão explícita e teste. Trocar
isso por caixinhas piora a auditabilidade que a sessão inteira tentou construir.

---

## 7. OpenHands · **NÃO ADOTA — sobreposição direta**

Agente autônomo de codificação. É o papel que o Claude Code já exerce neste
repositório, com histórico, memória e as travas de contrato construídas aqui.
Rodar um segundo agente sobre o mesmo código cria dois autores sem coordenação —
e o problema desta stack não é falta de capacidade de escrever código: é excesso de
código escrito e não ligado (quatro casos numa sessão).

---

## 8. open-design · **NÃO AVALIADO — repositório ambíguo**

Não consegui identificar com certeza qual repositório é (o nome corresponde a mais
de um projeto). **Não avaliei** em vez de escolher um e fingir veredito. Se você
mandar a URL, avalio na próxima rodada.

---

## 9. Awesome · **LEITURA — sem ação**

Índice de índices. Serve para achar catálogo, não para resolver problema. Já
cumpriu o papel apontando para os dois primeiros desta lista.

---

## 10. awesome-llm-apps · **LEITURA — sem ação agora**

Coleção de aplicações de referência. Útil como repertório quando um produto novo
do relatório de oportunidades sair do papel. Nada aqui muda decisão hoje.

---

## Resumo

| Repo | Veredito | Motivo em uma linha |
|---|---|---|
| public-apis | **USO PONTUAL** | BrasilAPI cobre 4 gaps medidos, sem chave |
| free-for-dev | USO PONTUAL | consulta futura; nada urgente |
| awesome-mcp-servers | NÃO ADOTA | integração para fluxo que não existe sem cliente |
| Scrapling | **USO PONTUAL OFFLINE** | recupera 25 rasas, mas 20× peso e 12× latência |
| Ollama | NÃO ADOTA | pior que o Groq grátis; reavaliar como válvula de TPM |
| Langflow | NÃO ADOTA | terceira camada de orquestração sobre n8n + litellm |
| OpenHands | NÃO ADOTA | mesmo papel do agente que já opera o repo |
| open-design | NÃO AVALIADO | repositório ambíguo — falta a URL |
| Awesome | LEITURA | índice de índices |
| awesome-llm-apps | LEITURA | repertório para produto futuro |

**Uma adoção com trabalho concreto (BrasilAPI), uma com uso restrito e offline
(Scrapling), seis descartes com motivo, uma não avaliada.**

O padrão dos descartes não é técnico: quase todos perdem porque **duplicam camada
que já existe**. Numa stack com 24 processos e um único operador, cada peça nova
custa manutenção que ninguém tem — o mesmo raciocínio que fez o vocabulário mapear
91 nichos em 9 famílias em vez de criar 91 perfis.
