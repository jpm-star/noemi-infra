# Izanagi QA Report — ativação do relatório T1 + telemetria

## Summary
- **Entrega**: `beacon_snippet.py`, `relatorio_t1.py`, `beacon.py` (endurecido), 2 unidades systemd, 16 páginas HTML no ar
- **Tipo**: código Python + JS publicado em produção
- **Iterações**: 4 de 5
- **Status final**: PASSED WITH WARNINGS (1 passo humano pendente, declarado abaixo)

## Iteration Log

### Iteração 1 — `beacon_snippet.py`
| # | Check | Resultado | Detalhe |
|---|---|---|---|
| 1 | Self-check roda | PASS | 5 asserts, sem rede, sem DB |
| 2 | Índice de corte correto | **FAIL** | `html.lower().rfind("</body>")` — `lower()` altera o comprimento em alguns caracteres não-ASCII, o índice sairia deslocado e o snippet seria colado no meio da tag |

**Ação**: descartado. Trocado por `re.finditer(r"</body\s*>", …, re.I)` sobre o texto original.

### Iteração 2 — verificação em produção
| # | Check | Resultado | Detalhe |
|---|---|---|---|
| 3 | Snippet publicado compila | PASS | `node --check` rc=0 nas 16 páginas |
| 4 | Versão antiga era mesmo o bug | PASS | `node --check` no backup: `SyntaxError: Invalid regular expression flags` |
| 5 | Evento chega ao banco | PASS | POST real em `landing.jpos.com.br/beacon` → 204 → linha `cta` no SQLite de produção (a 1ª da história) |
| 6 | Qualidade do achado gerado | **FAIL ×3** | (a) "Falta de cliques no CTA" — o motor leu o *bug de rastreamento* como problema do cliente; (b) "revisar a copy", "fazer newsletter" — platitude que a própria regra do T1 proíbe; (c) "fazer parceria com chinelospedi.com" — tratou o domínio do próprio cliente como terceiro |

**Ação**: descartado, 4 linhas apagadas do banco de produção, `beacon.py` reescrito com 3 travas.

### Iteração 3 — travas de honestidade
| # | Check | Resultado | Detalhe |
|---|---|---|---|
| 7 | Conversão desconhecida ≠ 0% | PASS | `conversao_pct=None` sem histórico de `cta`; achado que fale de conversão é filtrado |
| 8 | Auto-referral | PASS | `_HOSTS` classifica o domínio do próprio cliente como `interno`, inclusive no histórico já gravado |
| 9 | Consumidores do formato antigo | **FAIL** | `static/index.html:630` renderizaria `null%`; `:788` tinha `??0` e mostraria **"0% de conversão"** — a mesma mentira, agora na tela do painel |
| 10 | Achado ainda platitude | **FAIL** | "avaliar a estratégia de marketing", "acompanhar o tráfego" |

**Ação**: descartado. UI corrigida para `—` + motivo. Diagnóstico da platitude: não havia padrão a achar (2 visitas externas no jpos, 0 no pedi) — o motor estava sendo forçado a falar.

### Iteração 4 — piso de sinal externo
| # | Check | Resultado | Detalhe |
|---|---|---|---|
| 11 | `MIN_EXTERNAS=10` | PASS | abaixo do piso o LLM **não é chamado** — provado por mock que levanta exceção se for |
| 12 | Motivo declarado | PASS | "53 visitas, mas só 0 vieram de fora do site" |
| 13 | Suíte do repo | PASS | 45 testes verdes |
| 14 | Unidades systemd | PASS | `systemd-analyze verify` rc=0 nas duas |
| 15 | Prova por mutação | PASS | o `node --check` do self-check **reprova** a corrupção real — a checagem tem dente |

**Ação**: enviado.

## Final Quality Score
15/15 checks passam na iteração final — 100%. 6 falhas encontradas e corrigidas no caminho (3 delas em código que já estava em produção).

## Remaining Warnings
1. **O timer não está instalado.** As unidades estão validadas e o job foi provado rodando contra dado real, mas instalá-lo exige o código no checkout principal (`/root/noemi-infra`), o que significa mesclar esta branch — decisão do JP, com trabalho não-commitado dele na `feat/conversao-cartucho`. Enquanto não for instalado, esta entrega é *capacidade provada*, não *entrega agendada*.
2. Uma linha de teste (`site='teste'`, `origem='verificacao-izanagi'`) ficou no banco como artefato da prova fim-a-fim.

## Notes
O padrão "construído e desligado" apareceu aqui em dois lugares ao mesmo tempo: o motor de insight sem chamador, e o snippet sem fonte única. A correção que fecha a classe do problema não é nenhuma das duas — é o `node --check` dentro do self-check: a landing ficou dias no ar com erro de sintaxe porque **nada no repositório passava um parser no que era publicado**. Existência de código nunca foi prova de execução.
