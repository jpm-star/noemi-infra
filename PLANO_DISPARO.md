# Plano de disparo — 27.107 leads, 26 dias úteis

**Nada foi importado. Nada foi disparado.** Tudo abaixo é dry-run contra a base real.

---

## Antes de tudo: o RADAR estava certo, com uma correção

Você apontou que todo cálculo anterior partiu de base errada. Verifiquei o widget de
ritmo (`ritmo.py`) linha a linha: **ele não usa o número de leads em lugar nenhum** —
calcula meta ÷ dias úteis restantes e o valor fechado. Esses números seguem válidos.

O que estava errado era a **minha leitura**, não o widget: escrevi que "42 fechamentos em
1.446 leads = 3%, agressivo mas possível". Com 27.107, é **0,15%**. A conclusão mudou, o
instrumento não. Adicionei ao widget o alcance e a conversão exigida, que era o que
faltava para ele responder essa pergunta sozinho.

---

## Tarefa 2 — Breakdown dos 3.477 com nome fantasia

A distribuição de nome fantasia é **inversa ao volume**, e isso decide tudo:

| Segmento | Com celular | Com FANTASIA | % |
|---|---:|---:|---:|
| cabeleireiro | 13.646 | **252** | 1,8% |
| estética | 5.171 | 258 | 5,0% |
| médico | 2.407 | 705 | 29,3% |
| advocacia | 1.938 | 127 | 6,6% |
| imobiliária | 1.235 | **821** | 66,5% |
| odontologia | 994 | 492 | 49,5% |
| fisioterapia | 800 | 397 | 49,6% |
| academia | 694 | 425 | 61,2% |
| **total** | **26.885** | **3.477** | 12,9% |

**Cabeleireiro é 51% do volume e só 1,8% tem nome fantasia** — é base de MEI, pessoa
física, sem marca registrada. Pela sua própria regra (fantasia obrigatória no WhatsApp),
o maior segmento da base **não abre o disparo automatizado**. Ele é material de cold call.

---

## Tarefa 1 — Ordem de entrada, por cobertura de template

Cruzei volume utilizável × catálogo de serviços do Motor Site × biblioteca de referências
de estrutura (96 refs).

| # | Segmento | Fantasia | Catálogo | Refs | Entra quando |
|---|---|---:|---|---:|---|
| 1 | **odontologia** | 492 | OK | 33 | **abre o disparo** |
| 2 | **academia** | 425 | OK | 10 | junto / logo depois |
| 3 | **fisioterapia** | 397 | OK | 33 | junto / logo depois |
| 4 | imobiliária | 821 | OK | **1** | depois de subir refs |
| 5 | estética | 258 | OK | 33 | ok, volume menor |
| 6 | médico | 705 | **FALTA** | 33 | depois do catálogo |
| 7 | cabeleireiro | 252 | OK | 4 | cold call, não WhatsApp |
| 8 | advocacia | 127 | OK | 9 | volume baixo |

**Abre por odontologia**: melhor combinação de nome utilizável (492), catálogo curado e
33 referências de estrutura. Academia e fisioterapia vêm junto — somados dão **1.314
leads**, que cobre as primeiras duas semanas de rampa com folga.

Dois bloqueios pequenos e concretos:
- **imobiliária tem 821 nomes bons e só 1 referência de estrutura.** É o maior ganho por
  esforço: subir 8-10 referências de imobiliária destrava o segundo maior bolsão.
- **médico não tem catálogo de serviços** (cai no LLM). 705 nomes esperando ~10 minutos
  de curadoria.

---

## Tarefa 3 — Capacidade

Estado atual em produção: **`PROSPECCAO_LIMITE_TETO=10`, incremento 0** — sem rampa. Nesse
ritmo, a base leva 7,4 anos. Instâncias Evolution hoje: **2 conectadas** (`dificil`,
`noemi ajuda papai`) e 1 caída (`joao mirandola`).

Premissas declaradas (`capacidade.py`, ajustáveis): rampa 10→250 msg/dia por instância
subindo a cada 2 dias, perda técnica 15%.

| Instâncias | Alcance na janela | Msg/dia no fim | % da base | Conversão exigida p/ 42 |
|---:|---:|---:|---:|---:|
| 1 | 2.516 | 250 | 10,9% | 1,67% |
| 2 | 5.032 | 500 | 21,8% | 0,83% |
| **3** | **7.548** | 750 | 32,8% | **0,56%** |
| 4 | 10.064 | 1.000 | 43,7% | 0,42% |
| 6 | 15.096 | 1.500 | 65,5% | 0,28% |
| 8 | 20.128 | 2.000 | 87,4% | 0,21% |

**Recomendo 3 instâncias.** O raciocínio: com 2 (as que já existem) a meta exige 0,83% de
conversão; com 3, cai para 0,56%. De 4 em diante o ganho por chip diminui e o risco
operacional sobe — mais números para aquecer, monitorar e perder.

E um limite que nenhum chip resolve: **os 3.477 com nome fantasia são a base real do
WhatsApp**, não os 27.107. Com 3 instâncias você alcança 7.548 — ou seja, **a capacidade
já ultrapassa o material utilizável no canal automatizado**. O gargalo verdadeiro não é
chip: é **nome fantasia**. Cada referência de imobiliária que você subir vale mais que um
chip novo.

**Não decidi contratar nada.** Chip novo é custo e é seu.

---

## Tarefa 4 — Nada importado

Confirmado em dry-run. Quando autorizar, por segmento:

```bash
cd /root/noemi-infra/apps/painel-operacoes

# WhatsApp automatizado — só nome fantasia, como você definiu
python3 importar_cnpja.py --dry-run --segmento odontologia     # 492
python3 importar_cnpja.py --segmento odontologia               # importa de verdade

# Cold call / porta-a-porta — aceita razão social
python3 importar_cnpja.py --segmento cabeleireiro --aceitar-razao-social --limite 500
```

Antes do primeiro disparo real, três coisas que **não** estão feitas:
1. `PROSPECCAO_LIMITE_TETO` e `LIMITE_INCREMENTO` seguem em 10 e 0 — a rampa não existe
   em produção, só no dimensionamento.
2. A instância `joao mirandola` está **caída** (`close`). Disparar com ela assim repete o
   incidente que já queimou 51 prospects.
3. O QA gate **reprovou** a mensagem de abertura (`promessa` nos três ângulos). Isso é
   anterior a qualquer volume.
