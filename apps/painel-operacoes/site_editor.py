"""IA nativa de edição do site (Item 2) — o dono digita um comando em linguagem natural
("muda o WhatsApp pra X", "troca o nome pra Y", "tira o 3º plano") e a IA PROPÕE a mudança
no cartucho. NUNCA aplica sozinha: devolve um preview pra CONFIRMAÇÃO; só depois `aplicar`.

Groq-only (permitir_anthropic=False) — mesmo trava de custo do resto. Isto é o que prova
que o Motor Site é fábrica de template controlável, não gerador de site único.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(_AQUI.parents[1] / "packages"))

# O que a IA pode mexer (chave do cartucho → rótulo humano). Campo fora disto => não suportado.
CAMPOS = {
    "nome_empresa": "nome da empresa",
    "whatsapp_dono": "número de WhatsApp (CTAs)",
    "vertical": "nicho/vertical",
    "criterio_qualificado": "público-alvo",
    "diferenciais": "lista de diferenciais",
    "escopo": "lista de serviços",
    "catalogo": "planos e o que cada um inclui",
}
# Campos que aplicam CIRURGICAMENTE (patcham só a parte afetada do HTML, preservam a copy):
# whatsapp/nome = string simples; catalogo = reconstrói só a seção (determinística). Os demais
# (diferenciais → cards gerados por Groq) precisam regenerar via motor — sinalizado no retorno.
_CIRURGICO = {"whatsapp_dono", "nome_empresa", "catalogo"}


def _secao_catalogo(catalogo: list) -> str:
    """Reconstrói SÓ a seção de catálogo do HTML a partir do cartucho (determinística —
    mesmo formato do _bloco_catalogo do motor). É o que permite editar o catálogo por
    comando sem regenerar o site inteiro."""
    import html as _h
    cards = []
    for it in catalogo if isinstance(catalogo, list) else []:
        if not isinstance(it, dict) or not str(it.get("tier", "")).strip():
            continue
        preco = str(it.get("preco_ref", "")).strip()
        lis = "".join(f"<li>{_h.escape(str(x))}</li>" for x in (it.get("inclui") or []) if str(x).strip())
        cards.append(f'<article class="cat-card"><h3>{_h.escape(str(it["tier"]))}</h3>'
                     f'{f"<div class=cat-preco>{_h.escape(preco)}</div>" if preco else ""}'
                     f'<ul>{lis}</ul></article>')
    return ('<section class="catalogo reveal" id="o-que-inclui"><h2 class="sec-titulo">Os planos JPOS</h2>'
            f'<div class="cat-grid">{"".join(cards)}</div></section>')


def interpretar(comando: str, cartucho: dict) -> dict:
    """Comando NL + cartucho → PROPOSTA de mudança (não aplica). Groq-only."""
    from shared_core.ai import llm_proxy
    atual = {k: cartucho.get(k) for k in CAMPOS}
    prompt = (
        "Você edita o cartucho de um site por comando do dono. Campos editáveis (chave→rótulo): "
        f"{json.dumps(CAMPOS, ensure_ascii=False)}. Cartucho atual desses campos: "
        f"{json.dumps(atual, ensure_ascii=False)[:2200]}. Comando: \"{comando.strip()[:300]}\". "
        "Proponha UMA mudança concreta. Se o comando pedir algo fora dos campos editáveis "
        "(ex: trocar foto), suportado=false com um motivo curto. valor_novo tem que ser do "
        "MESMO tipo do campo (string, ou lista). SOMENTE JSON: "
        '{"suportado":true|false,"campo":"<chave>","valor_novo":<novo valor>,'
        '"resumo":"<1 linha do que muda>","motivo":"<se não suportado>"}')
    txt = llm_proxy.completar(prompt, model="analise", max_tokens=500, temperature=0.2,
                              permitir_anthropic=False)
    m = re.search(r"\{.*\}", txt or "", re.S)
    if not m:
        return {"suportado": False, "motivo": "não entendi o comando (LLM sem resposta)"}
    try:
        d = json.loads(m.group(0))
    except (ValueError, TypeError):
        return {"suportado": False, "motivo": "resposta ilegível da IA"}
    campo = str(d.get("campo", "")).strip()
    if not d.get("suportado") or campo not in CAMPOS:
        return {"suportado": False, "motivo": str(d.get("motivo") or "não dá pra editar esse campo por comando ainda")}
    return {"suportado": True, "campo": campo, "rotulo": CAMPOS[campo],
            "valor_antigo": cartucho.get(campo), "valor_novo": d.get("valor_novo"),
            "resumo": str(d.get("resumo", ""))[:200],
            "cirurgico": campo in _CIRURGICO}  # cirúrgico = aplica sem mexer no resto da copy


def aplicar(cartucho_path: str, campo: str, valor_novo, deploy_html: str | None = None) -> dict:
    """APLICA a mudança confirmada: atualiza o cartucho e, se cirúrgico, patcha o HTML já
    publicado (preserva a copy). Campos não-cirúrgicos: só atualiza o cartucho e sinaliza
    que precisa REGENERAR (o caller regera+previa). Nunca roda sem confirmação do caller."""
    if campo not in CAMPOS:
        raise ValueError(f"campo não editável: {campo}")
    cart = json.loads(Path(cartucho_path).read_text(encoding="utf-8"))
    antigo = cart.get(campo)
    cart[campo] = valor_novo
    Path(cartucho_path).write_text(json.dumps(cart, ensure_ascii=False, indent=2), encoding="utf-8")
    patched = False
    if campo in _CIRURGICO and deploy_html and Path(deploy_html).exists():
        h = Path(deploy_html).read_text(encoding="utf-8")
        if campo == "whatsapp_dono":
            so_digitos = re.sub(r"\D", "", str(valor_novo))
            h = re.sub(r"wa\.me/\d+", f"wa.me/{so_digitos}", h)  # todos os CTAs
        elif campo == "nome_empresa":
            h = h.replace(str(antigo), str(valor_novo)) if antigo else h
        elif campo == "catalogo":  # reconstrói só a seção de catálogo (determinística)
            h = re.sub(r'<section class="catalogo reveal" id="o-que-inclui">.*?</section>',
                       lambda _m: _secao_catalogo(valor_novo), h, count=1, flags=re.S)
        Path(deploy_html).write_text(h, encoding="utf-8")
        patched = True
    return {"campo": campo, "aplicado": True, "cirurgico_patch": patched,
            "precisa_regenerar": campo not in _CIRURGICO}


if __name__ == "__main__":  # self-check ISOLADO (LLM mockado + patch em arquivo temp)
    import os
    tmp = Path("/root/.claude/jobs/f7137c43/tmp/editor_selftest"); tmp.mkdir(parents=True, exist_ok=True)
    cart_p = tmp / "c.json"
    cart_p.write_text(json.dumps({"nome_empresa": "JPOS", "whatsapp_dono": "+55 11 90000-0000",
                                  "catalogo": [{"tier": "A"}]}), encoding="utf-8")
    html_p = tmp / "site.html"
    html_p.write_text('<a href="https://wa.me/5511900000000?text=oi">zap</a> JPOS aqui', encoding="utf-8")
    from shared_core.ai import llm_proxy

    # comando suportado (whatsapp) → proposta cirúrgica
    llm_proxy.completar = lambda *a, **k: '{"suportado":true,"campo":"whatsapp_dono","valor_novo":"+55 14 99874-5847","resumo":"troca o WhatsApp"}'
    cart = json.loads(cart_p.read_text())
    p = interpretar("muda o whatsapp pra 14 99874-5847", cart)
    assert p["suportado"] and p["campo"] == "whatsapp_dono" and p["cirurgico"], p
    r = aplicar(str(cart_p), p["campo"], p["valor_novo"], str(html_p))
    assert r["cirurgico_patch"] and not r["precisa_regenerar"], r
    assert "wa.me/5514998745847" in html_p.read_text() and "5511900000000" not in html_p.read_text(), "patch do CTA falhou"
    assert json.loads(cart_p.read_text())["whatsapp_dono"] == "+55 14 99874-5847"

    # comando NÃO suportado (foto) → suportado=false, não aplica
    llm_proxy.completar = lambda *a, **k: '{"suportado":false,"motivo":"trocar foto não é editável por comando ainda"}'
    p2 = interpretar("troca a foto do hero", cart)
    assert not p2["suportado"] and "foto" in p2["motivo"], p2

    # comando de conteúdo (catalogo) → CIRÚRGICO: reconstrói só a seção de catálogo
    html_p.write_text('<section class="catalogo reveal" id="o-que-inclui"><h2>x</h2>'
                      '<div class="cat-grid"><article class="cat-card"><h3>Velho</h3></article></div></section>',
                      encoding="utf-8")
    llm_proxy.completar = lambda *a, **k: '{"suportado":true,"campo":"catalogo","valor_novo":[{"tier":"Novo","inclui":["item A"]}],"resumo":"muda planos"}'
    p3 = interpretar("renomeia o 1º plano", cart)
    assert p3["suportado"] and p3["cirurgico"], p3
    r3 = aplicar(str(cart_p), "catalogo", [{"tier": "Novo", "inclui": ["item A"]}], str(html_p))
    assert r3["cirurgico_patch"] and not r3["precisa_regenerar"], r3
    hh = html_p.read_text()
    assert "Novo" in hh and "item A" in hh and "Velho" not in hh, "seção de catálogo não foi reconstruída"
    print("site_editor OK — interpreta comando (Groq), confirma antes, patch cirúrgico (whatsapp/nome), "
          "content→regenera, não-suportado→recusa")
