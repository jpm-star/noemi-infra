"""Bloco 1: fallback local (Ollama) na cascata Anthropic → Ollama → regras."""
import pytest

from shared_core.ai import classificacao as c
from shared_core.ai import local_llm


def test_local_llm_offline_devolve_none(monkeypatch):
    # Ollama inacessível → completar() não crasha, devolve None (chamador degrada)
    monkeypatch.setenv("OLLAMA_URL", "http://127.0.0.1:59999")  # porta morta
    assert local_llm.completar("oi", max_tokens=5) is None
    assert local_llm.disponivel() is False


def test_cascata_anthropic_falha_usa_ollama(monkeypatch):
    # Anthropic falha (sem SDK/key no _texto_do_llm) e Ollama responde um JSON
    monkeypatch.setattr(local_llm, "completar", lambda *a, **k: '{"padrao":"luxo","tipo":"casa"}')
    texto, fonte = c._texto_do_llm({"descricao": "cobertura"}, "classifique")
    # com ANTHROPIC_API_KEY ausente o primário falha e cai no local
    assert fonte == "ollama-fallback" and "luxo" in texto


def test_cascata_ambos_fora_cai_nas_regras(monkeypatch):
    monkeypatch.setattr(local_llm, "completar", lambda *a, **k: None)  # Ollama fora também
    r = c._anthropic({"descricao": "apartamento simples", "preco": "200000"})
    assert r["fonte"] == "regras"
    assert r["padrao"] in c.PADROES and r["tipo"] in c.TIPOS  # regras sempre válidas


def test_ollama_saida_ilegivel_cai_nas_regras(monkeypatch):
    monkeypatch.setattr(local_llm, "completar", lambda *a, **k: "desculpe, não sei responder")
    r = c._anthropic({"descricao": "casa de campo"})
    assert r["fonte"] == "ollama-fallback-ilegivel"
    assert r["padrao"] in c.PADROES


@pytest.mark.skipif(not local_llm.disponivel(), reason="Ollama não está rodando")
def test_integracao_ollama_real():
    t = local_llm.completar('Responda só JSON: {"padrao":"luxo"}', max_tokens=30)
    assert t and "{" in t
