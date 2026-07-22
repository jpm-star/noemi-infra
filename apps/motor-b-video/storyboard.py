"""Storyboarding por cenas (Motor B — item 4, fecha a Onda 1).

Quebra o imóvel numa sequência de cenas (fachada → sala → cozinha → suíte), gera
um clipe curto por cena via video.generate (mesmo toggle mock/real), encadeando o
ÚLTIMO frame de uma cena como START frame da próxima — walkthrough contínuo — e
concatena tudo num vídeo único.

O encadeamento start/end é o mecanismo REAL do Higgsfield (first/last-frame
conditioning). Em MOCK_MODE a orquestração roda igual (extrai o último frame e o
passa adiante em `_start_frame_path`); só o generate é simulado. Quando o
image-to-video real (Fase 2) anexar a imagem/start-frame, o encadeamento já está
pronto — nada muda aqui.

Reuso puro (sem sistema novo): Auto Director (movimento por cômodo) vem do
prompt_builder; a geração é o video.generate de sempre; o corte/concat é o FFmpeg
do pos.py. Corte seco basta — o frame casado JÁ dá continuidade (é o ponto do
end→start); xfade é polimento opcional, não o mecanismo.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pos
import prompt_builder
import templates

# shared_core (classificacao/video/log_span) é importado TARDE dentro das funções:
# mantém o módulo importável standalone (self-check de planejamento puro roda sem
# packages/ no path) e casa com o padrão de import tardio do resto do app.

# roteiro default quando o cliente sobe UMA foto e pede walkthrough
_PLANO_PADRAO = ["fachada", "sala", "cozinha", "suite"]
DUR_CENA = 4  # segundos por cena (walkthrough: cenas curtas; 4 cenas ≈ 16s)


def eh_storyboard(config: dict) -> bool:
    """True se o job pede walkthrough: flag `storyboard` ou lista `cenas`."""
    cenas = config.get("cenas")
    return bool(config.get("storyboard")) or (isinstance(cenas, list) and len(cenas) >= 1)


def planejar_cenas(config: dict, origem_id: str) -> list[dict]:
    """Ordena as cenas. Explícitas (config['cenas']=[{comodo,asset_id},...]) vencem;
    senão deriva o roteiro default sobre a foto única de origem. Função pura."""
    cenas = config.get("cenas")
    if isinstance(cenas, list) and cenas:
        return [{"comodo": (c.get("comodo") or f"cena {i + 1}"),
                 "asset_id": c.get("asset_id") or origem_id, "ordem": i}
                for i, c in enumerate(cenas)]
    return [{"comodo": comodo, "asset_id": origem_id, "ordem": i}
            for i, comodo in enumerate(_PLANO_PADRAO)]


def _plano_da_cena(asset: dict, cena: dict, base: dict, brand: dict,
                   start_frame_path: str | None, asset_file) -> dict:
    """cfg da cena: classifica → template → prompt COM o cômodo (Auto Director pega
    o movimento certo). `_start_frame_path` é o elo com a cena anterior (seam do
    Higgsfield real; efêmero, nunca persistido)."""
    from shared_core.ai import classificacao
    entrada = {**base, "comodo": cena["comodo"], "asset_origem": asset["id"],
               "owner": asset.get("owner"), "_imagem_path": str(asset_file(asset))}
    if start_frame_path:
        entrada["_start_frame_path"] = start_frame_path
    clas = classificacao.classificar(entrada)
    template = templates.escolher_template(clas, base.get("template"))
    plano = prompt_builder.construir_prompt(clas, template, entrada, brand=brand)
    dur = int(base.get("duracao_cena") or DUR_CENA)
    return {**{k: v for k, v in base.items() if not k.startswith("_")},
            "prompt": plano["prompt"], "duration": dur,
            "aspect_ratio": plano["aspect_ratio"], "comodo": cena["comodo"],
            "movimento": plano["movimento"],
            **({"_start_frame_path": start_frame_path} if start_frame_path else {})}


def gerar_walkthrough(origem: dict, cfg: dict, brand: dict, jid: str,
                      *, get_asset, asset_file) -> dict:
    """Gera o walkthrough completo. Devolve um out-dict no MESMO formato de
    video.generate (bytes/mime/modelo/custo_creditos/meta), pra fluir igual no
    worker. `get_asset`/`asset_file` são injetados (evita import circular c/ storage
    no caminho de teste)."""
    from shared_core.ai import video
    from shared_core.obs import log_span
    cenas = planejar_cenas(cfg, origem["id"])
    aspect = cfg.get("aspect_ratio") or "9:16"
    w, h = pos._ALVO.get(aspect, pos._ALVO["9:16"])

    clips: list[bytes] = []
    custo = 0
    modelos: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        start_frame_path: str | None = None  # 1ª cena usa a própria foto
        for cena in cenas:
            asset = get_asset(cena["asset_id"]) or origem
            plano = _plano_da_cena(asset, cena, cfg, brand, start_frame_path, asset_file)
            out = video.generate(asset, plano)
            clips.append(out["bytes"])
            custo += out.get("custo_creditos") or 0
            modelos.append(out.get("modelo", "?"))
            # encadeia: último frame desta cena → START da próxima
            try:
                frame_png = pos.extrair_frame(out["bytes"], fim=True)
                fp = Path(tmp) / f"elo_{cena['ordem']}.png"
                fp.write_bytes(frame_png)
                start_frame_path = str(fp)
            except pos.PosErro as e:
                # sem o elo, a próxima cena começa da própria foto (degrada, não quebra)
                log_span("motor_b.storyboard", job=jid, ok=False, etapa="elo",
                         cena=cena["comodo"], erro=e.mensagem)
                start_frame_path = None
        walkthrough = pos.concatenar(clips, w, h)

    modelo = modelos[0] if len(set(modelos)) == 1 else "mixed"
    log_span("motor_b.storyboard", job=jid, ok=True, cenas=[c["comodo"] for c in cenas],
             n=len(cenas), aspect=aspect)
    return {
        "bytes": walkthrough,
        "mime": "video/mp4",
        "modelo": f"{modelo}/storyboard",
        "custo_creditos": custo,
        "meta": {"storyboard": True, "cenas": [c["comodo"] for c in cenas],
                 "n_cenas": len(cenas), "aspect": aspect},
    }


if __name__ == "__main__":  # self-check: planejamento puro (sem gerar vídeo)
    p = planejar_cenas({"storyboard": True}, "asset1")
    assert [c["comodo"] for c in p] == _PLANO_PADRAO
    assert all(c["asset_id"] == "asset1" for c in p)
    e = planejar_cenas({"cenas": [{"comodo": "loft", "asset_id": "a2"}]}, "asset1")
    assert e[0]["comodo"] == "loft" and e[0]["asset_id"] == "a2"
    assert eh_storyboard({"storyboard": True}) and not eh_storyboard({})
    print("storyboard OK — plano default:", [c["comodo"] for c in p])
