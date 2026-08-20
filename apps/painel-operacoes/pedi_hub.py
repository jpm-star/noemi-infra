"""Central Pé Di — o que virava brief agora é botão no painel.

Tudo que este módulo expõe já existia como função; o que faltava era caminho pra
JP acionar sem pedir pra alguém rodar script. Aqui não há lógica de negócio nova:
é a camada que liga o painel ao que já foi construído.

  gerar demo        → gen_demos_venda (foto real do Places + gate de motion)
  captar leads      → pedi_leads (Places + leitura do site do lead)
  sondar negócio    → Places direto, ANTES de gerar (evita o caso Canevaroli:
                      gerar o demo inteiro pra descobrir que não há foto)
  cotar             → pedi_custo
  primeiro toque    → pedi_toque

ponytail: job roda em thread com status consultável, não em ARQ. ARQ pediria
Redis + worker + unit systemd nova pra um operador único que está com a tela
aberta. Se o painel reiniciar no meio de um job, ele se perde — é aceitável aqui.
Upgrade quando houver mais de um operador ou job que valha retomar: trocar
`_iniciar` por enfileiramento, a assinatura já é a mesma.
"""
from __future__ import annotations

import os
import threading
import time
import traceback
import unicodedata
import re
from pathlib import Path

SITES = Path("/var/www/sites")

_JOBS: dict[str, dict] = {}
_LOCK = threading.Lock()
_SEQ = [0]


def _slug(txt: str) -> str:
    t = unicodedata.normalize("NFKD", txt or "").encode("ascii", "ignore").decode()
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", t.lower())).strip("-")[:60]


# ─────────────────────────── jobs ───────────────────────────

def _iniciar(rotulo: str, fn, *args, **kw) -> str:
    """Roda fn numa thread e devolve o id pra tela acompanhar."""
    with _LOCK:
        _SEQ[0] += 1
        jid = f"j{_SEQ[0]:04d}"
        _JOBS[jid] = {"id": jid, "rotulo": rotulo, "estado": "rodando",
                      "inicio": time.time(), "log": [], "resultado": None, "erro": None}

    def _rodar():
        try:
            r = fn(*args, **kw)
            _JOBS[jid].update(estado="ok", resultado=r)
        except Exception as e:  # noqa: BLE001 — o erro é o resultado do job, não crash do painel
            _JOBS[jid].update(estado="erro", erro=f"{type(e).__name__}: {e}",
                              log=_JOBS[jid]["log"] + traceback.format_exc().splitlines()[-3:])
        finally:
            _JOBS[jid]["fim"] = time.time()

    threading.Thread(target=_rodar, daemon=True).start()
    return jid


def job(jid: str) -> dict:
    j = dict(_JOBS.get(jid) or {"estado": "desconhecido"})
    if j.get("inicio"):
        j["duracao"] = round((j.get("fim") or time.time()) - j["inicio"], 1)
    return j


def jobs(limite: int = 12) -> list[dict]:
    return [job(k) for k in list(_JOBS)[-limite:][::-1]]


# ─────────────────────────── demos ───────────────────────────

def listar_demos() -> list[dict]:
    """Todo demo publicado, com tier, motion e quantas fotos são REAIS.

    Lê do disco, não de um registro paralelo: o que está em /var/www/sites é o que
    o lead abre, e um índice separado seria mais uma coisa pra divergir.
    """
    if not SITES.is_dir():
        return []
    fora = []
    for d in sorted(SITES.iterdir()):
        idx = d / "index.html"
        if not idx.is_dir() and idx.exists():
            html = idx.read_text(encoding="utf-8", errors="ignore")
            tier = (re.search(r'data-tier="([^"]+)"', html) or [None, "—"])[1]
            mot = (re.search(r'data-motion="([^"]+)"', html) or [None, "—"])[1]
            nome = (re.search(r"<title>([^<]+)", html) or [None, d.name])[1]
            img = d / "img"
            fora.append({
                "slug": d.name, "nome": nome.strip(), "tier": tier, "motion": mot,
                "fotos_reais": len(list(img.glob("*.jpg"))) if img.is_dir() else 0,
                "placeholders": len(list(img.glob("ph*.svg"))) if img.is_dir() else 0,
                "generico": ("loremflickr" in html or "picsum" in html),
                "url": f"https://p.jpos.com.br/{d.name}/",
                "atualizado": int(idx.stat().st_mtime),
            })
    return fora


def fila_demos() -> list[dict]:
    """Demos prontos pra prospectar: contato + vídeo + mensagem já escrita.

    O vídeo vai como LINK do próprio domínio, não anexo: o WhatsApp renderiza
    preview com play, então o lead vê o site dele antes de decidir clicar. É o
    "vídeo de cara" sem disparo automático — disparo em massa queima o número e é
    decisão do JP, não default de ferramenta.
    """
    import json as _json
    import urllib.parse
    fora = []
    for d in listar_demos():
        meta_f = SITES / d["slug"] / "meta.json"
        tem_video = (SITES / d["slug"] / "video.mp4").exists()
        if not meta_f.exists():
            continue
        try:
            m = _json.loads(meta_f.read_text(encoding="utf-8"))
        except ValueError:
            continue
        fone = re.sub(r"\D", "", m.get("telefone") or "")
        # fixo sem DDD (8 dígitos) não vira WhatsApp: prefixar 55 produziria um
        # número que EXISTE e é de outra pessoa. Melhor sem link do que link errado.
        if len(fone) < 10:
            fone = ""
        elif not fone.startswith("55"):
            fone = "55" + fone
        video = f"https://p.jpos.com.br/{d['slug']}/video.mp4"
        # gancho honesto: muda conforme ele já tenha site ou não
        if m.get("site_atual"):
            gancho = ("Vi o site de vocês e montei uma versão nova pra comparar — "
                      "com as avaliações do Google de vocês na página.")
        else:
            gancho = ("Vocês não têm site e apareceram no Google com nota alta. "
                      "Montei um pra vocês verem como ficaria.")
        nota_br = str(m.get("nota", "")).replace(".", ",")  # 4.6 -> 4,6
        nota = (f" Vocês estão com {nota_br} de {m['avaliacoes']} avaliações — "
                f"isso é o que a página mostra logo de cara."
                if m.get("nota") and m.get("avaliacoes") else "")
        msg = (f"Oi! Aqui é o João Pedro, da JPOS.\n\n{gancho}{nota}\n\n"
               f"Vídeo de 10s: {video}\nSite: {d['url']}\n\n"
               f"Fiz sem compromisso. Se não fizer sentido, é só falar.")
        fora.append({
            "slug": d["slug"], "negocio": m.get("negocio") or d["nome"], "tier": d["tier"],
            "telefone": m.get("telefone") or "", "tem_video": tem_video,
            "tem_site_hoje": bool(m.get("site_atual")),
            "nota": m.get("nota"), "avaliacoes": m.get("avaliacoes", 0),
            "url": d["url"], "video": video if tem_video else "", "mensagem": msg,
            "link": f"https://wa.me/{fone}?text={urllib.parse.quote(msg)}" if fone else "",
        })
    fora.sort(key=lambda x: (x["avaliacoes"] or 0), reverse=True)
    return fora


def sondar(busca: str) -> dict:
    """O negócio tem perfil no Google e quantas fotos? Rodar ANTES de gerar.

    Existe porque descobrir que um lead não tem foto DEPOIS de gerar o demo custa
    uma rodada inteira — foi o que aconteceu com o Canevaroli.
    """
    import gen_demos_venda as g
    k = g._chave()
    r = g._get(g._TEXTSEARCH, {"query": busca, "language": "pt-BR", "key": k})
    res = r.get("results") or []
    if not res:
        return {"achou": False, "status": r.get("status"), "busca": busca,
                "recado": "sem perfil no Google Places — o demo sai com bloco de cor "
                          "da marca, e isso vira gancho de venda"}
    top = res[0]
    det = g._get(g._DETAILS, {"place_id": top["place_id"],
                              "fields": "photos,name,formatted_address,website,"
                                        "formatted_phone_number,rating,user_ratings_total",
                              "language": "pt-BR", "key": k}).get("result") or {}
    n = len(det.get("photos") or [])
    return {"achou": True, "nome": det.get("name"), "endereco": det.get("formatted_address"),
            "telefone": det.get("formatted_phone_number"), "site": det.get("website") or "",
            "nota": det.get("rating"), "avaliacoes": det.get("user_ratings_total"),
            "fotos": n, "busca": busca,
            "recado": ("dá pra gerar com foto real" if n >= 3 else
                       f"só {n} foto(s) — parte dos cards vai sair em bloco de cor")}


def gerar_demo(nome: str, cidade: str, tier: str, modelo: str, slug: str = "") -> dict:
    """Cria um demo novo a partir de um dos modelos de serviço já escritos.

    `modelo` existe porque copy de serviço é o que leva tempo pra escrever bem, e
    reaproveitar o conjunto certo (clube, assessoria, box...) entrega um demo
    apresentável em segundos. Trocar texto depois é editar o dataset.
    """
    import gen_demos_venda as g
    slug = _slug(slug or f"{nome}-{cidade}")
    if not slug:
        raise ValueError("nome inválido")
    base = g.MODELOS.get(modelo)
    if not base:
        raise ValueError(f"modelo desconhecido: {modelo}")
    d = {"negocio": nome.strip(), "tier": (tier or "T3").upper(),
         "busca": f"{nome}, {cidade}, SP",
         "cor": base["cor"], "cor2": base["cor2"],
         "tagline": base["tagline"].format(cidade=cidade),
         "servicos": base["servicos"](cidade)}
    g.NEGOCIOS[slug] = d
    return g.gerar([slug])[slug]


def regerar(slug: str, tier: str = "") -> dict:
    """Republica um demo, opcionalmente noutro tier — pra comparar T1 e T4 ao vivo."""
    import gen_demos_venda as g
    if slug not in g.NEGOCIOS:
        raise ValueError(f"{slug} não é um demo gerenciado (foi criado fora do painel)")
    if tier:
        g.NEGOCIOS[slug]["tier"] = tier.upper()
    return g.gerar([slug])[slug]


def excluir_demo(slug: str) -> dict:
    """Remove o demo do ar. Só dentro de /var/www/sites e só um nível — o slug vem
    da tela, e um '..' aqui apagaria coisa que não é demo."""
    limpo = _slug(slug)
    alvo = SITES / limpo
    if not limpo or alvo.parent != SITES or not alvo.is_dir():
        raise ValueError(f"slug inválido: {slug}")
    import shutil
    shutil.rmtree(alvo)
    return {"removido": limpo}


def corrigir_imagens(slug: str) -> dict:
    """Troca SÓ as imagens de um demo antigo, sem tocar copy, tier ou layout.

    Os demos gerados antes do gate ainda apontam pro loremflickr com fallback
    picsum aleatório — é o bug do gato, vivo em demo que já está em prospecção.
    Regerar por cima traria copy diferente e mexeria no que já funciona; aqui só
    as URLs de imagem mudam.
    """
    import gen_demos_venda as g
    alvo = SITES / _slug(slug)
    idx = alvo / "index.html"
    if alvo.parent != SITES or not idx.exists():
        raise ValueError(f"demo inexistente: {slug}")
    html = idx.read_text(encoding="utf-8")
    if "loremflickr" not in html and "picsum" not in html:
        return {"slug": slug, "ja_estava_ok": True, "trocadas": 0}

    nome = (re.search(r"<title>([^<]+)", html) or [None, slug])[1].strip()
    cidade = _slug(slug).split("-")[-1]
    fotos = g.fotos_do_negocio(f"{nome}, {cidade}, SP", g._chave(), quantas=6)
    if not fotos:
        return {"slug": slug, "erro": "sem foto no Places", "nome": nome, "trocadas": 0}

    (alvo / "img").mkdir(parents=True, exist_ok=True)
    locais = []
    for i, dados in enumerate(fotos, 1):
        (alvo / "img" / f"{i:02d}.jpg").write_bytes(dados)
        locais.append(f"img/{i:02d}.jpg")

    # Cada URL de banco vira foto real, ciclando se houver menos foto que card.
    # Ciclar repete imagem — repetir foto do lugar CERTO é muito melhor que uma
    # foto certa e cinco aleatórias.
    n = [0]

    def _troca(m):
        u = locais[n[0] % len(locais)]
        n[0] += 1
        return u

    html2 = re.sub(r'https://loremflickr\.com/[^"\']+', _troca, html)
    html2 = re.sub(r'https://picsum\.photos/[^"\']+', _troca, html2)
    idx.write_text(html2, encoding="utf-8")
    return {"slug": slug, "nome": nome, "fotos_baixadas": len(fotos),
            "trocadas": n[0], "limpo": "loremflickr" not in html2 and "picsum" not in html2}


def job_corrigir_imagens(slugs: list[str]) -> str:
    def _rodar():
        return [corrigir_imagens(s) for s in slugs]
    return _iniciar(f"corrigir imagem · {len(slugs)} demo(s)", _rodar)


# ─────────────────────────── ações longas ───────────────────────────

def job_gerar_demo(nome: str, cidade: str, tier: str, modelo: str) -> str:
    return _iniciar(f"demo · {nome}", gerar_demo, nome, cidade, tier, modelo)


def job_regerar(slug: str, tier: str = "") -> str:
    return _iniciar(f"regerar · {slug}", regerar, slug, tier)


def job_captar(segmento: str, cidades: list[str], alvo: int) -> str:
    """Captação sob demanda: segmento novo sem esperar brief."""
    def _rodar():
        import pedi_leads
        chave = pedi_leads._chave()
        pedi_leads.SEGMENTOS.setdefault(segmento, {"alvo": alvo, "termos": (segmento,)})
        pedi_leads.SEGMENTOS[segmento]["alvo"] = alvo
        pedi_leads._ADERENCIA.setdefault(segmento, _slug(segmento).replace("-", "|"))
        achados, diag = pedi_leads.coletar_segmento(
            segmento, chave, cidades=tuple(cidades) or pedi_leads.CIDADES)
        destino = os.environ.get("PEDI_LEADS_CSV", "/root/jpos-entregaveis/pedi_leads.csv")
        anexados = pedi_leads.anexar(achados, destino)
        return {"coletados": len(achados), "anexados": anexados, "diagnostico": diag,
                "csv": destino}
    return _iniciar(f"captar · {segmento}", _rodar)


def saude() -> dict:
    """Um lugar só pra responder 'está tudo de pé?' sem abrir cinco abas."""
    import pedi_custo
    demos = listar_demos()
    csv = Path(os.environ.get("PEDI_LEADS_CSV", "/root/jpos-entregaveis/pedi_leads.csv"))
    n_leads = 0
    if csv.exists():
        n_leads = max(0, sum(1 for _ in csv.open(encoding="utf-8-sig")) - 1)
    try:
        import pedi_toque
        placar = pedi_toque.placar()
    except Exception:  # noqa: BLE001
        placar = {}
    return {
        "demos": {"total": len(demos),
                  "com_foto_real": sum(1 for d in demos if d["fotos_reais"] > 0),
                  "com_imagem_generica": [d["slug"] for d in demos if d["generico"]],
                  "por_tier": {t: sum(1 for d in demos if d["tier"] == t)
                               for t in ("T1", "T2", "T3", "T4", "—")}},
        "leads": {"no_csv": n_leads, **placar},
        "custo_par": {t: pedi_custo.custo_par(t) for t in pedi_custo.TIPOS},
        "places_key": bool(os.environ.get("GOOGLE_PLACES_API_KEY")
                           or "GOOGLE_PLACES_API_KEY" in
                           Path("/root/noemi-infra/.env").read_text(errors="ignore")),
        "jobs_rodando": sum(1 for j in _JOBS.values() if j["estado"] == "rodando"),
    }


if __name__ == "__main__":
    import json
    import sys
    if "--selfcheck" in sys.argv:
        assert _slug("Força Total Esportes, Araçatuba") == "forca-total-esportes-aracatuba"
        assert _slug("  ") == ""
        # travessia de diretório não pode virar rm -rf em /var/www
        for mau in ("../../etc", "..", "/etc/passwd", ""):
            try:
                excluir_demo(mau)
                raise AssertionError(f"aceitou slug perigoso: {mau!r}")
            except ValueError:
                pass
        jid = _iniciar("teste", lambda: {"ok": True})
        for _ in range(50):
            if job(jid)["estado"] != "rodando":
                break
            time.sleep(0.05)
        assert job(jid)["estado"] == "ok" and job(jid)["resultado"] == {"ok": True}
        # erro dentro do job não pode derrubar o painel
        jid2 = _iniciar("falha", lambda: 1 / 0)
        for _ in range(50):
            if job(jid2)["estado"] != "rodando":
                break
            time.sleep(0.05)
        assert job(jid2)["estado"] == "erro" and "ZeroDivisionError" in job(jid2)["erro"]
        d = listar_demos()
        assert isinstance(d, list) and all("slug" in x for x in d)
        print("OK — self-check do hub passou.")
    else:
        print(json.dumps({"saude": saude(), "demos": listar_demos()},
                         ensure_ascii=False, indent=2, default=str))
