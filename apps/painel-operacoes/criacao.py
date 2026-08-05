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

import hashlib
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


def _garante_demo_url(c: sqlite3.Connection) -> None:
    """Coluna que fecha o ciclo: o link da demo volta pro card do lead. Idempotente."""
    cols = {r[1] for r in c.execute("PRAGMA table_info(tracker_prospects)")}
    if "demo_url" not in cols:
        c.execute("ALTER TABLE tracker_prospects ADD COLUMN demo_url TEXT")


def briefing_do_lead(prospect_id: int) -> dict:
    """Tudo que já se sabe do lead, pronto pro Studio — sem o JP digitar nada.

    Procedência: o que vem do CRM entra como INFERIDO. Isso não é decoração — impede
    que uma hipótese de garimpo vire afirmação em primeira pessoa no site do cliente.
    Material que o JP subir depois vence isso.

    T3/T4 com site: o site ATUAL entra como fonte de ingestão automaticamente. É a
    fonte mais rica que existe (texto real do cliente, não inferência)."""
    if not prospect_id:
        return {"achou": False}
    try:
        with _db_leads() as c:
            _garante_demo_url(c)
            r = c.execute("SELECT * FROM tracker_prospects WHERE id=?", (prospect_id,)).fetchone()
            if not r:
                return {"achou": False}
            lead = dict(r)
            socios = [dict(x) for x in c.execute(
                "SELECT nome,cargo,poder_decisao FROM tracker_socios WHERE prospect_id=? "
                "ORDER BY (poder_decisao IS NOT NULL) DESC, id LIMIT 4", (prospect_id,))]
            # o site do lead pode estar em QUALQUER uma das 3 tabelas de garimpo —
            # olhar só uma devolvia vazio pra T4 que tem site (medido no prospect 31).
            site = ""
            emp = lead.get("empresa") or ""
            for tabela, col in (("leads_t3t4", "nome"), ("leads_alvo", "nome"),
                                ("leads_clinicas", "nome")):
                try:
                    row = c.execute(f"SELECT website FROM {tabela} WHERE lower({col})=lower(?) "
                                    f"AND website IS NOT NULL AND website!='' LIMIT 1",
                                    (emp,)).fetchone()
                except sqlite3.Error:
                    continue
                if row:
                    site = (row["website"] or "").strip()
                    break
    except sqlite3.Error as e:
        return {"achou": False, "erro": str(e)[:120]}

    import prospeccao_dia as _pd
    cidade = (lead.get("cidade_uf") or "").strip()
    segmento = (lead.get("segmento") or "").strip()
    tier = (lead.get("tier") or "").strip().upper()
    achado = " ".join(str(lead.get("sinal") or "").split())
    # o "FALE ISTO" do card — mesma função da Prospecção do dia, sem duplicar a regra
    fala = _pd.gancho(tier, segmento, cidade, achado)
    decisor = next((s["nome"] for s in socios if s.get("nome")), "")

    campos = {"nome": (lead.get("empresa") or "").strip(),
              "nicho": segmento, "cidade": cidade,
              "whatsapp": (lead.get("telefone") or "").strip(),
              "publico": f"clientes de {cidade}" if cidade else "",
              "diferenciais": achado}
    return {
        "achou": True, "prospect_id": prospect_id, "tier": tier or "",
        "campos": campos,
        # tudo que veio do CRM é hipótese até o JP confirmar
        "proveniencia": {k: "inferido" for k, v in campos.items() if v},
        "decisor": decisor, "socios": socios,
        "razao_social": (lead.get("razao_social") or "").strip(),
        "cnpj": (lead.get("cnpj") or "").strip(),
        "achado": achado, "fala": fala,
        "site_atual": site,
        "demo_url": (lead.get("demo_url") or "").strip(),
        # T3/T4 com site: puxa o site como fonte de ingestão (a mais rica que existe)
        "ingerir_site": bool(site) and tier in ("T3", "T4"),
    }


def registrar_demo(prospect_id: int, url: str) -> dict:
    """Fecha o ciclo: o link gerado volta pro card do lead, sem copiar e colar."""
    if not prospect_id or not (url or "").strip():
        return {"ok": False, "erro": "prospect_id e url são obrigatórios"}
    try:
        with _db_leads() as c:
            _garante_demo_url(c)
            cur = c.execute("UPDATE tracker_prospects SET demo_url=?, atualizado_em=? "
                            "WHERE id=?",
                            (url.strip(), __import__("datetime").datetime.now(
                                __import__("datetime").timezone.utc).isoformat(), prospect_id))
            c.commit()
    except sqlite3.Error as e:
        return {"ok": False, "erro": str(e)[:120]}
    return {"ok": cur.rowcount > 0, "prospect_id": prospect_id, "url": url.strip()}


def _semente(nome: str, lead_id: int = 0) -> int:
    """Semente ESTÁVEL da escolha automática (estrutura + acento de morfismo).

    hash() do Python é randomizado por processo — usar ele faria a estrutura mudar a
    cada regeração do MESMO site (péssimo pra iterar numa demo). md5 do nome é estável
    entre processos, então o preview do Studio mostra o que a geração vai fazer de
    verdade. É por isso que isto é uma função e não duas linhas repetidas: preview e
    geração TÊM que usar a mesma conta, senão o preview mente."""
    return lead_id or (int(hashlib.md5((nome or "").encode()).hexdigest()[:8], 16) % 997)


def modelos(nicho: str = "", tier: str = "", nome: str = "", lead_id: int = 0) -> dict:
    """STUDIO #2 — galeria SELECIONÁVEL: 9 morfismos + estruturas do segmento, com o
    que o motor escolheria sozinho já marcado como `auto`.

    Preview honesto: o CSS de cada morfismo vem de `estilos.css()` — o MESMO que seria
    injetado no site. E as estruturas vêm de `receitas.pool()`, o mesmo pool do sorteio.
    Preview que renderiza de outra fonte mente no dia em que o motor muda."""
    import estilos as _est
    import receitas as _rec
    sem = _semente(nome, lead_id)
    auto_e = _est.escolher(nicho, tier=str(tier or ""), semente=sem)
    auto_r = _rec.escolher(nicho, semente=sem)
    # `css` = o que iria pro site. `css_preview` = o mesmo, ESCOPADO numa seção, pra
    # renderizar o cartão de amostra sem o morfismo vazar e repintar o painel inteiro.
    estilos_ = [{**e, "css": _est.css(e["valor"]),
                 "css_preview": _est.css(e["valor"], escopo=f"pv-{e['valor']}"),
                 "auto": e["valor"] == auto_e["principal"]}
                for e in _est.listar()]
    acento = auto_e.get("acento") or {}
    receitas_ = [{"nome": r["nome"], "ordem": r.get("ordem") or [], "hero": r.get("hero", ""),
                  "porque": r.get("porque", ""), "origem": r.get("origem", ""),
                  "auto": r["nome"] == auto_r["nome"]}
                 for r in _rec.pool(nicho)]
    return {"segmento": _rec.segmento_de(nicho), "estilos": estilos_, "receitas": receitas_,
            "auto": {"estilo": auto_e["principal"], "porque": auto_e["porque"],
                     "acento": acento, "receita": auto_r["nome"]},
            "conceitos": _est.conceitos(nicho)}


def gerar(nome: str, nicho: str, whatsapp: str = "", diferenciais: list[str] | str = "",
          publico: str = "", cor: str = "", preset: int = 0,
          foto: tuple | None = None, video: tuple | None = None, copy_livre: str = "",
          fotos: list[tuple] | None = None, estilo: str = "",
          autofill: dict | None = None, lead_id: int = 0, tier: str = "",
          receita_nome: str = "") -> dict:
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
    import time as _t
    t_inicio = _t.time()
    # C3: o que está ESCRITO nas fotos (placa/tabela de planos/horário) vira contexto da copy
    ocr_txt = _ocr_fotos(fotos)
    if ocr_txt:
        diferenciais = list(diferenciais) + [f"[lido nas fotos do cliente] {ocr_txt[:600]}"]
    # ESTRUTURA: receita do SEGMENTO do lead (default do nicho + referências aprovadas).
    # semente = lead_id -> leads diferentes do mesmo nicho pegam receitas diferentes.
    import receitas as _rec
    # semente ESTÁVEL: hash() do Python é randomizado por processo — usar ele faria a
    # estrutura mudar a cada regeração do MESMO site (péssimo pra iterar numa demo).
    _sem = _semente(nome, lead_id)
    # STUDIO #2: o JP pode ESCOLHER a estrutura na galeria; vazio segue automático.
    # Nome que não existe no pool cai no automático em vez de gerar site sem ordem.
    receita = next((r for r in _rec.pool(nicho) if r["nome"] == receita_nome.strip()),
                   None) if receita_nome.strip() else None
    if receita:  # pool() devolve ordem CRUA; escolher() normaliza — a mão precisa também
        receita = {**receita,
                   "ordem": _rec._norm_ordem(receita.get("ordem")) or _rec.ORDEM_DEFAULT}
    receita = receita or _rec.escolher(nicho, semente=_sem)
    briefing = {"nome_empresa": nome, "nicho": nicho.strip(), "whatsapp": (whatsapp or "").strip(),
                "diferenciais": diferenciais, "publico": (publico or "").strip(),
                "cor_primaria": (cor or "").strip() or None,
                # ESTRUTURA: ordem das seções + tipo de hero (vazio = default do motor)
                "receita_ordem": receita.get("ordem") or [],
                "receita_hero": receita.get("hero") or ""}
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
    # ACABAMENTO (morfismo). Vazio = AUTOMÁTICO: escolhido por segmento+tier, com acento
    # numa seção onde outro morfismo comunica melhor (ex: preço em brutalismo dentro de
    # um site minimal). Estilo explícito da UI continua vencendo.
    import estilos as _est
    _auto = _est.escolher(nicho, tier=str(tier or ""), semente=_sem)
    _principal = estilo or _auto["principal"]
    _acento = {} if estilo else _auto["acento"]   # estilo manual = pele única, sem acento
    if _bloco_est := _est.bloco(_principal, _acento):
        _injetar(site_dir / "index.html", _bloco_est)
    _est_desc = _auto["porque"] if not estilo else estilo
    # QA PÓS-GERAÇÃO (JP 2026-08-05): telefone de mentira NÃO passa. Marcar depois não
    # basta — 14 sites já tinham subido assim e o lead clica antes de alguém revisar.
    # Não apaga o site (o JP pode querer olhar), mas devolve ok=False: o painel mostra
    # o erro e o link não é tratado como entregável.
    _tel_ruins = telefones_falsos_no_html(
        (site_dir / "index.html").read_text(encoding="utf-8", errors="ignore"))
    if _tel_ruins:
        return {"ok": False, "url": url, "slug": slug,
                "erro": f"QA bloqueou: telefone placeholder no site ({', '.join(_tel_ruins)}). "
                        f"Corrija o WhatsApp do briefing e gere de novo."}
    try:
        with _db_noemi() as c:
            c.execute("INSERT INTO sites_gerados (cliente,segmento,slug,url,criado_em) VALUES (?,?,?,?,?)",
                      (nome, nicho.strip(), slug, url,
                       __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()))
            c.commit()
    except Exception:  # noqa: BLE001 — registro é secundário; o site já está no disco
        pass
    ficha = _ficha(site_dir, {
        "nome": nome, "nicho": nicho, "lead_id": lead_id, "slug": slug, "url": url,
        "autofill": autofill or {}, "final": {"nicho": nicho, "whatsapp": whatsapp,
                                              "publico": publico, "diferenciais": diferenciais},
        "fotos_enviadas": len(fotos), "fotos_gravadas": len(rels), "ocr": ocr_txt,
        "estilo": _est_desc, "receita": receita, "segundos": round(_t.time() - t_inicio, 1),
        "hero_foto": bool(foto and foto[0]), "hero_video": bool(video and video[0]),
        "copy_livre": bool((copy_livre or "").strip()),
    })
    return {"ok": True, "url": url, "slug": slug, "fotos": len(rels), "estilo": _est_desc,
            "estrutura": receita.get("nome"), "estrutura_origem": receita.get("origem"),
            "ficha": ficha, "segundos": round(_t.time() - t_inicio, 1),
            "ocr": (ocr_txt[:180] + "…") if len(ocr_txt) > 180 else ocr_txt}


def _ficha(site_dir: Path, d: dict) -> str:
    """FICHA.md por site: o que foi automático vs o que o JP teve que ajustar.

    O campo que importa é "intervenção humana" — o que o motor NÃO resolveu sozinho
    vira o backlog de automação. Fica em branco pro JP preencher enquanto testa."""
    auto, manual = [], []
    for campo, valor_auto in (d.get("autofill") or {}).items():
        final = str((d.get("final") or {}).get(campo, ""))
        va = str(valor_auto or "")
        if not va:
            continue
        (auto if va.strip() == final.strip() else manual).append(
            f"`{campo}`" + ("" if va.strip() == final.strip() else f" — autofill deu «{va[:60]}», virou «{final[:60]}»"))
    r = d.get("receita") or {}
    agora = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
    txt = f"""# FICHA — {d['nome']}

- **URL:** {d['url']}
- **Gerado em:** {agora.isoformat(timespec='seconds')} · **levou {d['segundos']}s** (briefing → no ar)
- **Nicho:** {d['nicho']} · **lead_id:** {d.get('lead_id') or '—'}

## Estrutura (o que variou além da pele)
- **Receita:** `{r.get('nome','default')}` · **origem:** `{r.get('origem','default')}`
- **Por quê:** {r.get('porque','—')}
- **Ordem das seções:** {' → '.join(r.get('ordem') or []) or 'default do motor'}
- **Hero:** {r.get('hero') or 'pelo dado enviado'}
- **Estilo (morfismo):** {d.get('estilo') or 'padrão do motor'}

## Entrada
- **Veio do autofill e ficou:** {', '.join(auto) if auto else '—'}
- **Autofill errou / corrigido à mão:** {', '.join(manual) if manual else '—'}
- Copy pronta do cliente: {'sim (sobrescreveu a IA)' if d.get('copy_livre') else 'não (copy da IA)'}

## Mídia
- Fotos enviadas: **{d['fotos_enviadas']}** · gravadas na galeria: **{d['fotos_gravadas']}**
- Hero: {'vídeo do cliente' if d.get('hero_video') else ('foto do cliente' if d.get('hero_foto') else 'sem mídia (gradiente)')}
- Visão/OCR leu: {('sim — ' + (d.get('ocr') or '')[:300]) if d.get('ocr') else 'NÃO (caiu no briefing sem contexto de imagem)'}

## Intervenção humana (preencher enquanto testa)
> O que EU tive que ajustar que o motor não resolveu sozinho.
> Cada linha aqui é candidata a virar automação.

- [ ]
- [ ]

## Diagnóstico
- **100% automático hoje:** estrutura escolhida por segmento, copy, galeria, {'OCR/visão das fotos, ' if d.get('ocr') else ''}publicação.
- **Ainda depende do JP:** seleção das fotos, revisão da copy, escolha do morfismo{'' if d.get('ocr') else ', contexto visual (nenhuma foto lida)'}.
"""
    try:
        (site_dir / "FICHA.md").write_text(txt, encoding="utf-8")
        return f"{site_dir}/FICHA.md"
    except OSError:
        return ""


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


# Telefone de mentira em site publicado é o erro mais caro do gerador: o lead CLICA e cai
# no vazio. Detecção por PADRÃO, não por lista — a varredura de 2026-08-05 achou 14 dos 50
# sites no ar com números de uma família que nenhuma lista previa (…99998888, …111000N).
_TEL_FALSO = (
    re.compile(r"(\d)\1{5,}"),                   # 6+ dígitos iguais seguidos
    re.compile(r"9{4,}8{4,}"),                   # 99998888 e parentes
    re.compile(r"1{3,}0{3,}\d?\b"),              # série de demo …111000N
    re.compile(r"(?:0123|1234|2345|3456|4567|5678|6789){2,}"),
)


def telefone_falso(numero: str) -> bool:
    """Número tem CARA de placeholder? Espelha `sdr_motor.app.identidade.telefone_falso`.
    Duplicado de propósito: os dois repos são deployados separados e um import cruzado
    faria o QA do gerador depender do backend da Noemi estar instalado."""
    d = re.sub(r"\D", "", numero or "")
    return len(d) >= 10 and any(rx.search(d) for rx in _TEL_FALSO)


def telefones_falsos_no_html(html: str) -> list[str]:
    """Todos os números com cara de placeholder no HTML (wa.me, tel:, texto solto)."""
    achados = set()
    for num in re.findall(r"(?:wa\.me/|tel:\+?|whatsapp[^0-9]{0,20})(\d{10,15})", html, re.I):
        if telefone_falso(num):
            achados.add(num)
    return sorted(achados)


def _gate(idx: Path) -> dict:
    """Checklist manual de qualidade (izanagi não roda aqui): stub/placeholder, motion, vídeo, tamanho."""
    try:
        html = idx.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return {"status": "órfão", "tem_stub": False, "motion": False, "video": False,
                "kb": 0, "tel_falso": []}
    low = html.lower()
    kb = len(html) // 1024
    tem_stub = any(s in low for s in _STUB)
    motion = ("@keyframes" in low) or ("animation:" in low) or ("transition:" in low)
    video = "<video" in low
    tel_falso = telefones_falsos_no_html(html)
    if tem_stub or kb < 6:
        status = "stub"
    elif tel_falso:
        # NÃO é "no ar": um site que manda o lead pra número morto é pior que um stub,
        # porque parece pronto. Aparece vermelho na galeria e no Studio.
        status = "telefone falso"
    else:
        status = "no ar"
    return {"status": status, "tem_stub": tem_stub, "motion": motion, "video": video,
            "kb": kb, "tel_falso": tel_falso}


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
    # QA de telefone: pega a FAMÍLIA de falsos que a varredura achou nos 50 sites no ar,
    # e não confunde número real (senão o QA vira ruído e alguém desliga)
    for falso in ("5514000000000", "5566999998888", "14999998888", "5518991110009",
                  "5514991110008"):
        assert telefone_falso(falso), falso
    for real in ("5514998745847", "5514996900353", "5516988364226", "5514991694754"):
        assert not telefone_falso(real), real
    assert telefones_falsos_no_html(
        '<a href="https://wa.me/5566999998888">fala</a>') == ["5566999998888"]
    assert telefones_falsos_no_html(
        '<a href="https://wa.me/5514998745847">fala</a>') == []
    # o gate rebaixa o status: site com telefone morto NÃO é "no ar"
    ruim = d / "tel-ruim"; ruim.mkdir()
    (ruim / "index.html").write_text(
        "<html>" + "conteúdo real de verdade " * 400
        + '<a href="https://wa.me/5566999998888">z</a></html>', encoding="utf-8")
    g2 = _gate(ruim / "index.html")
    assert g2["status"] == "telefone falso" and g2["tel_falso"] == ["5566999998888"], g2
    # STUDIO #2 — galeria selecionável: preview usa a MESMA fonte da geração
    assert _semente("Clínica X") == _semente("Clínica X")          # estável entre chamadas
    assert _semente("Clínica X", 42) == 42                          # lead_id manda
    m = modelos("clínica odontológica", "T1", "Clínica X")
    assert len(m["estilos"]) >= 9 and all(e.get("css") is not None for e in m["estilos"])
    # o CSS do preview é ESCOPADO: nenhuma regra solta que repinte o painel
    for e in m["estilos"]:
        if e["css_preview"]:
            assert f"pv-{e['valor']}" in e["css_preview"], e["valor"]
            assert not re.search(r"(^|\})\s*body\s*\{", e["css_preview"]), e["valor"]
    autos = [e for e in m["estilos"] if e["auto"]]
    assert len(autos) == 1 and autos[0]["valor"] == m["auto"]["estilo"], autos
    assert autos[0]["valor"] == "minimal", autos  # T1 força minimal (isca leve)
    ra = [r for r in m["receitas"] if r["auto"]]
    assert len(ra) == 1 and ra[0]["nome"] == m["auto"]["receita"], ra
    assert all(r["ordem"] for r in m["receitas"]), m["receitas"]
    # o auto do preview é EXATAMENTE o que a geração escolheria (mesma semente)
    import receitas as _rc
    assert _rc.escolher("clínica odontológica",
                        semente=_semente("Clínica X"))["nome"] == m["auto"]["receita"]
    # nicho desconhecido não explode nem inventa estrutura
    assert modelos("xyzsegmento")["receitas"], "pool sempre devolve ao menos a default"
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
