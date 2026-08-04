"""Aba CRIAÇÃO — interface operacional que fala com o motor de sites (motor-isca-sites
/ /root/motor-site). NÃO rebuilda o gerador: chama o MESMO `montar_site` que a rota
/studio/gerar usa, com o MESMO contrato de briefing (texto). Lista os sites gerados
com status inferido (disco + gate de qualidade manual).

CONTRATO REAL DO MOTOR (lido de builder_web.py + app/pipeline.py, não assumido):
  briefing = {nome_empresa, nicho, whatsapp, diferenciais[list], publico, cor_primaria}
  -> copy escrita por LLM (Groq); motion = banco CSS nativo.
  NÃO aceita: upload de foto, upload de vídeo, blob de copy-livre. (gap reportado.)
"""
from __future__ import annotations

import html as html_mod
import os
import re
import sqlite3
import sys
from pathlib import Path

SITES_DIR = Path(os.environ.get("SITE_OUT_DIR", "/var/www/sites"))
_MOTOR = os.environ.get("MOTOR_SITE_DIR", "/root/motor-site")
# stubs de CONTEÚDO (não o atributo HTML placeholder="", que é UX legítima de form):
_STUB = ("lorem ipsum", "em breve", "coming soon", "sua empresa aqui", "em construção",
         "texto de exemplo", "seu texto aqui", "descrição do serviço aqui", "xxxxx")


def _montar_site():
    """Import tardio do motor real (mesmo setup do builder_web.py). Carrega a chave
    Groq do sdr-motor/.env (fallback que o motor usa). Levanta se o motor não carregar."""
    os.environ.setdefault("SITE_ORQUESTRADOR", "llm")
    os.environ.setdefault("SITE_GERADOR", "template")
    os.environ.setdefault("SITE_DEPLOY", "local")
    os.environ.setdefault("SITE_OUT_DIR", str(SITES_DIR))
    os.environ.setdefault("SITE_BASE_URL", os.environ.get("SITE_BASE_URL", "https://p.jpos.com.br"))
    envf = "/root/sdr-motor/.env"
    if os.path.exists(envf):
        for ln in open(envf, encoding="utf-8", errors="ignore"):
            ln = ln.strip()
            if ln and not ln.startswith("#") and "=" in ln:
                k, v = ln.split("=", 1)
                os.environ.setdefault(k, v.strip().strip('"'))
    for p in (str(Path(__file__).resolve().parents[2] / "packages"), _MOTOR):
        if p not in sys.path:
            sys.path.insert(0, p)
    from app.pipeline import montar_site
    return montar_site


def _db_noemi() -> sqlite3.Connection:
    from shared_core.storage import db
    return db.conn()


def _db_leads() -> sqlite3.Connection:
    """leads.db (tracker_prospects + leads_alvo). Banco SEPARADO do noemi.db — o merge
    é em Python, sem ATTACH (padrão da casa)."""
    p = Path(os.environ.get("LEADS_DB", str(Path(__file__).resolve().parents[2] / "data" / "leads.db")))
    c = sqlite3.connect(p, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def dados_lead(nome: str) -> dict:
    """C1 — autofill: tudo que a pesquisa já sabe do lead vira briefing preenchido.

    Merge em Python de tracker_prospects (curado à mão, vence) + leads_alvo (garimpo).
    Devolve campos vazios quando não há dado — a UI só preenche o que veio."""
    nome = (nome or "").strip()
    if not nome:
        return {}
    tp: dict = {}
    la: dict = {}
    try:
        with _db_leads() as c:
            r = c.execute("SELECT * FROM tracker_prospects WHERE lower(empresa)=lower(?) "
                          "ORDER BY id DESC LIMIT 1", (nome,)).fetchone()
            tp = dict(r) if r else {}
            r2 = c.execute("SELECT * FROM leads_alvo WHERE lower(nome)=lower(?) LIMIT 1",
                           (nome,)).fetchone()
            la = dict(r2) if r2 else {}
    except sqlite3.Error:
        return {}
    if not tp and not la:
        return {}
    cidade = (tp.get("cidade_uf") or la.get("cidade_origem") or "").strip()
    # "conteúdo pesquisado": sinal do tracker + notas + motivo da dor do garimpo, um por linha
    achados = [str(tp.get("sinal") or "").strip(), str(tp.get("notas") or "").strip(),
               str(la.get("motivo_da_dor") or la.get("_motivo") or "").strip()]
    vistos: set[str] = set()
    linhas = []
    for a in achados:
        for ln in a.splitlines():
            ln = " ".join(ln.split())
            if len(ln) > 2 and ln.lower() not in vistos:
                vistos.add(ln.lower())
                linhas.append(ln)
    return {
        "achou": True,
        "nicho": (tp.get("segmento") or la.get("categoria") or "").strip(),
        "whatsapp": (tp.get("telefone") or la.get("telefone") or "").strip(),
        # público não é campo pesquisado: derivado da cidade (honesto, editável por cima)
        "publico": f"clientes de {cidade}" if cidade else "",
        "diferenciais": "\n".join(linhas),
        "cidade": cidade,
        "tier": (tp.get("tier") or la.get("tier_sugerido") or "").strip(),
        "fonte": "tracker" if tp else "leads-alvo",
    }


def _slug_seguro(slug: str) -> Path | None:
    """Path do site SE o slug for seguro. Barra traversal (../), absoluto e qualquer
    coisa fora de SITES_DIR — o caller apaga diretório, então isto é trava de segurança."""
    s = (slug or "").strip().strip("/")
    if not s or not re.fullmatch(r"[A-Za-z0-9._-]+", s) or s in (".", ".."):
        return None
    alvo = (SITES_DIR / s).resolve()
    try:
        raiz = SITES_DIR.resolve()
    except OSError:
        return None
    if alvo == raiz or raiz not in alvo.parents:
        return None
    return alvo


def apagar(slug: str) -> dict:
    """C2 — apaga o site: pasta em /var/www/sites/<slug> + linha(s) em sites_gerados.
    Irreversível (a confirmação é na UI). Idempotente: apagar órfão sem pasta funciona."""
    alvo = _slug_seguro(slug)
    if alvo is None:
        return {"ok": False, "erro": f"slug inválido: {slug!r}"}
    import shutil
    apagou_dir = False
    if alvo.is_dir():
        try:
            shutil.rmtree(alvo)
            apagou_dir = True
        except OSError as e:
            return {"ok": False, "erro": f"falhou apagar pasta: {e}"}
    linhas = 0
    try:
        with _db_noemi() as c:
            cur = c.execute("DELETE FROM sites_gerados WHERE slug=?", (alvo.name,))
            linhas = cur.rowcount or 0
            c.commit()
    except Exception as e:  # noqa: BLE001 — pasta já foi; registro é secundário
        return {"ok": True, "slug": alvo.name, "pasta": apagou_dir, "linhas": 0,
                "aviso": f"registro não apagado: {e}"}
    return {"ok": True, "slug": alvo.name, "pasta": apagou_dir, "linhas": linhas}


def limpar_orfaos() -> dict:
    """C2 (varredura) — remove do registro as linhas cujo site não existe mais em disco
    (aparecem como 'órfão (sem arquivo)'). Não toca em disco: só limpa o registro."""
    mortos: list[str] = []
    try:
        with _db_noemi() as c:
            for r in c.execute("SELECT DISTINCT slug FROM sites_gerados"):
                slug = dict(r)["slug"]
                alvo = _slug_seguro(slug)
                if alvo is None or not (alvo / "index.html").exists():
                    mortos.append(slug)
            for slug in mortos:
                c.execute("DELETE FROM sites_gerados WHERE slug=?", (slug,))
            c.commit()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "erro": str(e), "removidos": mortos}
    return {"ok": True, "removidos": mortos, "total": len(mortos)}


_IMG_EXT = {"jpg", "jpeg", "png", "webp", "gif", "avif"}
_VID_EXT = {"mp4", "webm", "mov", "m4v"}


def _ext(nome_arq: str, permitidos: set[str], padrao: str) -> str:
    e = (nome_arq or "").rsplit(".", 1)[-1].lower().strip()
    return e if e in permitidos else padrao


def gerar(nome: str, nicho: str, whatsapp: str = "", diferenciais: list[str] | str = "",
          publico: str = "", cor: str = "", preset: int = 0,
          foto: tuple | None = None, video: tuple | None = None, copy_livre: str = "",
          fotos: list[tuple] | None = None, estilo: str = "") -> dict:
    """Dispara o motor REAL com o briefing. `foto`/`video` = (bytes, nome_arquivo) opcionais
    (PROMPT 2): salvos em <slug>/{img,vid} e embutidos no hero via contrato estendido do motor.
    `fotos` = lista (bytes, nome) do acervo do cliente (C3): passam por OCR (contexto pra copy)
    e viram galeria no fim da página. `copy_livre` sobrescreve a copy gerada.
    Registra em sites_gerados. NÃO simula — erro vira texto."""
    nome = (nome or "").strip()
    if not nome or not (nicho or "").strip():
        return {"ok": False, "erro": "empresa e nicho são obrigatórios"}
    if isinstance(diferenciais, str):
        diferenciais = [d.strip() for d in diferenciais.splitlines() if d.strip()]
    fotos = [f for f in (fotos or []) if f and f[0]]
    # C3: o que está ESCRITO nas fotos (placa/tabela de planos/horário) vira contexto da copy
    ocr_txt = _ocr_fotos(fotos)
    if ocr_txt:
        diferenciais = list(diferenciais) + [f"[lido nas fotos do cliente] {ocr_txt[:600]}"]
    briefing = {"nome_empresa": nome, "nicho": nicho.strip(), "whatsapp": (whatsapp or "").strip(),
                "diferenciais": diferenciais, "publico": (publico or "").strip(),
                "cor_primaria": (cor or "").strip() or None}
    # assets do cliente: passa o caminho RELATIVO no briefing; os bytes são gravados pós-geração.
    foto_ext = video_ext = None
    if foto and foto[0]:
        foto_ext = _ext(foto[1], _IMG_EXT, "jpg")
        briefing["hero_imagem"] = f"img/hero.{foto_ext}"
    if video and video[0]:
        video_ext = _ext(video[1], _VID_EXT, "mp4")
        briefing["hero_video"] = f"vid/hero.{video_ext}"
    if (copy_livre or "").strip():
        briefing["copy_livre"] = copy_livre.strip()
    try:
        montar_site = _montar_site()
    except Exception as e:  # noqa: BLE001 — motor não carregou = gap de infra, reporta
        return {"ok": False, "erro": f"motor não carregou: {type(e).__name__}: {e}"}
    try:
        r = montar_site(briefing)
    except Exception as e:  # noqa: BLE001 — falha de geração vira erro legível, não site vazio
        return {"ok": False, "erro": f"geração falhou: {type(e).__name__}: {e}"}
    url = r.deploy.url
    slug = re.sub(r".*/([^/]+)/?$", r"\1", url.rstrip("/"))
    # grava os assets do cliente no dir do site (o HTML já referencia os caminhos relativos)
    site_dir = SITES_DIR / slug
    try:
        if foto and foto[0]:
            (site_dir / "img").mkdir(parents=True, exist_ok=True)
            (site_dir / "img" / f"hero.{foto_ext}").write_bytes(foto[0])
        if video and video[0]:
            (site_dir / "vid").mkdir(parents=True, exist_ok=True)
            (site_dir / "vid" / f"hero.{video_ext}").write_bytes(video[0])
        # C3: acervo do cliente -> <slug>/img/g01.. + galeria injetada no fim da página
        rels: list[str] = []
        if fotos:
            (site_dir / "img").mkdir(parents=True, exist_ok=True)
            for i, (b, n) in enumerate(fotos, 1):
                e = _ext(n, _IMG_EXT, "jpg")
                (site_dir / "img" / f"g{i:02d}.{e}").write_bytes(b)
                rels.append(f"img/g{i:02d}.{e}")
    except OSError as e:
        return {"ok": False, "erro": f"site gerado mas falhou salvar asset: {e}"}
    if rels:
        _injetar(site_dir / "index.html", _galeria_html(rels, f"{nome} por dentro"))
    if estilo:  # camada de acabamento (morfismo) por cima do tema do motor
        import estilos as _est
        _injetar(site_dir / "index.html", _est.bloco(estilo))
    try:
        with _db_noemi() as c:
            c.execute("INSERT INTO sites_gerados (cliente,segmento,slug,url,criado_em) VALUES (?,?,?,?,?)",
                      (nome, nicho.strip(), slug, url,
                       __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()))
            c.commit()
    except Exception:  # noqa: BLE001 — registro é secundário; o site já está no disco
        pass
    return {"ok": True, "url": url, "slug": slug, "fotos": len(rels), "estilo": estilo,
            "ocr": (ocr_txt[:180] + "…") if len(ocr_txt) > 180 else ocr_txt}


def _ocr_fotos(fotos: list[tuple]) -> str:
    """C3 — lê o TEXTO visível nas fotos do cliente (placa, tabela de planos, banner,
    horário) via a interface fixa `visao.analisar_frames` (Tesseract grátis; Gemini se
    VISAO_GEMINI=1). Isso vira CONTEXTO real pra copy — o que está escrito na parede da
    empresa entra no site. Degrada pra '' sem nunca quebrar a geração."""
    if not fotos:
        return ""
    raiz = str(Path(__file__).resolve().parents[2] / "packages")
    if raiz not in sys.path:
        sys.path.insert(0, raiz)
    try:
        from shared_core.ai import visao
        texto, _fonte = visao.analisar_frames([b for b, _n in fotos[:8] if b])
        return (texto or "").strip()
    except Exception:  # noqa: BLE001 — sem tesseract/PIL → segue sem OCR
        return ""


def _galeria_html(arquivos: list[str], titulo: str = "Galeria") -> str:
    """Grid responsivo + lazy load, auto-contido (sem dependência externa).
    ponytail: injetado no HTML pronto em vez de alterar o engine do motor — o layout
    fino (fotos por seção: ambiente/equipe/resultado) fica pra ajuste depois."""
    if not arquivos:
        return ""
    itens = "".join(
        f'<figure><img loading="lazy" decoding="async" src="{a}" alt="{html_mod.escape(titulo)} {i+1}"></figure>'
        for i, a in enumerate(arquivos))
    return f"""
<section class="jpos-galeria" id="galeria">
  <h2>{html_mod.escape(titulo)}</h2>
  <div class="jpos-grid">{itens}</div>
</section>
<style>
.jpos-galeria{{max-width:1100px;margin:0 auto;padding:48px 20px}}
.jpos-galeria h2{{font-size:clamp(1.4rem,3vw,2rem);margin:0 0 20px;text-align:center}}
.jpos-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:12px}}
.jpos-grid figure{{margin:0;aspect-ratio:4/3;overflow:hidden;border-radius:12px;background:#e9ecef}}
.jpos-grid img{{width:100%;height:100%;object-fit:cover;display:block;transition:transform .4s cubic-bezier(.16,1,.3,1)}}
.jpos-grid figure:hover img{{transform:scale(1.06)}}
@media (prefers-reduced-motion:reduce){{.jpos-grid img{{transition:none}}}}
</style>"""


def _injetar(idx: Path, bloco: str) -> bool:
    """Insere o bloco antes de </body> (ou no fim). True se gravou."""
    if not bloco or not idx.exists():
        return False
    try:
        h = idx.read_text(encoding="utf-8", errors="ignore")
        novo = (h.replace("</body>", bloco + "\n</body>", 1) if "</body>" in h else h + bloco)
        idx.write_text(novo, encoding="utf-8")
        return True
    except OSError:
        return False


def _gate(idx: Path) -> dict:
    """Checklist manual de qualidade (izanagi não roda aqui): stub/placeholder, motion, vídeo, tamanho."""
    try:
        html = idx.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return {"status": "órfão", "tem_stub": False, "motion": False, "video": False, "kb": 0}
    low = html.lower()
    kb = len(html) // 1024
    tem_stub = any(s in low for s in _STUB)
    motion = ("@keyframes" in low) or ("animation:" in low) or ("transition:" in low)
    video = "<video" in low
    if tem_stub or kb < 6:
        status = "stub"
    else:
        status = "no ar"
    return {"status": status, "tem_stub": tem_stub, "motion": motion, "video": video, "kb": kb}


def listar_sites() -> list[dict]:
    """Sites gerados: sites_gerados (dedup por slug, mais recente) UNIÃO /var/www/sites/,
    com status inferido (disco + gate). Ordenado por criação desc."""
    reg: dict[str, dict] = {}
    try:
        with _db_noemi() as c:
            for r in c.execute("SELECT cliente,segmento,slug,url,criado_em FROM sites_gerados "
                               "ORDER BY id DESC"):
                d = dict(r)
                reg.setdefault(d["slug"], d)  # dedup por slug: guarda o mais recente (id desc)
    except Exception:  # noqa: BLE001
        pass
    # sites no disco que não estão na tabela (órfãos de disco) também aparecem
    if SITES_DIR.exists():
        for d in sorted(SITES_DIR.iterdir()):
            if d.is_dir() and d.name not in reg:
                reg[d.name] = {"cliente": d.name, "segmento": "", "slug": d.name,
                               "url": f"{os.environ.get('SITE_BASE_URL','https://p.jpos.com.br')}/{d.name}/",
                               "criado_em": ""}
    out = []
    for slug, d in reg.items():
        idx = SITES_DIR / slug / "index.html"
        g = _gate(idx) if idx.exists() else {"status": "órfão (sem arquivo)", "tem_stub": False,
                                             "motion": False, "video": False, "kb": 0}
        out.append({**d, **g})
    out.sort(key=lambda x: (x.get("criado_em") or ""), reverse=True)
    return out


if __name__ == "__main__":  # self-check offline (sem gerar site real, sem rede)
    import tempfile
    os.environ["NOEMI_DATA_DIR"] = tempfile.mkdtemp(suffix="_criacao")
    d = Path(tempfile.mkdtemp(suffix="_sites")); os.environ["SITE_OUT_DIR"] = str(d)
    SITES_DIR = d  # rebind o global p/ o dir de teste (import já rodou com o default)
    # site bom
    (d / "bom-site").mkdir(); (d / "bom-site" / "index.html").write_text(
        "<html>" + "conteúdo real de verdade " * 400 + "<style>@keyframes x{}</style><video></video></html>",
        encoding="utf-8")
    # site stub
    (d / "ruim-site").mkdir(); (d / "ruim-site" / "index.html").write_text(
        "<html>Lorem ipsum placeholder</html>", encoding="utf-8")
    assert _gate(d / "bom-site" / "index.html")["status"] == "no ar"
    g = _gate(d / "bom-site" / "index.html"); assert g["motion"] and g["video"], g
    assert _gate(d / "ruim-site" / "index.html")["status"] == "stub"
    sites = listar_sites()
    slugs = {s["slug"]: s for s in sites}
    assert "bom-site" in slugs and "ruim-site" in slugs, slugs.keys()
    assert slugs["bom-site"]["status"] == "no ar" and slugs["ruim-site"]["status"] == "stub"
    # gerar valida obrigatórios sem chamar o motor
    assert gerar("", "x")["ok"] is False
    # C2 — trava de segurança do apagar: traversal/absoluto/vazio NUNCA viram path
    globals()["SITES_DIR"] = d
    for mau in ("../etc", "..", "", "/", "a/../../b", "/etc/passwd", "."):
        assert _slug_seguro(mau) is None, mau
    assert _slug_seguro("bom-site") == (d / "bom-site").resolve()
    assert apagar("../etc")["ok"] is False
    # apaga de verdade (pasta some) e é idempotente no 2º apagar
    assert (d / "ruim-site").is_dir()
    r = apagar("ruim-site")
    assert r["ok"] and r["pasta"] and not (d / "ruim-site").exists(), r
    assert apagar("ruim-site")["ok"] is True  # idempotente: já não existe, não quebra
    # C3 — galeria: vazia não injeta; com fotos gera grid lazy e entra antes de </body>
    assert _galeria_html([]) == ""
    g = _galeria_html(["img/g01.jpg", "img/g02.jpg"], "Academia X")
    assert 'loading="lazy"' in g and "jpos-grid" in g and "g02.jpg" in g
    # com </body>: entra ANTES do fechamento; sem </body>: cai no append (não perde o bloco)
    com = d / "com-body.html"
    com.write_text("<html><body>oi</body></html>", encoding="utf-8")
    assert _injetar(com, g)
    t = com.read_text(encoding="utf-8")
    assert t.index("jpos-grid") < t.index("</body>"), t[-200:]
    sem = d / "bom-site" / "index.html"  # fixture sem </body> → append no fim
    assert _injetar(sem, g) and "jpos-grid" in sem.read_text(encoding="utf-8")
    assert _injetar(d / "nao-existe.html", g) is False  # arquivo ausente = False, não crash
    assert _ocr_fotos([]) == ""  # sem fotos = sem OCR, nunca quebra
    print("criacao OK — gate, listar dedup+disco, gerar valida, apagar seguro (anti-traversal), galeria lazy")
