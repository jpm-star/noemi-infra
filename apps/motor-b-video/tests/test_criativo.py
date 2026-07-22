"""Motor B refinamento criativo (Bloco C): itens que estendem classificação/prompt."""
import metadados
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


# -- item 1: título automático ----------------------------------------------
def test_titulo_compoe_partes_reais():
    t = metadados.titulo({"tipo": "apartamento", "padrao": "luxo"},
                         {"descricao": "3 quartos com vista pro mar", "localizacao": "Balneário Camboriú"})
    assert t == "Apartamento 3 quartos - Balneário Camboriú - Vista Mar - Alto Padrão"


def test_titulo_nao_inventa_dado_faltando():
    # sem quartos/local/destaque/padrão econômico → só o tipo, nada inventado
    assert metadados.titulo({"tipo": "casa", "padrao": "economico"}, {"descricao": "casa"}) == "Casa"


# -- item 2: hashtags automáticas -------------------------------------------
def test_hashtags_relevantes_8_a_10_sem_repetir():
    h = metadados.hashtags({"tipo": "apartamento", "padrao": "luxo"},
                           {"descricao": "vista mar com piscina", "localizacao": "Balneário Camboriú"})
    assert 8 <= len(h) <= 10 and len(set(h)) == len(h)
    assert "#apartamento" in h and "#imoveisdeluxo" in h and "#vistamar" in h
    assert "#balneariocamboriu" in h and all(t.startswith("#") for t in h)


def test_hashtags_sem_dados_ainda_da_minimo():
    h = metadados.hashtags({"tipo": "casa", "padrao": "economico"}, {})
    assert len(h) >= 8 and "#casa" in h
