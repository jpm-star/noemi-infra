"""Gera vários sites de uma vez a partir de pastas — o caminho das 5 demos.

O FLUXO QUE ISTO ATENDE: o JP organiza no Drive uma pasta por cliente, nomeada
`Empresa - Segmento - Cidade`, com as fotos dentro. Baixa tudo, aponta este script pra
pasta-mãe, e sai um site por subpasta com URL, QA e relatório.

POR QUE O NOME DA PASTA É O BRIEFING: `Studio Charles - salão de beleza - Lins` já tem
as três coisas que o motor precisa (nome, nicho, cidade). A organização que você ia
fazer de qualquer jeito vira a entrada estruturada — sem formulário, sem planilha.

POR QUE PASTA LOCAL E NÃO A API DO DRIVE: falar com o Drive exige credencial de serviço,
escopo OAuth e uma dependência pesada pra resolver o que um arrastar de mouse resolve.
Baixar a pasta é grátis; a integração custaria uma decisão de arquitetura por conta de
zero ganho real (ver CLAUDE.md).

O QUE ELE FAZ POR SITE, nesta ordem:
  1. lê o nome da pasta -> nome, nicho, cidade
  2. a MAIOR foto vira hero; as demais alimentam o acervo do NICHO (com a portaria de
     `acervo_ingerir`: foto com texto impresso não entra)
  3. gera pelo motor, com o acervo do segmento se o cliente não mandou foto suficiente
  4. roda o gate visual e reporta o VEREDITO (inclusive 'indeterminado')
  5. escreve um relatório .md com tudo — é o que vai junto na conversa com o cliente

Rodar:
    python lote_sites.py ~/Downloads/clientes --whatsapp 5514998745847
    python lote_sites.py ~/Downloads/clientes --so-listar    # confere antes de gastar
    python lote_sites.py --check
"""
from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(_AQUI))
sys.path.insert(0, str(_AQUI.parents[1] / "packages"))

IMG_EXT = {".jpg", ".jpeg", ".png", ".webp"}
# `Empresa - Segmento - Cidade`. Aceita hífen simples, travessão e " – " porque o Drive
# e o macOS trocam o caractere sem avisar, e uma pasta renomeada no celular não pode
# quebrar a geração.
_SEP = re.compile(r"\s*[-–—]\s*")


def ler_pasta(d: Path) -> dict | None:
    """`Empresa - Segmento - Cidade` -> briefing parcial. None se o nome não seguir.

    None é FILTRO, não erro: pasta "fotos antigas" ou "_backup" no meio do lote não pode
    virar site de cliente com nome de pasta."""
    partes = [p.strip() for p in _SEP.split(d.name) if p.strip()]
    if len(partes) < 2 or d.name.startswith((".", "_")):
        return None
    fotos = sorted((f for f in d.iterdir() if f.suffix.lower() in IMG_EXT and f.is_file()),
                   key=lambda f: -f.stat().st_size)
    return {"nome_empresa": partes[0], "nicho": partes[1].lower(),
            "cidade": partes[2] if len(partes) > 2 else "", "fotos": fotos, "pasta": d}


def _acervo_do_nicho(nicho: str, fotos: list[Path]) -> list[str]:
    """Fotos do cliente entram no acervo do NICHO (menos a de hero). Sem foto do
    cliente, usa o acervo que já existe pro segmento.

    Foto do cliente vence a do acervo sempre: é o negócio dele de verdade. Mas passa
    pela mesma portaria — o post de Instagram com texto impresso reprova igual."""
    import acervo_fotos
    if len(fotos) > 1:
        import acervo_ingerir
        r = acervo_ingerir.ingerir(nicho, [str(f) for f in fotos[1:]])
        if r["aprovadas"]:
            return r["urls"]
    try:
        return acervo_fotos.garantir(nicho) or []
    except Exception:  # noqa: BLE001 — acervo é enfeite, não trava a geração
        return []


def gerar_um(b: dict, whatsapp: str, com_qa: bool = True) -> dict:
    """Gera um site e devolve o resultado com o veredito do gate visual."""
    for k, v in dict(SITE_ORQUESTRADOR="llm", SITE_GERADOR="template", SITE_DEPLOY="local",
                     SITE_OUT_DIR="/var/www/sites",
                     SITE_BASE_URL="https://p.jpos.com.br").items():
        os.environ.setdefault(k, v)
    if "/root/motor-site" not in sys.path:
        sys.path.insert(0, "/root/motor-site")
    from app.pipeline import montar_site

    t0 = time.monotonic()
    briefing = {"nome_empresa": b["nome_empresa"], "nicho": b["nicho"],
                "whatsapp": whatsapp, "cidade": b["cidade"], "cor_primaria": None,
                "diferenciais": [], "publico": "",
                "acervo": _acervo_do_nicho(b["nicho"], b["fotos"])}
    try:
        r = montar_site(briefing)
    except Exception as e:  # noqa: BLE001 — um cliente que falha não derruba o lote
        return {**b, "ok": False, "erro": f"{type(e).__name__}: {e}"[:180],
                "segundos": round(time.monotonic() - t0, 1)}
    url = r.deploy.url
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    out = {**b, "ok": True, "url": url, "slug": slug,
           "segundos": round(time.monotonic() - t0, 1),
           # só as posições PREENCHIDAS: o acervo devolve "" onde não há foto, e contar
           # o comprimento da lista diria "4 fotos" pra um acervo vazio de 4 posições
           "fotos_usadas": sum(1 for u in briefing["acervo"] if u),
           "veredito": "não auditado"}
    if com_qa:
        try:
            import qa_visual
            a = qa_visual.auditar(url)
            out["veredito"] = a["veredito"]
            out["defeitos"] = [f"{s['sonda']}: {s['txt']}" for s in a["sondas"][:4]] \
                + list(a["defeitos_visao"])[:4]
            out["fonte_visao"] = a.get("fonte_visao", "-")
        except Exception as e:  # noqa: BLE001
            out["veredito"] = f"QA não rodou ({type(e).__name__})"
    return out


def relatorio(res: list[dict]) -> str:
    """O .md que vai junto na conversa. Diz o que foi feito e o que NÃO foi verificado."""
    ok = [r for r in res if r.get("ok")]
    L = [f"# Lote de sites — {len(ok)}/{len(res)} gerados", ""]
    for r in res:
        if not r.get("ok"):
            L += [f"### ⛔ {r['nome_empresa']}", f"- **não gerou:** `{r.get('erro','?')}`", ""]
            continue
        icone = {"aprovado": "✅", "reprovado": "⛔"}.get(r["veredito"], "⚠️")
        L += [f"### {icone} {r['nome_empresa']}",
              f"- **site:** {r['url']}",
              f"- **ramo/cidade:** {r['nicho']} · {r['cidade'] or '—'}",
              f"- **gerado em:** {r['segundos']}s · {r['fotos_usadas']} foto(s) nos cards",
              f"- **gate visual:** {r['veredito']}"
              + (f" (juiz: `{r.get('fonte_visao','-')}`)" if r["veredito"] == "indeterminado" else "")]
        for d in r.get("defeitos", [])[:5]:
            L.append(f"  - {d}")
        if r["veredito"] == "indeterminado":
            L.append("  - *sem veredito: as sondas passaram mas o juiz de visão não "
                     "respondeu. Olhe você antes de mandar pro cliente.*")
        L.append("")
    ind = sum(1 for r in ok if r["veredito"] == "indeterminado")
    if ind:
        L += [f"> ⚠️ {ind} site(s) sem veredito visual. Isso não é aprovação — "
              "é o gate dizendo que ninguém olhou.", ""]
    return "\n".join(L)


def rodar(raiz: Path, whatsapp: str, com_qa: bool = True) -> list[dict]:
    alvos = [b for b in (ler_pasta(d) for d in sorted(raiz.iterdir()) if d.is_dir()) if b]
    return [gerar_um(b, whatsapp, com_qa) for b in alvos]


def _autoteste() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        raiz = Path(tmp)
        for nome in ("Studio Charles - salão de beleza - Lins",
                     "Auto Teco – oficina mecânica – Botucatu",   # travessão do macOS
                     "Só Nome E Ramo - pet shop",
                     "_backup", "fotos antigas"):
            (raiz / nome).mkdir()
        (raiz / "Studio Charles - salão de beleza - Lins" / "a.jpg").write_bytes(b"x" * 10)
        (raiz / "Studio Charles - salão de beleza - Lins" / "grande.jpg").write_bytes(b"x" * 99)
        lidas = [b for b in (ler_pasta(d) for d in sorted(raiz.iterdir()) if d.is_dir()) if b]
        nomes = sorted(b["nome_empresa"] for b in lidas)
        assert nomes == ["Auto Teco", "Studio Charles", "Só Nome E Ramo"], nomes
        # "fotos antigas" tem só uma parte -> não é cliente; "_backup" é infraestrutura
        assert all(b["nome_empresa"] not in ("_backup", "fotos antigas") for b in lidas)
        b = [x for x in lidas if x["nome_empresa"] == "Studio Charles"][0]
        assert b["nicho"] == "salão de beleza" and b["cidade"] == "Lins", b
        # a MAIOR foto é a primeira: é ela que vira hero
        assert b["fotos"][0].name == "grande.jpg", [f.name for f in b["fotos"]]
        # travessão do macOS lê igual ao hífen
        t = [x for x in lidas if x["nome_empresa"] == "Auto Teco"][0]
        assert t["nicho"] == "oficina mecânica" and t["cidade"] == "Botucatu", t
        # sem cidade não trava: o motor cai em "na sua região"
        s = [x for x in lidas if x["nome_empresa"] == "Só Nome E Ramo"][0]
        assert s["cidade"] == "" and s["nicho"] == "pet shop", s

    # o relatório não pode transformar 'indeterminado' em ✅
    md = relatorio([{"ok": True, "nome_empresa": "X", "url": "u", "nicho": "n", "cidade": "c",
                     "segundos": 1, "fotos_usadas": 0, "veredito": "indeterminado",
                     "fonte_visao": "sem_juiz:ocr"},
                    {"ok": False, "nome_empresa": "Y", "erro": "boom"}])
    assert "⚠️ X" in md and "✅" not in md and "⛔ Y" in md, md
    assert "não é aprovação" in md, md
    print("lote_sites OK — nome da pasta vira briefing (hífen ou travessão), pasta sem "
          "ramo e _backup ficam de fora, maior foto é o hero, e 'indeterminado' não "
          "vira ✅ no relatório")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Gera um site por subpasta 'Empresa - Segmento - Cidade'.")
    ap.add_argument("raiz", nargs="?", help="pasta-mãe baixada do Drive")
    ap.add_argument("--whatsapp", default=os.environ.get("JPOS_WHATSAPP", "5514998745847"))
    ap.add_argument("--so-listar", action="store_true", help="mostra o que faria, sem gerar")
    ap.add_argument("--sem-qa", action="store_true", help="pula o gate visual (mais rápido)")
    ap.add_argument("--saida", default="", help="onde gravar o relatório .md")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    if a.check:
        _autoteste()
        raise SystemExit(0)
    if not a.raiz:
        ap.error("informe a pasta-mãe (ou use --check)")
    raiz = Path(a.raiz).expanduser()
    if not raiz.is_dir():
        raise SystemExit(f"não achei a pasta {raiz}")
    if a.so_listar:
        for d in sorted(raiz.iterdir()):
            if not d.is_dir():
                continue
            b = ler_pasta(d)
            print(f"  {'✓' if b else '·'} {d.name}"
                  + (f"  ->  {b['nome_empresa']} | {b['nicho']} | {b['cidade'] or '—'} "
                     f"| {len(b['fotos'])} foto(s)" if b else "  (fora do padrão, pulada)"))
        raise SystemExit(0)
    res = rodar(raiz, a.whatsapp, com_qa=not a.sem_qa)
    md = relatorio(res)
    print(md)
    destino = Path(a.saida) if a.saida else raiz / "RELATORIO.md"
    destino.write_text(md, encoding="utf-8")
    print(f"\nrelatório em {destino}")
