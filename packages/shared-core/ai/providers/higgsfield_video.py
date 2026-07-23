"""Provider REAL: Higgsfield via MCP connector da Messages API.

Padrão já provado em /root/motor-video/app/providers/higgsfield.py (43 testes):
UMA chamada à API Anthropic com mcp_servers → https://mcp.higgsfield.ai/mcp;
Claude escolhe a ferramenta (Kling/Veo/Seedance), gera e devolve a URL.

Pré-requisitos no .env (conta do OPERADOR, nunca do cliente final):
  ANTHROPIC_API_KEY      — resolvida pelo SDK
  HIGGSFIELD_MCP_TOKEN   — access token OAuth (concluído 2026-07-21, plano plus)

ESTA é a função que entra no lugar do mock quando MOCK_MODE=false.
Nenhum outro arquivo do monorepo muda.

IMAGE-TO-VIDEO (Fase A, 2026-07-23): quando config['imagem_url'] vem preenchida
(URL pública do asset, montada pelo worker), a foto REAL do imóvel é o frame de
origem e a instrução proíbe inventar cenário — corrige o "texto→vídeo" que
alucinava um imóvel fictício. Sem imagem_url, cai no fallback texto→vídeo antigo.
Requer o Motor B publicamente acessível (videoshiggs.noemi.digital) pro MCP
buscar a imagem via URL.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

from shared_core.ai.cost import track_cost

_URL_VIDEO = re.compile(r"https?://[^\s\"'<>)\]]+\.(?:mp4|mov|webm)[^\s\"'<>)\]]*", re.I)
_URL_QUALQUER = re.compile(r"https?://[^\s\"'<>)\]]+", re.I)
_MAX_CONTINUACOES = 8  # teto do loop pause_turn (geração de vídeo leva minutos)

# --- OAuth: o token do MCP expira (~24h); o Motor B renova sozinho ----------
# O access token vem no .env como SEED; o refresh rotaciona (cada uso invalida o
# anterior), então o par access+refresh vive num cache GRAVÁVEL que vence o .env.
# Motor B é o DONO do refresh token — não compartilha com a sessão MCP do Claude
# Code (senão um invalida o outro na rotação).
_TOKEN_URL = os.environ.get("HIGGSFIELD_TOKEN_URL", "https://mcp.higgsfield.ai/oauth2/token")
_MARGEM_S = 300  # renova 5 min antes de expirar, nunca no fio


def _cache_path() -> Path:
    return Path(os.environ.get("NOEMI_DATA_DIR", "data")) / "higgsfield_token.json"


def _ler_cache() -> dict:
    try:
        return json.loads(_cache_path().read_text())
    except (OSError, ValueError):
        return {}


def _gravar_cache(d: dict) -> None:
    p = _cache_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(d))
    os.chmod(tmp, 0o600)
    tmp.replace(p)


def _refresh(refresh_token: str, client_id: str) -> dict:
    """Troca refresh_token por um access token novo. Cliente público (PKCE),
    sem client_secret. Devolve {access_token, refresh_token, expires_at}."""
    dados = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
    }).encode()
    # User-Agent obrigatório: o WAF da Higgsfield devolve 403 pro UA default do
    # urllib (mesmo comportamento do Groq). Sem isto o refresh nunca completa.
    req = urllib.request.Request(_TOKEN_URL, data=dados,
                                 headers={"Content-Type": "application/x-www-form-urlencoded",
                                          "Accept": "application/json",
                                          "User-Agent": "noemi-motor-b/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        tok = json.loads(r.read())
    return {
        "access_token": tok["access_token"],
        # o servidor pode ou não rotacionar o refresh; se não vier, mantém o atual
        "refresh_token": tok.get("refresh_token", refresh_token),
        "expires_at": time.time() + int(tok.get("expires_in", 3600)),
        "client_id": client_id,
    }


def _token_atual(forcar: bool = False) -> str:
    """Access token VÁLIDO, renovando via refresh se estiver perto de expirar.
    Fonte de verdade = cache gravável; .env só semeia na 1ª vez. `forcar` renova
    já (usado pra validar o refresh sem esperar a expiração natural)."""
    cache = _ler_cache()
    client_id = cache.get("client_id") or os.environ.get("HIGGSFIELD_CLIENT_ID")
    refresh_token = cache.get("refresh_token") or os.environ.get("HIGGSFIELD_REFRESH_TOKEN")
    access = cache.get("access_token") or os.environ.get("HIGGSFIELD_MCP_TOKEN")
    exp = cache.get("expires_at", 0)

    precisa = forcar or not access or time.time() > (exp - _MARGEM_S)
    if precisa and refresh_token and client_id:
        novo = _refresh(refresh_token, client_id)
        _gravar_cache(novo)
        return novo["access_token"]
    if not access:
        raise RuntimeError("HIGGSFIELD_MCP_TOKEN ausente e sem refresh — configure o .env")
    return access


@track_cost("higgsfield")
def generate(asset: dict, config: dict) -> dict:
    token = _token_atual()

    import anthropic  # tardio: mock roda sem o SDK instalado

    client = anthropic.Anthropic()
    mcp_url = os.environ.get("HIGGSFIELD_MCP_URL", "https://mcp.higgsfield.ai/mcp")
    modelo = os.environ.get("HIGGSFIELD_ANTHROPIC_MODEL", "claude-opus-4-8")
    messages: list[dict] = [{"role": "user", "content": _instrucao(asset, config)}]

    for _ in range(_MAX_CONTINUACOES):
        resp = client.beta.messages.create(
            model=modelo,
            max_tokens=int(os.environ.get("HIGGSFIELD_MAX_TOKENS", "16000")),
            betas=["mcp-client-2025-11-20"],
            thinking={"type": "adaptive"},
            mcp_servers=[{"type": "url", "url": mcp_url, "name": "higgsfield",
                          "authorization_token": token}],
            tools=[{"type": "mcp_toolset", "mcp_server_name": "higgsfield"}],
            messages=messages,
        )
        if resp.stop_reason == "pause_turn":  # loop server-side pausou; reenviar continua
            messages = [messages[0], {"role": "assistant", "content": resp.content}]
            continue
        if resp.stop_reason == "refusal":
            raise RuntimeError("geração recusada pela API (stop_reason=refusal)")
        url = _extrair_url(resp)
        with urllib.request.urlopen(url, timeout=300) as r:  # baixa pro bucket local
            dados = r.read()
        if dados[4:8] != b"ftyp":  # fallback de URL pode pegar página de status
            raise RuntimeError(f"download de {url[:120]} não é mp4 — URL errada extraída da resposta")
        return {
            "bytes": dados,
            "mime": "video/mp4",
            "modelo": modelo,
            "custo_creditos": config.get("custo_estimado", None),
            "meta": {"url_provider": url, "job_id": resp.id, "asset_origem": asset["id"],
                     "modelo_video": config.get("model") or _MODELO_VIDEO,
                     "image_to_video": bool(config.get("imagem_url"))},
        }
    raise TimeoutError(f"Higgsfield MCP não terminou em {_MAX_CONTINUACOES} continuações (pause_turn)")


# Modelo default: Kling é o melhor para image-to-video imobiliário (movimento
# realista + física). Override por config.model ou env.
_MODELO_VIDEO = os.environ.get("MOTOR_B_VIDEO_MODEL", "kling")


def _instrucao(asset: dict, config: dict) -> str:
    imagem_url = config.get("imagem_url")
    modelo = config.get("model") or _MODELO_VIDEO
    if imagem_url:
        # IMAGE-TO-VIDEO: a foto REAL do imóvel é o frame de origem. Instrução
        # anti-alucinação é o núcleo da correção — sem isto o modelo inventa um
        # imóvel fictício (o bug do "texto→vídeo"). Regra do mercado imobiliário:
        # nunca inventar features que não estão na foto.
        partes = [
            f"Gere UM vídeo IMAGE-TO-VIDEO com o modelo {modelo} usando as ferramentas do "
            "servidor MCP da Higgsfield, e aguarde até ficar pronto.",
            f"IMAGEM DE ORIGEM (frame inicial obrigatório): {imagem_url}",
            "Anime ESTA foto do imóvel real com movimento de câmera — NÃO gere um imóvel "
            "novo, NÃO invente cômodos, móveis ou acabamentos que não aparecem na foto. "
            "O vídeo deve ser fiel ao imóvel da imagem.",
            f"Direção de câmera/ritmo/luz: {config.get('prompt', 'movimento sutil e cinematográfico')}",
        ]
    else:
        # fallback texto→vídeo (sem foto disponível) — mantém o comportamento antigo,
        # honestamente pior. Só cai aqui se imagem_url não vier.
        partes = [
            f"Gere UM vídeo com o modelo {modelo} usando as ferramentas do servidor MCP da "
            "Higgsfield e aguarde até ficar pronto.",
            f"Descrição do vídeo: {config.get('prompt', 'vídeo promocional do material enviado')}",
            f"Contexto do material de origem: produto={asset['produto']}, metadata={asset['metadata']}",
        ]
    if config.get("duration"):
        partes.append(f"Duração alvo: {config['duration']}s.")
    partes.append("Ao final, responda com APENAS a URL do vídeo pronto na última linha.")
    return "\n".join(partes)


def _extrair_url(resp) -> str:
    textos: list[str] = []
    for block in resp.content:
        tipo = getattr(block, "type", "")
        if tipo == "text":
            textos.append(block.text)
        elif tipo == "mcp_tool_result":
            for item in getattr(block, "content", []) or []:
                textos.append(getattr(item, "text", "") or "")
    corpo = "\n".join(textos)
    urls = _URL_VIDEO.findall(corpo) or _URL_QUALQUER.findall(textos[-1] if textos else "")
    if not urls:
        raise RuntimeError(f"resposta sem URL de vídeo (stop_reason={resp.stop_reason}): {corpo[:500]}")
    return urls[-1]
