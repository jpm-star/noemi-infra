"""Registrar venda fechada no campo — o caminho mais curto entre "fechei" e virar dado.

POR QUE EXISTE: o endpoint `/api/campo/fechamento` já existia e NENHUMA tela chamava.
Resultado: 1.532 prospects, `valor_fechado` vazio em 100% das linhas. O widget "Fechado"
da /obs/campo mostrava R$ 0 pra sempre, e a modelagem financeira ficava presa em
premissa. Construído e não ligado é o mesmo que não existir.

TRÊS COISAS QUE O ENDPOINT ANTIGO NÃO RESOLVIA, e que quebram no primeiro uso real:

1. A fila da /obs/campo é só T3/T4 — 68 leads. O funil tem 1.462 em T1/T2. Fechar um
   T1 na porta e não achar o nome na tela é o caso COMUM, não o raro.
2. Venda com quem não está no banco (indicação, walk-in) não tinha caminho nenhum.
   É exatamente a venda que some.
3. Ele não gravava o TIER. Sem tier, a venda entra no total e não entra em nenhuma
   linha da modelagem — vira número órfão.

`buscar` é por pedaço do nome, sem acento e sem caixa: no celular, na porta do cliente,
ninguém digita "Restaurante & Cia Ltda" certo.
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from datetime import date, datetime, timezone

TIERS = ("T1", "T2", "T3", "T4")
STATUS_FECHADO = "Fechado"
_MAX_BUSCA = 12


def _db() -> sqlite3.Connection:
    """Mesma conexão que o resto do painel usa — sem segunda fonte de verdade."""
    import ritmo
    return ritmo._db()


def normalizar(txt: str) -> str:
    """Minúsculo, sem acento, só alfanumérico. É a chave de deduplicação por nome."""
    t = unicodedata.normalize("NFKD", str(txt or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()


def buscar(q: str, limite: int = _MAX_BUSCA) -> list[dict]:
    """Prospects cujo nome contém `q`. Vazio devolve os já fechados (pra conferir)."""
    termo = normalizar(q)
    import ritmo
    ritmo.garantir_coluna()
    with _db() as c:
        linhas = c.execute(
            "SELECT id, empresa, tier, cidade_uf, status, valor_fechado "
            "FROM tracker_prospects ORDER BY empresa").fetchall()
    achados = []
    for r in linhas:
        d = dict(r)
        if termo:
            if termo not in normalizar(d.get("empresa")):
                continue
        elif not (d.get("valor_fechado") or 0):
            continue
        achados.append({"id": d["id"], "empresa": d["empresa"], "tier": d.get("tier") or "",
                        "cidade": d.get("cidade_uf") or "", "status": d.get("status") or "",
                        "valor_fechado": d.get("valor_fechado") or 0})
        if len(achados) >= limite:
            break
    return achados


def registrar(*, prospect_id: int = 0, empresa: str = "", tier: str = "",
              valor: float = 0.0, quando: str = "", notas: str = "") -> dict:
    """Marca a venda. Aceita prospect existente OU nome novo. Nunca duplica por nome.

    Não valida se o valor bate com o preço do tier de propósito: desconto, permuta e
    parcelamento existem, e uma trava aqui faria o JP desistir de registrar — o que é
    exatamente o problema que este módulo veio resolver. O valor real vale mais que o
    valor "certo".
    """
    tier = (tier or "").strip().upper()
    if tier and tier not in TIERS:
        return {"ok": False, "erro": f"tier inválido: {tier}"}
    try:
        valor = float(valor or 0)
    except (TypeError, ValueError):
        return {"ok": False, "erro": "valor não é número"}
    if valor <= 0:
        return {"ok": False, "erro": "valor precisa ser maior que zero"}
    quando = (quando or date.today().isoformat())[:10]
    agora = datetime.now(timezone.utc).isoformat()

    import ritmo
    ritmo.garantir_coluna()
    criado = False
    with _db() as c:
        pid = int(prospect_id or 0)
        if not pid:
            nome = (empresa or "").strip()
            if not nome:
                return {"ok": False, "erro": "informe o prospect ou o nome da empresa"}
            # dedup por nome normalizado: no campo, "Padaria do Zé" e "padaria do ze"
            # são o mesmo cliente. Inserir os dois inflaria o contador de fechamentos.
            alvo = normalizar(nome)
            for r in c.execute("SELECT id, empresa FROM tracker_prospects"):
                if normalizar(r["empresa"]) == alvo:
                    pid = int(r["id"])
                    break
            if not pid:
                cur = c.execute(
                    "INSERT INTO tracker_prospects (empresa, tier, status, notas, "
                    "criado_em, atualizado_em) VALUES (?,?,?,?,?,?)",
                    (nome[:120], tier, STATUS_FECHADO, notas[:2000], agora, agora))
                pid = int(cur.lastrowid)
                criado = True

        sets = ["valor_fechado=?", "status=?", "atualizado_em=?"]
        vals: list = [valor, STATUS_FECHADO, agora]
        if tier:
            sets.append("tier=?")
            vals.append(tier)
        if notas:
            sets.append("notas=?")
            vals.append(notas[:2000])
        # data_proxima_acao guarda a DATA DA VENDA quando não há coluna própria pra isso.
        # Coluna nova pediria migration; o campo já é TEXT e está livre depois do fecho.
        sets.append("data_proxima_acao=?")
        vals.append(quando)
        vals.append(pid)
        cur = c.execute(f"UPDATE tracker_prospects SET {', '.join(sets)} WHERE id=?", vals)
        c.commit()
        if not cur.rowcount:
            return {"ok": False, "erro": f"prospect {pid} não existe"}
        row = dict(c.execute(
            "SELECT id, empresa, tier, valor_fechado, status FROM tracker_prospects "
            "WHERE id=?", (pid,)).fetchone())
    return {"ok": True, "criado": criado, "prospect": row,
            "quando": quando, "ritmo": ritmo.painel()}


def desfazer(prospect_id: int) -> dict:
    """Errou o valor ou marcou o cliente errado. Sem isto, o jeito de corrigir seria
    mexer no banco na mão — que é justamente o que não pode acontecer no campo."""
    import ritmo
    ritmo.garantir_coluna()
    with _db() as c:
        cur = c.execute("UPDATE tracker_prospects SET valor_fechado=NULL, "
                        "status='Em conversa', atualizado_em=? WHERE id=?",
                        (datetime.now(timezone.utc).isoformat(), int(prospect_id)))
        c.commit()
    if not cur.rowcount:
        return {"ok": False, "erro": f"prospect {prospect_id} não existe"}
    return {"ok": True, "prospect_id": int(prospect_id), "ritmo": ritmo.painel()}


if __name__ == "__main__":  # self-check das partes puras (sem tocar no banco)
    assert normalizar("Padaria do Zé") == "padaria do ze"
    assert normalizar("  RESTAURANTE & CIA  LTDA ") == "restaurante cia ltda"
    assert normalizar("Padaria do Zé") == normalizar("padaria do ze")
    assert normalizar(None) == ""
    # tier inválido é recusado ANTES de qualquer escrita
    assert registrar(tier="T9", valor=100)["ok"] is False
    assert "T9" in registrar(tier="T9", valor=100)["erro"]
    # valor zero/negativo/lixo não vira venda
    for v in (0, -1, "abc"):
        r = registrar(prospect_id=1, valor=v)
        assert r["ok"] is False, (v, r)
    # sem prospect e sem nome também não
    assert registrar(valor=500)["ok"] is False
    print("venda OK — nome normalizado (dedup no campo), tier validado, "
          "valor <= 0 e lixo recusados antes de escrever")
