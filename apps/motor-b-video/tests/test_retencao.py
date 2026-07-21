"""Retenção de disco: purga origem de job terminal velho, preserva vídeo."""
import json

import jobs
import retention
from shared_core import storage
from shared_core.storage.db import conn, data_dir

PNG = bytes.fromhex("89504e470d0a1a0a")  # cabeçalho só; conteúdo não importa aqui


def _job_terminal_velho(dias_atras: int) -> tuple[dict, dict]:
    origem = storage.create_asset("t", jobs.PRODUTO, "image/jpeg", b"origem-bytes")
    video = storage.create_asset("t", jobs.PRODUTO, "video/mp4", b"video-bytes-final")
    job = jobs.criar(origem["id"])
    jobs.atualizar(job["id"], "completed", asset_video=video["id"])
    velho = f"2000-01-0{max(1, 9 - dias_atras)}T00:00:00+00:00"  # bem no passado
    with conn() as c:
        c.execute("UPDATE jobs SET atualizado_em=? WHERE id=?", (velho, job["id"]))
    return origem, video


def test_purga_origem_velha_preserva_video():
    origem, video = _job_terminal_velho(dias_atras=1)
    assert storage.asset_file(origem).exists()
    resumo = retention.limpar(dias=30, obs_max_mb=999999)
    assert resumo["origens_purgadas"] >= 1
    # arquivo da origem sumiu, linha fica (FK), marcada
    assert not storage.asset_file(origem).exists()
    assert storage.get_asset(origem["id"])["metadata"]["arquivo_removido"] is True
    # vídeo final intacto
    assert storage.asset_file(video).exists()


def test_job_recente_nao_e_purgado():
    origem = storage.create_asset("t", jobs.PRODUTO, "image/jpeg", b"recente")
    job = jobs.criar(origem["id"])
    jobs.atualizar(job["id"], "completed",
                   asset_video=storage.create_asset("t", jobs.PRODUTO, "video/mp4", b"v")["id"])
    retention.limpar(dias=30, obs_max_mb=999999)
    assert storage.asset_file(origem).exists()  # job de hoje não é tocado


def test_rotaciona_obs_grande():
    obs = data_dir() / "obs.jsonl"
    obs.write_text("x" * (2 * 1024 * 1024))  # 2MB
    assert retention.limpar(dias=30, obs_max_mb=1)["obs_rotacionado"] is True
    rotacionado = data_dir() / "obs.jsonl.1"
    assert rotacionado.exists() and rotacionado.stat().st_size >= 2 * 1024 * 1024  # o 2MB foi movido
    # a própria retenção loga seu resultado depois de rotacionar → obs.jsonl
    # renasce pequeno. É o comportamento certo: novas escritas vão pro arquivo fresco.
    if obs.exists():
        assert obs.stat().st_size < 4096
