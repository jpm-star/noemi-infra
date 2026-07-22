"""Robustez do parse da classificação real (LLM como código) — sem rede."""
from shared_core.ai import classificacao as c


def test_extrair_json_sem_bloco_nao_crasha():
    # antes: re.search(...).group(0) → AttributeError. agora: None.
    assert c._extrair_json("desculpe, não posso ajudar") is None
    assert c._extrair_json("") is None
    assert c._extrair_json(None) is None


def test_extrair_json_malformado_vira_none():
    assert c._extrair_json('{"padrao": "luxo",}') is None  # vírgula final
    assert c._extrair_json("texto {não json} fim") is None


def test_extrair_json_valido():
    assert c._extrair_json('bla {"padrao":"luxo"} bla') == {"padrao": "luxo"}


def test_validar_coage_enum_invalido_pra_regra():
    # LLM devolve padrão fora do domínio → cai na classificação por regras
    d = c._validar({"padrao": "moderno", "tipo": "kitnet"}, {"descricao": "apartamento simples"})
    assert d["padrao"] in c.PADROES and d["tipo"] in c.TIPOS
    assert d["fonte"] == "anthropic"


def test_validar_duracao_fora_da_faixa_clampa():
    d = c._validar({"duracao": 999}, {"descricao": "casa"})
    assert 8 <= d["duracao"] <= 15


def test_validar_campos_ausentes_usam_regra():
    # só padrao veio; tom/duracao/cta preenchidos pela regra (não ficam vazios)
    d = c._validar({"padrao": "luxo"}, {"descricao": "cobertura de luxo"})
    assert d["padrao"] == "luxo" and d["tom"] and isinstance(d["cta"], bool) and d["duracao"]
