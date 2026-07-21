"""Auth do Site Studio: hash de senha + cookie de sessão assinado."""
import base64
import hashlib
import hmac

import auth


def test_verificacao_de_senha():
    assert auth.verificar_senha("joaop", "senha-teste") is True
    assert auth.verificar_senha("joaop", "errada") is False
    assert auth.verificar_senha("outro", "senha-teste") is False  # usuário errado


def test_sessao_valida_e_adulterada():
    tok = auth.emitir_sessao("joaop")
    assert auth.validar_sessao(tok) == "joaop"
    assert auth.validar_sessao(tok[:-3] + "AAA") is None  # assinatura adulterada
    assert auth.validar_sessao(None) is None
    assert auth.validar_sessao("lixo-sem-ponto") is None


def test_sessao_expirada_rejeitada():
    corpo = b"joaop:1"  # expira em 1970
    sig = hmac.new(auth._segredo(), corpo, hashlib.sha256).digest()
    tok = (base64.urlsafe_b64encode(corpo).decode() + "." +
           base64.urlsafe_b64encode(sig).decode())
    assert auth.validar_sessao(tok) is None


def test_senha_nunca_em_texto_puro():
    conteudo = open(auth._arquivo(), encoding="utf-8").read()
    assert "senha-teste" not in conteudo  # só o hash mora em disco
    assert "hash" in conteudo and "salt" in conteudo
