"""Frontend de TESTE do Site Builder (ferramenta interna, não produto p/ cliente).

JP (ou eu) cola um briefing → vê o site gerado e publicado → itera rápido, sem
rodar `montar_site.py` na mão a cada vez. Dirige o pipeline REAL do motor-site
(stub→template→local): sem LLM, sem chave, HTML de verdade em /var/www/sites
servido por go.noemi.digital.

ponytail: ponte de import pro repo motor-site (/root/motor-site) em vez de
duplicar o pipeline — o app motor-isca-sites do monorepo é ponteiro pra ele
(ver auditoria §1). Screenshot do preview foi PULADO: exige headless browser
(playwright/chromium ~400MB), não instalado — 'barato' não fecha; mostro o link.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# ponte pro pipeline do motor-site (repo separado, ainda não migrado pro monorepo)
_MOTOR_SITE = os.environ.get("MOTOR_SITE_DIR", "/root/motor-site")
if _MOTOR_SITE not in sys.path:
    sys.path.insert(0, _MOTOR_SITE)

from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import HTMLResponse

# defaults do pipeline: gerador template real, deploy local em /var/www/sites,
# URLs sob go.noemi.digital (novo lar do isca). Sobrescrevíveis por env.
os.environ.setdefault("SITE_ORQUESTRADOR", "stub")   # sem LLM (Fase futura liga 'llm')
os.environ.setdefault("SITE_GERADOR", "template")
os.environ.setdefault("SITE_DEPLOY", "local")
os.environ.setdefault("SITE_OUT_DIR", "/var/www/sites")
os.environ.setdefault("SITE_BASE_URL", "https://go.noemi.digital")

from app.pipeline import montar_site  # noqa: E402  (após ajustar sys.path)

app = FastAPI(title="Site Builder — teste interno")

_FORM = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Site Builder — teste</title><style>
:root{color-scheme:dark}*{box-sizing:border-box}
body{font-family:system-ui,sans-serif;background:#0b0f1a;color:#e6e9f0;max-width:640px;margin:0 auto;padding:24px}
h1{font-size:1.4rem}h1 span{color:#7c5cff}label{display:block;font-size:.85rem;color:#8b93a7;margin:12px 0 4px}
input,textarea{width:100%;padding:9px 11px;border-radius:8px;border:1px solid #232d45;background:#131a2b;color:#e6e9f0}
button{margin-top:18px;width:100%;padding:12px;border:0;border-radius:10px;background:#7c5cff;color:#fff;font-weight:600;font-size:1rem;cursor:pointer}
.res{margin-top:20px;padding:16px;border:1px solid #232d45;border-radius:12px;background:#131a2b}
a{color:#7c5cff}.err{color:#ff6b6b}small{color:#8b93a7}
</style></head><body>
<h1>🌐 Site Builder — <span>teste interno</span></h1>
<small>Dirige o pipeline real (stub→template→local). Publica em go.noemi.digital.</small>
<form method="post" action="/gerar">
<label>Nome da empresa *</label><input name="nome" required placeholder="Escritório Contábil Silva">
<label>Nicho *</label><input name="nicho" required placeholder="contabilidade">
<label>WhatsApp *</label><input name="whatsapp" required placeholder="5566999998888">
<label>Diferenciais (um por linha)</label><textarea name="diferenciais" rows="3" placeholder="20 anos de mercado&#10;Atendimento em 1h"></textarea>
<label>Público-alvo</label><input name="publico" placeholder="pequenas empresas do agro">
<label>Cor primária (hex, opcional)</label><input name="cor" placeholder="#1d4ed8">
<button>Gerar e publicar</button></form>
__RESULTADO__
</body></html>"""


@app.get("/", response_class=HTMLResponse)
def form() -> str:
    return _FORM.replace("__RESULTADO__", "")


@app.post("/gerar", response_class=HTMLResponse)
def gerar(nome: str = Form(...), nicho: str = Form(...), whatsapp: str = Form(...),
          diferenciais: str = Form(""), publico: str = Form(""), cor: str = Form("")) -> str:
    briefing = {
        "nome_empresa": nome.strip(),
        "nicho": nicho.strip(),
        "whatsapp": whatsapp.strip(),
        "diferenciais": [d.strip() for d in diferenciais.splitlines() if d.strip()],
        "publico": publico.strip(),
        "cor_primaria": cor.strip() or None,
    }
    try:
        r = montar_site(briefing)
    except Exception as e:  # pipeline levanta em qualquer estágio — mostra o motivo
        bloco = f'<div class="res err">Falhou na geração: {type(e).__name__}: {e}</div>'
        return _FORM.replace("__RESULTADO__", bloco)
    url = r.deploy.url
    bloco = (f'<div class="res">✅ Publicado.<br><b>Preview:</b> '
             f'<a href="{url}" target="_blank" rel="noopener">{url}</a><br>'
             f'<small>arquivos: {r.deploy.meta.get("out_dir", "?")}</small></div>')
    return _FORM.replace("__RESULTADO__", bloco)


@app.get("/health")
def health() -> dict:
    return {"ok": True, "gerador": os.environ["SITE_GERADOR"], "deploy": os.environ["SITE_DEPLOY"]}
