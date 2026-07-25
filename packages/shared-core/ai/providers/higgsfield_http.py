"""Provider REAL via MCP HTTP DIRETO — sem loop Anthropic (custo Anthropic = R$0).

Substitui o caminho de higgsfield_video.py (que orquestrava via
client.beta.messages.create, pagando tokens Opus a cada continuação pra reenviar
os ~77 schemas de tool do MCP). Aqui falamos JSON-RPC direto com
https://mcp.higgsfield.ai/mcp (SSE), chamando as tools na mão:
  media_import_url(foto) -> generate_video(kling3_0, start_image) -> job_status(poll)
Mesmo resultado (Kling image-to-video, guardrail anti-alucinação), mesmo formato
de entrega. Único custo = créditos Higgsfield.

Reusa _token_atual() de higgsfield_video (auto-refresh OAuth já provado).
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.request

from shared_core.ai.cost import track_cost
from shared_core.ai.providers.higgsfield_video import _token_atual, _MODELO_VIDEO

_MCP_URL = os.environ.get("HIGGSFIELD_MCP_URL", "https://mcp.higgsfield.ai/mcp")
_URL_VIDEO = re.compile(r"https?://[^\s\"'<>)\]]+\.(?:mp4|mov|webm)[^\s\"'<>)\]]*", re.I)
_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_POLL_MAX = int(os.environ.get("HIGGSFIELD_POLL_MAX", "90"))   # ~90 x 2s = 3min
_POLL_S = float(os.environ.get("HIGGSFIELD_POLL_S", "2"))
_RPC_ID = 0


def _rpc(name: str, arguments: dict, token: str) -> dict:
    """Uma chamada tools/call ao MCP. Devolve o result já parseado (JSON do texto
    da tool, quando é JSON; senão {'_text': ...})."""
    global _RPC_ID
    _RPC_ID += 1
    body = json.dumps({"jsonrpc": "2.0", "id": _RPC_ID, "method": "tools/call",
                       "params": {"name": name, "arguments": arguments}}).encode()
    req = urllib.request.Request(_MCP_URL, data=body, headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream", "User-Agent": "noemi-motor-b/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        raw = r.read().decode("utf-8", "replace")
    data = _sse_json(raw)
    if "error" in data:
        raise RuntimeError(f"MCP {name} erro: {data['error']}")
    result = data.get("result", {})
    # o texto da tool costuma ser JSON string; devolve parseado + o texto cru
    textos = [c.get("text", "") for c in result.get("content", []) if c.get("type") == "text"]
    corpo = "\n".join(textos)
    parsed: dict = {"_text": corpo, "_result": result}
    try:
        j = json.loads(corpo)
        if isinstance(j, dict):
            parsed.update(j)
    except (ValueError, TypeError):
        pass
    return parsed


def _sse_json(raw: str) -> dict:
    """Extrai o JSON-RPC do corpo SSE (linhas 'data: {...}'). Pega o 1º com result/error."""
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            try:
                d = json.loads(line[5:].strip())
                if "result" in d or "error" in d:
                    return d
            except ValueError:
                continue
    # fallback: talvez JSON puro (não-SSE)
    try:
        return json.loads(raw)
    except ValueError:
        raise RuntimeError(f"resposta MCP não parseável: {raw[:300]}")


def _prompt(config: dict) -> str:
    """Direção pro generate_video, com guardrail anti-alucinação (idêntico ao do
    caminho antigo). Usa o prompt já montado pelo prompt_builder quando existe."""
    base = config.get("prompt", "movimento de câmera sutil e cinematográfico")
    return (f"{base} Mantenha-se 100% fiel à imagem de origem: NÃO invente cômodos, "
            "móveis, estruturas ou acabamentos que não aparecem na foto.")


@track_cost("higgsfield")
def generate(asset: dict, config: dict) -> dict:
    # sanitização do payload PRIMEIRO (fail-fast antes de token/rede): sem
    # imagem_url não há image-to-video — erro tratável, nunca 500 no worker.
    imagem_url = config.get("imagem_url")
    if not imagem_url:
        raise RuntimeError("higgsfield_http exige config['imagem_url'] (image-to-video); "
                           "sem foto, use o mock ou preencha a URL do asset")
    token = _token_atual()
    modelo = config.get("model") or _MODELO_VIDEO

    # 1) importa a foto -> media_id (a tool pode responder JSON OU texto humano
    # "...Pass media_id <uuid>..."; pega dos dois via regex de UUID no fallback)
    imp = _rpc("media_import_url", {"url": imagem_url, "type": "image"}, token)
    media_id = imp.get("media_id") or _primeiro_uuid(imp.get("_text", ""))
    if not media_id:
        raise RuntimeError(f"media_import_url sem media_id: {imp.get('_text', '')[:200]}")

    # 2) gera o vídeo (image-to-video, Kling default). generate_video aninha tudo
    # em "params" (schema anyOf object/string), diferente de import/status.
    gen = _rpc("generate_video", {"params": {
        "model": modelo,
        "prompt": _prompt(config),
        "medias": [{"role": "start_image", "value": media_id}],
        "aspect_ratio": config.get("aspect_ratio", "9:16"),
        "duration": int(config.get("duration", 5)),
        "sound": "off", "mode": "std",
    }}, token)
    job_id = _job_id(gen)
    if not job_id:
        raise RuntimeError(f"generate_video sem job id: {gen.get('_text', '')[:200]}")

    # 3) poll até completar -> URL do mp4
    url = None
    for _ in range(_POLL_MAX):
        st = _rpc("job_status", {"jobId": job_id}, token)
        texto = st.get("_text", "")
        if st.get("status") == "failed" or "— failed" in texto:
            raise RuntimeError(f"job {job_id} falhou: {texto[:200]}")
        achou = _URL_VIDEO.findall(texto)
        if achou and ("completed" in texto or st.get("status") == "completed"):
            url = achou[-1]
            break
        time.sleep(_POLL_S)
    if not url:
        raise TimeoutError(f"job {job_id} não completou em {_POLL_MAX*_POLL_S:.0f}s")

    # 4) baixa o mp4 pro bucket local
    with urllib.request.urlopen(url, timeout=300) as r:
        dados = r.read()
    if dados[4:8] != b"ftyp":
        raise RuntimeError(f"download de {url[:120]} não é mp4")
    return {
        "bytes": dados, "mime": "video/mp4", "modelo": modelo,
        "custo_creditos": config.get("custo_estimado"),
        "meta": {"url_provider": url, "job_id": job_id, "asset_origem": asset["id"],
                 "modelo_video": modelo, "image_to_video": True, "orquestrador": "http_direto"},
    }


def _primeiro_uuid(texto: str) -> str | None:
    m = _UUID.search(texto or "")
    return m.group(0) if m else None


def _job_id(gen: dict) -> str | None:
    """Extrai o job id do generate_video (results[0].id, id, ou UUID no texto)."""
    if gen.get("results"):
        return gen["results"][0].get("id")
    return gen.get("id") or gen.get("job_id") or _primeiro_uuid(gen.get("_text", ""))


if __name__ == "__main__":  # self-check offline: parsing de SSE + job id, sem rede
    sse = 'event: message\ndata: {"result":{"content":[{"type":"text","text":"{\\"media_id\\":\\"m1\\"}"}]}}\n'
    d = _sse_json(sse)
    assert d["result"]["content"][0]["text"] == '{"media_id":"m1"}', "SSE parse falhou"
    assert _job_id({"results": [{"id": "j9"}]}) == "j9"
    assert _job_id({"job_id": "jx"}) == "jx"
    assert _job_id({}) is None
    # prompt mantém o guardrail
    assert "NÃO invente" in _prompt({"prompt": "dolly suave"})
    print("higgsfield_http OK — SSE parse + job_id + guardrail")
