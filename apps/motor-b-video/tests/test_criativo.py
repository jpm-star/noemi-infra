"""Motor B refinamento criativo (Bloco C): itens que estendem classificação/prompt."""
import prompt_builder
import templates
from shared_core.ai import classificacao


# -- item 5: detecção de iluminação e ambiente ------------------------------
def test_iluminacao_ambiente_no_mock():
    c = classificacao.classificar({"descricao": "Cobertura com piscina e vista pro pôr do sol"})
    assert c["iluminacao"] == "artificial noturna"  # pôr do sol → noturna
    assert c["ambiente"] in ("externo", "misto")     # piscina → tem externo


def test_iluminacao_diurna_interno_default():
    c = classificacao.classificar({"descricao": "Apartamento com sala e dois quartos"})
    assert c["iluminacao"] == "natural diurna"
    assert c["ambiente"] == "interno"


def test_prompt_usa_iluminacao_e_ambiente():
    c = classificacao.classificar({"descricao": "Casa com quintal e churrasqueira à noite"})
    p = prompt_builder.construir_prompt(c, templates.escolher_template(c),
                                        {"descricao": "Casa com quintal e churrasqueira à noite"})
    assert "iluminação real do imóvel" in p["prompt"]
    assert "Ambiente predominante" in p["prompt"]
