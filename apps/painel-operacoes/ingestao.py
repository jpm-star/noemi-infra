#!/usr/bin/env python3
"""INGESTÃO TOTAL — tudo que o cliente manda entra por uma porta só.

Hoje o material chega picado (foto aqui, texto ali) e o motor completa o resto com
genérico — foi assim que a Academia Bellator saiu com foto de banco de imagem. Aqui
cada fonte vira material estruturado e, o mais importante, MARCADO:

    real     = veio do cliente (foto dele, texto do site dele, resposta do form)
    gerado   = o motor produziu porque faltou material
    inferido = derivado do que se sabe do lead (CRM), não afirmado por ele

Sem essa marcação o site mistura o que é do cliente com o que foi inventado e ninguém
consegue auditar depois — que é exatamente como um "site personalizado" vira template.

Fontes: site atual (link), formulário (Google Forms colado), PDF (reusa o pipeline
que já existe), fotos/vídeos (já suportado) e o CRM (leads.db).
"""
from __future__ import annotations

import gzip
import html
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(_AQUI))
sys.path.insert(0, str(_AQUI.parents[1] / "packages"))

REAL, GERADO, INFERIDO = "real", "gerado", "inferido"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")


def _buscar(url: str, timeout: int = 25) -> str:
    """HTML da página. UA de navegador (muito site bloqueia UA de script) e gunzip
    manual — o urllib não descomprime sozinho (mesmo gotcha do IBGE)."""
    req = urllib.request.Request(url, headers={"User-Agent": _UA,
                                               "Accept": "text/html,*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        bruto = r.read()
    if bruto[:2] == b"\x1f\x8b":
        bruto = gzip.decompress(bruto)
    for enc in ("utf-8", "latin-1"):
        try:
            return bruto.decode(enc)
        except UnicodeDecodeError:
            continue
    return bruto.decode("utf-8", errors="ignore")


def _texto_de(htm: str) -> str:
    """Texto visível. Remove script/style ANTES de tirar as tags — senão o conteúdo
    de <script> entra como se fosse copy do cliente."""
    h = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", htm)
    h = re.sub(r"(?s)<!--.*?-->", " ", h)
    h = re.sub(r"(?i)<(br|/p|/div|/h[1-6]|/li)[^>]*>", "\n", h)
    h = re.sub(r"<[^>]+>", " ", h)
    h = html.unescape(h)
    linhas = [" ".join(x.split()) for x in h.splitlines()]
    return "\n".join(x for x in linhas if len(x) > 2)


def do_site(url: str) -> dict:
    """Site ATUAL do cliente → material REAL (o que ele já diz de si mesmo).

    Vale mais que qualquer briefing: é a copy que ele escolheu, os serviços que ele
    de fato oferece e o tom da casa. Pra T3/T4 (que já têm site) isso é a diferença
    entre 'refizemos seu site' e 'fizemos um site genérico com seu nome'."""
    url = (url or "").strip()
    if not url.startswith("http"):
        url = "https://" + url.lstrip("/")
    try:
        htm = _buscar(url)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "erro": f"não deu pra ler o site: {str(e)[:120]}", "fonte": url}
    texto = _texto_de(htm)
    titulo = ""
    if m := re.search(r"(?is)<title[^>]*>(.*?)</title>", htm):
        titulo = " ".join(html.unescape(m.group(1)).split())[:160]
    desc = ""
    if m := re.search(r'(?is)<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']', htm):
        desc = " ".join(html.unescape(m.group(1)).split())[:300]
    # blocos com cara de serviço/diferencial: linha curta e afirmativa
    blocos = [x for x in texto.split("\n") if 12 <= len(x) <= 110][:40]
    emails = sorted(set(re.findall(r"[\w.\-+]+@[\w\-]+\.[\w.\-]+", htm)))[:5]
    zaps = sorted(set(re.findall(r"(?:wa\.me/|api\.whatsapp\.com/send\?phone=)(\d{10,13})", htm)))[:3]
    return {"ok": True, "fonte": url, "marca": REAL, "titulo": titulo, "descricao": desc,
            "texto": texto[:8000], "blocos": blocos, "emails": emails, "whatsapp": zaps,
            "tem_conteudo": len(texto) > 400}


_ROTULOS = {
    "nome": ("nome", "empresa", "negócio", "negocio", "razão", "razao"),
    "nicho": ("nicho", "segmento", "ramo", "area", "área", "atividade"),
    "cidade": ("cidade", "municipio", "município", "regiao", "região", "onde"),
    "whatsapp": ("whatsapp", "telefone", "celular", "contato", "zap"),
    "email": ("email", "e-mail"),
    "servicos": ("serviço", "servico", "serviços", "servicos", "produto", "procedimento",
                 "especialidade"),
    "diferenciais": ("diferencial", "diferenciais", "destaque", "por que", "porque",
                     "vantagem", "sobre"),
    "horario": ("horário", "horario", "funcionamento", "atendimento"),
}


def do_formulario(texto: str) -> dict:
    """Resposta de Google Forms COLADA → campos do briefing.

    O JP recebe a resposta como texto ('Pergunta: resposta' por linha) e hoje redigita
    tudo à mão. Casa o rótulo da pergunta com o campo do briefing por palavra-chave —
    o que não casar vira `extra`, que ainda alimenta a copy em vez de sumir."""
    campos: dict[str, list[str]] = {}
    extra: list[str] = []
    for linha in (texto or "").splitlines():
        linha = linha.strip()
        if not linha:
            continue
        rot, sep, val = linha.partition(":")
        if not sep or not val.strip():
            if len(linha) > 12:
                extra.append(linha)
            continue
        rot_l, val = rot.strip().lower(), val.strip()
        alvo = next((c for c, chaves in _ROTULOS.items() if any(k in rot_l for k in chaves)), "")
        if alvo:
            campos.setdefault(alvo, []).append(val)
        elif len(val) > 3:
            extra.append(f"{rot.strip()}: {val}")
    saida = {k: ("\n".join(v) if k in ("servicos", "diferenciais") else v[0])
             for k, v in campos.items()}
    if extra:
        saida["extra"] = "\n".join(extra[:15])
    return {"ok": bool(saida), "marca": REAL, "campos": saida,
            "reconhecidos": sorted(campos), "nao_mapeados": len(extra)}


def do_pdf(caminho: str) -> dict:
    """PDF → texto, reusando a extração do Radar (não duplica). Só o TEXTO — o insight
    do Radar é outra coisa; aqui o PDF é material de briefing."""
    import subprocess
    import tempfile
    p = Path(caminho)
    if not p.exists():
        return {"ok": False, "erro": "arquivo não encontrado"}
    with tempfile.TemporaryDirectory() as td:
        saida = Path(td) / "t.txt"
        try:
            subprocess.run(["pdftotext", "-layout", "-q", str(p), str(saida)],
                           check=True, capture_output=True, timeout=120)
            texto = saida.read_text(encoding="utf-8", errors="ignore").strip()
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "erro": str(e)[:120]}
    return {"ok": bool(texto), "marca": REAL, "texto": texto[:8000],
            "blocos": [x.strip() for x in texto.split("\n") if 12 <= len(x.strip()) <= 110][:30]}


def do_crm(nome: str) -> dict:
    """O que já se sabe do lead (autofill + QSA + achado da prospecção). Marcado
    INFERIDO: é verdade sobre o lead, mas não foi ELE que disse — então não pode
    virar afirmação na primeira pessoa no site."""
    try:
        import criacao
        d = criacao.dados_lead(nome)
    except Exception:  # noqa: BLE001
        d = {}
    if not d.get("achou"):
        return {"ok": False}
    return {"ok": True, "marca": INFERIDO, "campos": {
        k: v for k, v in d.items()
        if k in ("nicho", "whatsapp", "publico", "diferenciais", "cidade", "tier") and v}}


_HF_CACHE: tuple[bool, str] | None = None


def higgsfield_disponivel() -> tuple[bool, str]:
    """Higgsfield supre material visual faltante em vez de cair em banco de imagem
    (caso Academia Bellator). Pergunta ao provider de verdade — credencial válida
    mas SEM CRÉDITO conta como indisponível: gerar visual que vai falhar no meio da
    criação do site é pior que saber antes e marcar a mídia como ausente.

    ponytail: memo por processo. A resposta só muda quando o JP compra crédito;
    sondar a cada consolidação seria uma chamada de rede por site gerado."""
    global _HF_CACHE
    if _HF_CACHE is None:
        try:
            from shared_core.ai import higgsfield
            _HF_CACHE = higgsfield.disponivel()
        except Exception as e:  # noqa: BLE001
            _HF_CACHE = (False, f"provider indisponível: {e}"[:120])
    return _HF_CACHE


def consolidar(*, nome: str = "", site_url: str = "", formulario: str = "",
               pdfs: list[str] | None = None, fotos: int = 0, videos: int = 0,
               usar_crm: bool = True) -> dict:
    """Junta TUDO num briefing só, com a procedência de cada peça.

    Precedência: o que o CLIENTE disse (site/form/PDF) vence o que se INFERIU do CRM.
    Material do cliente é verdade; CRM é hipótese."""
    material: dict = {"nome": nome}
    proveniencia: dict[str, str] = {}
    fontes: list[dict] = []

    if usar_crm and nome:
        crm = do_crm(nome)
        if crm.get("ok"):
            for k, v in crm["campos"].items():
                material[k] = v
                proveniencia[k] = INFERIDO
            fontes.append({"tipo": "crm", "ok": True, "campos": len(crm["campos"])})

    if formulario.strip():
        f = do_formulario(formulario)
        for k, v in (f.get("campos") or {}).items():
            material[k] = v
            proveniencia[k] = REAL  # o cliente respondeu: vence o CRM
        fontes.append({"tipo": "formulário", "ok": f["ok"],
                       "campos": len(f.get("campos") or {}), "extra": f.get("nao_mapeados", 0)})

    textos_reais: list[str] = []
    if site_url.strip():
        s = do_site(site_url)
        fontes.append({"tipo": "site atual", "ok": s.get("ok", False),
                       "erro": s.get("erro", ""), "blocos": len(s.get("blocos") or [])})
        if s.get("ok"):
            textos_reais.append(s.get("texto", ""))
            if s.get("blocos") and not material.get("diferenciais"):
                material["diferenciais"] = "\n".join(s["blocos"][:6])
                proveniencia["diferenciais"] = REAL
            if s.get("emails") and not material.get("email"):
                material["email"] = s["emails"][0]
                proveniencia["email"] = REAL

    for cam in (pdfs or []):
        d = do_pdf(cam)
        fontes.append({"tipo": f"pdf:{Path(cam).name}", "ok": d.get("ok", False),
                       "blocos": len(d.get("blocos") or [])})
        if d.get("ok"):
            textos_reais.append(d.get("texto", ""))
            if d.get("blocos") and not material.get("servicos"):
                material["servicos"] = "\n".join(d["blocos"][:8])
                proveniencia["servicos"] = REAL

    if textos_reais:
        material["contexto_cliente"] = "\n\n".join(textos_reais)[:12000]
        proveniencia["contexto_cliente"] = REAL

    material["midia"] = ["foto"] * fotos + ["video"] * videos
    if fotos or videos:
        proveniencia["midia"] = REAL
    else:
        hf_ok, hf_msg = higgsfield_disponivel()
        proveniencia["midia"] = GERADO if hf_ok else ""
        fontes.append({"tipo": "visual gerado", "ok": hf_ok, "erro": "" if hf_ok else hf_msg})

    reais = sum(1 for v in proveniencia.values() if v == REAL)
    return {"material": material, "proveniencia": proveniencia, "fontes": fontes,
            "campos_reais": reais, "campos_total": len(proveniencia)}


if __name__ == "__main__":  # self-check (sem rede)
    f = do_formulario("Nome da empresa: Clínica Aurea\n"
                      "Segmento: odontologia estética\n"
                      "Cidade: Bauru\n"
                      "WhatsApp: (14) 99999-0000\n"
                      "Quais serviços vocês oferecem?: lentes de contato dental\n"
                      "Serviços: clareamento\n"
                      "Uma curiosidade qualquer: fundada em 2015")
    assert f["campos"]["nome"] == "Clínica Aurea", f
    assert f["campos"]["cidade"] == "Bauru" and "clareamento" in f["campos"]["servicos"]
    assert "lentes de contato" in f["campos"]["servicos"], f["campos"]["servicos"]
    assert f["nao_mapeados"] == 1, f  # a curiosidade vira extra, não some

    htm = ("<html><head><title>Clínica Aurea — Odontologia</title>"
           '<meta name="description" content="Odontologia estética em Bauru">'
           "<style>.x{color:red}</style><script>var segredo='NAO_ENTRA'</script></head>"
           "<body><h1>Bem-vindo</h1><p>Atendimento humanizado desde 2015</p>"
           "<li>Clareamento dental</li><li>Lentes de contato</li>"
           '<a href="https://wa.me/5514999990000">zap</a>'
           "<p>contato@aurea.com.br</p></body></html>")
    t = _texto_de(htm)
    assert "NAO_ENTRA" not in t and "color:red" not in t, "script/style vazaram pro texto"
    assert "Clareamento dental" in t
    # consolidação: cliente vence CRM
    c = consolidar(nome="X", formulario="Cidade: Assis", usar_crm=False, fotos=2)
    assert c["material"]["cidade"] == "Assis" and c["proveniencia"]["cidade"] == REAL
    assert c["proveniencia"]["midia"] == REAL and len(c["material"]["midia"]) == 2
    c2 = consolidar(nome="X", usar_crm=False)          # sem mídia e sem Higgsfield
    assert c2["proveniencia"]["midia"] == "", c2["proveniencia"]
    print("ingestao OK — form mapeia rótulo→campo (extra preservado), site limpa "
          "script/style, procedência marca real/inferido/gerado")
