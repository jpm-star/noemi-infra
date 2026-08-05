"""Higgsfield — geração de imagem e vídeo, via interface FIXA por capacidade.

Segue a regra de ouro do CLAUDE.md: quem chama pede `imagem.gerar()` / `video.de_fotos()`,
nunca "higgsfield.soul()". Trocar o provider por baixo não quebra nada em cima.

Contrato descoberto por sondagem na API (2026-08-05), não por documentação:
    POST /v1/text2image/soul   {"params": {"prompt", "width_and_height"}}
    POST /v1/image2video/dop   {"params": {"prompt", "input_images"}}
Auth por DOIS headers: hf-api-key (client id) + hf-secret.
`width_and_height` é enum FECHADO — resolução livre dá 422 (foi o 1º erro real).

ORÇAMENTO: crédito é finito (mesma disciplina do CNPJá). Teto por rodada explícito e
`sem_credito` distinguido de erro real — 403 "Not enough credits" não é bug, é saldo.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

_BASE = "https://platform.higgsfield.ai"
_UA = "curl/8.5.0"  # WAF costuma barrar UA de urllib (mesmo gotcha de Groq/Resend)

# enum fechado da API — pedir fora disso é 422. Mapeado por INTENÇÃO, não por número:
# quem chama pede "paisagem", não decora "1536x1152".
FORMATOS = {
    "paisagem": "1536x1152", "paisagem_larga": "2048x1152", "quadrado": "1536x1536",
    "retrato": "1152x1536", "story": "1152x2048", "hero": "2048x1536",
}


class SemCredito(RuntimeError):
    """403 'Not enough credits' — saldo, não bug. Quem chama decide se avisa ou espera."""


def configurado() -> tuple[bool, str]:
    cid = os.environ.get("HIGGSFIELD_CLIENT_ID", "").strip()
    sec = os.environ.get("HIGGSFIELD_SECRET", "").strip()
    if not (cid and sec):
        return False, "HIGGSFIELD_CLIENT_ID/SECRET ausentes"
    return True, "configurado"


def _post(caminho: str, params: dict, timeout: int = 180) -> dict:
    ok, motivo = configurado()
    if not ok:
        raise RuntimeError(motivo)
    corpo = json.dumps({"params": params}).encode()
    req = urllib.request.Request(
        f"{_BASE}{caminho}", data=corpo, method="POST",
        headers={"hf-api-key": os.environ["HIGGSFIELD_CLIENT_ID"].strip(),
                 "hf-secret": os.environ["HIGGSFIELD_SECRET"].strip(),
                 "Content-Type": "application/json", "User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        txt = ""
        try:
            txt = e.read().decode()[:300]
        except Exception:  # noqa: BLE001
            pass
        if e.code == 403 and "credit" in txt.lower():
            raise SemCredito(txt) from e
        raise RuntimeError(f"HTTP {e.code}: {txt}") from e


def gerar_imagem(prompt: str, formato: str = "paisagem") -> dict:
    """Imagem a partir de texto. Usada quando o cliente NÃO mandou foto — o que evita
    cair em banco de imagem genérico (caso Academia Bellator). Sempre marcar o
    resultado como `gerado` na procedência: é visual do motor, não do cliente."""
    if not (prompt or "").strip():
        return {"ok": False, "erro": "prompt vazio"}
    wh = FORMATOS.get(formato, FORMATOS["paisagem"])
    try:
        d = _post("/v1/text2image/soul", {"prompt": prompt.strip()[:900],
                                          "width_and_height": wh})
    except SemCredito as e:
        return {"ok": False, "sem_credito": True, "erro": str(e)[:160]}
    except RuntimeError as e:
        return {"ok": False, "erro": str(e)[:200]}
    return {"ok": True, "job": d.get("id") or d.get("job_id") or "", "bruto": d}


def video_de_fotos(prompt: str, urls: list[str]) -> dict:
    """Vídeo a partir de FOTOS REAIS do lugar (image2video). É o motor imobiliária:
    as fotos do imóvel viram apresentação em movimento, sem inventar o que não existe.

    `urls` precisam ser PÚBLICAS — a API busca a imagem, não aceita upload direto."""
    urls = [u for u in (urls or []) if str(u).startswith("http")]
    if not urls:
        return {"ok": False, "erro": "nenhuma URL pública de imagem"}
    try:
        d = _post("/v1/image2video/dop", {"prompt": (prompt or "").strip()[:900],
                                          "input_images": urls[:20]})
    except SemCredito as e:
        return {"ok": False, "sem_credito": True, "erro": str(e)[:160]}
    except RuntimeError as e:
        return {"ok": False, "erro": str(e)[:200]}
    return {"ok": True, "job": d.get("id") or d.get("job_id") or "", "bruto": d}


def disponivel() -> tuple[bool, str]:
    """Dá pra gerar AGORA? Distingue os 3 estados que importam: sem credencial,
    sem crédito, pronto. Uma chamada barata que falha cedo — melhor que descobrir
    no meio da geração de um site."""
    ok, motivo = configurado()
    if not ok:
        return False, motivo
    r = gerar_imagem("teste", "quadrado")
    if r.get("sem_credito"):
        return False, "sem crédito de API (o crédito da plataforma/UI é um pool separado)"
    if not r.get("ok"):
        return False, r.get("erro", "erro desconhecido")[:120]
    return True, "pronto"


if __name__ == "__main__":  # self-check: reporta estado, não gera nada caro
    ok, motivo = configurado()
    print(f"credenciais: {ok} — {motivo}")
    print(f"formatos: {', '.join(FORMATOS)}")
    assert gerar_imagem("")["ok"] is False              # prompt vazio nunca chama a API
    assert video_de_fotos("x", [])["ok"] is False       # sem URL pública, idem
    assert video_de_fotos("x", ["nao-e-url"])["ok"] is False
    if ok:
        d, m = disponivel()
        print(f"disponível pra gerar: {d} — {m}")
