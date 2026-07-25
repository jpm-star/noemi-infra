"""Site Studio — ferramenta de PRODUÇÃO do JP pra gerar site de cliente.

Era ferramenta de teste (localhost, sem auth); virou produção: login single-user,
exposto em go.noemi.digital/studio via Caddy (TLS), histórico dos sites gerados,
identidade visual própria. Dirige o pipeline REAL do motor-site (stub→template→
local, SEM LLM) → publica em go.noemi.digital/<slug>/.

App fica em 127.0.0.1:8020; o Caddy é a borda pública (handle /studio/*). Rotas
todas sob /studio (Caddy encaminha o prefixo). Auth: cookie assinado (ver auth.py).

ponytail: ponte de import pro /root/motor-site (não duplica pipeline). Histórico
na SQLite do monorepo (sites_gerados). Screenshot do preview omitido (headless
browser ~400MB não é 'barato') — mostro <iframe> do site real + link.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

_PACOTES = str(Path(__file__).resolve().parents[2] / "packages")  # shared_core
if _PACOTES not in sys.path:
    sys.path.insert(0, _PACOTES)
_MOTOR_SITE = os.environ.get("MOTOR_SITE_DIR", "/root/motor-site")
if _MOTOR_SITE not in sys.path:
    sys.path.insert(0, _MOTOR_SITE)

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import auth
from shared_core.storage.db import conn

os.environ.setdefault("SITE_ORQUESTRADOR", "stub")   # sem LLM (Camada 2 adiada)
os.environ.setdefault("SITE_GERADOR", "template")
os.environ.setdefault("SITE_DEPLOY", "local")
os.environ.setdefault("SITE_OUT_DIR", "/var/www/sites")
os.environ.setdefault("SITE_BASE_URL", "https://go.noemi.digital")

from app.pipeline import montar_site  # noqa: E402

import og  # banner OG (preview no WhatsApp) — best-effort

_SECURE = os.environ.get("STUDIO_INSECURE_COOKIE") != "1"  # tests usam http
app = FastAPI(title="Site Studio")


# -- histórico -------------------------------------------------------------
def _registrar_site(cliente: str, segmento: str, slug: str, url: str) -> None:
    from datetime import datetime, timezone
    with conn() as c:
        c.execute(
            "INSERT INTO sites_gerados (cliente, segmento, slug, url, criado_em) VALUES (?,?,?,?,?)",
            (cliente, segmento, slug, url, datetime.now(timezone.utc).isoformat()),
        )


def _listar_sites(limite: int = 50) -> list[dict]:
    with conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT cliente, segmento, url, criado_em FROM sites_gerados ORDER BY id DESC LIMIT ?",
            (limite,)).fetchall()]


# -- auth ------------------------------------------------------------------
def _logado(request: Request) -> str | None:
    return auth.validar_sessao(request.cookies.get(auth.COOKIE))


def _para_login() -> RedirectResponse:
    return RedirectResponse("/studio/login", status_code=303)


# -- UI --------------------------------------------------------------------
_CSS = """
:root{--bg:#0a0b14;--card:#14162a;--linha:#262a44;--txt:#eceeffee;--fraco:#8a90b0;
--roxo:#8b5cff;--roxo2:#c9b8ff;--ok:#37e0a6;color-scheme:dark}
*{box-sizing:border-box;margin:0}body{font-family:'Segoe UI',system-ui,sans-serif;
background:radial-gradient(1200px 600px at 80% -10%,#1c1740 0,var(--bg) 55%);color:var(--txt);min-height:100vh}
.top{display:flex;align-items:center;justify-content:space-between;padding:18px 28px;border-bottom:1px solid var(--linha)}
.marca{display:flex;align-items:center;gap:10px;font-weight:700;font-size:1.15rem;letter-spacing:.3px}
.marca .d{width:22px;height:22px;border-radius:6px;background:linear-gradient(135deg,var(--roxo),#5b7cff);
box-shadow:0 0 18px rgba(139,92,255,.6)}.marca small{color:var(--fraco);font-weight:400;font-size:.75rem}
.sair{color:var(--fraco);text-decoration:none;font-size:.85rem;border:1px solid var(--linha);padding:6px 12px;border-radius:8px}
.sair:hover{color:var(--txt);border-color:var(--roxo)}
.wrap{max-width:1040px;margin:0 auto;padding:28px;display:grid;grid-template-columns:1fr 380px;gap:24px}
@media(max-width:840px){.wrap{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--linha);border-radius:16px;padding:22px}
h2{font-size:1rem;margin-bottom:4px}.sub{color:var(--fraco);font-size:.85rem;margin-bottom:16px}
label{display:block;font-size:.8rem;color:var(--fraco);margin:12px 0 5px}
input,textarea{width:100%;padding:10px 12px;border-radius:10px;border:1px solid var(--linha);
background:#0e1020;color:var(--txt);font-size:.92rem}input:focus,textarea:focus{outline:0;border-color:var(--roxo)}
.row{display:flex;gap:12px}.row>div{flex:1}
button{margin-top:18px;width:100%;padding:13px;border:0;border-radius:12px;cursor:pointer;font-weight:700;font-size:1rem;
background:linear-gradient(135deg,var(--roxo),#5b7cff);color:#fff;box-shadow:0 8px 24px rgba(91,124,255,.25)}
button:hover{filter:brightness(1.08)}
.res{margin-top:18px;padding:16px;border:1px solid var(--roxo);border-radius:12px;background:rgba(139,92,255,.08)}
.res a{color:var(--roxo2)}.err{border-color:#ff6b6b;background:rgba(255,107,107,.08)}
iframe{width:100%;height:280px;border:1px solid var(--linha);border-radius:10px;margin-top:10px;background:#fff}
.hist h2{margin-bottom:12px}.item{padding:11px 0;border-bottom:1px solid var(--linha)}
.item:last-child{border:0}.item b{font-size:.92rem}.item .meta{color:var(--fraco);font-size:.76rem;margin-top:2px}
.item a{color:var(--roxo2);font-size:.8rem;text-decoration:none;word-break:break-all}.vazio{color:var(--fraco);font-size:.85rem}
.login{max-width:360px;margin:12vh auto}.badge{display:inline-block;font-size:.7rem;color:var(--ok);
border:1px solid var(--ok);border-radius:99px;padding:2px 9px;margin-bottom:14px}
"""


# botão voltar universal (todas as abas do Studio): volta pro QG/referrer
_VOLTAR = ("<a href='#' title='Voltar' onclick=\"history.length>1?history.back():"
           "location.assign(document.referrer||'https://go.noemi.digital/');return false\" "
           "style='position:fixed;top:14px;left:14px;z-index:99;background:rgba(0,0,0,.55);"
           "color:#fff;text-decoration:none;padding:7px 13px;border-radius:20px;font-size:.85rem;"
           "font-weight:600'>‹ Voltar</a>")


def _pagina(corpo: str, titulo: str = "Site Studio") -> str:
    return (f"<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{titulo}</title><style>{_CSS}</style></head><body>{_VOLTAR}{corpo}</body></html>")


def _topo(com_sair: bool = True) -> str:
    sair = "<a class='sair' href='/studio/logout'>sair</a>" if com_sair else ""
    return ("<div class='top'><div class='marca'><span class='d'></span>"
            "<div>noemi <b>studio</b><br><small>gerador de sites de cliente</small></div></div>"
            f"{sair}</div>")


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _tela_principal(resultado_html: str = "") -> str:
    itens = _listar_sites()
    if itens:
        linhas = "".join(
            f"<div class='item'><b>{_esc(i['cliente'])}</b>"
            f"<div class='meta'>{_esc(i['segmento'] or '—')} · {i['criado_em'][:10]}</div>"
            f"<a href='{_esc(i['url'])}' target='_blank' rel='noopener'>{_esc(i['url'])}</a></div>"
            for i in itens)
    else:
        linhas = "<div class='vazio'>Nenhum site gerado ainda.</div>"
    form = f"""<div class='card'>
<a href='/studio/combo' style='display:block;text-align:center;margin-bottom:16px;padding:12px;
border-radius:12px;text-decoration:none;color:#fff;font-weight:700;
background:linear-gradient(135deg,var(--roxo),#5b7cff)'>⚡ Onboarding rápido (3 perguntas)</a>
<h2>Novo site</h2>
<div class='sub'>Briefing → site publicado em go.noemi.digital, na hora.</div>
<form method='post' action='/studio/gerar'>
<label>Nome do negócio *</label><input name='nome' required placeholder='Escritório Contábil Silva'>
<div class='row'><div><label>Segmento *</label><input name='nicho' required placeholder='contabilidade'></div>
<div><label>WhatsApp *</label><input name='whatsapp' required placeholder='5566999998888'></div></div>
<label>Diferenciais (um por linha)</label><textarea name='diferenciais' rows='3' placeholder='20 anos de mercado&#10;Atendimento em 1h'></textarea>
<div class='row'><div><label>Público-alvo</label><input name='publico' placeholder='produtores rurais'></div>
<div><label>Cor primária</label><input name='cor' placeholder='#1d4ed8'></div></div>
<button>Gerar e publicar</button></form>{resultado_html}</div>"""
    hist = f"<div class='card hist'><h2>Histórico</h2>{linhas}</div>"
    return _pagina(_topo() + f"<div class='wrap'>{form}{hist}</div>")


def _tela_login(erro: str = "") -> str:
    msg = f"<div class='res err'>{_esc(erro)}</div>" if erro else ""
    corpo = f"""<div class='login'><div class='marca' style='justify-content:center;margin-bottom:18px'>
<span class='d'></span><div>noemi <b>studio</b></div></div>
<div class='card'><span class='badge'>acesso restrito</span>
<form method='post' action='/studio/login'>
<label>Usuário</label><input name='usuario' value='joaop' autocomplete='username'>
<label>Senha</label><input name='senha' type='password' required autocomplete='current-password'>
<button>Entrar</button></form>{msg}</div></div>"""
    return _pagina(_topo(com_sair=False) + corpo, "Entrar — Site Studio")


# -- rotas -----------------------------------------------------------------
@app.get("/studio/login", response_class=HTMLResponse)
def login_form(request: Request):
    if _logado(request):
        return RedirectResponse("/studio", status_code=303)
    return HTMLResponse(_tela_login())


@app.post("/studio/login")
def login(usuario: str = Form(...), senha: str = Form(...)):
    if not auth.verificar_senha(usuario.strip(), senha):
        return HTMLResponse(_tela_login("Usuário ou senha inválidos."), status_code=401)
    resp = RedirectResponse("/studio", status_code=303)
    resp.set_cookie(auth.COOKIE, auth.emitir_sessao(usuario.strip()), max_age=auth.COOKIE_MAX_S,
                    httponly=True, secure=_SECURE, samesite="lax", path="/studio")
    return resp


@app.get("/studio/logout")
def logout():
    resp = RedirectResponse("/studio/login", status_code=303)
    resp.delete_cookie(auth.COOKIE, path="/studio")
    return resp


@app.get("/studio", response_class=HTMLResponse)
def principal(request: Request):
    if not _logado(request):
        return _para_login()
    return HTMLResponse(_tela_principal())


@app.post("/studio/gerar", response_class=HTMLResponse)
def gerar(request: Request, nome: str = Form(...), nicho: str = Form(...), whatsapp: str = Form(...),
          diferenciais: str = Form(""), publico: str = Form(""), cor: str = Form("")):
    if not _logado(request):
        return _para_login()
    briefing = {
        "nome_empresa": nome.strip(), "nicho": nicho.strip(), "whatsapp": whatsapp.strip(),
        "diferenciais": [d.strip() for d in diferenciais.splitlines() if d.strip()],
        "publico": publico.strip(), "cor_primaria": cor.strip() or None,
    }
    try:
        r = montar_site(briefing)
    except Exception as e:
        bloco = "<div class='res err'>Não deu pra gerar o site agora. Confira os campos e tente de novo.</div>"
        return HTMLResponse(_tela_principal(bloco))
    url = r.deploy.url
    slug = re.sub(r".*/([^/]+)/?$", r"\1", url.rstrip("/"))
    _registrar_site(nome.strip(), nicho.strip(), slug, url)
    _aplicar_og(r, nicho.strip(), slug)
    bloco = (f"<div class='res'>✅ <b>Publicado.</b><br>"
             f"<a href='{_esc(url)}' target='_blank' rel='noopener'>{_esc(url)}</a>"
             f"<iframe src='{_esc(url)}' title='preview'></iframe></div>")
    return HTMLResponse(_tela_principal(bloco))


# == Combo Prestador de Serviço: onboarding ultra-simples =====================
# 3 perguntas, UMA por tela (conversa, não cadastro), zero jargão. Ao final:
# site publicado + config da Noemi Básica salva. Reusa o MESMO montar_site.
_COMBO_CSS = """<style>
.combo{max-width:440px;margin:9vh auto;padding:0 20px;text-align:center}
.combo .passo{color:var(--fraco);font-size:.8rem;letter-spacing:.5px;margin-bottom:10px}
.combo .pergunta{font-size:1.5rem;font-weight:700;margin-bottom:6px;line-height:1.25}
.combo .dica{color:var(--fraco);font-size:.9rem;margin-bottom:22px}
.combo input{font-size:1.15rem;padding:15px 16px;text-align:center}
.combo .pts{display:flex;gap:7px;justify-content:center;margin-top:22px}
.combo .pts i{width:9px;height:9px;border-radius:99px;background:var(--linha)}
.combo .pts i.on{background:var(--roxo)}
.combo .voltar{display:inline-block;margin-top:16px;color:var(--fraco);font-size:.82rem;text-decoration:none}
.pronto{max-width:460px;margin:8vh auto;text-align:center;padding:0 20px}
.pronto .ok{font-size:2.6rem}.pronto h1{font-size:1.6rem;margin:8px 0 6px}
.pronto p{color:var(--fraco);margin-bottom:18px}
.pronto .link{display:block;background:var(--card);border:1px solid var(--roxo);border-radius:12px;
padding:14px;color:var(--roxo2);word-break:break-all;text-decoration:none;margin-bottom:8px}
.pronto iframe{width:100%;height:300px;border:1px solid var(--linha);border-radius:12px;background:#fff}
</style>"""

_PASSOS = ["nome", "servico", "whatsapp"]
_PERGUNTA = {
    "nome": ("Como chama o seu negócio?", "Pode ser seu nome mesmo, ex: Eletricista do João",
             "nome", "text", "Eletricista do João"),
    "servico": ("O que você faz?", "Do jeito que o cliente procura, ex: eletricista, encanador, diarista",
                "servico", "text", "eletricista"),
    "whatsapp": ("Qual o seu WhatsApp?", "Com DDD — é pra onde o cliente vai te chamar",
                 "whatsapp", "tel", "66 99999-9999"),
}


def _tela_combo(passo: str, nome: str = "", servico: str = "") -> str:
    pergunta, dica, campo, tipo, ph = _PERGUNTA[passo]
    idx = _PASSOS.index(passo)
    proximo = _PASSOS[idx + 1] if idx + 1 < len(_PASSOS) else "pronto"
    pts = "".join(f"<i class='{'on' if i <= idx else ''}'></i>" for i in range(len(_PASSOS)))
    ocultos = (f"<input type='hidden' name='nome' value='{_esc(nome)}'>" if passo != "nome" else "")
    ocultos += (f"<input type='hidden' name='servico' value='{_esc(servico)}'>" if passo == "whatsapp" else "")
    voltar = ("" if passo == "nome" else
              "<a class='voltar' href='/studio/combo'>← começar de novo</a>")
    # último passo dispara montar_site (segundos): trava o botão e avisa que está criando
    onsubmit = ("onsubmit=\"var b=this.querySelector('button');b.disabled=true;"
                "b.textContent='Criando seu site... leva alguns segundos'\"" if proximo == "pronto" else "")
    corpo = f"""{_COMBO_CSS}<div class='combo'>
<div class='passo'>PASSO {idx + 1} DE 3</div>
<div class='pergunta'>{pergunta}</div><div class='dica'>{dica}</div>
<form method='post' action='/studio/combo' {onsubmit}>
<input type='hidden' name='passo' value='{proximo}'>{ocultos}
<input name='{campo}' type='{tipo}' required autofocus placeholder='{ph}'>
<button>{'Criar meu site' if proximo == 'pronto' else 'Continuar'}</button>
</form><div class='pts'>{pts}</div>{voltar}</div>"""
    return _pagina(_topo(com_sair=False) + corpo, "Começar — Noemi")


def _meta_dir() -> Path:
    return Path(os.environ.get("SITE_META_DIR") or (Path(os.environ["SITE_OUT_DIR"]).parent / "sites-meta"))


def _cartucho_basica(nome: str, servico: str, whatsapp: str, slug: str) -> Path:
    """Salva a config da Noemi Básica do prestador (o cliente nunca vê 'cartucho').
    Fica pronta pra conectar a um número — plugar no WhatsApp é passo do JP."""
    dest = _meta_dir() / slug
    dest.mkdir(parents=True, exist_ok=True)
    cart = {
        "plano": "noemi_basica",
        "nome_empresa": nome, "vertical": servico, "whatsapp_dono": whatsapp,
        "tom": "simples, direto e cordial",
        "persona": (f"Você é a assistente virtual de {nome} ({servico}). Responda os clientes de "
                    f"forma curta e clara, confirme pedidos de orçamento ou visita, informe horário "
                    f"e região quando perguntarem e, quando não souber algo, diga que vai passar o "
                    f"recado pro {nome}."),
        "escopo": "atendimento básico: o que faz, horário, região, orçamento simples, recado",
    }
    caminho = dest / "cartucho.json"
    caminho.write_text(json.dumps(cart, ensure_ascii=False, indent=1), encoding="utf-8")
    return caminho


def _aplicar_og(r, nicho: str, slug: str) -> None:
    """Gera o banner OG + injeta a meta no site recém-publicado. Best-effort:
    OG é preview, nunca bloqueia a publicação."""
    try:
        og.aplicar(r.brief.nome_empresa, r.brief.subheadline, nicho, slug,
                   os.environ.get("SITE_OUT_DIR", "/var/www/sites"),
                   os.environ.get("SITE_BASE_URL", "https://go.noemi.digital"))
    except Exception:
        pass


def _combo_gerar(nome: str, servico: str, whatsapp: str) -> HTMLResponse:
    briefing = {"nome_empresa": nome, "nicho": servico, "whatsapp": whatsapp,
                "diferenciais": [], "publico": "", "cor_primaria": None}
    try:
        r = montar_site(briefing)
    except Exception as e:  # mostra recado simples, sem stack técnico
        corpo = (f"{_COMBO_CSS}<div class='pronto'><div class='ok'>😕</div>"
                 f"<h1>Deu um probleminha</h1><p>Tenta de novo em instantes.</p>"
                 f"<a class='link' href='/studio/combo'>Recomeçar</a></div>")
        return HTMLResponse(_pagina(_topo(com_sair=False) + corpo), status_code=500)
    url = r.deploy.url
    slug = re.sub(r".*/([^/]+)/?$", r"\1", url.rstrip("/"))
    _registrar_site(nome, servico, slug, url)
    _cartucho_basica(nome, servico, whatsapp, slug)
    _aplicar_og(r, servico, slug)
    corpo = f"""{_COMBO_CSS}<div class='pronto'><div class='ok'>🎉</div>
<h1>Pronto, {_esc(nome)}!</h1>
<p>Seu site já está no ar e a Noemi já está pronta pra responder seus clientes no WhatsApp.</p>
<a class='link' href='{_esc(url)}' target='_blank' rel='noopener'>{_esc(url)}</a>
<iframe src='{_esc(url)}' title='seu site'></iframe></div>"""
    return HTMLResponse(_pagina(_topo(com_sair=False) + corpo, "Tudo pronto — Noemi"))


@app.get("/studio/combo", response_class=HTMLResponse)
def combo_inicio(request: Request):
    if not _logado(request):
        return _para_login()
    return HTMLResponse(_tela_combo("nome"))


@app.post("/studio/combo", response_class=HTMLResponse)
def combo_passo(request: Request, passo: str = Form(...), nome: str = Form(""),
                servico: str = Form(""), whatsapp: str = Form("")):
    if not _logado(request):
        return _para_login()
    nome, servico, whatsapp = nome.strip()[:120], servico.strip()[:80], whatsapp.strip()[:40]
    if passo == "servico" and nome:
        return HTMLResponse(_tela_combo("servico", nome))
    if passo == "whatsapp" and nome and servico:
        return HTMLResponse(_tela_combo("whatsapp", nome, servico))
    if passo == "pronto" and nome and servico and whatsapp:
        return _combo_gerar(nome, servico, whatsapp)
    return HTMLResponse(_tela_combo("nome"))  # dado faltando → recomeça limpo


@app.get("/studio/health")
def health() -> dict:
    return {"ok": True, "gerador": os.environ["SITE_GERADOR"], "auth": True}
