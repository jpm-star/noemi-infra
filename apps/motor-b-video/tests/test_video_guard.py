"""Prompt 2 (QA vídeo): requisição de vídeo SEM imagem falha graciosamente —
guard levanta erro tratável ANTES da chamada externa, nunca estoura 500 no worker.

Cobre os sanitizadores do higgsfield_http (image-to-video): sem imagem_url e
media_id nulo → RuntimeError claro (o worker cai no retry/failed, não em 500).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packages"))
from shared_core.ai.providers import higgsfield_http as hh


def test_sem_imagem_levanta_erro_tratavel():
    # image-to-video sem imagem_url: guard levanta ANTES de qualquer rede
    with pytest.raises(RuntimeError, match="imagem_url"):
        hh.generate({"id": "a1", "owner": "x"}, {"prompt": "casa bonita"})


def test_media_id_regex_do_texto_humano():
    # media_import_url às vezes volta texto humano com o UUID no meio — extrai
    uuid = "20c13d1b-664f-4098-b769-52579b685228"
    assert hh._primeiro_uuid(f"Pass media_id {uuid} as medias[].value") == uuid
    assert hh._primeiro_uuid("sem uuid aqui") is None


def test_generate_video_aninha_params():
    # o generate_video exige args em {"params": {...}} — a montagem preserva isso
    # (regressão do 'invalid arguments'): checa que o builder usa a chave params.
    import inspect
    fonte = inspect.getsource(hh.generate)
    assert '"params"' in fonte, "generate_video precisa aninhar args em params"
