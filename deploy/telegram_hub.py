#!/usr/bin/env python3
"""Hub do Telegram (@noemi_alert_bot) — o JP manda VÍDEO (arquivo) ou LINK e recebe
o insight do Radar de volta. Arquivo enviado pelo Telegram é servido direto (sem
bot-detection de IG/YT) — a solução robusta pro problema de scraping.

Fluxo por mensagem do JP (só do chat dele):
  - vídeo/documento de vídeo → baixa via getFile → radar.analisar_arquivo → responde
  - texto com link http     → radar.analisar(link)        → responde
  - (foto/recibo → OCR financeiro: próxima fase)

Poll com offset (data/telegram_offset.json). systemd timer. Reusa radar + notify.
Só processa mensagens do TELEGRAM_CHAT_ID (privacidade).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(_AQUI.parents[0] / "apps" / "painel-operacoes"))
sys.path.insert(0, str(_AQUI.parents[0] / "packages"))

_ESTADO = _AQUI.parents[0] / "data" / "telegram_offset.json"
_URL_RE = re.compile(r"https?://[^\s]+")
_API = "https://api.telegram.org/bot{tok}/{m}"


def _tok() -> str:
    return os.environ.get("TELEGRAM_BOT_TOKEN", "")


def _conta_legenda(m: dict) -> str:
    """@handle na legenda/texto → rótulo da conta (pro JP agrupar arquivos)."""
    mm = re.search(r"@[\w.]+", (m.get("caption") or m.get("text") or ""))
    return mm.group(0) if mm else ""


def _instrucao_legenda(m: dict) -> str:
    """Texto do JP (menos URL e @handle) = a instrução pro LLM responder."""
    t = m.get("caption") or m.get("text") or ""
    t = _URL_RE.sub("", t)
    t = re.sub(r"@[\w.]+", "", t).strip(" -–—\n\t")
    return t if len(t) >= 4 else ""


def _get(metodo: str, params: dict) -> dict:
    url = _API.format(tok=_tok(), m=metodo) + "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            return json.loads(r.read().decode())
    except Exception:  # noqa: BLE001
        return {}


def _responder(chat_id: str, texto: str) -> None:
    from shared_core import notify
    notify.telegram(texto)  # usa TELEGRAM_CHAT_ID; msg direta pro JP


def _baixar_arquivo(file_id: str, destino: Path) -> tuple[Path | None, str]:
    """(caminho, erro). Baixa um arquivo do Telegram (getFile → download). O getFile
    de bot tem TETO de 20MB — reel HD estoura e volta 'file is too big' (erro normal
    do Telegram, não bug nosso). Surfacea o motivo pra orientar o JP."""
    info = _get("getFile", {"file_id": file_id})
    fp = (info.get("result") or {}).get("file_path")
    if not fp:
        desc = (info.get("description") or "").lower()
        if "too big" in desc or "file is too big" in desc:
            return None, "grande"  # >20MB: limite do Telegram pra bots
        return None, "getfile"
    url = f"https://api.telegram.org/file/bot{_tok()}/{fp}"
    out = destino / Path(fp).name
    try:
        urllib.request.urlretrieve(url, out)
        return out, ""
    except Exception:  # noqa: BLE001
        return None, "download"


def _fmt_insight(a: dict) -> str:
    """Formata a resposta rica pro Telegram."""
    l = [f"📡 *{a.get('categoria','?')}* · ★{a.get('score','?')}", "", a.get("insight", "")]
    if a.get("onde_usar"):
        l.append("\n🎯 onde usar: " + ", ".join(a["onde_usar"]))
    if a.get("verticais"):
        l.append("🏷️ verticais: " + ", ".join(a["verticais"]))
    if a.get("axioma"):
        l.append("⚡ axioma: " + a["axioma"])
    if a.get("assimilacao"):
        l.append("🧠 assimilar: " + a["assimilacao"])
    mods = a.get("modelos") or {}
    if mods:  # templates replicáveis por domínio — o "de lá saia template de TUDO"
        icones = {"video": "🎬", "site": "🌐", "negocio": "💼", "produto": "📦",
                  "operacao": "⚙️", "projeto": "🧪"}
        l.append("\n📐 *templates replicáveis:*")
        l += [f"{icones.get(k,'•')} {k}: {v}" for k, v in mods.items()]
    return "\n".join(l)[:3500]


def _processar_msg(m: dict, chat_alvo: str) -> str | None:
    """Processa 1 mensagem: vídeo/doc de vídeo ou link. Devolve o status (log)."""
    import radar
    chat = str((m.get("chat") or {}).get("id") or "")
    if chat_alvo and chat != chat_alvo:
        return None  # só o JP
    # 1) vídeo ou documento de vídeo → baixa e analisa o arquivo
    conta = _conta_legenda(m)  # @handle na legenda vence (arquivo não traz autor)
    instr = _instrucao_legenda(m)  # texto do JP (replicar/adaptar/comparar) → vai pro LLM
    vid = m.get("video") or (m.get("document") if "video" in ((m.get("document") or {}).get("mime_type") or "") else None)
    if vid and vid.get("file_id"):
        # teto de 20MB do getFile de bot: avisa ANTES de tentar (reel HD estoura)
        if (vid.get("file_size") or 0) > 20 * 1024 * 1024:
            _responder(chat, "✗ vídeo >20MB — é limite do **Telegram** pra bots (não meu, "
                             "não dá pra subir). Caminho pra vídeo grande: joga no **Google "
                             "Drive** e me manda o LINK (leio o vídeo inteiro), ou manda o "
                             "link do **YouTube** (baixo só o áudio). Link não tem limite.")
            radar.registrar_job(False, origem=conta or "telegram", motivo="arquivo >20MB (limite Telegram)")
            return "arquivo_grande"
        _responder(chat, "🎬 recebi o vídeo, analisando…")
        with tempfile.TemporaryDirectory(prefix="tg_") as td:
            arq, erro = _baixar_arquivo(vid["file_id"], Path(td))
            if not arq:
                msg = ("✗ vídeo >20MB — limite do Telegram pra bots. Joga no Google Drive "
                       "e me manda o LINK (sem limite), ou o link do YouTube." if erro == "grande"
                       else "✗ não consegui baixar o arquivo do Telegram — tenta reenviar.")
                _responder(chat, msg)
                radar.registrar_job(False, origem=conta or "telegram", motivo=f"download {erro}")
                return f"download_falhou_{erro}"
            try:
                a = radar.analisar_arquivo(str(arq), origem=conta or "telegram", instrucao=instr)
                _responder(chat, _fmt_insight(a))
                radar.registrar_job(True, origem=a.get("origem") or conta or "telegram", url="(vídeo enviado)")
                return f"video ok id={a['id']}"
            except Exception as e:  # noqa: BLE001
                _responder(chat, f"✗ falhou: {str(e)[:200]}")
                radar.registrar_job(False, origem=conta or "telegram", motivo=str(e)[:150])
                return "analise_falhou"
    # 2) link no texto
    txt = m.get("text") or m.get("caption") or ""
    links = _URL_RE.findall(txt)
    if links:
        url = links[0].rstrip(").,")
        _responder(chat, "🔗 analisando o link…")
        try:
            a = radar.analisar(url, origem=conta or None, instrucao=instr)  # legenda > metadado > url
            _responder(chat, _fmt_insight(a))
            radar.registrar_job(True, origem=a.get("origem") or "", url=url)
            return f"link ok id={a['id']}"
        except Exception as e:  # noqa: BLE001
            # IG/YT bloqueiam IP de datacenter (ou a sessão venceu) → guia pro caminho
            # garantido: o vídeo enviado direto NÃO usa yt-dlp (ffmpeg local, 100%).
            dica = ("\n\n💡 O Instagram costuma bloquear meu IP (ou a sessão venceu). "
                    "Caminho garantido: baixa o reel no teu celular e me manda o VÍDEO "
                    "aqui — analiso 100%, sem depender do link."
                    if "instagram" in url.lower()
                    else "\n\n💡 Se o link não abrir, me manda o vídeo direto que eu analiso.")
            _responder(chat, f"✗ {str(e)[:160]}{dica}")
            radar.registrar_job(False, origem=conta or "", url=url, motivo=str(e)[:150])
            return "link_falhou"
    return None


def rodar(*, buscar=None) -> dict:
    if not _tok():
        return {"erro": "TELEGRAM_BOT_TOKEN não configurado"}
    chat_alvo = os.environ.get("TELEGRAM_CHAT_ID", "")
    try:
        off = json.loads(_ESTADO.read_text()).get("offset", 0)
    except (OSError, ValueError):
        off = 0
    upd = (buscar or (lambda o: _get("getUpdates", {"offset": o, "timeout": 0}))) (off + 1)
    resultados = upd.get("result", []) if isinstance(upd, dict) else []
    feitos = []
    maior = off
    for u in resultados:
        maior = max(maior, u.get("update_id", off))
        msg = u.get("message") or u.get("channel_post")
        if msg:
            r = _processar_msg(msg, chat_alvo)
            if r:
                feitos.append(r)
    if resultados:
        _ESTADO.parent.mkdir(parents=True, exist_ok=True)
        _ESTADO.write_text(json.dumps({"offset": maior}))
    return {"processados": len(feitos), "detalhe": feitos}


if __name__ == "__main__":
    if "--selftest" in sys.argv:  # roteamento (sem rede): link vs vídeo vs nada
        vistos = []
        import types
        mod = types.ModuleType("radar")
        mod.analisar = lambda u, origem=None, instrucao="": {"id": 1, "categoria": "vendas", "score": 5,
                                               "insight": instrucao or "x", "onde_usar": ["a"], "verticais": [], "axioma": "", "assimilacao": ""}
        mod.analisar_arquivo = lambda p, origem=None, url_ref="", instrucao="": {"id": 2, "categoria": "mkt", "score": 4, "insight": "y",
                                                       "onde_usar": [], "verticais": [], "axioma": "", "assimilacao": ""}
        mod.registrar_job = lambda ok, **k: None
        sys.modules["radar"] = mod
        globals()["_responder"] = lambda c, t: vistos.append(t)
        globals()["_baixar_arquivo"] = lambda fid, d: (Path("/tmp/fake.mp4"), "")
        assert "link ok" in _processar_msg({"chat": {"id": "1"}, "text": "olha https://youtu.be/x"}, "1")
        assert "video ok" in _processar_msg({"chat": {"id": "1"}, "video": {"file_id": "F"}}, "1")
        assert _processar_msg({"chat": {"id": "9"}, "text": "https://x.com"}, "1") is None  # outro chat
        assert _processar_msg({"chat": {"id": "1"}, "text": "oi sem link"}, "1") is None
        print("telegram_hub OK — roteia link/vídeo, ignora outro chat e texto sem link")
    else:
        print(json.dumps(rodar(), ensure_ascii=False))
