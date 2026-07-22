"""Cascata de LLM: proxy LiteLLM (cloud) → Ollama local → regras determinísticas."""
import pytest

from shared_core.ai import classificacao as c
from shared_core.ai import llm_proxy, local_llm


def test_local_llm_offline_devolve_none(monkeypatch):
    monkeypatch.setenv("OLLAMA_URL", "http://127.0.0.1:59999")  # porta morta
    assert local_llm.completar("oi", max_tokens=5) is None
    assert local_llm.disponivel() is False


def test_proxy_offline_devolve_none(monkeypatch):
    monkeypatch.setenv("LITELLM_URL", "http://127.0.0.1:59998")
    assert llm_proxy.completar("oi", max_tokens=5) is None
    assert llm_proxy.disponivel() is False


def test_proxy_ok_e_a_camada_1(monkeypatch):
    monkeypatch.setattr(llm_proxy, "completar", lambda *a, **k: '{"padrao":"luxo","tipo":"casa"}')
    texto, fonte = c._texto_do_llm({"descricao": "cobertura"}, "classifique")
    assert fonte == "proxy" and "luxo" in texto


def test_proxy_fora_cai_no_ollama(monkeypatch):
    monkeypatch.setattr(llm_proxy, "completar", lambda *a, **k: None)                    # proxy fora
    monkeypatch.setattr(local_llm, "completar", lambda *a, **k: '{"padrao":"rural"}')    # ollama responde
    texto, fonte = c._texto_do_llm({"descricao": "sítio"}, "classifique")
    assert fonte == "ollama-fallback" and "rural" in texto


def test_ambos_fora_cai_nas_regras(monkeypatch):
    monkeypatch.setattr(llm_proxy, "completar", lambda *a, **k: None)
    monkeypatch.setattr(local_llm, "completar", lambda *a, **k: None)
    r = c._anthropic({"descricao": "apartamento simples", "preco": "200000"})
    assert r["fonte"] == "regras" and r["padrao"] in c.PADROES and r["tipo"] in c.TIPOS


def test_saida_ilegivel_cai_nas_regras(monkeypatch):
    monkeypatch.setattr(llm_proxy, "completar", lambda *a, **k: "desculpe, não sei")
    r = c._anthropic({"descricao": "casa de campo"})
    assert r["fonte"] == "proxy-ilegivel" and r["padrao"] in c.PADROES


@pytest.mark.skipif(not llm_proxy.disponivel(), reason="LiteLLM proxy fora")
def test_integracao_proxy_real():
    import os
    if not os.environ.get("LITELLM_MASTER_KEY"):
        pytest.skip("sem LITELLM_MASTER_KEY no ambiente")
    t = llm_proxy.completar('Responda só JSON: {"padrao":"luxo"}', model="analise", max_tokens=30)
    assert t and "{" in t
