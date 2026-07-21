"""Provider REAL: Higgsfield via MCP connector da Messages API.

Padrão já provado em /root/motor-video/app/providers/higgsfield.py (43 testes):
UMA chamada à API Anthropic com mcp_servers → https://mcp.higgsfield.ai/mcp;
Claude escolhe a ferramenta (Kling/Veo/Seedance), gera e devolve a URL.

Pré-requisitos no .env (conta do OPERADOR, nunca do cliente final):
  ANTHROPIC_API_KEY      — resolvida pelo SDK
  HIGGSFIELD_MCP_TOKEN   — access token OAuth (concluído 2026-07-21, plano plus)

ESTA é a função que entra no lugar do mock quando MOCK_MODE=false.
Nenhum outro arquivo do monorepo muda.

LIMITE HONESTO (Fase 1): o modo real é PROMPT-ONLY — a mídia enviada pelo
cliente ainda NÃO é anexada à geração (só produto/metadata viram texto no
prompt). Image-to-video de verdade = Fase 2: media_upload/media_import_url
do MCP antes do generate_video (ver deploy/PENDENCIAS.md §4).
"""
from __future__ import annotations

import os
import re
import urllib.request

from shared_core.ai.cost import track_cost

_URL_VIDEO = re.compile(r"https?://[^\s\"'<>)\]]+\.(?:mp4|mov|webm)[^\s\"'<>)\]]*", re.I)
_URL_QUALQUER = re.compile(r"https?://[^\s\"'<>)\]]+", re.I)
_MAX_CONTINUACOES = 8  # teto do loop pause_turn (geração de vídeo leva minutos)


@track_cost("higgsfield")
def generate(asset: dict, config: dict) -> dict:
    token = os.environ.get("HIGGSFIELD_MCP_TOKEN")
    if not token:
        raise RuntimeError("HIGGSFIELD_MCP_TOKEN ausente — mantenha MOCK_MODE=true até configurar o .env")

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
            "meta": {"url_provider": url, "job_id": resp.id, "asset_origem": asset["id"]},
        }
    raise TimeoutError(f"Higgsfield MCP não terminou em {_MAX_CONTINUACOES} continuações (pause_turn)")


def _instrucao(asset: dict, config: dict) -> str:
    partes = [
        "Gere UM vídeo usando as ferramentas do servidor MCP da Higgsfield e aguarde até ficar pronto.",
        f"Descrição do vídeo: {config.get('prompt', 'vídeo promocional do material enviado')}",
        f"Contexto do material de origem: produto={asset['produto']}, metadata={asset['metadata']}",
    ]
    if config.get("duration"):
        partes.append(f"Duração alvo: {config['duration']}s.")
    if config.get("model"):
        partes.append(f"Preferência de modelo de geração: {config['model']}.")
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
