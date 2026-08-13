"""Provider de vídeo via Gemini (Veo) — a 2ª opção ao lado do Higgsfield.

MESMO CONTRATO do higgsfield_http: recebe (asset, config) e devolve
{bytes, mime, modelo, custo_creditos, meta}. Quem chama é `video.generate`;
nenhum app conhece este módulo pelo nome.

DUAS DIFERENÇAS REAIS PRO HIGGSFIELD (não são detalhe de implementação):

1. A FOTO VAI INLINE, NÃO POR URL. O Higgsfield importa a imagem por URL
   (`media_import_url`) — por isso o Motor B publica o asset e manda o link. O Veo
   quer os BYTES em base64 dentro do payload. Então aqui a foto é baixada e embutida.
   Consequência prática: este caminho funciona mesmo sem MOTOR_B_PUBLIC_URL resolvendo
   de fora, e é o único que funciona se o DNS do bucket cair.

2. O VEO GERA ÁUDIO NATIVO. Kling não. Se um dia o Motor B quiser trilha/voz vinda do
   modelo em vez do pós-processamento, é por aqui.

CUSTO — o Gemini NÃO é o barato (medido, não estimado):
    Higgsfield kling3_0 ......... 7,5 créditos x US$0,039 = US$0,29 por clipe de 5s
    Veo 3.1 Lite (720p) ......... US$0,05/s               = US$0,25   <- o único mais barato
    Veo 3.1 Fast ................ US$0,15/s               = US$0,75
    Veo 3.1 padrão (1080p) ...... US$0,40/s               = US$2,00
Ou seja: no modelo PADRÃO o Gemini custa 7x o Higgsfield, e só o Lite ganha no preço.
Por isso `video.escolher_provider` no modo "custo" compara por MODELO, não por
fornecedor — e por isso o default do Motor B continua Higgsfield. O valor do Gemini
não é desconto: é áudio nativo (Kling não tem) e um caminho vivo quando o OAuth do
Higgsfield cai. Preços da tabela oficial em 13/08/2026; override por env.

RESOLUÇÃO MUDA O PREÇO e não é modelada aqui: o Lite a 720p custa US$0,05/s, mas
subir a resolução sobe o valor. Como o Motor B entrega 1080x1920 vertical, tratar o
Lite como US$0,05/s é o piso — se o Veo cobrar mais por 1080p, o número real fica
acima. Medir na 1ª fatura real e ajustar GEMINI_USD_S.
"""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request

from shared_core.ai.cost import track_cost

_BASE = os.environ.get("GEMINI_API_BASE", "https://generativelanguage.googleapis.com/v1beta")
_MODELO = os.environ.get("GEMINI_VIDEO_MODELO", "veo-3.1-generate-preview")
_POLL_MAX = int(os.environ.get("GEMINI_POLL_MAX", "60"))     # 60 x 10s = 10min
_POLL_S = float(os.environ.get("GEMINI_POLL_S", "10"))
_TIMEOUT = int(os.environ.get("GEMINI_TIMEOUT_S", "120"))

# US$ por SEGUNDO de vídeo. Fonte: ai.google.dev/gemini-api/docs/pricing (13/08/2026).
# Chave = modelo; o fallback é o mais CARO conhecido de propósito: subestimar custo de
# um modelo novo faz o teto diário deixar passar gasto que ninguém autorizou.
# CONFERIDO CONTRA A CONTA (13/08/2026): estes 3 são os que a chave da JPOS enxerga
# em models.list. Os veo-3.0 NÃO aparecem — tabela com modelo inexistente é armadilha:
# alguém configura, toma 404, e culpa o código.
_USD_POR_S = {
    "veo-3.1-generate-preview": 0.40,        # padrão, 1080p
    "veo-3.1-fast-generate-preview": 0.15,
    "veo-3.1-lite-generate-preview": 0.05,   # 720p — o único mais barato que o Kling
}
_USD_POR_S_DESCONHECIDO = 0.60

# Quanto vale 1 crédito Higgsfield em dólar (plano PLUS anual). Serve pra expressar o
# custo do Gemini na MESMA unidade que o resto do sistema já contabiliza — senão o teto
# diário e o histórico de custo passam a somar laranja com banana.
_USD_POR_CREDITO = float(os.environ.get("HIGGS_CREDITO_USD", "0.039"))


def usd_por_segundo(modelo: str | None = None) -> float:
    m = modelo or _MODELO
    env = os.environ.get("GEMINI_USD_S")
    if env:
        try:
            return float(env)
        except ValueError:
            pass
    return _USD_POR_S.get(m, _USD_POR_S_DESCONHECIDO)


# MEDIDO, não suposto (geração real em 13/08/2026, veo-3.1-lite): o Veo devolveu
# 720x1280 com 8,000s de duração. Como este provider NÃO manda parâmetro de duração,
# quem decide é o modelo — então o custo TEM que sair daqui, e não do config.
#
# Isto começou como bug meu: eu calculava o custo por `config["duration"]`. Um caller
# pedindo duration=5 veria "US$0,25" e a fatura viria US$0,40, porque o vídeo sai com
# 8s de qualquer jeito. Estimativa de custo que obedece um campo que o fornecedor
# ignora não é estimativa, é ficção — e o modo "custo" decidiria com base nela.
_DUR_ENTREGUE_S = 8.0


def custo_estimado_usd(config: dict) -> float:
    """Quanto ESTE job custaria aqui. É o número que a escolha por custo compara.

    Ignora `config["duration"]` de propósito: ver `_DUR_ENTREGUE_S`. Se um dia o
    provider passar a mandar duração pra API, este é o lugar que muda junto.
    """
    return usd_por_segundo(config.get("model")) * _DUR_ENTREGUE_S


def configurado() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY", "").strip())


def _chave() -> str:
    k = os.environ.get("GEMINI_API_KEY", "").strip()
    if not k:
        raise RuntimeError("gemini_video exige GEMINI_API_KEY no ambiente")
    return k


def _req(url: str, *, dados: bytes | None = None, metodo: str = "GET") -> bytes:
    req = urllib.request.Request(url, data=dados, method=metodo, headers={
        "x-goog-api-key": _chave(),
        "Content-Type": "application/json",
        "User-Agent": "noemi-motor-b/1.0",
    })
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
        return r.read()


def _foto_inline(imagem_url: str) -> dict:
    """Baixa a foto e devolve o bloco inlineData que o Veo espera.

    O mime sai do header da resposta, não da extensão da URL: o bucket do Motor B
    serve por /api/assets/<id>/file, sem extensão nenhuma — adivinhar por sufixo
    daria 'image/file'.
    """
    with urllib.request.urlopen(imagem_url, timeout=_TIMEOUT) as r:
        dados = r.read()
        mime = (r.headers.get("Content-Type") or "image/jpeg").split(";")[0].strip()
    if not mime.startswith("image/"):
        raise RuntimeError(f"imagem_url devolveu {mime!r}, não uma imagem")
    return {"inlineData": {"mimeType": mime, "data": base64.b64encode(dados).decode()}}


def _prompt(config: dict) -> str:
    """Mesmo guardrail anti-alucinação do caminho Higgsfield. O modelo muda; a regra
    de não inventar cômodo que não está na foto é do PRODUTO, não do fornecedor."""
    base = config.get("prompt", "movimento de câmera sutil e cinematográfico")
    return (f"{base} Mantenha-se 100% fiel à imagem de origem: NÃO invente cômodos, "
            "móveis, estruturas ou acabamentos que não aparecem na foto.")


@track_cost("gemini")
def generate(asset: dict, config: dict) -> dict:
    modelo = config.get("model") or _MODELO
    instancia: dict = {"prompt": _prompt(config)}
    imagem_url = config.get("imagem_url")
    if imagem_url:
        instancia["image"] = _foto_inline(imagem_url)

    # aspectRatio: o Veo aceita só 16:9 e 9:16. O Motor B trava 9:16; qualquer outra
    # coisa é erro de configuração e vira 400 — melhor recusar aqui, com nome.
    aspecto = config.get("aspect_ratio", "9:16")
    if aspecto not in ("16:9", "9:16"):
        raise RuntimeError(f"Veo aceita 16:9 ou 9:16, não {aspecto!r}")

    corpo = json.dumps({"instances": [instancia],
                        "parameters": {"aspectRatio": aspecto}}).encode()
    op = json.loads(_req(f"{_BASE}/models/{modelo}:predictLongRunning",
                         dados=corpo, metodo="POST"))
    nome_op = op.get("name")
    if not nome_op:
        raise RuntimeError(f"predictLongRunning sem operation name: {str(op)[:200]}")

    uri = None
    for _ in range(_POLL_MAX):
        st = json.loads(_req(f"{_BASE}/{nome_op}"))
        if st.get("error"):
            raise RuntimeError(f"Veo falhou: {str(st['error'])[:200]}")
        if st.get("done"):
            amostras = (((st.get("response") or {}).get("generateVideoResponse") or {})
                        .get("generatedSamples") or [])
            if not amostras:
                # done sem amostra = filtro de segurança do Google na maioria das vezes.
                # Erro nomeado, não KeyError: o operador precisa saber que o vídeo foi
                # recusado, não que o código quebrou.
                raise RuntimeError(f"Veo terminou sem vídeo (filtro?): {str(st)[:200]}")
            uri = (amostras[0].get("video") or {}).get("uri")
            break
        time.sleep(_POLL_S)
    if not uri:
        raise TimeoutError(f"Veo não completou em {_POLL_MAX * _POLL_S:.0f}s")

    dados = _req(uri)
    if dados[4:8] != b"ftyp":
        raise RuntimeError(f"download de {uri[:120]} não é mp4")

    usd = custo_estimado_usd({**config, "model": modelo})
    return {
        "bytes": dados, "mime": "video/mp4", "modelo": modelo,
        # na MESMA unidade do resto do sistema (crédito Higgsfield equivalente), pra
        # o teto diário e o histórico continuarem somando a mesma coisa
        "custo_creditos": round(usd / _USD_POR_CREDITO, 2),
        "meta": {"url_provider": uri, "operacao": nome_op, "asset_origem": asset["id"],
                 "modelo_video": modelo, "image_to_video": bool(imagem_url),
                 "provider": "gemini", "custo_usd": round(usd, 4),
                 "audio_nativo": True},
    }


if __name__ == "__main__":  # self-check offline (sem rede, sem chave)
    os.environ.pop("GEMINI_API_KEY", None)
    assert configurado() is False
    # 8s de Veo 3.1 padrão = US$3,20 — bem mais caro que o Higgsfield (US$0,29)
    assert abs(custo_estimado_usd({}) - 3.20) < 1e-9, custo_estimado_usd({})
    assert custo_estimado_usd({}) > 7.5 * _USD_POR_CREDITO
    # e o `duration` do caller NÃO altera o custo (o Veo entrega 8s de todo jeito)
    assert custo_estimado_usd({"duration": 5}) == custo_estimado_usd({"duration": 8})
    # modelo desconhecido usa o teto CARO (nunca subestima)
    assert usd_por_segundo("veo-9-inexistente") == _USD_POR_S_DESCONHECIDO
    # o Lite é o único que ganha do Higgsfield no preço — prova que a tabela discrimina
    lite = custo_estimado_usd({"model": "veo-3.1-lite-generate-preview"})
    assert abs(lite - 0.40) < 1e-9, lite          # 8s x US$0,05 = US$0,40 (fatura real)
    assert custo_estimado_usd({}) > lite
    # duration lixo não explode nem muda nada
    assert custo_estimado_usd({"duration": "abc"}) == custo_estimado_usd({})
    # sem chave, qualquer chamada de rede falha com mensagem nomeada
    try:
        _chave()
        raise AssertionError("deveria ter exigido a chave")
    except RuntimeError as e:
        assert "GEMINI_API_KEY" in str(e)
    # guardrail sobrevive
    assert "NÃO invente" in _prompt({"prompt": "dolly suave"})
    print(f"gemini_video OK — inerte sem chave; {len(_USD_POR_S)} modelos precificados; "
          f"custo de 1 clipe ({_DUR_ENTREGUE_S:.0f}s): padrão US$ {custo_estimado_usd({}):.2f} · "
          f"lite US$ {lite:.2f}; duration do caller não mexe no custo")
