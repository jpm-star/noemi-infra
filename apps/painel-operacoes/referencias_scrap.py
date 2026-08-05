#!/usr/bin/env python3
"""Ingestão AUTOMÁTICA de referências de estrutura — o gargalo do motor.

Por que o motor gerava sempre a mesma coisa: `templates_referencia` tinha ZERO linhas.
A biblioteca existia, o pool de receitas sabia consumi-la, e ninguém nunca a alimentou
porque o único caminho era o JP colar print a print.

A DECISÃO QUE MUDA A QUALIDADE AQUI: pra uma URL, a estrutura está no HTML — não
precisa de visão. Ler o DOM dá a ordem real das seções, determinística, de graça e sem
gastar cota de LLM. Visão sobre screenshot é o caminho CARO e impreciso; fica só pro
print manual, onde não há HTML.

O que sai não é decorativo: é uma `ordem` no vocabulário de `receitas.BLOCOS`, que é
exatamente o que `receitas.pool()` consome pra montar site. Referência que não vira
ordem utilizável é enfeite — por isso `de_url` descarta o que não mapeia em nada.

Uso:
    python referencias_scrap.py --url https://exemplo.com --segmento clinica
    python referencias_scrap.py --galeria onepagelove --segmento clinica --limite 12
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(_AQUI))
sys.path.insert(0, str(_AQUI.parents[1] / "packages"))

# Sinais de cada bloco do NOSSO vocabulário dentro de um HTML alheio. Ordem de teste
# importa: o primeiro que casar ganha a seção, então o mais específico vem antes.
# São heurísticas de forma (tag/classe/id/texto), não de marca — a ideia é aprender
# ESTRUTURA, nunca copiar conteúdo.
_SINAIS: tuple[tuple[str, str], ...] = (
    ("antesdepois", r"antes[-_ ]?e?[-_ ]?depois|before[-_ ]?after|transforma|resultado"),
    ("depoimentos", r"depoiment|testimonial|review|avalia[çc][ãa]|o que dizem|clientes? dizem"),
    ("faq", r"\bfaq\b|perguntas frequentes|d[úu]vidas|frequently asked"),
    ("preco", r"pre[çc]o|pricing|planos?\b|investimento|tabela de valores|assinatura"),
    ("calculadora", r"calculadora|simulador|calculate|estimate|or[çc]amento online"),
    ("formulario", r"<form|contato|contact|fale conosco|agendar|solicite|get in touch"),
    ("catalogo_motion", r"galeria|gallery|portfolio|portf[óo]lio|nossos trabalhos|cases?\b"),
    ("catalogo", r"servi[çc]os|services|produtos|products|o que fazemos|especialidades"),
    ("sobre", r"sobre|about|quem somos|nossa hist[óo]ria|our story|who we are"),
)

GALERIAS = {
    "onepagelove": "https://onepagelove.com/inspiration",
    "lapaninja": "https://www.lapa.ninja/",
    "landbook": "https://land-book.com/",
}



# ── REGISTRO DE TENTATIVAS ───────────────────────────────────────────────────────
# Tabela PRÓPRIA, e não `templates_referencia`, por um motivo concreto: URL rejeitada
# por estrutura rasa (<3 blocos) NÃO entra em templates_referencia. Sem registro da
# TENTATIVA, o cron semanal rebaixaria as mesmas URLs ruins toda semana, pra sempre.
def _tabela_vistas(c) -> None:
    c.execute("""CREATE TABLE IF NOT EXISTS referencias_vistas (
        url TEXT PRIMARY KEY, fonte TEXT, resultado TEXT, blocos INTEGER,
        segmento TEXT, visto_em TEXT)""")


def _vistas() -> set[str]:
    import receitas
    c = receitas._db(None)
    _tabela_vistas(c)
    return {r[0] for r in c.execute("SELECT url FROM referencias_vistas")}


def _marcar_visto(url: str, fonte: str, resultado: str, blocos: int, segmento: str) -> None:
    import receitas
    from datetime import datetime, timezone
    c = receitas._db(None)
    _tabela_vistas(c)
    c.execute("INSERT OR REPLACE INTO referencias_vistas "
              "(url,fonte,resultado,blocos,segmento,visto_em) VALUES (?,?,?,?,?,?)",
              (url, fonte, resultado, blocos, segmento,
               datetime.now(timezone.utc).isoformat()))
    c.commit()


# Texto que denuncia o ramo do site. Só title+h1: é onde o negócio se nomeia; corpo
# inteiro traria menu e rodapé e casaria segmento errado.
def _segmento_do_html(html: str) -> str:
    import receitas
    pedacos = []
    for tag in ("title", "h1", "h2"):
        for m in re.finditer(rf"<{tag}[^>]*>(.*?)</{tag}>", html or "", re.S | re.I):
            pedacos.append(re.sub(r"<[^>]+>", " ", m.group(1)))
            if len(pedacos) >= 4:
                break
    texto = " ".join(pedacos)[:400]
    return receitas.segmento_de(texto) or ""


def _blocos_do_html(html: str) -> list[str]:
    """Ordem das seções do HTML no vocabulário de `receitas.BLOCOS`.

    Ordena pela POSIÇÃO da 1ª ocorrência de cada sinal no corpo. A 1ª tentativa fatiava
    por `<section>` e casava um bloco por fatia — morreu no mundo real: site moderno não
    usa seção semântica, a página inteira virava uma fatia só e rendia 1 bloco (medido:
    1 de 3 clínicas reais passava). Posição funciona com qualquer marcação, porque a
    ordem visual do documento é a ordem do argumento — que é o que queremos aprender."""
    import receitas
    corpo = html[html.lower().find("<body"):] if "<body" in html.lower() else html
    # fora script/style/svg (JS e ícone têm palavra que casa sinal e mente na posição)
    corpo = re.sub(r"<(script|style|svg|noscript)\b.*?</\1>", " ", corpo, flags=re.S | re.I)
    # o <head> e menus repetem os termos; o menu fica no topo e distorceria tudo.
    # Cortar o 1º <nav>/<header> resolve sem precisar entender o site.
    corpo = re.sub(r"<(nav|header)\b.*?</\1>", " ", corpo, count=2, flags=re.S | re.I)

    posicoes: dict[str, int] = {}
    for bloco, rx in _SINAIS:
        if bloco not in receitas.BLOCOS:
            continue
        m = re.search(rx, corpo, re.I)
        if m:
            posicoes[bloco] = m.start()
    return [b for b, _ in sorted(posicoes.items(), key=lambda kv: kv[1])]


def de_url(url: str, segmento: str = "", tag: str = "", aprovada: bool = False,
           fonte: str = "manual") -> dict:
    """Uma URL → uma referência de ESTRUTURA gravada. {ok, ordem, motivo}.

    Descarta o que rende menos de 3 blocos: referência de 1-2 seções não ensina ordem
    de argumento nenhuma e só sujaria o pool com ruído."""
    import ingestao
    import receitas
    url = (url or "").strip()
    if not url.startswith("http"):
        url = "https://" + url.lstrip("/")
    try:
        html = ingestao._buscar(url)      # MESMO fetch da ingestão (UA, gzip, timeout)
    except Exception as e:  # noqa: BLE001
        _marcar_visto(url, fonte, f"erro:{type(e).__name__}", 0, segmento or "")
        return {"ok": False, "url": url, "motivo": f"não baixou: {type(e).__name__}"}
    ordem = _blocos_do_html(html or "")
    # segmento vazio = DETECTA do HTML já baixado (sem 2ª requisição, sem LLM).
    # Também melhora o botão manual, que hoje obriga escolher o segmento na mão.
    seg = (segmento or "").strip() or _segmento_do_html(html or "") or "generico"
    if len(ordem) < 3:
        _marcar_visto(url, fonte, "rasa", len(ordem), seg)
        return {"ok": False, "url": url, "ordem": ordem, "segmento": seg,
                "motivo": f"só {len(ordem)} bloco(s) — pouco pra ensinar ordem"}
    hero = "video" if "<video" in (html or "").lower() else ""
    receita = {"ordem": ordem, "hero": hero,
               "porque": f"estrutura observada em {re.sub(r'^https?://', '', url)[:60]}"}
    receitas.referencia_salvar(
        tag=tag or re.sub(r"^https?://(www\.)?", "", url)[:60],
        segmento=seg, imagem=url, receita=receita,
        tipo="estrutura", aprovada=aprovada)
    _marcar_visto(url, fonte, "salva", len(ordem), seg)
    return {"ok": True, "url": url, "ordem": ordem, "hero": hero, "segmento": seg}


def _links_da_galeria(html: str, base: str) -> list[str]:
    """URLs de sites REAIS linkados na galeria. Ignora link interno da própria galeria
    (é a diferença entre aprender com 12 sites e aprender com 12 páginas do mesmo site)."""
    host = re.sub(r"^https?://(www\.)?", "", base).split("/")[0]
    achados: list[str] = []
    for m in re.finditer(r'href=["\'](https?://[^"\'?#]+)', html, re.I):
        u = m.group(1)
        h = re.sub(r"^https?://(www\.)?", "", u).split("/")[0]
        if host in h or any(x in h for x in ("twitter", "facebook", "instagram", "github",
                                             "linkedin", "youtube", "pinterest", "t.co")):
            continue
        raiz = f"https://{h}"
        if raiz not in achados:
            achados.append(raiz)
    return achados


def de_galeria(galeria: str, segmento: str = "", limite: int = 12,
               aprovada: bool = False, so_novos: bool = True) -> dict:
    """Galeria aberta → N referências, sem o JP colar print nenhum.

    Só galerias públicas e sem paywall (as que o JP indicou). Pega ESTRUTURA: nada de
    texto, marca ou imagem do site alheio entra no nosso banco."""
    import ingestao
    base = GALERIAS.get(galeria, galeria)
    try:
        html = ingestao._buscar(base)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "galeria": base, "erro": f"{type(e).__name__}"}
    urls = _links_da_galeria(html or "", base)
    ja = _vistas() if so_novos else set()
    novos = [u for u in urls if u not in ja][:max(1, limite)]
    if not novos:
        # fonte sem novidade não é erro: é o caso NORMAL numa rodada semanal
        return {"ok": True, "galeria": base, "tentadas": 0, "salvas": 0,
                "referencias": [], "descartadas": [], "sem_novidade": True,
                "ja_vistos": len(urls)}
    fora = [de_url(u, segmento, aprovada=aprovada, fonte=galeria) for u in novos]
    bons = [r for r in fora if r.get("ok")]
    return {"ok": True, "galeria": base, "tentadas": len(fora), "salvas": len(bons),
            "sem_novidade": False, "referencias": bons,
            "descartadas": [{"url": r["url"], "motivo": r["motivo"]}
                            for r in fora if not r.get("ok")][:8]}



# ── RODADA SEMANAL (cron) ────────────────────────────────────────────────────────
LOG = Path(os.environ.get("NOEMI_DATA_DIR", str(_AQUI.parents[1] / "data"))) / "pool.log"


def rodada_semanal(limite_por_fonte: int = 10) -> dict:
    """Varre as 3 galerias e ingere só o que é NOVO. Chamada pelo timer semanal.

    Reusa `de_galeria` — a MESMA função do botão manual. Nenhuma extração duplicada
    aqui: o que esta função acrescenta é iterar as fontes, tolerar fonte sem novidade
    (que é o caso normal numa semana calma, não erro) e deixar uma linha legível."""
    from collections import Counter
    from datetime import datetime, timezone
    inicio = datetime.now(timezone.utc)
    por_fonte, por_segmento, erros = {}, Counter(), []
    for fonte in GALERIAS:
        try:
            r = de_galeria(fonte, segmento="", limite=limite_por_fonte, aprovada=True)
        except Exception as e:  # noqa: BLE001 — uma fonte fora não derruba a rodada
            erros.append(f"{fonte}: {type(e).__name__}")
            por_fonte[fonte] = {"salvas": 0, "erro": type(e).__name__}
            continue
        if not r.get("ok"):
            erros.append(f"{fonte}: {r.get('erro', 'falhou')}")
            por_fonte[fonte] = {"salvas": 0, "erro": r.get("erro", "falhou")}
            continue
        por_fonte[fonte] = {"salvas": r.get("salvas", 0),
                            "tentadas": r.get("tentadas", 0),
                            "sem_novidade": r.get("sem_novidade", False)}
        for ref in r.get("referencias", []):
            por_segmento[ref.get("segmento") or "generico"] += 1

    total = sum(v.get("salvas", 0) for v in por_fonte.values())
    seg_txt = " ".join(f"{k}={v}" for k, v in sorted(por_segmento.items())) or "-"
    fon_txt = " ".join(
        f"{k}={v.get('salvas', 0)}" + ("(sem novidade)" if v.get("sem_novidade") else "")
        + (f"(ERRO {v['erro']})" if v.get("erro") else "")
        for k, v in por_fonte.items())
    linha = (f"{inicio.isoformat(timespec='seconds')} rodada_semanal "
             f"novas={total} | fontes: {fon_txt} | segmentos: {seg_txt}"
             + (f" | erros: {'; '.join(erros)}" if erros else ""))
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(linha + "\n")
    except OSError:
        pass
    print(linha)
    return {"ok": True, "novas": total, "por_fonte": por_fonte,
            "por_segmento": dict(por_segmento), "erros": erros, "log": str(LOG)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url")
    ap.add_argument("--galeria", choices=[*GALERIAS, "todas"])
    ap.add_argument("--segmento", default="", help="vazio = detecta do HTML")
    ap.add_argument("--limite", type=int, default=12)
    ap.add_argument("--aprovar", action="store_true", help="entra no pool já aprovada")
    ap.add_argument("--semanal", action="store_true", help="rodada do cron: 3 fontes, só o novo")
    a = ap.parse_args()
    if a.semanal:
        rodada_semanal(a.limite)
        return
    if a.url:
        print(de_url(a.url, a.segmento, aprovada=a.aprovar))
        return
    alvos = list(GALERIAS) if a.galeria == "todas" else [a.galeria or "onepagelove"]
    for g in alvos:
        r = de_galeria(g, a.segmento, a.limite, aprovada=a.aprovar)
        print(f"{g}: {r.get('salvas', 0)}/{r.get('tentadas', 0)} salvas")
        for d in r.get("descartadas", [])[:3]:
            print("   descartada:", d["url"][:50], "—", d["motivo"])


if __name__ == "__main__":
    main()
