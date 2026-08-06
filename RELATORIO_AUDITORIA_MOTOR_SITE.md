# Auditoria do motor de sites — 2026-08-06

Disparada pelos 2 bugs visuais da Clínica Implante Real. **Os dois são meus**, introduzidos
hoje. Registro completo, inclusive o que não virou fix.

---

## 1. Hero sem título — CAUSA RAIZ

### O que acontecia
O `<h1>` existia no HTML, com `opacity: 1` e largura real, e **não aparecia na tela**. Nos
DOIS sites (Rações & Cia e Clínica Implante Real).

### Por quê
O H1 usa `background-clip: text` — o texto é pintado pelo **gradiente do fundo do próprio
h1**, com `-webkit-text-fill-color: transparent`:

```css
@supports ((-webkit-background-clip:text) or (background-clip:text)) {
  .hero h1 { background:linear-gradient(...); background-clip:text;
             -webkit-text-fill-color:transparent; } }
```

Hoje eu adicionei uma animação "palavra a palavra" que **fatia o h1 em `<span class="pal">`**
por JS. Os spans:
- **herdam** `-webkit-text-fill-color: transparent` (é propriedade herdada);
- **não herdam** o gradiente de fundo (ele vive na caixa do pai).

Resultado: 7 palavras com texto transparente sobre fundo nenhum. Invisíveis.

Provado no navegador: `webkitTextFillColor: "rgba(0, 0, 0, 0)"`, `nPals: 7`, cada span com
`opacity: 1` e `width: 299px`. O conteúdo estava lá, pintado de nada.

### Sobre "o fix prometido no Rações & Cia nunca chegou no template-base"
**A pergunta tem uma premissa que a auditoria não confirma.** Não houve fix de hero
prometido antes: o que corrigi no Rações & Cia foram os **serviços genéricos e as fotos**
(dicionário de 5 segmentos, estátua de urso). O hero quebrou **depois**, quando adicionei a
animação de scroll — e quebrou nos dois sites ao mesmo tempo, porque está no template-base.
Foi regressão nova, não fix esquecido. Eu não vi porque só capturei a seção de serviços na
verificação.

### Correção
Removi o fatiamento. O h1 anima **inteiro** (`titulo-entra`: fade + blur + translate), o
que preserva o gradiente e entrega quase o mesmo efeito.

**Regra que fica:** não se fatia elemento que usa `background-clip: text`.

---

## 2. Letra gigante em "Nossos serviços" — CAUSA RAIZ

### O que acontecia
Cinco cards com um "A", "L", "C", "I", "O" gigantes ocupando o card inteiro.

### Por quê
Também meu, e de hoje. Ao remover o fallback do `loremflickr` (que publicou uma **estátua
de urso** ilustrando "Acessórios"), coloquei no lugar uma "placa": gradiente do tema + a
**inicial do serviço** em `clamp(2.4rem, 6vw, 3.6rem)`.

Isoladamente a ideia é defensável — sóbria, na paleta, nunca errada sobre o serviço.
Publicada, lê como **placeholder quebrado**. A decisão de design estava errada, não o
código: nenhum fallback está "mal escolhido" aqui, o fallback é que era ruim.

O gatilho é o acervo vazio: `odontologia` não tem fotos julgadas em `/var/www/sites/_acervo/`,
então **todos** os 5 cards caem na placa de uma vez — o que amplifica o defeito.

### Correção
A placa passa a usar **ícone de traço** (Lucide, já existia em `app/icones.py`), mapeado por
palavra-chave do serviço, com `sparkles` como neutro. O texto do serviço continua no card —
é ele que informa.

| Serviço | Ícone |
|---|---|
| Avaliação / Consulta / Diagnóstico | `check-circle` |
| Limpeza / Higiene / Banho / Tosa | `sparkles` |
| Clareamento / Estética | `star` |
| Implante / Prótese / Cirurgia | `shield-check` |
| Ortodontia / Aparelho | `heart` |
| desconhecido | `sparkles` |

O mapa é curto de propósito: um mapa grande daria ilusão de precisão que ele não tem.

---

## 3. Biblioteca de referência — o gerador FILTRA, a UI não

**A suspeita de contaminação cruzada não se confirma no gerador.** `receitas.referencias_aprovadas`
faz exatamente o filtro certo:

```sql
SELECT * FROM templates_referencia
WHERE segmento=? AND aprovada=1 AND tipo='estrutura'
```

Uma clínica odontológica (`segmento_de(...) = 'clinica'`) **não consegue** puxar estrutura
de outro segmento. Os SaaS que você viu na tela vêm de `/api/criacao/referencias`, que
lista **tudo** para revisão — é a tela de curadoria, não a fonte da geração.

### Estado real da biblioteca (166 referências)

| Segmento | Aprovadas (alimentam o gerador) | Pendentes (só UI) |
|---|---:|---:|
| clinica | 28 | 19 |
| **servicos** | **32** | 0 |
| academia | 10 | 14 |
| advocacia | 9 | 14 |
| **generico** | **6** | 0 |
| salao | 4 | 14 |
| imobiliaria | 1 | 14 |
| restaurante | 1 | 0 |
| **total** | **91** | **75** |

### O que é lixo de verdade
Nenhuma referência está sem segmento. Mas **38 das 91 aprovadas (42%) estão em baldes que
não são segmento de negócio**: `servicos` (32) e `generico` (6). Não contaminam clínica
— só são consultadas quando o nicho casa com elas — mas são 42% da biblioteca "aprendida"
sem nicho identificável, e valem uma reclassificação.

### O risco real, que não é o que parecia
O upload em lote grava o segmento **que o operador escolhe no formulário**
(`segmento: str = Form("")`) — não há classificação automática por conteúdo da imagem. Se
14 prints de SaaS forem subidos com "clinica" selecionado, entram como clinica. Hoje eles
estão `aprovada=0` e **não alimentam nada**; o dia em que forem aprovados em massa sem
revisão, contaminam de verdade.

**Isto é uma decisão sua, não um bug:** aprovar em lote sem olhar é o que abre a porta.

### Achado colateral
`imobiliaria` tem **1** referência aprovada e **821 leads com nome fantasia** — a maior
razão nomes/estrutura da base. Já registrado no `PLANO_DISPARO.md`: subir refs de
imobiliária rende mais que um chip novo.

---

## 4. Conhecimento que a conta perderia (registrado mesmo sem virar fix)

1. **`background-clip: text` é frágil a qualquer manipulação de DOM interna.** Vale para o
   h1 e para qualquer elemento que ganhe esse tratamento depois.
2. **O acervo vazio amplifica defeito de fallback.** Com fotos parciais, um card feio passa
   despercebido; com acervo zerado, os 5 caem no fallback ao mesmo tempo e o defeito vira a
   seção inteira. Testar fallback com acervo VAZIO, não com acervo parcial.
3. **Screenshot de uma seção não valida a página.** Eu capturei `#servicos` e declarei a
   demo corrigida — o hero estava quebrado no mesmo arquivo. Captura de página inteira, ou
   pelo menos hero + uma seção.
4. **`opacity: 1` e `width > 0` não significam visível.** `-webkit-text-fill-color` engana
   qualquer verificação que só olhe geometria e opacidade. Um QA visual por geometria teria
   aprovado esta página.
5. **A rotação de receita por lead funciona** (`escolher(nicho, semente=id)`): leads
   diferentes do mesmo nicho pegam estruturas diferentes, em vez de todos caírem na
   primeira. Isso está certo e não precisa mexer.
6. **`aprovada=0` é uma quarentena real e está sendo respeitada.** 75 das 166 referências
   estão nela agora, sem afetar geração.

---

## 5. Estado das tarefas

| # | Tarefa | Estado |
|---|---|---|
| 1 | Auditoria documentada | **feito** (este documento) |
| 2 | Corrigir os 2 bugs no template-base | **feito**, com 2 testes de regressão |
| 3 | Filtrar biblioteca por segmento | **já filtrava** — auditado e documentado; o que falta é reclassificar os 42% em baldes |
| 4 | QA visual multimodal retroativo (28 sites) | **não feito** |
| 5 | Simplificar a interface do operador | **não feito** (o pedido chegou cortado) |
