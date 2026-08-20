"""Integração Google (Calendar + Sheets) via SERVICE ACCOUNT — sem OAuth interativo,
sem dep pesada (googleapiclient) e sem pip: assina o JWT do SA com o `openssl` do
sistema e fala REST via urllib. INERTE sem credencial (GOOGLE_SERVICE_ACCOUNT_JSON
vazio) — mesmo padrão do Resend: nunca crasha, nunca finge sucesso.

Env:
  GOOGLE_SERVICE_ACCOUNT_JSON  → o JSON do service account (inline OU caminho do arquivo)
  GOOGLE_SHEET_ID              → id da planilha de controle
  GOOGLE_CALENDAR_ID           → id do calendário (o e-mail do calendário compartilhado com o SA)
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

# drive.readonly: o pipeline da Pé Di LÊ a pasta de fotos do JP. Somente leitura de
# propósito — este código nunca deve poder apagar material do cliente.
_SCOPES = ("https://www.googleapis.com/auth/calendar "
           "https://www.googleapis.com/auth/spreadsheets "
           "https://www.googleapis.com/auth/drive.readonly")
_TOKEN_URL = "https://oauth2.googleapis.com/token"


def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _sa() -> dict | None:
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if not raw:
        return None
    try:
        d = json.loads(raw) if raw.lstrip().startswith("{") else json.loads(open(raw, encoding="utf-8").read())
        return d if d.get("client_email") and d.get("private_key") else None
    except (ValueError, OSError):
        return None


def configurado() -> bool:
    """True se o SA está no env (o chamador decide se dispara)."""
    return _sa() is not None


def _token() -> str | None:
    """JWT do SA assinado via openssl → access_token do Google. None se inerte/erro."""
    sa = _sa()
    if not sa:
        return None
    now = int(time.time())
    header = _b64u(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    claim = _b64u(json.dumps({"iss": sa["client_email"], "scope": _SCOPES, "aud": _TOKEN_URL,
                              "iat": now, "exp": now + 3600}).encode())
    signing_input = f"{header}.{claim}"
    keyfile = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False) as kf:
            kf.write(sa["private_key"])
            keyfile = kf.name
        sig = subprocess.run(["openssl", "dgst", "-sha256", "-sign", keyfile],
                             input=signing_input.encode(), capture_output=True, timeout=15).stdout
        if not sig:
            return None
        jwt = f"{signing_input}.{_b64u(sig)}"
        data = urllib.parse.urlencode({"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                                       "assertion": jwt}).encode()
        with urllib.request.urlopen(_TOKEN_URL, data=data, timeout=20) as r:
            return json.loads(r.read()).get("access_token")
    except (urllib.error.URLError, OSError, ValueError, KeyError, subprocess.SubprocessError):
        return None
    finally:
        if keyfile:
            try:
                os.unlink(keyfile)
            except OSError:
                pass


def _api(metodo: str, url: str, tok: str, corpo: dict | None) -> tuple[bool, str]:
    data = json.dumps(corpo).encode() if corpo is not None else None
    req = urllib.request.Request(url, data=data, method=metodo,
                                 headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return True, r.read().decode("utf-8")[:300]
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {(e.read()[:160] if e.fp else b'').decode(errors='replace')}"
    except (urllib.error.URLError, OSError) as e:
        return False, str(e)[:160]


# --- Drive (somente leitura) ---------------------------------------------------
# `_api` trunca a resposta em 300 chars (bom pra confirmar POST, inútil pra listar),
# então o Drive tem seus próprios dois acessos: um que devolve JSON inteiro e um que
# devolve bytes.
#
# `supportsAllDrives`/`includeItemsFromAllDrives`/`corpora=allDrives` NÃO são
# opcionais: a conta do JP é Workspace e as pastas vivem num Drive COMPARTILHADO
# (id começa com `0A`). Sem esses três, a API responde 200 com lista vazia — falha
# que se disfarça de "pasta sem nada".
_DRIVE = "https://www.googleapis.com/drive/v3/files"
_TODOS_OS_DRIVES = {"supportsAllDrives": "true", "includeItemsFromAllDrives": "true",
                    "corpora": "allDrives"}


def _drive_get(url: str, tok: str) -> tuple[bool, dict | str]:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return True, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {(e.read()[:200] if e.fp else b'').decode(errors='replace')}"
    except (urllib.error.URLError, OSError, ValueError) as e:
        return False, str(e)[:200]


def drive_listar(pasta_id: str, so_pastas: bool = False) -> tuple[bool, list | str]:
    """Filhos diretos de uma pasta. Pagina até o fim — 100 fotos numa subpasta é
    normal e a API entrega 100 por página."""
    tok = _token()
    if not tok:
        return False, "sem GOOGLE_SERVICE_ACCOUNT_JSON (inerte)"
    itens, page = [], ""
    while True:
        q = f"'{pasta_id}' in parents and trashed = false"
        if so_pastas:
            q += " and mimeType = 'application/vnd.google-apps.folder'"
        params = {**_TODOS_OS_DRIVES, "q": q, "pageSize": "100",
                  "fields": "nextPageToken,files(id,name,mimeType,size)"}
        if page:
            params["pageToken"] = page
        ok, d = _drive_get(f"{_DRIVE}?{urllib.parse.urlencode(params)}", tok)
        if not ok:
            return False, d
        itens.extend(d.get("files") or [])
        page = d.get("nextPageToken") or ""
        if not page:
            return True, itens


def drive_achar_pasta(nome: str) -> tuple[bool, str]:
    """Id da pasta com esse nome exato. Devolve erro nomeando o SA quando não acha:
    a causa quase sempre é 'existe, mas não foi compartilhada com o service account',
    e sem o e-mail na mensagem ninguém sabe com quem compartilhar."""
    tok = _token()
    if not tok:
        return False, "sem GOOGLE_SERVICE_ACCOUNT_JSON (inerte)"
    q = (f"name = '{nome.replace(chr(39), chr(92) + chr(39))}' and trashed = false "
         "and mimeType = 'application/vnd.google-apps.folder'")
    params = {**_TODOS_OS_DRIVES, "q": q, "pageSize": "10", "fields": "files(id,name)"}
    ok, d = _drive_get(f"{_DRIVE}?{urllib.parse.urlencode(params)}", tok)
    if not ok:
        return False, str(d)
    achadas = d.get("files") or []
    if not achadas:
        sa = _sa() or {}
        return False, (f"não achei a pasta {nome!r} no Drive. Se ela já existe, "
                       f"compartilhe com {sa.get('client_email', 'o service account')} (Leitor).")
    return True, achadas[0]["id"]


def drive_baixar(file_id: str, limite_mb: int = 60) -> tuple[bool, bytes | str]:
    """Bytes do arquivo. `limite_mb` corta antes de estourar a RAM com um vídeo."""
    tok = _token()
    if not tok:
        return False, "sem GOOGLE_SERVICE_ACCOUNT_JSON (inerte)"
    url = f"{_DRIVE}/{file_id}?alt=media&supportsAllDrives=true"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            dados = r.read(limite_mb * 1024 * 1024 + 1)
        if len(dados) > limite_mb * 1024 * 1024:
            return False, f"arquivo passa de {limite_mb} MB"
        return True, dados
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {(e.read()[:200] if e.fp else b'').decode(errors='replace')}"
    except (urllib.error.URLError, OSError) as e:
        return False, str(e)[:200]


def sheets_append(valores: list, sheet_id: str | None = None, aba: str = "A1") -> tuple[bool, str]:
    """Adiciona uma linha na planilha de controle. Inerte sem credencial."""
    tok = _token()
    if not tok:
        return False, "sem GOOGLE_SERVICE_ACCOUNT_JSON (inerte)"
    sid = sheet_id or os.environ.get("GOOGLE_SHEET_ID", "")
    if not sid:
        return False, "sem GOOGLE_SHEET_ID"
    url = (f"https://sheets.googleapis.com/v4/spreadsheets/{sid}/values/{urllib.parse.quote(aba)}"
           ":append?valueInputOption=USER_ENTERED")
    return _api("POST", url, tok, {"values": [[str(v) for v in valores]]})


def calendar_criar_evento(titulo: str, inicio_iso: str, fim_iso: str, descricao: str = "",
                          calendar_id: str | None = None) -> tuple[bool, str]:
    """Cria um evento no calendário. Inerte sem credencial. Datas em ISO 8601 c/ timezone."""
    tok = _token()
    if not tok:
        return False, "sem GOOGLE_SERVICE_ACCOUNT_JSON (inerte)"
    cid = calendar_id or os.environ.get("GOOGLE_CALENDAR_ID", "")
    if not cid:
        return False, "sem GOOGLE_CALENDAR_ID"
    url = f"https://www.googleapis.com/calendar/v3/calendars/{urllib.parse.quote(cid)}/events"
    return _api("POST", url, tok, {"summary": titulo, "description": descricao,
                                   "start": {"dateTime": inicio_iso}, "end": {"dateTime": fim_iso}})


if __name__ == "__main__":  # self-check: INERTE sem credencial (nunca crasha)
    for k in ("GOOGLE_SERVICE_ACCOUNT_JSON", "GOOGLE_SHEET_ID", "GOOGLE_CALENDAR_ID"):
        os.environ.pop(k, None)
    assert configurado() is False
    assert _token() is None
    ok, m = sheets_append(["x"])
    assert ok is False and "GOOGLE_SERVICE_ACCOUNT_JSON" in m, (ok, m)
    ok2, m2 = calendar_criar_evento("t", "2026-01-01T10:00:00-03:00", "2026-01-01T11:00:00-03:00")
    assert ok2 is False and "GOOGLE_SERVICE_ACCOUNT_JSON" in m2, (ok2, m2)
    # b64url sem padding (formato JWT)
    assert _b64u(b"abc") == "YWJj" and "=" not in _b64u(b"ab")
    for chamada in (lambda: drive_listar("x"), lambda: drive_achar_pasta("y"),
                    lambda: drive_baixar("z")):
        ok3, m3 = chamada()
        assert ok3 is False and "GOOGLE_SERVICE_ACCOUNT_JSON" in str(m3), (ok3, m3)
    assert "drive.readonly" in _SCOPES and "drive.file" not in _SCOPES
    print("google_integ OK — inerte sem SA (Resend-pattern); JWT via openssl; "
          "sheets/calendar/drive(ro) prontos")
