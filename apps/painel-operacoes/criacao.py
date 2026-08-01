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


_IMG_EXT = {"jpg", "jpeg", "png", "webp", "gif", "avif"}
_VID_EXT = {"mp4", "webm", "mov", "m4v"}


def _ext(nome_arq: str, permitidos: set[str], padrao: str) -> str:
    e = (nome_arq or "").rsplit(".", 1)[-1].lower().strip()
    return e if e in permitidos else padrao


def gerar(nome: str, nicho: str, whatsapp: str = "", diferenciais: list[str] | str = "",
          publico: str = "", cor: str = "", preset: int = 0,
          foto: tuple | None = None, video: tuple | None = None, copy_livre: str = "") -> dict:
    """Dispara o motor REAL com o briefing. `foto`/`video` = (bytes, nome_arquivo) opcionais
    (PROMPT 2): salvos em <slug>/{img,vid} e embutidos no hero via contrato estendido do motor.
    `copy_livre` sobrescreve a copy gerada. Registra em sites_gerados. NÃO simula — erro vira texto."""
    nome = (nome or "").strip()
    if not nome or not (nicho or "").strip():
        return {"ok": False, "erro": "empresa e nicho são obrigatórios"}
    if isinstance(diferenciais, str):
        diferenciais = [d.strip() for d in diferenciais.splitlines() if d.strip()]
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
    except OSError as e:
        return {"ok": False, "erro": f"site gerado mas falhou salvar asset: {e}"}
    try:
        with _db_noemi() as c:
            c.execute("INSERT INTO sites_gerados (cliente,segmento,slug,url,criado_em) VALUES (?,?,?,?,?)",
                      (nome, nicho.strip(), slug, url,
                       __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()))
            c.commit()
    except Exception:  # noqa: BLE001 — registro é secundário; o site já está no disco
        pass
    return {"ok": True, "url": url, "slug": slug}


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
    print("criacao OK — gate (no ar/stub/motion/video), listar dedup+disco, gerar valida obrigatórios")
