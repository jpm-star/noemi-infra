# Playbook das demos — do Drive ao site, com prova

Como sair de "tenho as fotos" para "mandei o link" sem terminal e sem retrabalho.
Escrito em 2026-08-16, depois de consertar o que estava quebrado silenciosamente.

---

## 1. Como nomear a pasta (isto é o briefing)

Uma pasta por cliente, exatamente assim:

```
Studio Charles - salão de beleza - Lins
Auto Teco - oficina mecânica - Botucatu
Clínica Vida - clínica odontológica - Bauru
```

`Empresa - Segmento - Cidade`. Só isso. O nome da pasta já tem as três coisas que o
motor precisa — não há formulário para preencher depois.

Regras que o script aplica sozinho:

- Aceita hífen `-` ou travessão `–` (o Drive e o celular trocam sem avisar).
- **Sem cidade funciona**: `Empresa - Segmento` gera igual, e o site diz "na sua região".
- Pasta começando com `_` ou `.`, ou sem o `-`, é **pulada**. Então `_backup` e
  `fotos soltas` podem conviver na mesma pasta-mãe sem virar site de cliente.
- **A maior foto vira o hero.** Ordene por isso: a foto de capa deve ser a de maior
  resolução. As demais viram os cards de serviço.

### O segmento tem que estar no catálogo

O motor conhece 169 nichos. Se o segmento não casar, o site cai no estilo genérico —
funciona, mas perde a decisão de estilo. Confira antes:

```bash
.venv/bin/python -c "import sys;sys.path.insert(0,'apps/painel-operacoes');
import vocabulario as v;print(v.segmento_do_nicho('cabeleireiro'))"
```

Devolveu vazio? Me avise: o termo entra no catálogo em uma linha, e passa a valer para
todas as gerações futuras.

---

## 2. Gerar o lote

Baixe a pasta-mãe do Drive. Depois:

```bash
cd /root/noemi-infra

# 1) CONFIRA antes de gastar geração — mostra o que entendeu de cada pasta
.venv/bin/python apps/painel-operacoes/lote_sites.py ~/Downloads/clientes --so-listar

# 2) gera de verdade (um site por pasta, com QA)
.venv/bin/python apps/painel-operacoes/lote_sites.py ~/Downloads/clientes
```

Sai um `RELATORIO.md` dentro da pasta-mãe com URL, tempo, quantas fotos entraram e o
**veredito do gate visual** de cada site. É o que você lê antes de mandar qualquer link.

Mediana real de geração: **11,1s** por site (medido em 27 gerações).

---

## 3. Ler o veredito — e o que NÃO é aprovação

| Ícone | Veredito | O que fazer |
|---|---|---|
| ✅ | `aprovado` | as sondas passaram **e** o juiz de visão olhou e não achou defeito. Pode mandar. |
| ⛔ | `reprovado` | tem defeito listado. Corrija ou regenere antes de mostrar. |
| ⚠️ | `indeterminado` | **as sondas passaram, mas ninguém olhou a página.** Não é aprovação. Abra e olhe. |

O `indeterminado` existe porque até 2026-08-16 o gate dizia `aprovado: true` quando o
juiz de visão falhava — e ele falhava **sempre**, de forma determinística. Todo relatório
que citou "passou no QA visual" antes dessa data está falando de algo que não foi
verificado.

Se vier muito `indeterminado` seguido, é rate limit do provider: espere alguns minutos e
rode `qa_visual.py <slug>` de novo.

---

## 4. As fotos

Ordem de preferência que o motor aplica sozinho:

1. **Foto do cliente** (a que você pôs na pasta) — vence sempre, é o negócio dele.
2. **Acervo do nicho** — fotos já julgadas, compartilhadas por todos os clientes do ramo.
3. Banco de imagem genérico — último caso.

### A portaria: foto com texto impresso não entra

Print de post de Instagram tem o texto do post impresso na imagem. Usado como hero, o
título do site é escrito **por cima** do título da foto, e sai ilegível — foi o que
aconteceu na Academia Bellator. O Tesseract lê cada foto na entrada e reprova as que têm
legenda ou marca d'água.

Então: **mande foto, não print.** Print de story, post ou flyer é reprovado por desenho.

### Nichos com acervo pronto (2026-08-16)

`academia` · `clínica de estética` · `clínica odontológica` · `escritório de advocacia` ·
`escritório de contabilidade` · `imobiliária` · `oficina mecânica` · `pet shop` ·
`salão de beleza`

Cobrem 1.311 dos 1.532 leads do CRM. Nicho fora dessa lista gera igual, só sem foto de
acervo — se for virar demo recorrente, peça o acervo dele.

---

## 5. Depois de gerar: ligar o site ao lead

O site não serve de nada solto no disco. Para ele aparecer no CRM junto do telefone:

```bash
.venv/bin/python apps/painel-operacoes/casar_demos.py            # confere
.venv/bin/python apps/painel-operacoes/casar_demos.py --aplicar  # grava demo_url
```

O casamento é **conservador de propósito** — demo mandado para a empresa errada é pior
que demo nenhum. Ele exige nome distintivo, cidade batendo e ramo batendo, e recusa
empate em vez de chutar. Ambiguidade aparece na lista como `????` para você resolver.

---

## 6. O que ainda depende de você

Coisas que **não** estão no código e por isso não entram em site nenhum
automaticamente — se um cliente perguntar, a resposta tem que vir de você:

- garantia e política de reembolso
- de quem é o domínio (seu ou do cliente)
- prazo de contrato e o que acontece ao cancelar
- o que exatamente entra em cada tier além do que está no `precos.json`

O FAQ do `jpos.com.br` foi escrito **sem** esses itens de propósito: inventar política
comercial num site é como o cliente descobre que você inventa.
