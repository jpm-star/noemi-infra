"""Auth do Site Studio — single-user, stdlib pura (sem itsdangerous/bcrypt).

Senha: pbkdf2_hmac(sha256) com salt; só o hash mora em disco (data/builder_auth.json),
nunca o texto puro. Sessão: cookie assinado com hmac-sha256 (user:expiry) — verificação
em tempo constante. JP troca a senha re-rodando `python auth.py set-password`.

ponytail: single-user, sem tabela de usuários nem framework de sessão — o que a
tarefa pede (só o JP usa) com o mínimo seguro. Multi-user = quando existir 2º login.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path

USUARIO = "joaop"
_ITERACOES = 240_000
_SESSAO_MAX_S = 30 * 24 * 3600  # 30 dias — "não pedir login toda hora"


def _arquivo() -> Path:
    p = os.environ.get("BUILDER_AUTH_FILE")
    if p:
        return Path(p)
    from shared_core.storage.db import data_dir
    return data_dir() / "builder_auth.json"


# -- senha -----------------------------------------------------------------
def _hash_senha(senha: str, salt: bytes, iteracoes: int = _ITERACOES) -> str:
    return hashlib.pbkdf2_hmac("sha256", senha.encode(), salt, iteracoes).hex()


def definir_senha(senha: str) -> None:
    """Cria/atualiza o arquivo de auth com o hash da senha. Preserva (ou gera)
    o segredo de sessão. Só o hash vai pro disco."""
    caminho = _arquivo()
    atual = _ler_bruto()
    salt = secrets.token_bytes(16)
    dados = {
        "usuario": USUARIO,
        "salt": salt.hex(),
        "hash": _hash_senha(senha, salt),
        "iteracoes": _ITERACOES,
        "session_secret": atual.get("session_secret") or secrets.token_hex(32),
    }
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(dados, indent=2))
    os.chmod(caminho, 0o600)


def _ler_bruto() -> dict:
    caminho = _arquivo()
    if not caminho.exists():
        return {}
    return json.loads(caminho.read_text())


def _config() -> dict:
    d = _ler_bruto()
    if not d:
        raise RuntimeError(
            "auth não configurada — rode: python apps/motor-isca-sites/auth.py set-password")
    return d


def verificar_senha(usuario: str, senha: str) -> bool:
    d = _config()
    if usuario != d["usuario"]:
        return False
    calc = _hash_senha(senha, bytes.fromhex(d["salt"]), d["iteracoes"])
    return hmac.compare_digest(calc, d["hash"])  # tempo constante


# -- sessão (cookie assinado) ---------------------------------------------
def _segredo() -> bytes:
    return bytes.fromhex(_config()["session_secret"])


def emitir_sessao(usuario: str) -> str:
    exp = int(time.time()) + _SESSAO_MAX_S
    corpo = f"{usuario}:{exp}".encode()
    assinatura = hmac.new(_segredo(), corpo, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(corpo).decode() + "." + base64.urlsafe_b64encode(assinatura).decode()


def validar_sessao(cookie: str | None) -> str | None:
    """Devolve o usuário se o cookie é válido e não expirou, senão None."""
    if not cookie or "." not in cookie:
        return None
    try:
        corpo_b64, sig_b64 = cookie.split(".", 1)
        corpo = base64.urlsafe_b64decode(corpo_b64)
        sig = base64.urlsafe_b64decode(sig_b64)
    except Exception:
        return None
    esperado = hmac.new(_segredo(), corpo, hashlib.sha256).digest()
    if not hmac.compare_digest(sig, esperado):
        return None
    try:
        usuario, exp = corpo.decode().rsplit(":", 1)
    except ValueError:
        return None
    if int(exp) < int(time.time()):
        return None
    return usuario


COOKIE = "studio_sessao"
COOKIE_MAX_S = _SESSAO_MAX_S


if __name__ == "__main__":
    import sys

    if len(sys.argv) >= 2 and sys.argv[1] == "set-password":
        senha = os.environ.get("BUILDER_PASSWORD") or (sys.argv[2] if len(sys.argv) > 2 else "")
        if not senha:
            senha = input("nova senha: ").strip()
        definir_senha(senha)
        print(f"senha de '{USUARIO}' gravada (hash) em {_arquivo()}")
    else:
        print("uso: python auth.py set-password [SENHA]  (ou BUILDER_PASSWORD=... )")
