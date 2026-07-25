"""Módulo de e-mail outbound (Gmail API) — SEPARADO do motor de leads.

Fila simples no BD (tabela emails no leads.db) + throttle diário (warm-up de
domínio) + template em arquivo (JP itera a copy sem deploy). O envio real usa a
Gmail API via service account com domain-wide delegation (import tardio — só
carrega quando for enviar de verdade). Sem credencial = modo dry-run (grava
'sent' com message_id fake) pra testar a fila/throttle SEM mandar e-mail.

NÃO usa n8n nem orquestrador. Um worker/cron chama processar_fila(N).

Env:
  EMAIL_DAILY_LIMIT   máx envios/dia (default 25 — warm-up)
  EMAIL_FROM          caixa de envio (ex: vendas@noemi.digital)
  EMAIL_SA_JSON       service account json (domain-wide delegation)
  EMAIL_TEMPLATE      caminho do arquivo de template (senão usa _TEMPLATE_PADRAO)
  LEADS_DB            sqlite dos leads (default data/leads.db)
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_ESTADOS = ("pending", "sent", "failed")
_TEMPLATE_PADRAO = (
    "Oi! Aqui é a Noemi (Noemi Digital). Montei um site de demonstração pra "
    "{nome} — dá uma olhada rápida: {link}\n\n"
    "Se curtir, a gente coloca no ar já com atendimento automático no WhatsApp "
    "24h (agendamento, dúvidas, orçamento). Posso te mostrar como fica?\n\n"
    "— Noemi · noemi.digital"
)


def _db() -> sqlite3.Connection:
    p = Path(os.environ.get("LEADS_DB", "data/leads.db"))
    p.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(p, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("""CREATE TABLE IF NOT EXISTS emails (
        id INTEGER PRIMARY KEY AUTOINCREMENT, lead_id TEXT, to_addr TEXT NOT NULL,
        subject TEXT, body TEXT, status TEXT DEFAULT 'pending', message_id TEXT,
        erro TEXT, criado_em TEXT, enviado_em TEXT)""")
    c.commit()
    return c


def render_template(lead: dict) -> str:
    """Corpo do e-mail pro lead. Template de arquivo (EMAIL_TEMPLATE) ou o padrão.
    Placeholders: {nome} {link} {cidade} {telefone}."""
    arq = os.environ.get("EMAIL_TEMPLATE", "")
    tpl = Path(arq).read_text("utf-8") if arq and Path(arq).exists() else _TEMPLATE_PADRAO
    return tpl.format(nome=lead.get("nome", ""), link=lead.get("link", ""),
                      cidade=lead.get("cidade", ""), telefone=lead.get("telefone", ""))


def enfileirar(to_addr: str, subject: str, body: str, lead_id: str | None = None) -> int:
    """Coloca 1 e-mail na fila (status pending). Devolve o id. NÃO envia."""
    with _db() as c:
        cur = c.execute("INSERT INTO emails (lead_id, to_addr, subject, body, status, criado_em) "
                        "VALUES (?,?,?,?, 'pending', ?)",
                        (lead_id, to_addr, subject, body, datetime.now(timezone.utc).isoformat()))
        c.commit()
        return cur.lastrowid


def _enviados_hoje(c: sqlite3.Connection) -> int:
    hoje = datetime.now(timezone.utc).date().isoformat()
    return c.execute("SELECT COUNT(*) FROM emails WHERE status='sent' AND substr(enviado_em,1,10)=?",
                     (hoje,)).fetchone()[0]


def send_email(to: str, subject: str, body: str, lead_id: str | None = None, *, enviar=None) -> dict:
    """Envia 1 e-mail JÁ (respeita o throttle diário). Grava lead_id/status/
    timestamp/message_id. `enviar` injetável (teste); default = Gmail API.
    Retorna {status, message_id|erro}."""
    limite = int(os.environ.get("EMAIL_DAILY_LIMIT", "25"))
    with _db() as c:
        if _enviados_hoje(c) >= limite:
            return {"status": "throttled", "erro": f"limite diário {limite} atingido"}
        eid = c.execute("INSERT INTO emails (lead_id, to_addr, subject, body, status, criado_em) "
                        "VALUES (?,?,?,?, 'pending', ?)",
                        (lead_id, to, subject, body, datetime.now(timezone.utc).isoformat())).lastrowid
        c.commit()
    try:
        mid = (enviar or _enviar_gmail)(to, subject, body)
        _marcar(eid, "sent", message_id=mid)
        return {"status": "sent", "message_id": mid, "id": eid}
    except Exception as e:  # noqa: BLE001 — falha não derruba o lote
        _marcar(eid, "failed", erro=str(e)[:300])
        return {"status": "failed", "erro": str(e)[:300], "id": eid}


def processar_fila(limite_lote: int = 10, *, enviar=None) -> dict:
    """Worker: pega N pendentes e envia respeitando o throttle diário. Cron chama isto."""
    limite_dia = int(os.environ.get("EMAIL_DAILY_LIMIT", "25"))
    enviados = falhas = 0
    with _db() as c:
        resto = max(0, limite_dia - _enviados_hoje(c))
        pend = c.execute("SELECT * FROM emails WHERE status='pending' ORDER BY id LIMIT ?",
                         (min(limite_lote, resto),)).fetchall()
    for e in pend:
        try:
            mid = (enviar or _enviar_gmail)(e["to_addr"], e["subject"], e["body"])
            _marcar(e["id"], "sent", message_id=mid); enviados += 1
        except Exception as ex:  # noqa: BLE001
            _marcar(e["id"], "failed", erro=str(ex)[:300]); falhas += 1
    return {"enviados": enviados, "falhas": falhas, "restante_dia": max(0, resto - enviados)}


def _marcar(eid: int, status: str, *, message_id: str | None = None, erro: str | None = None) -> None:
    with _db() as c:
        c.execute("UPDATE emails SET status=?, message_id=?, erro=?, enviado_em=? WHERE id=?",
                  (status, message_id, erro, datetime.now(timezone.utc).isoformat(), eid))
        c.commit()


def _enviar_gmail(to: str, subject: str, body: str) -> str:
    """Envia via Gmail API (service account + domain-wide delegation). Sem
    credencial → dry-run (message_id fake, NÃO manda). Import tardio das libs Google."""
    sa = os.environ.get("EMAIL_SA_JSON", "")
    frm = os.environ.get("EMAIL_FROM", "vendas@noemi.digital")
    if not sa or not Path(sa).exists():
        return f"dryrun-{abs(hash((to, subject))) % 10**10}"  # sem SA: não envia
    import base64
    from email.mime.text import MIMEText
    from google.oauth2 import service_account  # dep: google-auth
    from googleapiclient.discovery import build  # dep: google-api-python-client
    cred = service_account.Credentials.from_service_account_file(
        sa, scopes=["https://www.googleapis.com/auth/gmail.send"], subject=frm)
    svc = build("gmail", "v1", credentials=cred)
    msg = MIMEText(body); msg["to"] = to; msg["from"] = frm; msg["subject"] = subject
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    r = svc.users().messages().send(userId="me", body={"raw": raw}).execute()
    return r.get("id", "")


# hook fase 2 (deixado pronto): checar resposta na thread e marcar o lead
def checar_respostas(*, ler=None) -> int:
    """Fase 2: consulta as threads dos enviados (gmail.readonly) e marca lead
    'respondeu'. `ler(message_id)->bool` injetável. Sem credencial = no-op (0)."""
    if not os.environ.get("EMAIL_SA_JSON"):
        return 0
    marcados = 0
    with _db() as c:
        enviados = c.execute("SELECT id, lead_id, message_id FROM emails WHERE status='sent'").fetchall()
    for e in enviados:
        if e["message_id"] and (ler or _tem_resposta)(e["message_id"]):
            _marcar_lead_respondeu(e["lead_id"]); marcados += 1
    return marcados


def _tem_resposta(message_id: str) -> bool:  # placeholder Gmail readonly (fase 2)
    return False


def _marcar_lead_respondeu(lead_id: str | None) -> None:
    if not lead_id:
        return
    with _db() as c:
        try:
            c.execute("UPDATE leads_clinicas SET status='respondeu-email' WHERE place_id=?", (lead_id,))
            c.commit()
        except sqlite3.Error:
            pass


if __name__ == "__main__":  # self-check: fila + throttle + template (mock sender, sem Gmail)
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        os.environ["LEADS_DB"] = str(Path(td) / "e.db")
        os.environ["EMAIL_DAILY_LIMIT"] = "2"
        env = []
        mock = lambda to, s, b: (env.append(to) or f"mid-{len(env)}")
        assert send_email("a@x.com", "oi", "corpo", "L1", enviar=mock)["status"] == "sent"
        assert send_email("b@x.com", "oi", "corpo", "L2", enviar=mock)["status"] == "sent"
        # 3º estoura o throttle diário (limite=2)
        assert send_email("c@x.com", "oi", "corpo", "L3", enviar=mock)["status"] == "throttled"
        assert len(env) == 2, env
        # fila: enfileira 1 e o worker respeita o limite (já bateu 2 hoje)
        enfileirar("d@x.com", "oi", "corpo", "L4")
        r = processar_fila(enviar=mock)
        assert r["enviados"] == 0 and r["restante_dia"] == 0, r  # throttle segura
        # template renderiza placeholders
        corpo = render_template({"nome": "Clínica X", "link": "http://demo/x"})
        assert "Clínica X" in corpo and "http://demo/x" in corpo
        print("email OK — fila, throttle diário, template, dry-run sem credencial")
