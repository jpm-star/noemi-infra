"""Fase A: image-to-video real — a foto do imóvel é o frame de origem, não texto.

Cobre a correção da causa raiz do "sapo com asas": com imagem_url, a instrução
manda ANIMAR a foto e PROÍBE inventar imóvel; sem, cai no fallback texto→vídeo.
"""
from shared_core.ai.providers import higgsfield_video as hv

_ASSET = {"id": "a1", "produto": "motor-b", "metadata": {}}


def test_com_imagem_vira_image_to_video():
    cfg = {"imagem_url": "https://videoshiggs.noemi.digital/api/assets/a1/file",
           "prompt": "dolly suave, golden hour", "duration": 8}
    instr = hv._instrucao(_ASSET, cfg)
    assert "IMAGE-TO-VIDEO" in instr
    assert cfg["imagem_url"] in instr           # a foto real entra na chamada
    assert "NÃO gere um imóvel" in instr        # guardrail anti-alucinação
    assert "kling" in instr.lower()             # modelo fixado


def test_model_do_config_sobrepoe_default():
    instr = hv._instrucao(_ASSET, {"imagem_url": "http://x/a", "model": "veo"})
    assert "veo" in instr.lower() and "kling" not in instr.lower()


def test_sem_imagem_cai_no_fallback_texto():
    instr = hv._instrucao(_ASSET, {"prompt": "vídeo do imóvel"})
    assert "IMAGE-TO-VIDEO" not in instr
    assert "Descrição do vídeo" in instr


def test_worker_monta_url_so_para_imagem():
    import worker
    img = {"id": "x9", "mime": "image/jpeg"}
    vid = {"id": "v9", "mime": "video/mp4"}
    assert worker._imagem_url(img).endswith("/api/assets/x9/file")
    assert worker._imagem_url(img).startswith("https://")
    assert worker._imagem_url(vid) is None      # vídeo de origem não vira frame único
