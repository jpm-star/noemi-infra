# Alertas de e-mail — variantes (JPOS Radar, alerta vermelho)

Versionado (não hardcoded na função de envio). Mesmo padrão de prompt-como-arquivo.
Campos: `{titulo_achado}`, `{achado_completo}`, `{fonte}`, `{timestamp}`. A variante 5
(consolidado) usa `{lista_achados}` no lugar de um achado único.

Estrutura fixa em todas: assunto `[JPOS Radar] ...` + corpo com o achado, origem,
timestamp, e a nota "não é deadline, é log de quando apareceu". Muda SÓ o grau de
urgência percebida no tom.

---

## variante: padrao
Assunto: [JPOS Radar] Alerta vermelho detectado — {titulo_achado}

JP,

O Radar identificou um item de urgência real (não é lembrete de rotina):

{achado_completo}

Origem: {fonte} · Detectado em: {timestamp}

Isso não tem prazo — é log de quando apareceu, não deadline. Olha quando puder.

---

## variante: tecnica
Assunto: [JPOS Radar] Vermelho técnico — {titulo_achado}

JP,

Sinal de infra/operação que pede olhar (não é ruído de rotina):

{achado_completo}

Origem: {fonte} · Detectado em: {timestamp}

Sem prazo — é registro de quando o padrão apareceu, não deadline. Trata quando encaixar.

---

## variante: comercial
Assunto: [JPOS Radar] Vermelho — risco de perder venda: {titulo_achado}

JP,

O Radar pegou um padrão que está custando cliente/venda agora:

{achado_completo}

Origem: {fonte} · Detectado em: {timestamp}

Não é deadline — é o log de quando apareceu. Mas cada dia parado aqui é dinheiro que
escorre. Olha quando puder, de preferência cedo.

---

## variante: recorrencia
Assunto: [JPOS Radar] Vermelho CONFIRMADO (3ª+ vez) — {titulo_achado}

JP,

Isto não é ruído: o mesmo padrão já apareceu 3+ vezes no Radar. Recorrência confirmada
= sinal forte:

{achado_completo}

Origem: {fonte} · Detectado em: {timestamp}

Sem prazo — é log de quando apareceu. Mas repetir 3+ vezes é o Radar batendo na porta:
considera priorizar.

---

## variante: consolidado
Assunto: [JPOS Radar] {n_vermelhos} alertas vermelhos hoje

JP,

Mais de um item de urgência real apareceu hoje — resumo pra você não receber e-mail
solto por item:

{lista_achados}

Detectado em: {timestamp}

Nenhum é deadline — é o log do dia. Olha quando puder; os de recorrência confirmada
merecem a frente da fila.
