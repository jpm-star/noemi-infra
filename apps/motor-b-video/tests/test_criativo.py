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


# -- item 3: hook automático (cena de abertura) -----------------------------
def test_hook_por_padrao():
    assert "impacto" in prompt_builder.escolher_hook({"padrao": "luxo"}).lower()
    assert "trailer" in prompt_builder.escolher_hook({"padrao": "lancamento"}).lower()


def test_hook_entra_na_abertura_nao_no_meio():
    clas = {"padrao": "luxo", "tipo": "apartamento"}
    tpl = templates.escolher_template(clas)
    p_abre = prompt_builder.construir_prompt(clas, tpl, {}, papel="abertura")
    p_meio = prompt_builder.construir_prompt(clas, tpl, {}, papel="meio")
    assert p_abre["hook"] in p_abre["prompt"]
    assert p_abre["hook"] not in p_meio["prompt"]  # meio não leva hook
    # clipe único (completo) também abre com hook
    assert prompt_builder.construir_prompt(clas, tpl, {})["hook"] in \
        prompt_builder.construir_prompt(clas, tpl, {})["prompt"]
