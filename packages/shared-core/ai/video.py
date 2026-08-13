"""Interface FIXA de geração de vídeo: video.generate(asset, config).

Nenhum app chama provider pelo nome (higgsfield/gemini/kling) — só esta função.

>>> PONTO DE TROCA mock → real (ver README raiz): MOCK_MODE=false no ambiente.
>>> ORQUESTRADOR (real): "http" (default) = MCP HTTP direto, custo Anthropic R$0;
>>> "agent" = loop antigo via Messages API (Opus, caro — só se precisar).

DOIS PROVIDERS REAIS (13/08/2026): Higgsfield (Kling) e Gemini (Veo). Ver
`escolher_provider` pra regra de qual roda.

Contrato de retorno (dict): bytes, mime, modelo, custo_creditos, meta.
"""
from __future__ import annotations

import os

PROVIDERS = ("higgsfield", "gemini")

# Default DELIBERADAMENTE igual ao comportamento anterior. Ligar um provider novo é
# decisão comercial (custo por vídeo triplica) — não pode acontecer porque alguém
# fez deploy sem ler o CHANGELOG.
PADRAO = "higgsfield"


def _custo_usd(provider: str, config: dict) -> float:
    """Estimativa em US$ deste job em cada provider. Usada só pelo modo 'custo'."""
    if provider == "gemini":
        from shared_core.ai.providers import gemini_video
        return gemini_video.custo_estimado_usd(config)
    from shared_core.ai.providers import gemini_video, higgsfield_http
    creditos = higgsfield_http._custo_creditos(config.get("model") or "kling3_0")
    return creditos * gemini_video._USD_POR_CREDITO


def escolher_provider(config: dict | None = None) -> str:
    """Qual provider roda este job. Precedência: config > env > padrão.

        config["provider"] = "gemini"   -> escolha MANUAL, por job (vence tudo)
        VIDEO_PROVIDER = "gemini"       -> escolha manual, por deploy
        VIDEO_PROVIDER = "custo"        -> o mais barato pro job (ver abaixo)
        (nada)                          -> higgsfield, o comportamento de sempre

    Sobre o modo "custo" — a comparação certa é POR CLIPE, não por segundo:

        Higgsfield Kling ..... 5s  x  (7,5 créd. x US$0,039)  =  US$0,29
        Veo 3.1 Lite ......... 8s  x  US$0,05/s               =  US$0,40
        Veo 3.1 Fast ......... 8s  x  US$0,15/s               =  US$1,20
        Veo 3.1 padrão ....... 8s  x  US$0,40/s               =  US$3,20

    O Lite é mais barato POR SEGUNDO que o Kling (US$0,05 vs US$0,058) e ainda assim
    sai mais caro POR VÍDEO, porque o Veo entrega 8s e o Kling 5s — e o Motor B publica
    um clipe, não uma hora de vídeo. Comparar US$/s teria escolhido errado.
    (Duração de 8s MEDIDA numa geração real em 13/08/2026, não suposta.)

    Ou seja: hoje "custo" escolhe Higgsfield sempre. O modo existe porque preço de
    modelo muda toda semana — quando mudar, a conta se vira sozinha via GEMINI_USD_S.

    O valor do Gemini não é desconto: é áudio nativo (Kling não tem) e um caminho vivo
    quando o OAuth do Higgsfield está fora. Pra isso, escolha manual.
    """
    cfg = config or {}
    escolha = (str(cfg.get("provider") or os.environ.get("VIDEO_PROVIDER") or PADRAO)
               .strip().lower())
    if escolha == "custo":
        disponiveis = [p for p in PROVIDERS if _configurado(p)]
        if not disponiveis:
            return PADRAO           # nenhum configurado: deixa o provider dar o erro nomeado
        return min(disponiveis, key=lambda p: _custo_usd(p, cfg))
    if escolha not in PROVIDERS:
        raise ValueError(f"VIDEO_PROVIDER inválido: {escolha!r} (use {', '.join(PROVIDERS)} ou 'custo')")
    return escolha


def _configurado(provider: str) -> bool:
    if provider == "gemini":
        from shared_core.ai.providers import gemini_video
        return gemini_video.configurado()
    # Higgsfield: o token vive em arquivo com refresh automático; considerar sempre
    # disponível mantém o comportamento anterior (ele já falha com erro nomeado).
    return True


def generate(asset: dict, config: dict) -> dict:
    if os.environ.get("MOCK_MODE", "true").lower() != "false":
        from shared_core.ai.providers import mock_video
        return mock_video.generate(asset, config)
    if escolher_provider(config) == "gemini":
        from shared_core.ai.providers import gemini_video
        return gemini_video.generate(asset, config)
    # Real: HTTP direto por padrão (sem loop Anthropic). "agent" reativa o antigo.
    if os.environ.get("ORQUESTRADOR", "http").lower() == "agent":
        from shared_core.ai.providers import higgsfield_video
        return higgsfield_video.generate(asset, config)
    from shared_core.ai.providers import higgsfield_http
    return higgsfield_http.generate(asset, config)


if __name__ == "__main__":  # self-check offline
    for v in ("VIDEO_PROVIDER", "GEMINI_API_KEY"):
        os.environ.pop(v, None)
    # sem nada configurado, o comportamento é o DE SEMPRE
    assert escolher_provider() == "higgsfield"
    assert escolher_provider({}) == "higgsfield"
    # escolha manual por job vence o env
    os.environ["VIDEO_PROVIDER"] = "higgsfield"
    assert escolher_provider({"provider": "gemini"}) == "gemini"
    # escolha manual por deploy
    os.environ["VIDEO_PROVIDER"] = "gemini"
    assert escolher_provider() == "gemini"
    # valor inválido falha ALTO (não cai calado no default: seria vídeo caro sem aviso)
    os.environ["VIDEO_PROVIDER"] = "veo"
    try:
        escolher_provider()
        raise AssertionError("deveria recusar provider inválido")
    except ValueError as e:
        assert "veo" in str(e)
    # modo custo: HOJE o Higgsfield ganha em todos os modelos do Veo, inclusive o Lite
    os.environ["VIDEO_PROVIDER"] = "custo"
    os.environ["GEMINI_API_KEY"] = "fake-pra-self-check"
    assert escolher_provider({}) == "higgsfield"
    assert escolher_provider({"model": "veo-3.1-lite-generate-preview"}) == "higgsfield"
    # ...mas a comparação PRECISA discriminar, senão este teste não prova nada: uma
    # função que devolve sempre "higgsfield" passaria mesmo comparando errado. Baixando
    # o preço do Veo por env, a escolha TEM que virar.
    os.environ["GEMINI_USD_S"] = "0.001"          # US$0,008 o clipe de 8s
    assert escolher_provider({}) == "gemini", "o modo custo não está comparando de verdade"
    os.environ.pop("GEMINI_USD_S")
    # e sem chave do Gemini o modo custo nem considera ele
    os.environ.pop("GEMINI_API_KEY")
    os.environ["GEMINI_USD_S"] = "0.001"
    assert escolher_provider({}) == "higgsfield", "provider sem chave não pode ser escolhido"
    os.environ.pop("GEMINI_USD_S")
    os.environ.pop("VIDEO_PROVIDER")
    print(f"video OK — {len(PROVIDERS)} providers, padrão={PADRAO}, manual vence env, "
          "inválido falha alto, modo custo escolhe Kling hoje E discrimina quando o preço muda")
