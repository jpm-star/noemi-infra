"""Envio de e-mail — abstração simples, provider trocável por baixo (CLAUDE.md:
interface fixa, provider embaixo). Interface: enviar(assunto, corpo, para).

Provider via env EMAIL_PROVIDER (default 'smtp'). Hoje: SMTP (smtplib stdlib — casa
com App Password do Gmail ou qualquer SMTP). Amanhã: sendgrid/mailgun/resend entram
como mais uma função no dispatch, sem tocar quem chama.

INERTE sem credencial: `configurado()` = False e `enviar()` devolve (False, motivo) —
nunca crasha, nunca finge sucesso. Fica pronto esperando o JP colar a credencial no env.

Env (SMTP): SMTP_HOST, SMTP_PORT (587), SMTP_USER, SMTP_PASS, SMTP_FROM (default=USER),
EMAIL_ALERTA_PARA (destinatário default dos alertas).
"""
from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage


def _cfg_smtp() -> dict | None:
    """Config SMTP do env, ou None se faltar o essencial (host/user/pass)."""
    host = os.environ.get("SMTP_HOST", "").strip()
    user = os.environ.get("SMTP_USER", "").strip()
    pw = os.environ.get("SMTP_PASS", "").strip()
    if not (host and user and pw):
        return None
    return {"host": host, "port": int(os.environ.get("SMTP_PORT", "587")),
            "user": user, "pw": pw, "from": os.environ.get("SMTP_FROM", user).strip()}


def _enviar_smtp(assunto: str, corpo: str, para: str) -> tuple[bool, str]:
    cfg = _cfg_smtp()
    if not cfg:
        return False, "sem credencial SMTP (SMTP_HOST/USER/PASS vazios)"
    msg = EmailMessage()
    msg["Subject"] = assunto
    msg["From"] = cfg["from"]
    msg["To"] = para
    msg.set_content(corpo)
    try:
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=20) as s:
            s.starttls()
            s.login(cfg["user"], cfg["pw"])
            s.send_message(msg)
        return True, "enviado"
    except Exception as e:  # noqa: BLE001 — envio best-effort, nunca derruba o chamador
        return False, f"falha SMTP: {str(e)[:120]}"


# dispatch de provider (trocável): nome lógico -> (checa_config, envia)
_PROVIDERS = {
    "smtp": (lambda: _cfg_smtp() is not None, _enviar_smtp),
    # "sendgrid": (...), "resend": (...)  # entram aqui sem mexer no resto
}


def _provider():
    nome = os.environ.get("EMAIL_PROVIDER", "smtp").strip().lower()
    return _PROVIDERS.get(nome, _PROVIDERS["smtp"])


def configurado() -> bool:
    """True se o provider ativo tem credencial (pra o chamador decidir se dispara)."""
    return _provider()[0]()


def enviar(assunto: str, corpo: str, para: str | None = None) -> tuple[bool, str]:
    """(ok, motivo). Inerte (False, motivo) se sem credencial — nunca crasha."""
    dest = (para or os.environ.get("EMAIL_ALERTA_PARA", "")).strip()
    if not dest:
        return False, "sem destinatário (EMAIL_ALERTA_PARA vazio)"
    return _provider()[1](assunto, corpo, dest)


if __name__ == "__main__":  # self-check: inerte sem credencial, envia com provider mockado
    for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASS"):
        os.environ.pop(k, None)
    assert configurado() is False
    ok, motivo = enviar("x", "y", "jp@x.com")
    assert ok is False and "credencial" in motivo, (ok, motivo)

    # provider mockado prova que a interface funciona quando a credencial existe
    enviados = []
    _PROVIDERS["mock"] = (lambda: True, lambda a, c, p: (enviados.append((a, c, p)) or (True, "enviado")))
    os.environ["EMAIL_PROVIDER"] = "mock"
    assert configurado() is True
    ok, motivo = enviar("assunto", "corpo", "jp@x.com")
    assert ok and enviados == [("assunto", "corpo", "jp@x.com")], (ok, enviados)
    # sem destinatário => inerte
    os.environ.pop("EMAIL_ALERTA_PARA", None)
    assert enviar("a", "b")[0] is False
    print("email_envio OK — inerte sem credencial; provider trocável; envia quando configurado")
