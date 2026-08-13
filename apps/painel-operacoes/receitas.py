"""Receitas de ESTRUTURA por segmento + repositório de referências (aprendizado).

O motor já tinha 9 blocos modulares, mas a ORDEM era literal no template — por isso
todo site saía igual, variando só a pele (morfismo). Aqui vive o que decide a ordem:

  1. RECEITAS — escritas à mão por segmento, pensando no que CONVERTE naquele nicho
     (academia vende experimentação e horário; imobiliária vende busca; advocacia
     vende autoridade). Não é estética: é ordem de argumento.
  2. templates_referencia — referências que o JP sobe (print de site bom + tag +
     segmento). A visão (Groq, grátis) lê e PROPÕE uma receita; aprovada, ela entra
     no pool daquele segmento ao lado das default. É o canal permanente de
     aprendizado — o catálogo cresce, não é fechado.

Escolha na geração: sorteia entre as receitas DO SEGMENTO do lead (nunca de um pool
genérico — misturar tudo faz o motor convergir de volta pra uma média sem cara).

Coluna `tipo` já existe na tabela ('estrutura' hoje) pra quando surgir um 2º tipo real
de aprendizado (copy, oferta, motion). Generalizar agora, com 1 tipo só, seria a
abstração especulativa que o CLAUDE.md proíbe.

ponytail: dados + funções puras. Sem classe, sem registry, sem framework.
"""
from __future__ import annotations

import logging
import json
import sqlite3
from datetime import datetime, timezone

log = logging.getLogger("painel.receitas")


# Blocos que o motor sabe renderizar (nomes = chaves do template_real).
BLOCOS = ("sobre", "catalogo_motion", "catalogo", "antesdepois", "preco",
          "calculadora", "depoimentos", "faq", "formulario")

ORDEM_DEFAULT = list(BLOCOS)

# Receitas por segmento. Cada uma é uma HIPÓTESE de ordem de argumento — a referência
# do JP (ou o resultado real) corrige depois. `hero`: video|foto|texto ('' = pelo dado).
RECEITAS: dict[str, list[dict]] = {
    "academia": [
        {"nome": "experimental-primeiro", "hero": "video",
         "ordem": ["sobre", "catalogo_motion", "preco", "antesdepois", "depoimentos", "faq", "formulario"],
         "porque": "academia vende EXPERIMENTAÇÃO: modalidades e plano cedo, prova depois"},
        {"nome": "prova-primeiro", "hero": "foto",
         "ordem": ["sobre", "antesdepois", "depoimentos", "catalogo_motion", "preco", "faq", "formulario"],
         "porque": "transformação (antes/depois) é o argumento mais forte pra quem hesita"},
        {"nome": "preco-na-cara", "hero": "foto",
         "ordem": ["preco", "sobre", "catalogo_motion", "depoimentos", "faq", "formulario"],
         "porque": "mensalidade baixa como âncora: preço antes de tudo tira a objeção nº1"},
    ],
    "clinica": [
        {"nome": "confianca-primeiro", "hero": "foto",
         "ordem": ["sobre", "depoimentos", "catalogo_motion", "faq", "preco", "formulario"],
         "porque": "saúde compra por CONFIANÇA: quem somos e prova antes de procedimento/preço"},
        {"nome": "procedimento-vitrine", "hero": "foto",
         "ordem": ["catalogo_motion", "sobre", "antesdepois", "depoimentos", "faq", "formulario"],
         "porque": "paciente busca procedimento específico — vitrine no topo encurta o caminho"},
        {"nome": "duvida-antes", "hero": "texto",
         "ordem": ["sobre", "faq", "catalogo_motion", "depoimentos", "formulario"],
         "porque": "objeção (dói? convênio? quanto custa?) resolvida antes de pedir contato"},
    ],
    "salao": [
        {"nome": "portfolio-manda", "hero": "foto",
         "ordem": ["antesdepois", "sobre", "catalogo_motion", "preco", "depoimentos", "formulario"],
         "porque": "beleza se vende pelo OLHO: antes/depois no topo, texto depois"},
        {"nome": "servico-preco", "hero": "foto",
         "ordem": ["catalogo_motion", "preco", "antesdepois", "sobre", "depoimentos", "formulario"],
         "porque": "cliente já sabe o que quer (corte/mecha) e pergunta quanto custa"},
    ],
    "imobiliaria": [
        {"nome": "busca-no-topo", "hero": "texto",
         "ordem": ["catalogo_motion", "calculadora", "sobre", "depoimentos", "faq", "formulario"],
         "porque": "imóvel se procura, não se lê: vitrine + simulador antes de institucional"},
        {"nome": "simulador-isca", "hero": "foto",
         "ordem": ["calculadora", "catalogo_motion", "sobre", "faq", "depoimentos", "formulario"],
         "porque": "'cabe no meu bolso?' é a 1ª pergunta — simulador como isca de entrada"},
    ],
    "advocacia": [
        {"nome": "autoridade-diagnostico", "hero": "texto",
         "ordem": ["sobre", "faq", "depoimentos", "catalogo", "formulario"],
         "porque": "advogado vende AUTORIDADE: quem é, dúvida respondida, aí o contato"},
        {"nome": "dor-primeiro", "hero": "texto",
         "ordem": ["faq", "sobre", "catalogo", "depoimentos", "formulario"],
         "porque": "quem procura advogado tem uma dor concreta — responder a dor abre a porta"},
    ],
}

# Sinônimos → chave canônica (o nicho do lead vem escrito de qualquer jeito).
_ALIAS = {
    "academia": ("academia", "gym", "fitness", "crossfit", "musculação", "musculacao", "personal"),
    "clinica": ("clinica", "clínica", "odonto", "dentista", "saúde", "saude", "médic", "medic",
                "fisio", "psic", "estética", "estetica", "veterin"),
    "salao": ("salão", "salao", "beleza", "cabelei", "barbear", "manicure", "spa"),
    "imobiliaria": ("imobili", "imóve", "imove", "corretor", "aluguel", "leilão", "leilao"),
    "advocacia": ("advoc", "advogad", "jurídic", "juridic", "contabil", "contador"),
    # Segmentos que o SCRAPER já sabia produzir mas o vocabulário não reconhecia: as
    # referências eram salvas como 'petshop' e o pool procurava por 'pet shop' — nunca
    # se encontravam. Pet shop caía na receita default com 1 opção, e é a causa raiz do
    # "Rações & Cia saiu no template de sempre" (2026-08-05). Manter estas duas listas
    # em sincronia: referencias_scrap._TERMOS_SEG produz, este _ALIAS resolve.
    "petshop": ("pet shop", "petshop", "pet ", "ração", "racao", "agropet", "banho e tosa",
                "animais", "veterinária", "veterinaria"),
    "restaurante": ("restaurante", "pizzaria", "lanchonete", "padaria", "cafeteria",
                    "hamburgueria", "bar ", "delivery de comida", "food"),
    "servicos": ("agência", "agencia", "consultoria", "marketing", "design", "software",
                 "assessoria", "gráfica", "grafica"),
}


def segmento_de(nicho: str) -> str:
    """Nicho livre ('clínica odontológica em Bauru') → chave de segmento. '' se nenhum.

    Duas passadas, nesta ordem:
      1. `_ALIAS` — os termos curtos e históricos deste módulo, que já vinham
         casando (e que `referencias_scrap` precisa continuar resolvendo igual).
      2. `vocabulario.NICHOS` — os 91 nomes de nicho do JP, casados do termo MAIS
         LONGO pro mais curto. A ordem importa: "clínica veterinária" tem que
         resolver como clinica antes de "veterin" puxar pra petshop.

    Por que o vocabulário vem DEPOIS e não substitui: `_ALIAS` tem entradas que o
    scraper produz e que não são nome de nicho ("pet ", "food"). Trocar uma lista
    pela outra quebraria o casamento que já funciona; somar não quebra nada.

    Continua devolvendo "" pro que ninguém mapeou — é assim que `catalogo_vivo`
    conta o nicho novo em vez de forçá-lo num segmento que não serve.
    """
    n = (nicho or "").strip().lower()
    for chave, termos in _ALIAS.items():
        if any(t in n for t in termos):
            return chave
    try:
        import vocabulario
        return vocabulario.segmento_do_nicho(nicho)
    except Exception:  # noqa: BLE001 — vocabulário é enriquecimento, não caminho crítico
        return ""


def _norm_ordem(ordem) -> list[str]:
    """Só nomes de bloco que o motor conhece, sem repetir. Lixo é descartado."""
    fora: list[str] = []
    for b in (ordem or []):
        b = str(b).strip().lower()
        if b in BLOCOS and b not in fora:
            fora.append(b)
    return fora


def pool(segmento: str, con: sqlite3.Connection | None = None) -> list[dict]:
    """Receitas candidatas: as default DO SEGMENTO + as referências aprovadas dele.
    Segmento desconhecido → só a ordem default (não inventa estrutura)."""
    seg = segmento_de(segmento) or (segmento or "").strip().lower()
    fora = [{**r, "origem": "default", "segmento": seg} for r in RECEITAS.get(seg, [])]
    if not fora:
        fora = [{"nome": "default", "hero": "", "ordem": ORDEM_DEFAULT,
                 "porque": "ordem padrão do motor", "origem": "default", "segmento": seg}]
    for r in referencias_aprovadas(seg, con):
        ordem = _norm_ordem((r.get("receita") or {}).get("ordem"))
        if ordem:
            fora.append({"nome": r.get("tag") or f"ref-{r['id']}", "hero": (r.get("receita") or {}).get("hero", ""),
                         "ordem": ordem, "porque": f"referência do JP: {r.get('tag') or ''}".strip(),
                         "origem": f"referencia:{r['id']}", "segmento": seg})
    return fora


# Bloco -> campo do BriefingSite que o sustenta. Só entram os que o template deixa
# VAZIO por falta de dado (`_bloco_preco`, `_bloco_catalogo` e `_bloco_antes_depois`
# devolvem "" e o bloco some do corpo). `calculadora` e `catalogo_motion` ficam fora
# de propósito: renderizam sempre, a partir do segmento — não dependem de dado do lead.
EXIGE_DADO = {"preco": "ancora_preco", "catalogo": "catalogo", "antesdepois": "antes_depois"}


def viaveis(nicho: str, dados: dict | None = None,
            con: sqlite3.Connection | None = None) -> list[dict]:
    """Receitas do pool que o DADO deste lead sustenta.

    Medido em 2026-08-08 nos 63 sites publicados: `catalogo` e `antesdepois` nunca
    apareceram, `preco` apareceu em 1 (1%) — porque o briefing que o painel monta
    (`criacao.py`) não carrega `ancora_preco`, `catalogo` nem `antes_depois`. Não é
    "às vezes falta": nesse fluxo esses blocos são impossíveis. A receita era sorteada
    prometendo estrutura que o motor não tinha como entregar, e o bloco sumia calado.

    `dados=None` = "não sei o que existe" → pool inteiro. Filtrar por ignorância seria
    pior que não filtrar.
    """
    p = pool(nicho, con)
    if dados is None:
        return p
    tem = {b for b, campo in EXIGE_DADO.items() if dados.get(campo)}

    def perda(r) -> int:
        return len({b for b in _norm_ordem(r.get("ordem")) if b in EXIGE_DADO} - tem)

    # Menor PERDA, não "perda zero". Filtro binário seria inútil onde mais dói: medido
    # em 2026-08-08, com o dado que o funil tem hoje, 3 dos 5 segmentos (academia, salao,
    # advocacia) não têm UMA receita sequer que não peça preço/catálogo/antes-depois.
    # Exigir perfeição ali devolveria o pool inteiro e a escolha voltaria a ser cega.
    # Ranquear entrega a receita que chega mais INTEIRA à página, mesmo sem dado nenhum.
    melhor = min(perda(r) for r in p)
    return [r for r in p if perda(r) == melhor]  # nunca vazio: `melhor` veio do próprio pool


def escolher(nicho: str, semente: int = 0, con: sqlite3.Connection | None = None,
             dados: dict | None = None) -> dict:
    """Escolhe UMA receita do pool do segmento. `semente` (ex: id do lead) faz a escolha
    ser determinística e ROTATIVA — leads diferentes do mesmo nicho pegam receitas
    diferentes, em vez de todo mundo cair na primeira.

    `dados` = campos do briefing já resolvidos. Com ele o sorteio corre só entre as
    receitas VIÁVEIS, e o fallback é outra receita REAL do segmento — não o esqueleto
    genérico, que já foi causa de mesmice antes."""
    p = viaveis(nicho, dados, con)
    r = dict(p[semente % len(p)])
    r["ordem"] = _norm_ordem(r.get("ordem")) or ORDEM_DEFAULT
    return r


# ─────────────────────────── repositório de referências ───────────────────────────

def _tabela(c: sqlite3.Connection) -> None:
    c.execute("""CREATE TABLE IF NOT EXISTS templates_referencia (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tipo TEXT NOT NULL DEFAULT 'estrutura',   -- estrutura | (copy/oferta/motion quando existirem)
        segmento TEXT, tag TEXT, imagem TEXT,     -- imagem = caminho relativo em data/referencias/
        receita TEXT,                             -- JSON {ordem:[...], hero:"", leitura:"..."}
        aprovada INTEGER NOT NULL DEFAULT 0,
        criado_em TEXT)""")
    c.commit()


def _db(con: sqlite3.Connection | None = None) -> sqlite3.Connection:
    if con is not None:
        _tabela(con)
        return con
    from shared_core.storage import db
    c = db.conn()
    _tabela(c)
    return c


def referencia_salvar(tag: str, segmento: str, imagem: str, receita: dict | None = None,
                      tipo: str = "estrutura", aprovada: bool = False,
                      con: sqlite3.Connection | None = None) -> dict:
    """Grava uma referência. `receita` pode vir vazia (a visão preenche depois)."""
    seg = segmento_de(segmento) or (segmento or "").strip().lower()
    linha = (tipo, seg, (tag or "").strip()[:120], imagem,
             json.dumps(receita or {}, ensure_ascii=False), 1 if aprovada else 0,
             datetime.now(timezone.utc).isoformat())
    c = _db(con)
    cur = c.execute("INSERT INTO templates_referencia (tipo,segmento,tag,imagem,receita,aprovada,criado_em) "
                    "VALUES (?,?,?,?,?,?,?)", linha)
    c.commit()
    return {"id": cur.lastrowid, "tipo": tipo, "segmento": seg, "tag": linha[2],
            "imagem": imagem, "receita": receita or {}, "aprovada": bool(aprovada),
            "criado_em": linha[6]}


def _linha(r) -> dict:
    d = dict(r)
    try:
        d["receita"] = json.loads(d.get("receita") or "{}")
    except (ValueError, TypeError):
        d["receita"] = {}
    d["aprovada"] = bool(d.get("aprovada"))
    return d


def referencias_listar(segmento: str = "", con: sqlite3.Connection | None = None) -> list[dict]:
    c = _db(con)
    if segmento:
        seg = segmento_de(segmento) or segmento.strip().lower()
        rows = c.execute("SELECT * FROM templates_referencia WHERE segmento=? ORDER BY id DESC", (seg,))
    else:
        rows = c.execute("SELECT * FROM templates_referencia ORDER BY id DESC")
    return [_linha(r) for r in rows]


def referencias_aprovadas(segmento: str, con: sqlite3.Connection | None = None) -> list[dict]:
    seg = segmento_de(segmento) or (segmento or "").strip().lower()
    try:
        c = _db(con)
        rows = c.execute("SELECT * FROM templates_referencia WHERE segmento=? AND aprovada=1 "
                         "AND tipo='estrutura' ORDER BY id DESC", (seg,))
        return [_linha(r) for r in rows]
    except Exception as e:  # noqa: BLE001 — repositório indisponível não pode travar geração
        # Degradar continua certo; degradar em SILÊNCIO é o que custou caro. Este except
        # engolia `ModuleNotFoundError: shared_core` quando `packages/` saía do sys.path:
        # as 91 referências aprovadas sumiam do pool, todo site caía na ordem padrão do
        # motor, e não havia uma linha em lugar nenhum dizendo por quê. Foi exatamente o
        # que me enganou ao diagnosticar o "esqueleto genérico" em 2026-08-09.
        # ModuleNotFoundError é bug de deploy (path errado), não indisponibilidade — por
        # isso sobe de nível: WARNING some no meio do log, e é o caso mais provável.
        nivel = log.error if isinstance(e, (ModuleNotFoundError, ImportError)) else log.warning
        nivel("biblioteca de referências indisponível (%s: %s) — segmento=%r segue só com "
              "as receitas curadas", type(e).__name__, e, seg)
        return []


def diagnostico_biblioteca(con: sqlite3.Connection | None = None) -> dict:
    """Estado real da biblioteca de estrutura: o que alimenta o gerador e o que é inerte.

    Uma referência só chega ao gerador se `segmento` bate com uma chave de RECEITAS —
    `pool()` monta o pool a partir do segmento resolvido do nicho. Referência gravada em
    balde ('servicos', 'generico') fica APROVADA e nunca é consultada por lead nenhum:
    não contamina, e engana quem olha o total e acha que a biblioteca cresceu.

    Medido em 2026-08-06: 39 das 91 aprovadas (43%) eram órfãs assim."""
    c = _db(con)
    linhas = list(c.execute(
        "SELECT segmento, aprovada, COUNT(*) FROM templates_referencia GROUP BY 1,2"))
    uteis: dict[str, int] = {}
    orfas: dict[str, int] = {}
    pendentes = 0
    for seg, aprovada, n in linhas:
        seg = (seg or "?").strip().lower()
        if not aprovada:
            pendentes += n
        elif seg in RECEITAS:
            uteis[seg] = uteis.get(seg, 0) + n
        else:
            orfas[seg] = orfas.get(seg, 0) + n
    total_ap = sum(uteis.values()) + sum(orfas.values())
    return {
        "segmentos_do_motor": sorted(RECEITAS),
        "aprovadas_uteis": uteis,
        "aprovadas_orfas": orfas,
        "pendentes": pendentes,
        "total_aprovadas": total_ap,
        "pct_orfas": round(100 * sum(orfas.values()) / total_ap, 1) if total_ap else 0.0,
        # sem receita própria, a referência é inerte: ou reclassifica pro segmento certo,
        # ou cria a receita daquele segmento. Deletar não é necessário — só some da conta.
        "acao": "reclassificar para um segmento do motor, ou criar a receita do segmento",
    }


def referencia_aprovar(rid: int, aprovada: bool = True, con: sqlite3.Connection | None = None) -> dict:
    c = _db(con)
    c.execute("UPDATE templates_referencia SET aprovada=? WHERE id=?", (1 if aprovada else 0, rid))
    c.commit()
    return {"ok": True, "id": rid, "aprovada": aprovada}


def referencia_apagar(rid: int, con: sqlite3.Connection | None = None) -> dict:
    c = _db(con)
    c.execute("DELETE FROM templates_referencia WHERE id=?", (rid,))
    c.commit()
    return {"ok": True, "id": rid}


def ler_referencia(imagem_bytes: bytes, tag: str = "") -> dict:
    """Visão (Groq, grátis) lê o print e PROPÕE uma receita: ordem das seções + hero.
    Devolve {} se não conseguir — a referência fica guardada esperando aprovação manual."""
    if not imagem_bytes:
        return {}
    import sys
    from pathlib import Path
    raiz = str(Path(__file__).resolve().parents[2] / "packages")
    if raiz not in sys.path:
        sys.path.insert(0, raiz)
    prompt = (
        "Você analisa o LAYOUT de um site de referência para replicar a ESTRUTURA (não o conteúdo).\n"
        f"Contexto dado pelo humano: {tag or 'nenhum'}.\n"
        "Liste, de cima para baixo, quais destas seções aparecem e em que ORDEM. Nomes permitidos:\n"
        "sobre (quem somos / por que nós / diferenciais em cards)\n"
        "catalogo_motion (grade de serviços ou produtos)\n"
        "catalogo (lista do que está incluso)\n"
        "antesdepois (galeria antes/depois, portfólio visual)\n"
        "preco (planos/valores)\n"
        "calculadora (simulador)\n"
        "depoimentos (prova social, avaliações)\n"
        "faq (perguntas frequentes)\n"
        "formulario (captura de contato)\n"
        "E diga o tipo de hero: video, foto ou texto.\n"
        'Responda SÓ um JSON: {"ordem":["...","..."],"hero":"foto","leitura":"1 frase do padrão"}'
    )
    try:
        from shared_core.ai import visao
        txt, fonte = visao.analisar_frames([imagem_bytes], prompt=prompt)
    except Exception:  # noqa: BLE001
        return {}
    if not txt:
        return {}
    import re
    m = re.search(r"\{.*\}", txt, re.S)
    if not m:
        return {}
    try:
        d = json.loads(m.group(0))
    except ValueError:
        return {}
    ordem = _norm_ordem(d.get("ordem"))
    if not ordem:
        return {}
    hero = str(d.get("hero") or "").strip().lower()
    return {"ordem": ordem, "hero": hero if hero in ("video", "foto", "texto") else "",
            "leitura": str(d.get("leitura") or "")[:300], "fonte": fonte}


if __name__ == "__main__":  # self-check (sem rede, sem tocar o banco real)
    assert segmento_de("clínica odontológica em Bauru") == "clinica"
    assert segmento_de("Academia / musculação") == "academia"
    assert segmento_de("corretor de imóveis") == "imobiliaria"
    assert segmento_de("loja de parafuso") == ""
    # receita default do segmento
    r = escolher("academia")
    assert r["origem"] == "default" and r["ordem"][0] in BLOCOS, r
    # ROTAÇÃO: leads diferentes do mesmo nicho pegam receitas diferentes
    nomes = {escolher("academia", semente=i)["nome"] for i in range(6)}
    assert len(nomes) >= 3, f"deveria rotacionar entre as 3 receitas: {nomes}"
    # segmento desconhecido não inventa estrutura
    d = escolher("loja de parafuso")
    assert d["ordem"] == ORDEM_DEFAULT and d["nome"] == "default", d
    # ordem só aceita bloco conhecido
    assert _norm_ordem(["sobre", "SOBRE", "inexistente", "faq"]) == ["sobre", "faq"]
    # repositório em banco temporário
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    ref = referencia_salvar("hero com vídeo em loop", "academia", "ref/1.jpg",
                            {"ordem": ["preco", "sobre", "faq"], "hero": "video"}, con=con)
    assert ref["id"] and ref["segmento"] == "academia"
    assert not referencias_aprovadas("academia", con)          # não aprovada = fora do pool
    n_antes = len(pool("academia", con))
    referencia_aprovar(ref["id"], True, con=con)
    assert len(pool("academia", con)) == n_antes + 1, "aprovada tem que entrar no pool"
    assert any(x["origem"].startswith("referencia:") for x in pool("academia", con))
    # referência de OUTRO segmento não contamina (o balde único era o problema)
    referencia_salvar("grid de imóveis", "imobiliaria", "ref/2.jpg",
                      {"ordem": ["catalogo_motion"]}, aprovada=True, con=con)
    assert not any("imobili" in str(x) for x in pool("academia", con))
    assert len(referencias_listar("imobiliaria", con)) == 1
    referencia_apagar(ref["id"], con=con)
    assert len(pool("academia", con)) == n_antes
    assert ler_referencia(b"") == {}
    print(f"receitas OK — {sum(len(v) for v in RECEITAS.values())} receitas em "
          f"{len(RECEITAS)} segmentos, rotação, pool por segmento, referência não vaza de nicho")
