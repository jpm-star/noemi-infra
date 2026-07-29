# Radar — Backlog com spec (NÃO implementar hoje; decisão pós-sprint)

_Triagem dos ~118 análises + 4 auto_insights. Aqui o que tem substância mas NÃO entra na véspera
do sprint — ou porque é feature de produto (risco/escopo), ou porque é vetor novo fora do JPOS.
Cada item já vem com spec pra não re-analisar do zero depois._

## Por que ficou fora hoje (regra que apliquei)
Construir feature de produto às vésperas do sprint, em cima de sinal de Telegram scrapado (que já
provei ser ruidoso — tags de review eram furadas), viola "não construir o não-validado" do
CLAUDE.md e arrisca o que vende/roda amanhã. Véspera de sprint = só copy/material (risco zero).

## MOTOR SITE (adições candidatas — todas ADITIVAS, não mexem no default motion/T2)
1. **Seção "Casos de sucesso / portfólio"** — grid de prints de sites gerados + resultado.
   Spec: novo `_bloco_portfolio(itens)` no template, itens do cartucho; '' se vazio (gracioso).
   Esforço P. Bloqueio: cliente novo não TEM caso ainda — só faz sentido quando houver 2-3 reais.
2. **FAQ pós-lançamento / suporte** — já existe `_bloco_faq` por segmento. Gap real: FAQ de
   PÓS-VENDA (como mudar, como ver leads). Spec: adicionar 3 perguntas de operação ao `_FAQ`. P.
3. **Análise de concorrentes/SEO na venda** — usar o `auditor.py` (já existe!) pra gerar um
   "diagnóstico do site atual do lead" e mostrar na call. Spec: endpoint que roda auditor no
   site do lead → score + gaps. M. **Melhor ROI de venda do balde** — considerar pro próximo ciclo.

## NOEMI (NÃO TOCAR — roda o sprint amanhã; tudo aqui é backlog puro)
4. **Follow-up automático pós-cold-call sem resposta em N dias** — spec: job que relê `prospeccao_log`,
   dispara mensagem de follow-up via Evolution após N dias sem resposta. M. Risco: mexe no pipeline
   ativo → só pós-sprint.
5. **Qualificação por score de intenção na conversa** — spec: classificador (Groq) que pontua a
   conversa WhatsApp (0-10 intenção) e prioriza handoff. M. Já há `campos_qualificacao` no cartucho
   jpos.json — este é o consumo automático deles.
6. **Transcrição/análise de ligação** — spec: áudio da call → Whisper (já usado no Radar) → resumo
   + objeções + próximo passo no `prospeccao_log`. M-G.

## VETORES NOVOS (fora do escopo JPOS/Pé Di — decisão explícita do dono)
7. **Shopify/dropshipping (auto_insights ★8, 3x)** — vetor de e-commerce, não é produto atual.
   Spec de decisão: só se o JP quiser abrir frente de arbitragem/e-com. NÃO é JPOS.
8. **Vertical imobiliária (★7, 4x — Lober, REALTY GROUP)** — o motor JÁ tem tema imobiliária +
   calculadora de financiamento (`_bloco_calculadora`). Ação real: **cartucho de prospecção de
   imobiliárias** (já tenho 108 imobiliárias scrapadas!). É o vetor mais forte do Radar com uso
   imediato — candidato #1 do backlog pra virar BUILD no próximo ciclo.
9. **Ferramenta Ruflo / Claude Code (★6, 1x cada)** — menção fraca, ferramenta de terceiros.
   Só monitorar; sem ação.

## Recomendação de ordem pro próximo ciclo (pós-sprint)
1º **#3 (auditor na venda)** — reusa código pronto, ROI de venda direto. 2º **#8 (cartucho
imobiliária)** — tenho os leads. 3º **#4-5 (Noemi follow-up/score)** — depois que o pipeline
provar estabilidade no sprint.
