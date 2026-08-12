"""O acervo de fotos não pode travar a geração — ele é enfeite.

POR QUE EXISTE: um T1 de nicho novo ("padaria") passou de 400s e não terminou. A
causa era o acervo: loop aninhado (serviços x candidatas), cada julgamento de visão
levando 20-60s quando o Groq está em rate limit ou devolve só raciocínio. O código
já tratava o acervo como opcional (try/except em volta), mas opcional que TRAVA não
é opcional — e quem espera é o dono do negócio, do outro lado da mesa.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_estourar_o_orcamento_nao_desalinha_as_fotos(monkeypatch, tmp_path):
    """Posição pulada vira "" — o motor casa foto com serviço por ÍNDICE.

    Encurtar a lista seria pior que a lentidão: cada serviço herdaria a foto do
    seguinte e o site sairia com a imagem errada em cada card, sem nada quebrar.
    """
    import acervo_fotos as af

    servicos = [(f"servico {i}", "", f"kw{i}") for i in range(5)]
    monkeypatch.setattr(af, "RAIZ", tmp_path)
    monkeypatch.setattr(af, "ORCAMENTO_S", 10)
    monkeypatch.setattr(af, "_garante_chave_groq", lambda: None)
    monkeypatch.setattr(af, "_servicos", lambda n: servicos)
    monkeypatch.setattr(af, "buscar", lambda kw: ["http://x/1.jpg"])
    monkeypatch.setattr(af, "_http", lambda u: b"x" * (af.MIN_BYTES + 1))

    # relógio falso: cada julgamento "gasta" 6s — o orçamento de 10s estoura no 2º
    relogio = {"t": 0.0}
    monkeypatch.setattr(af.time, "monotonic", lambda: relogio["t"])

    def _lento(b, nome, nicho):
        relogio["t"] += 6.0
        return True, "ok"
    monkeypatch.setattr(af, "_visao_aprova", _lento)

    urls = af.garantir("nicho-de-teste")
    assert len(urls) == len(servicos), \
        "lista encurtada desalinha foto/serviço — cada card herdaria a imagem do próximo"
    assert urls[0] and urls[1], "as que couberam no orçamento têm que ter foto"
    assert urls[2:] == ["", "", ""], "as que estouraram viram vazio, não somem"


def test_orcamento_generoso_julga_tudo(monkeypatch, tmp_path):
    """Sem pressão de tempo, o comportamento é o de antes — nada regrediu."""
    import acervo_fotos as af

    servicos = [(f"s{i}", "", f"k{i}") for i in range(3)]
    monkeypatch.setattr(af, "RAIZ", tmp_path)
    monkeypatch.setattr(af, "ORCAMENTO_S", 9999)
    monkeypatch.setattr(af, "_garante_chave_groq", lambda: None)
    monkeypatch.setattr(af, "_servicos", lambda n: servicos)
    monkeypatch.setattr(af, "buscar", lambda kw: ["http://x/1.jpg"])
    monkeypatch.setattr(af, "_http", lambda u: b"x" * (af.MIN_BYTES + 1))
    monkeypatch.setattr(af, "_visao_aprova", lambda b, n, ni: (True, "ok"))

    urls = af.garantir("outro-nicho")
    assert all(urls) and len(urls) == 3
