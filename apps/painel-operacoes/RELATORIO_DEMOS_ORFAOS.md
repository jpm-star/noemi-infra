# Por que os demos não casaram com lead — e o que é recuperável

Medido em 2026-08-16. **Só mede — nada foi corrigido**, por pedido explícito.
Fonte: `/var/www/sites` (75 pastas) × `data/leads.db::tracker_prospects` (1.532 leads).
Scripts do diagnóstico rodaram fora do repo; `casar_demos.py` não foi tocado.

---

## O primeiro número já estava errado

Não são 74 demos, são **75 pastas de site** — e a maioria não representa cliente nenhum.

| Categoria | Pastas |
|---|---:|
| Site de **teste do motor** (empresa inventada) | 29 |
| Já casado com lead | 9 |
| Ambíguo (dois leads empatados) | 1 |
| `<title>` em formato **antigo**, lead existe no CRM | 19 |
| `<title>` antigo, nenhum lead corresponde | 6 |
| `<title>` ok, lead existe, matcher derrubou | 1 |
| `<title>` ok, nenhum lead corresponde | 10 |
| **Total** | **75** |

Os 29 de teste são `demo-salao-motor`, `odonto-motion-v2`, `site-demo-noemi`,
`marmoraria-teste-isca` e afins — vários com `<title>` literal `[Nome da Clínica]`.
Nunca foram demo de cliente e não deveriam contar no denominador.

**Demos de cliente de verdade: 46.** Destes, 9 casados.

---

## A causa dominante não é normalização nem divergência: é o `<title>`

`casar_demos.sites()` só aceita site cujo `<title>` siga `nicho em cidade | Nome`.
**42 das 66 pastas não casadas foram descartadas antes de qualquer pontuação** — o
matcher nunca as viu. O motivo é banal: uma geração mais antiga do motor escrevia só
o nome.

```
academia-bellator-assis        <title>Academia Bellator</title>
academia-xploud-assis          <title>Academia XPLOUD</title>
red-dragon-gym-presidente-...  <title>Red Dragon Gym</title>
```

Sem o ` em cidade | ` o regex não casa, e o site sai do universo. Não é erro de grafia,
de acento nem de abreviação: é **formato de saída de duas gerações diferentes do motor
convivendo no mesmo diretório**.

Dessas 42, 17 são teste do motor e 25 parecem cliente — **19 com lead identificável no CRM**,
correspondendo a **13 empresas** (6 delas têm a pasta duplicada, ver abaixo). Todas as 13
com telefone.

---

## 1. Recuperável em lote — 14 empresas

**13 por formato de `<title>`** (nome idêntico ao lead, `ratio = 1.0` salvo onde indicado):

| Site | Lead | Cidade | Telefone |
|---|---|---|---|
| Academia Bellator | #739 | Assis | (18) 99636-3839 |
| Academia Body Express | #546 | Botucatu | (14) 3354-7020 |
| Academia Cia Bio Fit | #567 | Jaú | (14) 99186-0643 |
| CTM Academia | #553 | Marília | (14) 3415-3193 |
| Espaço Vip | #701 | Adamantina | (18) 3522-9132 |
| Academia Forma e Força | #544 | Marília | (14) 3432-3092 |
| Malibu Exclusive | #627 | Araçatuba | (18) 99137-3814 |
| Red Dragon Gym | #584 | Presidente Prudente | (18) 99728-8927 |
| Academia Ricodo | #556 | Botucatu | (14) 99617-0777 |
| Academia Tito Coló | #555 | Jaú | (14) 99166-8975 |
| Academia VidAtiva | #690 | Birigui | (18) 99112-7031 |
| Winner Academia | #708 | Marília | (14) 3454-8813 |
| Academia XPLOUD | #554 | Assis | (18) 99685-6784 |

Todas academia — é a leva que o motor gerou antes da mudança de `<title>`.

**1 por normalização pura:**

| Site | Lead | O que derrubou |
|---|---|---|
| `academia-prime-gym` "Academia Prime Gym" (Bauru - SP) | #54 `ACADEMIA PRIME GYM` (Bauru) | `'Bauru - SP'` ≠ `'Bauru'` → cidade não bate → 1 token distintivo só (`prime`) → score 0 |

Nome idêntico (`ratio = 1.00`), mesmo ramo, mesma cidade escrita com e sem UF. É o caso
mais claro de conserto de string do lote inteiro — e é **um**, não dezenas.

**Efeito se corrigido: lista de ligação vai de 9 para 23.**

---

## 2. Erros de normalização encontrados — os três tipos, todos de baixo volume

1. **Sufixo de UF na cidade.** `'Bauru - SP'` vs `'Bauru'`. 1 caso.
2. **Entidade HTML não decodificada.** `_titulo()` remove tags mas não chama
   `html.unescape`: `Rações &amp; Cia` vira o token `amp`. 1 caso.
3. **Nome 100% genérico.** "Rações & Cia" — `racoes` e `cia` estão **as duas** em
   `_GENERICAS`, então sobram **zero** tokens distintivos e o score é 0 por construção.
   2 casos, e não é bug: é a regra funcionando. Empresa cujo nome é só palavra de ramo
   não pode ser casada por token — precisa de outra evidência (telefone, endereço, CNPJ).

Os dois casos "Rações" têm um agravante que **não** é normalização: existem sites em
**Lins** e em **Marília**, e o único lead #460 é de **Araçatuba**. Ou são três unidades,
ou a cidade do site foi inventada. Decisão humana, não regex.

---

## 3. Divergência real — 14 sites, e não é erro de dado

Sites cuja empresa simplesmente não está no CRM:

```
bike-point-marilia      pedal-livre-bauru       otica-visao-lins     cronometro-lins
pe-di / pe-di-chinelos  clinica-dental-prime    clinica-sorriso-bauru
odontologia-vida-nova   academia-impacto        charles-cabeleliro
clinica-vitalis         horizonte-imoveis       sao-francisco-engenharia
```

O CRM tem **14 segmentos, só isto**: odontologia (496+357+7+1), estética (171),
pet shop (99), advocacia (90), academia (86), imobiliária (83), oficina (81),
contabilidade (54), clínica médica (4), fisioterapia (1).

Prospects de **loja de bicicletas: 0. Ótica: 0. Pizzaria: 0. Marmoraria: 0. Chinelo: 0.**
(A busca por "otica" devolve 8 linhas, mas todas são "Jab**otica**bal" — coincidência de
substring, nenhuma ótica.)

Ou seja: esses sites foram gerados para demonstrar o catálogo de nichos, não para
prospects reais. **Não são demos órfãos — são amostras.** Nenhum conserto de matching
os casaria, porque não há com quem casar.

---

## 4. Dois achados colaterais que valem antes de afrouxar qualquer regra

**Pastas duplicadas — 6 empresas com 2 sites cada:**
`academia-bellator` + `academia-bellator-assis`, `ctm-academia-marilia` +
`academia-ctm-academia-marilia`, e o mesmo par com prefixo `academia-` para
Espaço Vip, Malibu, Red Dragon e Winner. Qualquer casamento em lote vai gravar
`demo_url` apontando para uma das duas arbitrariamente — decidir qual antes.

**Leads-lixo que casam com tudo:** `#408` e `#1531` têm `empresa` **vazia**; `#778` tem
`empresa = 'Clínica'`. Em qualquer matcher por similaridade ou contenção de string,
nome vazio está contido em toda string e casa com 100% dos sites. Meu próprio script de
diagnóstico caiu nisso na primeira rodada e produziu 36 falsos positivos antes de eu
filtrar. **Se o matching for afrouxado sem limpar esses três, eles viram os primeiros
falsos positivos.**

---

## 5. Preço T2 — não há conflito

Verificado em produção hoje:

```
jpos.com.br  →  T2 Presença  R$ 1.000 + R$ 397/mês
precos.json  →  setup: 1000, mensal: 397
```

**Idênticos.** E a sincronia é estrutural, não coincidência: `apps/site-jpos/dados.py`
lê `precos.json`, `publicar.py` gera o HTML a partir dele, e o rodapé do site carimba
`Valores de 2026-08-15` — a mesma data do `_atualizado_em` do arquivo. O teste
`test_catalogo_sincronizado` trava a divergência. **Nada a sincronizar.**

O "R$ 997" **não existe em lugar nenhum do código nem do site**. Os dois únicos hits de
`997` no repo são `% 997` (primo usado em hash de ID) em `builder_web.py:221` e
`criacao.py:334`. Os `1000` das páginas internas são `@media(min-width:1000px)`.

O 997 veio da fala na call — e as duas leituras possíveis são negócios diferentes:

| Leitura | 10 clientes |
|---|---|
| 997 **substitui** o T2 inteiro (pacote fechado, sem mensalidade) | R$ 9.970 uma vez, **zero recorrente** |
| 997 no lugar do **setup**, mantendo os 397/mês | R$ 9.970 + R$ 3.970/mês = **R$ 47.640/ano** |

A segunda é a que sustenta a conta de "10 clientes". A primeira derruba a recorrência
inteira. **Nada foi alterado** — mudar preço em produção é decisão comercial, e a
diferença entre as duas leituras é de R$ 37.670 no primeiro ano.

Para trocar: editar `precos.json`, `systemctl restart noemi-painel-obs`, republicar o site.
