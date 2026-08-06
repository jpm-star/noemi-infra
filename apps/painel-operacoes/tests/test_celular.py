"""Regressão do nono dígito.

A base da CNPJá (37.070 leads, todos com CNPJ e razão social) guarda telefone no
formato anterior a 2016: DDD + 8 dígitos. A regra antiga exigia 11 dígitos e devolvia
"" pra todos — 26.885 celulares válidos apareciam como "sem WhatsApp", e o funil foi
dimensionado por cima desse erro de leitura.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from prospeccao_dia import _wa, normalizar_celular  # noqa: E402


def test_celular_pre_2016_recupera_o_nono_digito():
    assert normalizar_celular("1499042321") == "14999042321"
    assert normalizar_celular("1481157037") == "14981157037"


def test_fixo_continua_fora():
    """Prefixo 2-5 era e continua fixo: não tem WhatsApp, não pode virar celular."""
    for fixo in ("1431049065", "1432241718", "1122334455"):
        assert normalizar_celular(fixo) == "", fixo


def test_idempotente_e_com_ddi():
    assert normalizar_celular("14999042321") == "14999042321"
    assert normalizar_celular("5514999042321") == "14999042321"
    assert normalizar_celular("+55 (14) 99904-2321") == "14999042321"


def test_lixo_nao_vira_numero():
    for x in ("", None, "1234", "abc", "0", "14399042321"):
        assert normalizar_celular(x) == "", repr(x)


def test_wa_monta_link_com_ddi():
    assert _wa("1499042321") == "5514999042321"
    assert _wa("1431049065") == ""
