"""Fonte ÚNICA do snippet de beacon que vai no HTML dos sites.

Por que este arquivo existe: o snippet era colado à mão em cada deploy. Resultado
medido em 14/08/2026 — nenhum dos 3 sites no ar media nada:
  - /var/www/jpos       (jpos.com.br)          → snippet nunca existiu
  - /var/www/pedi       (chinelospedi.com)     → perdeu na migração do Astro
  - /var/www/landing    (landing.jpos.com.br)  → corrompido: um replace ancorado em
    "</body>" cravou "</body></body>" DENTRO do JS. O motor JS leu isso como início
    de regex ("Invalid regular expression flags") e matou o bloco <script> inteiro no
    parse, então nem 'view' nem 'cta' disparavam.

Daí as três regras que este módulo garante e o self-check PROVA (não afirma):
  1. O snippet NUNCA contém a string "</body>" — foi o que permitiu a corrupção.
  2. O JS passa por `node --check` aqui, no repositório. A landing ficou dias no ar
     com erro de sintaxe porque ninguém rodava um parser em cima dele.
  3. injetar() é idempotente e REPÕE: acha qualquer beacon antigo/quebrado no HTML,
     remove e põe o atual. Rodar de novo depois de um deploy conserta sozinho.
"""
from __future__ import annotations

import re
from pathlib import Path

MARCA = "beacon-jpos-v2"

# CTAs reais destes sites: WhatsApp, telefone, e qualquer elemento marcado à mão.
_SELETOR = 'a[href*="wa.me"],a[href*="whatsapp"],a[href^="tel:"],[data-cta]'

# Qualquer <script> que fale com /beacon é considerado versão antiga desta mesma coisa.
_ANTIGO = re.compile(r"<script\b[^>]*>(?:(?!</script>).)*?/beacon(?:(?!</script>).)*?</script>",
                     re.S | re.I)


def js(site: str) -> str:
    """Só o JavaScript, sem as tags — é o que o `node --check` consegue validar."""
    s = re.sub(r"[^a-z0-9_-]", "", (site or "").strip().lower())[:60] or "site"
    return (
        f'(function(){{'
        f'function b(t){{try{{'
        # referrer do próprio domínio é navegação interna, não "tráfego vindo de".
        # Resolver aqui evita a análise sugerir parceria com o site do próprio cliente.
        f'var o=document.referrer;'
        f'try{{if(o&&new URL(o).host===location.host)o="interno"}}catch(e){{}}'
        f'navigator.sendBeacon("/beacon",JSON.stringify('
        f'{{site:"{s}",evento:t,origem:o,path:location.pathname}}))'
        f'}}catch(e){{}}}}'
        f'b("view");'
        f'document.addEventListener("click",function(v){{'
        f'var a=v.target.closest&&v.target.closest({_SELETOR!r});if(a)b("cta")}},true);'
        f'}})();'
    )


def snippet(site: str) -> str:
    """O bloco <script> pronto pra colar. `site` é a chave da coluna site_trafego.site."""
    return f"<script>/*{MARCA}*/{js(site)}</script>"


def injetar(caminho: str | Path, site: str) -> str:
    """Põe (ou repõe) o beacon num arquivo HTML. Devolve o que aconteceu:
    'ok' (já estava atual) | 'injetado' | 'substituido' | 'sem-body'."""
    p = Path(caminho)
    html = p.read_text(encoding="utf-8")
    novo = snippet(site)
    if novo in html:
        return "ok"
    limpo, n = _ANTIGO.subn("", html)
    # busca no texto original (não em .lower(): lower() muda o comprimento em alguns
    # caracteres não-ASCII e o índice sairia deslocado)
    fins = list(re.finditer(r"</body\s*>", limpo, re.I))
    if not fins:
        return "sem-body"
    i = fins[-1].start()
    p.write_text(limpo[:i] + novo + limpo[i:], encoding="utf-8")
    return "substituido" if n else "injetado"


if __name__ == "__main__":  # self-check: sem rede, sem DB, arquivo temporário
    import shutil
    import subprocess
    import tempfile

    d = Path(tempfile.mkdtemp(suffix="_beacon_snippet"))

    codigo = js("Pé Di!")
    assert 'site:"pdi"' in codigo, codigo                 # sanitiza a chave
    assert "</body>" not in snippet("pdi"), "regra 1 quebrada: snippet contém </body>"
    assert 'b("view")' in codigo and 'b("cta")' in codigo, codigo
    assert 'o="interno"' in codigo, "perdeu a marcação de navegação interna"

    # regra 2: o JS que vai pro ar passa por um parser DE VERDADE
    node = shutil.which("node")
    assert node, "node ausente: sem ele a regra 2 não é verificável — instale ou rode no host certo"
    f = d / "snippet.js"
    f.write_text(codigo, encoding="utf-8")
    r = subprocess.run([node, "--check", str(f)], capture_output=True, text=True)
    assert r.returncode == 0, f"JS do snippet não compila:\n{r.stderr[:400]}"

    # e o mesmo parser REPROVA a corrupção real que ficou dias no ar (prova por mutação)
    quebrado = codigo.replace("v.target.closest&&", "v.target.closest</body></body>")
    f2 = d / "quebrado.js"
    f2.write_text(quebrado, encoding="utf-8")
    r2 = subprocess.run([node, "--check", str(f2)], capture_output=True, text=True)
    assert r2.returncode != 0, "o node --check não pega a corrupção — a regra 2 seria teatro"

    # a) HTML limpo → injeta antes do </body>
    a = d / "limpo.html"
    a.write_text("<html><body><h1>oi</h1></body></html>", encoding="utf-8")
    assert injetar(a, "jpos") == "injetado"
    t = a.read_text(encoding="utf-8")
    assert t.index(MARCA) < t.rindex("</body>"), "snippet ficou fora do body"
    assert injetar(a, "jpos") == "ok", "não é idempotente"

    # b) o caso REAL que quebrou: beacon antigo corrompido com </body> dentro do JS
    ruim = ('<html><body><p>x</p><script>(function(){function s(e){navigator.sendBeacon('
            '"/beacon","{}")}var a=ev.target.closest</body></body>ev.target.closest("a")'
            '})();</script></body></html>')
    b = d / "corrompido.html"
    b.write_text(ruim, encoding="utf-8")
    assert injetar(b, "landing") == "substituido"
    t = b.read_text(encoding="utf-8")
    assert "</body></body>ev" not in t, "não removeu o beacon corrompido"
    assert t.count(MARCA) == 1 and t.count("sendBeacon") == 1, t
    assert t.count("</body>") == 1, "sobrou </body> órfão do bloco removido"

    # c) sem </body> → não escreve nada e avisa
    c = d / "sembody.html"
    c.write_text("<div>fragmento</div>", encoding="utf-8")
    assert injetar(c, "x") == "sem-body"
    assert c.read_text(encoding="utf-8") == "<div>fragmento</div>", "mexeu num arquivo que não devia"

    print("beacon_snippet OK — sanitiza site, sem </body> no JS, node --check aprova o bom e "
          "REPROVA o corrompido, injeta/idempotente/substitui, respeita HTML sem body")
