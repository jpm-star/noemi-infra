"""Noemi PESSOAL (task 4 v1) — uso pessoal do JP, ISOLADO da produção de negócio.

REGRA DURA: banco NOVO e isolado (`pessoal.db`, NUNCA noemi.db/sdr_motor_papai/cliente).
Cartucho "pessoal" (schema mínimo) só marca que é conversa do JP, não de cliente.
Mesmo canal WhatsApp/Evolution (sem instância/número novo) — a separação é de DADO.

v1 = SÓ registrar gasto: texto livre → Groq categoriza (NUNCA Anthropic) → grava.
"Ana, gastei 40 no mercado" vira linha categorizada sozinha. Lembrete/alarme e lista
de ações = BACKLOG (não buildado).
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(_AQUI.parents[1] / "packages"))

# Cartucho pessoal (schema mínimo): identifica que é o JP, define as categorias de gasto.
CARTUCHO_PESSOAL = {
    "nome": "pessoal", "dono": "JP", "assistente": "Ana",
    "categorias": ["mercado", "alimentação", "transporte", "lazer", "saúde",
                   "casa", "serviços", "assinatura", "outros"],
}
_GATILHOS = re.compile(r"\b(ana|noemi)\b|\bgast(ei|o|ar)\b|\bpaguei\b|\bcompr(ei|a)\b", re.I)


def _db() -> Path:
    """Banco ISOLADO (pessoal.db). NUNCA o noemi.db. Honra NOEMI_DATA_DIR p/ teste isolado."""
    d = Path(os.environ.get("NOEMI_DATA_DIR", str(_AQUI.parents[1] / "data")))
    d.mkdir(parents=True, exist_ok=True)
    return d / "pessoal.db"


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_db(), timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE IF NOT EXISTS gastos (id INTEGER PRIMARY KEY AUTOINCREMENT, "
              "ts TEXT, valor REAL, categoria TEXT, descricao TEXT, texto TEXT)")
    return c


def _numeros_pessoais() -> set[str]:
    """Allowlist de números do JP (env NOEMI_PESSOAL_NUMEROS, separado por vírgula).
    Só dígitos, pra casar independente de formatação (+55, espaços, etc)."""
    raw = os.environ.get("NOEMI_PESSOAL_NUMEROS", "")
    return {re.sub(r"\D", "", n) for n in raw.split(",") if re.sub(r"\D", "", n)}


def roteia_pessoal(remetente: str) -> bool:
    """DESAMBIGUAÇÃO no MESMO número Evolution: uma mensagem é PESSOAL (JP) se, e só se,
    o REMETENTE está na allowlist do JP. É o único critério não-ambíguo — keyword ('Ana')
    um lead também digita. Sem allowlist configurada => NUNCA roteia como pessoal (fail-safe:
    nada de cliente vira gasto por engano). É este gate que precisa estar ligado ANTES do canal."""
    num = re.sub(r"\D", "", remetente or "")
    return bool(num) and num in _numeros_pessoais()


def eh_pessoal(texto: str) -> bool:
    """Filtro de CONTEÚDO secundário (parece gasto?). NÃO é o gate de roteamento — o gate
    é roteia_pessoal(remetente). Serve pra distinguir gasto de outro comando pessoal (futuro)."""
    return bool(_GATILHOS.search(texto or ""))


def _categorizar(texto: str) -> dict | None:
    """Groq (NUNCA Anthropic) extrai {valor, categoria, descricao}. None se não é gasto."""
    from shared_core.ai import llm_proxy
    cats = "/".join(CARTUCHO_PESSOAL["categorias"])
    prompt = (f"Extraia de um texto livre de GASTO PESSOAL do JP. Categorias válidas: {cats}. "
              "Se NÃO for um gasto (ex: pergunta, lembrete), responda {\"gasto\":false}. "
              "Senão SOMENTE JSON: {\"gasto\":true,\"valor\":<número em reais>,"
              "\"categoria\":\"<uma das categorias>\",\"descricao\":\"<curta>\"}.\n\n"
              f"TEXTO: {texto[:500]}")
    txt = llm_proxy.completar(prompt, model="analise", max_tokens=150, temperature=0,
                              permitir_anthropic=False)
    m = re.search(r"\{.*\}", txt or "", re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except (ValueError, TypeError):
        return None
    if not d.get("gasto"):
        return None
    try:
        valor = round(float(d.get("valor")), 2)
    except (TypeError, ValueError):
        return None
    cat = str(d.get("categoria", "")).strip().lower()
    return {"valor": valor,
            "categoria": cat if cat in CARTUCHO_PESSOAL["categorias"] else "outros",
            "descricao": str(d.get("descricao", "")).strip()[:120]}


def registrar_gasto(texto: str) -> dict | None:
    """Texto livre → categoriza (Groq) → GRAVA no banco isolado. None se não for gasto."""
    g = _categorizar(texto)
    if not g:
        return None
    ts = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        cur = c.execute("INSERT INTO gastos (ts,valor,categoria,descricao,texto) VALUES (?,?,?,?,?)",
                        (ts, g["valor"], g["categoria"], g["descricao"], (texto or "")[:300]))
        c.commit()
    return {"id": cur.lastrowid, "ts": ts, **g}


def listar_gastos(limite: int = 50) -> list[dict]:
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT id,ts,valor,categoria,descricao FROM gastos ORDER BY id DESC LIMIT ?", (limite,))]


def resumo_gastos() -> dict:
    with _conn() as c:
        total = c.execute("SELECT COALESCE(SUM(valor),0) FROM gastos").fetchone()[0]
        por_cat = {r["categoria"]: r["s"] for r in c.execute(
            "SELECT categoria, ROUND(SUM(valor),2) s FROM gastos GROUP BY categoria ORDER BY s DESC")}
    return {"total": round(total, 2), "por_categoria": por_cat}


if __name__ == "__main__":  # self-check ISOLADO (LLM mockado, banco isolado)
    os.environ["NOEMI_DATA_DIR"] = "/root/.claude/jobs/f7137c43/tmp/pessoal_selftest"
    import shutil
    shutil.rmtree(os.environ["NOEMI_DATA_DIR"], ignore_errors=True)
    from shared_core.ai import llm_proxy

    assert eh_pessoal("Ana, gastei 40 no mercado") and not eh_pessoal("qual o clima hoje")

    # GATE de roteamento (desambiguação): só remetente na allowlist é pessoal (fail-safe)
    os.environ.pop("NOEMI_PESSOAL_NUMEROS", None)
    assert roteia_pessoal("5511999998888") is False  # sem allowlist => NUNCA pessoal
    os.environ["NOEMI_PESSOAL_NUMEROS"] = "+55 11 99999-8888"
    assert roteia_pessoal("5511999998888@s.whatsapp.net") is True   # casa ignorando formatação
    assert roteia_pessoal("5511777770000") is False                 # lead não entra
    os.environ.pop("NOEMI_PESSOAL_NUMEROS", None)

    # gasto normal → categoriza e grava
    llm_proxy.completar = lambda *a, **k: '{"gasto":true,"valor":40,"categoria":"mercado","descricao":"compras"}'
    r = registrar_gasto("Ana, gastei 40 no mercado")
    assert r and r["valor"] == 40.0 and r["categoria"] == "mercado", r

    # categoria fora da lista → cai em 'outros'
    llm_proxy.completar = lambda *a, **k: '{"gasto":true,"valor":15.5,"categoria":"cripto","descricao":"x"}'
    assert registrar_gasto("paguei 15,50 em cripto")["categoria"] == "outros"

    # não-gasto → None, não grava
    llm_proxy.completar = lambda *a, **k: '{"gasto":false}'
    assert registrar_gasto("Ana, que horas são?") is None

    res = resumo_gastos()
    assert res["total"] == 55.5 and res["por_categoria"].get("mercado") == 40.0, res
    assert len(listar_gastos()) == 2

    # ISOLAMENTO: escreveu em pessoal.db, NÃO em noemi.db
    assert (Path(os.environ["NOEMI_DATA_DIR"]) / "pessoal.db").exists()
    assert not (Path(os.environ["NOEMI_DATA_DIR"]) / "noemi.db").exists()
    print("pessoal OK — categoriza+grava, categoria fora→outros, não-gasto→None, "
          "resumo, banco ISOLADO (pessoal.db, nunca noemi.db)")
