"""Classificação do imóvel — pré-processamento antes do Higgsfield (Motor B v1.1).

Interface fixa `classificar(entrada) -> dict` (CLAUDE.md: provider nunca vaza).
Reusa o MESMO LLM já conectado no Motor B (Anthropic — ver higgsfield_video),
com o MESMO toggle mock/real do vídeo: MOCK_MODE=true → classificação
determinística por regras (roda hoje, sem chave); MOCK_MODE=false → Anthropic.

Saída: {padrao, tipo, tom, duracao, cta, fonte}. É input da etapa de prompt,
não feature visível pro cliente.
"""
from __future__ import annotations

import json
import os
import re

from shared_core.obs import log_span

PADROES = ("luxo", "economico", "lancamento", "rural", "comercial")
TIPOS = ("apartamento", "casa", "condominio")

# perfil de vídeo por padrão (tom / duração / CTA) — base do template depois
_PERFIL = {
    "luxo": {"tom": "sofisticado e contemplativo", "duracao": 12, "cta": False},
    "economico": {"tom": "acolhedor e direto", "duracao": 8, "cta": True},
    "lancamento": {"tom": "empolgante, estilo trailer", "duracao": 15, "cta": True},
    "rural": {"tom": "amplo e natural", "duracao": 12, "cta": False},
    "comercial": {"tom": "profissional e minimalista", "duracao": 10, "cta": False},
}


def classificar(entrada: dict) -> dict:
    if os.environ.get("MOCK_MODE", "true").lower() != "false":
        return _mock(entrada)
    return _anthropic(entrada)


# -- mock determinístico (regras) ------------------------------------------
def _num(v) -> float:
    if v is None:
        return 0.0
    digs = re.sub(r"[^\d]", "", str(v))
    return float(digs) if digs else 0.0


def _padrao(desc: str, preco: float) -> str:
    if any(k in desc for k in ("lançamento", "lancamento", "na planta", "pré-lançamento", "pre-lancamento")):
        return "lancamento"
    if any(k in desc for k in ("sala comercial", "loja", "galpão", "galpao", "escritório", "escritorio", "comercial", "corporativ")):
        return "comercial"
    if any(k in desc for k in ("rural", "sítio", "sitio", "chácara", "chacara", "fazenda", "haras", "campo")):
        return "rural"
    if preco >= 1_000_000 or any(k in desc for k in ("luxo", "alto padrão", "alto padrao", "cobertura", "mansão", "mansao", "premium")):
        return "luxo"
    return "economico"


def _tipo(desc: str) -> str:
    if any(k in desc for k in ("casa", "sobrado")):
        return "casa"
    if any(k in desc for k in ("condomínio", "condominio", "condominial")):
        return "condominio"
    return "apartamento"


def _regras(entrada: dict) -> dict:
    """Classificação determinística por regras (sem log) — base do mock E do
    fallback do modo real (sempre devolve saída válida)."""
    desc = (entrada.get("descricao") or "").lower()
    padrao = _padrao(desc, _num(entrada.get("preco")))
    p = _PERFIL[padrao]
    return {"padrao": padrao, "tipo": _tipo(desc), "tom": p["tom"],
            "duracao": p["duracao"], "cta": p["cta"], "fonte": "mock"}


def _mock(entrada: dict) -> dict:
    resultado = _regras(entrada)
    log_span("motor_b.classificacao", **resultado)
    return resultado


# -- real (Anthropic, mesmo provider do vídeo) -----------------------------
def _anthropic(entrada: dict) -> dict:
    import anthropic  # tardio: mock roda sem o SDK

    client = anthropic.Anthropic()
    modelo = os.environ.get("HIGGSFIELD_ANTHROPIC_MODEL", "claude-opus-4-8")
    instrucao = (
        "Classifique este imóvel para gerar um vídeo promocional. Responda APENAS um JSON "
        f'com as chaves: padrao (um de {list(PADROES)}), tipo (um de {list(TIPOS)}), '
        'tom (frase curta), duracao (segundos, 8-15), cta (true/false).\n\n'
        f"Dados: {json.dumps({k: entrada.get(k) for k in ('descricao', 'preco', 'localizacao')}, ensure_ascii=False)}"
    )
    conteudo: list = [{"type": "text", "text": instrucao}]
    conteudo += _bloco_imagem(entrada.get("_imagem_path"))  # analisa a FOTO, não só o texto
    resp = client.messages.create(
        model=modelo, max_tokens=400, temperature=0,  # tarefa determinística, não criativa
        messages=[{"role": "user", "content": conteudo}],
    )
    texto = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    bruto = _extrair_json(texto)
    if bruto is None:  # LLM sem JSON legível → fallback determinístico, nunca crasha
        log_span("motor_b.classificacao", ok=False, motivo="saida_llm_ilegivel", fonte="anthropic-fallback")
        return {**_regras(entrada), "fonte": "anthropic-fallback"}
    dados = _validar(bruto, entrada)  # valida enum/faixa; campo inválido cai na regra
    log_span("motor_b.classificacao", **dados)
    return dados


def _extrair_json(texto: str | None) -> dict | None:
    """Extrai o 1º objeto JSON do texto do LLM. None se não houver bloco {...} ou
    o JSON for malformado — o chamador cai no fallback."""
    m = re.search(r"\{.*\}", texto or "", re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
        return d if isinstance(d, dict) else None
    except (ValueError, TypeError):
        return None


def _validar(bruto: dict, entrada: dict) -> dict:
    """Valida a saída do LLM contra os domínios; qualquer campo inválido/ausente
    cai na classificação por regras. Garante saída sempre consistente."""
    d = {**_regras(entrada), "fonte": "anthropic"}
    if bruto.get("padrao") in PADROES:
        d["padrao"] = bruto["padrao"]
    if bruto.get("tipo") in TIPOS:
        d["tipo"] = bruto["tipo"]
    if isinstance(bruto.get("tom"), str) and bruto["tom"].strip():
        d["tom"] = bruto["tom"].strip()[:120]
    try:
        d["duracao"] = max(8, min(15, int(bruto["duracao"])))
    except (KeyError, TypeError, ValueError):
        pass
    if isinstance(bruto.get("cta"), bool):
        d["cta"] = bruto["cta"]
    return d


def _bloco_imagem(caminho: str | None) -> list:
    """Bloco de imagem (base64) pra classificação por VISÃO. Best-effort: sem
    foto legível, classifica só pelo texto."""
    if not caminho or not os.path.exists(caminho):
        return []
    import base64
    dados = open(caminho, "rb").read()
    if len(dados) > 5 * 1024 * 1024:  # imagem já é normalizada (≤1080/JPEG) antes daqui
        return []
    return [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                         "data": base64.standard_b64encode(dados).decode()}}]
