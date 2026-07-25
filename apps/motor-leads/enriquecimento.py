"""Camada 2 — ENRIQUECIMENTO (fetch + regex no HTML, ZERO LLM).

Pega o website do lead e extrai sinais determinísticos: SSL, responsivo,
plataforma (Wix/WordPress...), ano do rodapé (site abandonado), botão de
WhatsApp, chat/widget de atendimento. Sem site = flag sem_site.

`analisar_html(html, url)` é PURO (regex) — testável com fixture. `enriquecer(lead)`
faz o fetch (httpx) e chama a análise. Best-effort: site fora do ar = marca
status e segue (não quebra o lote).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

# e-mail: regex + mailto:. Filtra lixo (imagens, sentry/wix, exemplos) e prefere
# e-mail de negócio (contato@/comercial@ ou do mesmo domínio do site).
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_EMAIL_LIXO = ("sentry", "wixpress", "example.", "@2x", ".png", ".jpg", ".gif",
               "@sentry", "godaddy", "domain.com", "email.com", "seuemail")
_CONTATO_PATHS = ("/contato", "/contact")

# widgets de chat/atendimento mais comuns no BR (indício de que JÁ têm atendimento)
_CHAT_MARCADORES = ("tawk.to", "jivochat", "jivosite", "zendesk", "crisp.chat",
                    "intercom", "movidesk", "chatlio", "rdstation", "octadesk",
                    "zenvia", "chatguru", "manychat", "leadster", "blip.ai")
_WA_MARCADORES = ("wa.me", "api.whatsapp.com", "web.whatsapp.com")
_ANO_ATUAL = 2026


def analisar_html(html: str, url: str) -> dict:
    """Sinais extraídos do HTML (puro, sem rede). `url` só pra detectar SSL."""
    h = html or ""
    low = h.lower()
    gen = re.search(r'<meta[^>]+name=["\']generator["\'][^>]+content=["\']([^"\']+)', low)
    generator = (gen.group(1).strip() if gen else "")
    if not generator:  # plataformas que não põem generator mas deixam rastro
        for plat in ("wix.com", "jimdo", "wordpress", "squarespace", "webflow", "godaddy"):
            if plat in low:
                generator = plat
                break
    ano = _ano_rodape(h)
    return {
        "tem_ssl": url.startswith("https://"),
        "responsivo": bool(re.search(r'<meta[^>]+name=["\']viewport["\']', low)),
        "generator": generator,
        "ano_rodape": ano,
        "site_abandonado": ano is not None and ano < 2023,
        "tem_wa_button": any(m in low for m in _WA_MARCADORES),
        "tem_chat": any(m in low for m in _CHAT_MARCADORES),
        "site_de_agencia": _de_agencia(generator, ano),
        "email": extrair_email(h, urlparse(url).netloc),
    }


def extrair_email(html: str, dominio: str = "") -> str:
    """Melhor e-mail de negócio do HTML (mailto: + regex). '' se nenhum. Prefere
    contato@/comercial@/atendimento@ e e-mail do mesmo domínio do site."""
    achados: list[str] = []
    for m in re.finditer(r'mailto:([^"\'>?\s]+)', html or "", re.I):  # mailto: primeiro
        achados.append(m.group(1))
    achados += _EMAIL_RE.findall(html or "")
    limpos: list[str] = []
    for e in achados:
        e = e.strip().lower().rstrip(".")
        if e and "@" in e and e not in limpos and not any(x in e for x in _EMAIL_LIXO):
            limpos.append(e)
    if not limpos:
        return ""
    dom = (dominio or "").lower().replace("www.", "")

    def _peso(e: str) -> int:
        p = 0
        if any(e.startswith(x) for x in ("contato@", "comercial@", "atendimento@", "contato.", "faleconosco@")):
            p += 3
        if dom and e.endswith("@" + dom):
            p += 2
        if e.split("@")[-1] in ("gmail.com", "hotmail.com", "outlook.com", "yahoo.com"):
            p -= 1  # e-mail pessoal vale menos que o do domínio
        return p
    return sorted(limpos, key=_peso, reverse=True)[0]


def _ano_rodape(html: str) -> int | None:
    """Maior ano plausível (20xx) perto de © / copyright / footer. None se nenhum."""
    anos: list[int] = []
    for m in re.finditer(r'(?:©|&copy;|copyright|todos os direitos)[^0-9]{0,40}(20[0-9]{2})',
                         html, re.I):
        anos.append(int(m.group(1)))
    if not anos:  # fallback: qualquer 20xx no último trecho (rodapé) do HTML
        cauda = html[-4000:]
        anos = [int(a) for a in re.findall(r'\b(20[12][0-9])\b', cauda)]
    anos = [a for a in anos if 2000 <= a <= _ANO_ATUAL]
    return max(anos) if anos else None


def _de_agencia(generator: str, ano: int | None) -> bool:
    """Heurística de 'site bom recente de agência': sem plataforma DIY conhecida
    E com ano recente (>=2023). Não é certeza — é sinal pro tier T1/descarte."""
    diy = ("wix", "jimdo", "godaddy", "squarespace")
    return not any(d in generator for d in diy) and (ano is not None and ano >= 2023)


def enriquecer(lead: dict, *, fetch=None) -> dict:
    """Enriquece 1 lead. `fetch(url)->(status,html,url_final)` injetável (teste);
    default usa httpx. Sem website = sem_site. Best-effort no erro de rede."""
    l = dict(lead)
    site = (l.get("website") or "").strip()
    if not site:
        l.update({"sem_site": True, "http_status": None, "tem_ssl": False,
                  "responsivo": False, "generator": "", "ano_rodape": None,
                  "site_abandonado": False, "tem_wa_button": False, "tem_chat": False,
                  "site_de_agencia": False, "email": ""})
        return l
    fx = fetch or _fetch
    status, html, url_final = fx(site)
    l["sem_site"] = False
    l["http_status"] = status
    if status and 200 <= status < 400 and html:
        l.update(analisar_html(html, url_final or site))
    else:  # site no ar mas erro/redirect quebrado = tratado como abandonado
        l.update({"tem_ssl": site.startswith("https://"), "responsivo": False,
                  "generator": "", "ano_rodape": None, "site_abandonado": True,
                  "tem_wa_button": False, "tem_chat": False, "site_de_agencia": False,
                  "email": ""})
    # e-mail não achado na home → tenta páginas de contato (best-effort, timeout curto)
    if not l.get("email"):
        base = url_final or site
        for path in _CONTATO_PATHS:
            try:
                st, h, u = fx(urljoin(base, path))
            except Exception:  # noqa: BLE001
                continue
            if st and 200 <= st < 400 and h:
                em = extrair_email(h, urlparse(u or base).netloc)
                if em:
                    l["email"] = em
                    break
    return l


def _fetch(url: str):
    """(status, html, url_final) via httpx. Timeout curto (LEADS_FETCH_TIMEOUT,
    default 6s) pra não travar o lote de 1000. Erro/timeout → (None, '', url)."""
    import os

    import httpx
    try:
        to = float(os.environ.get("LEADS_FETCH_TIMEOUT", "6"))
        with httpx.Client(timeout=to, follow_redirects=True,
                          headers={"User-Agent": "Mozilla/5.0 (noemi-leads/1.0)"}) as c:
            r = c.get(url)
            return r.status_code, r.text, str(r.url)
    except Exception:  # noqa: BLE001 — site fora ≠ lote quebrado
        return None, "", url


if __name__ == "__main__":  # self-check: fixtures wix-abandonado vs moderno c/ wa+chat
    wix = ('<html><head><meta name="generator" content="Wix.com Website Builder">'
           '</head><body>...<footer>© 2019 Clínica X. Todos os direitos.</footer></body></html>')
    a = analisar_html(wix, "http://clinicax.com")
    assert a["generator"].startswith("wix") and a["ano_rodape"] == 2019 and a["site_abandonado"]
    assert not a["tem_ssl"] and not a["tem_wa_button"], a

    moderno = ('<html><head><meta name="viewport" content="width=device-width">'
               '</head><body><a href="https://wa.me/5511999998888">Zap</a>'
               '<script src="https://embed.tawk.to/abc/1"></script>'
               '<footer>© 2025 Clínica Y</footer></body></html>')
    b = analisar_html(moderno, "https://clinicay.com.br")
    assert b["responsivo"] and b["tem_wa_button"] and b["tem_chat"]
    assert not b["site_abandonado"] and b["site_de_agencia"], b

    semsite = enriquecer({"nome": "Clínica Z", "website": ""})
    assert semsite["sem_site"] and semsite["http_status"] is None and semsite["email"] == ""
    # e-mail: prefere contato@ e domínio do site, ignora lixo (sentry/imagem)
    hm = ('<a href="mailto:contato@clinicay.com.br">email</a> foto@2x.png '
          'suporte@sentry.io atendimento@gmail.com')
    assert extrair_email(hm, "clinicay.com.br") == "contato@clinicay.com.br"
    assert extrair_email("sem email aqui", "x.com") == ""
    print("enriquecimento OK — wix/2019, moderno wa+chat, sem_site, e-mail (contato@ > lixo)")
