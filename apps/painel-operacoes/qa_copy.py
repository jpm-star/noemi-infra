"""QA de copy: revisor LLM entre "copy gerada" e "site publicado".

Hoje o pipeline do motor-site é atômico (pipeline.py:36 sintetiza, :38 renderiza, :39
publica) — copy torta vai pro ar sem ninguém olhar. Este módulo é o portão: revisa a
copy com a MESMA cascata Groq que a escreveu (gateway LiteLLM → Groq direto), dá 1
retry se reprovar e BLOQUEIA no 2º fail, registrando o veto pra auditoria.

Arquivo novo, ninguém chama ainda. Integração (passo seguinte): gerar a copy via
`orquestrador_ativo().sintetizar(...)`, passar por `portao()` e devolver a copy aprovada
pro motor pelo campo `copy_livre` do briefing.

Self-check offline: python3 qa_copy.py --check
"""
from __future__ import annotations

import json
import sqlite3
import sys
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from typing import Any, Callable

_SEVERIDADES = ("ok", "leve", "grave")

_SYS = (
    "Você é editor-chefe de landing pages de conversão no Brasil. Recebe a copy de um "
    "site já gerado e o nicho do negócio, e faz REVISÃO CRÍTICA. Avalie: (1) gramática e "
    "ortografia em português do Brasil; (2) tom — profissional, direto, sem gíria e sem "
    "promessa irreal; (3) coerência com o nicho — a copy tem que soar de quem trabalha "
    "NESSE ramo, sem termo de outro setor; (4) clichê vazio ('referência em', 'qualidade "
    "e compromisso', 'resultado que fala por si'); (5) repetição da mesma ideia em seções "
    "diferentes; (6) fato inventado ou número que ninguém deu. "
    "Você NÃO reescreve, só julga. Responda SOMENTE em JSON: "
    "aprovado (boolean), problemas (lista de strings curtas e específicas, citando o "
    "trecho; lista vazia se aprovado), severidade (string: 'ok' se nada relevante, 'leve' "
    "se só ajuste cosmético, 'grave' se erro de gramática, tom errado, incoerência com o "
    "nicho ou fato inventado). Severidade 'grave' implica aprovado=false."
)


@dataclass
class Veredito:
    aprovado: bool
    problemas: list[str] = field(default_factory=list)
    severidade: str = "ok"
    tentativa: int = 1
    bloqueado: bool = False

    def dict(self) -> dict:
        return asdict(self)


def _texto_copy(copy: Any) -> str:
    """BriefingSite (dataclass) ou dict → só os campos de texto que o revisor julga."""
    d = asdict(copy) if is_dataclass(copy) and not isinstance(copy, type) else dict(copy or {})
    secoes = [{"titulo": str(s.get("titulo", "")), "corpo": str(s.get("corpo", ""))}
              for s in (d.get("secoes") or []) if isinstance(s, dict)]
    return json.dumps({k: d.get(k, "") for k in
                       ("nome_empresa", "headline", "subheadline", "cta_titulo", "cta_texto")}
                      | {"secoes": secoes}, ensure_ascii=False)


def _cascata() -> Callable[..., dict]:
    """A cascata Groq que já existe no motor-site. `criacao._montar_site()` faz o setup
    de sys.path + carrega o .env com a chave (mesmo caminho da geração).

    A chave é RESOLVIDA aqui por `_chave()` (env -> SITE_LLM_API_KEY -> .env do
    sdr-motor). Sem isso o revisor chamava `_groq_json` com chave vazia: o gateway
    LiteLLM respondia 401, o fallback direto do Groq não tinha credencial, e TODA
    revisão virava "revisor indisponível" -> severidade grave -> site bloqueado.
    Fail-closed é o comportamento certo, mas com chave vazia ele bloqueia 100% dos
    sites, inclusive os de copy boa.
    """
    import criacao
    criacao._montar_site()
    from app.providers.llm_orquestrador import _chave, _groq_json

    def chamar(prompt_sys: str, prompt_user: str, _chave_ignorada: str = "",
               temperatura: float = 0.2) -> dict:
        return _groq_json(prompt_sys, prompt_user, _chave_ignorada or _chave(), temperatura)

    return chamar


def revisar(copy: Any, nicho: str, *, chamar: Callable[..., dict] | None = None) -> Veredito:
    """Revisa a copy com o LLM. `chamar(sys, user, chave, temperatura)` injetável (testes).

    Falha do LLM NÃO aprova por omissão: vira veredito grave (o portão trata)."""
    chamar = chamar or _cascata()
    user = f"Nicho do negócio: {nicho or '(não informado)'}\nCopy gerada:\n{_texto_copy(copy)}"
    try:
        d = chamar(_SYS, user, "", 0.2)  # temperatura baixa: revisão, não criação
    except Exception as e:
        return Veredito(False, [f"revisor indisponível: {type(e).__name__}: {e}"], "grave")
    problemas = [str(p).strip() for p in (d.get("problemas") or []) if str(p).strip()][:10]
    sev = str(d.get("severidade", "")).strip().lower()
    sev = sev if sev in _SEVERIDADES else ("grave" if problemas else "ok")
    aprovado = bool(d.get("aprovado")) and sev != "grave"
    return Veredito(aprovado, problemas, sev)


# ---------------------------------------------------------------- auditoria

def _tabela(c: sqlite3.Connection) -> sqlite3.Connection:
    c.execute("""CREATE TABLE IF NOT EXISTS qa_copy_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        criado_em TEXT, ref TEXT, nicho TEXT,
        tentativa INTEGER, aprovado INTEGER, bloqueado INTEGER,
        severidade TEXT,
        problemas TEXT,   -- JSON [str]
        headline TEXT)""")
    c.commit()
    return c


def _db(con: sqlite3.Connection | None = None) -> sqlite3.Connection:
    if con is not None:
        return _tabela(con)
    from shared_core.storage import db
    return _tabela(db.conn())


def _registrar(v: Veredito, copy: Any, nicho: str, ref: str,
               con: sqlite3.Connection | None) -> None:
    """Auditoria do veto. Nunca derruba a geração: log quebrado vai pro stderr."""
    d = asdict(copy) if is_dataclass(copy) and not isinstance(copy, type) else dict(copy or {})
    linha = (datetime.now(timezone.utc).isoformat(timespec="seconds"), ref, nicho,
             v.tentativa, int(v.aprovado), int(v.bloqueado), v.severidade,
             json.dumps(v.problemas, ensure_ascii=False), str(d.get("headline", ""))[:300])
    try:
        c = _db(con)
        c.execute("""INSERT INTO qa_copy_log
            (criado_em, ref, nicho, tentativa, aprovado, bloqueado, severidade, problemas, headline)
            VALUES (?,?,?,?,?,?,?,?,?)""", linha)
        c.commit()
    except Exception as e:
        print(f"[qa_copy] log falhou ({e}): {linha}", file=sys.stderr)


def bloqueios(limite: int = 20, con: sqlite3.Connection | None = None) -> list[dict]:
    """Sinal pro operador: o que o QA barrou e por quê (mais recente primeiro)."""
    c = _db(con)
    rows = c.execute("SELECT * FROM qa_copy_log WHERE bloqueado=1 ORDER BY id DESC LIMIT ?",
                     (limite,)).fetchall()
    return [dict(r) | {"problemas": json.loads(r["problemas"] or "[]")} for r in rows]


# ---------------------------------------------------------------- portão

def portao(gerar_copy: Callable[[], Any], nicho: str, *, ref: str = "",
           chamar: Callable[..., dict] | None = None,
           con: sqlite3.Connection | None = None) -> tuple[Any | None, Veredito]:
    """ENTRADA DO INTEGRADOR. Gera → revisa → 1 retry → bloqueia.

    `gerar_copy()` é a síntese (chamada até 2x, a 2ª regenera do zero). Devolve
    (copy_aprovada, veredito) ou (None, veredito) quando bloqueia — nunca publica
    sozinho no 2º fail. Todo veredito fica em qa_copy_log.
    """
    v = Veredito(False)
    copy = None
    for tentativa in (1, 2):
        copy = gerar_copy()
        v = revisar(copy, nicho, chamar=chamar)
        v.tentativa = tentativa
        if v.aprovado:
            _registrar(v, copy, nicho, ref, con)
            return copy, v
        _registrar(v, copy, nicho, ref, con)   # reprovação da 1ª também é auditoria
    v.bloqueado = True
    _registrar(v, copy, nicho, ref, con)
    return None, v


if __name__ == "__main__":  # self-check offline: sem rede, sem banco de produção
    if "--check" not in sys.argv:
        sys.exit("uso: python3 qa_copy.py --check")
    _copy = {"nome_empresa": "Studio X", "headline": "Treino guiado em 45 min",
             "subheadline": "Plano montado por avaliação física",
             "secoes": [{"titulo": "Avaliação", "corpo": "Medimos antes de montar o plano."}],
             "cta_texto": "Agendar", "cta_titulo": "Comece pela avaliação"}
    _c = _tabela(sqlite3.connect(":memory:"))
    _c.row_factory = sqlite3.Row

    def _fake(*respostas):
        """LLM falso: devolve uma resposta por chamada, na ordem. Conta as chamadas."""
        fila = list(respostas)
        chamadas = []
        def f(s, u, k, t):
            chamadas.append(u)
            return fila.pop(0)
        f.chamadas = chamadas
        return f

    _ok = {"aprovado": True, "problemas": [], "severidade": "ok"}
    _mal = {"aprovado": False, "problemas": ["clichê 'referência em'"], "severidade": "grave"}

    # 1) aprovado de primeira: 1 geração, 1 revisão, publica
    ger = _fake(_ok)
    n = {"g": 0}
    def _gera():
        n["g"] += 1
        return _copy
    c1, v1 = portao(_gera, "academia", ref="t1", chamar=ger, con=_c)
    assert c1 is _copy and v1.aprovado and not v1.bloqueado, v1
    assert n["g"] == 1 and len(ger.chamadas) == 1, (n, ger.chamadas)

    # 2) 1 fail → retry regenera e passa
    ger = _fake(_mal, _ok)
    n["g"] = 0
    c2, v2 = portao(_gera, "academia", ref="t2", chamar=ger, con=_c)
    assert c2 is _copy and v2.aprovado and v2.tentativa == 2 and not v2.bloqueado, v2
    assert n["g"] == 2 and len(ger.chamadas) == 2, (n, ger.chamadas)

    # 3) 2 fails → BLOQUEIA, não publica, sinaliza
    ger = _fake(_mal, _mal)
    n["g"] = 0
    c3, v3 = portao(_gera, "academia", ref="t3", chamar=ger, con=_c)
    assert c3 is None and v3.bloqueado and not v3.aprovado, v3
    assert n["g"] == 2 and len(ger.chamadas) == 2, (n, ger.chamadas)
    assert v3.problemas == ["clichê 'referência em'"], v3

    # 4) auditoria: 1 bloqueio listado, com o motivo; e o log tem as 3 rodadas
    b = bloqueios(con=_c)
    assert len(b) == 1 and b[0]["ref"] == "t3" and b[0]["problemas"] == _mal["problemas"], b
    total = _c.execute("SELECT count(*) FROM qa_copy_log").fetchone()[0]
    assert total == 6, total   # t1:1  t2:2  t3:2 reprovas + 1 bloqueio

    # 5) severidade 'grave' vinda com aprovado=true não passa (LLM incoerente)
    v = revisar(_copy, "academia", chamar=_fake({"aprovado": True, "problemas": ["erro de crase"],
                                                 "severidade": "grave"}))
    assert not v.aprovado and v.severidade == "grave", v

    # 6) LLM fora do ar NÃO aprova por omissão
    def _explode(*a):
        raise RuntimeError("gateway fora")
    v = revisar(_copy, "academia", chamar=_explode)
    assert not v.aprovado and v.severidade == "grave" and "indisponível" in v.problemas[0], v

    print("qa_copy --check OK: aprovado publica · 1 fail vira retry · 2 fails bloqueiam "
          f"e sinalizam ({len(b)} bloqueio auditado, {total} vereditos no log)")
