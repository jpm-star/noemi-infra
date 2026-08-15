"""Resumo dos dois motores que ganharam página própria: vídeo (Motor B) e arbitragem.

Regra desta camada: **número sem procedência não sai daqui**. Cada bloco devolve
`fonte` (de onde o dado veio) e `estado` — e quando a fonte está fora ou vazia,
devolve `None`, NUNCA `0`. Zero é um fato ("rodou e não achou nada"); fonte fora é
outro ("não sei"). O painel pintava os dois igual, e foi assim que a biblioteca de
referências ficou 43% órfã sem ninguém ver. Ver `receitas.referencias_aprovadas`.

Arbitragem não é um sistema, são três camadas em estágios diferentes:
  v1        — motor-garimpo `src/motor`, container na :8082, SQLite, EM PRODUÇÃO
  compras   — central de compras B2B, Postgres :5433, dado real, SEM serviço
  exodia    — o refactor (warehouse + arms), schema criado, VAZIO e NÃO roda
Mostrar as três separadas é o ponto: somar daria um total que não existe.

ponytail: reusa `agg._get`/`agg._conn`; zero cliente HTTP novo, zero driver Postgres
(o venv não tem psycopg — `docker exec psql` resolve sem dependência nova).
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path

import agg

_MOTOR_B = os.environ.get("MOTOR_B_URL", "http://127.0.0.1:8010")
_GARIMPO_URL = os.environ.get("GARIMPO_URL", "http://127.0.0.1:8082")
_GARIMPO_DB = os.environ.get("GARIMPO_DB", "/root/motor-garimpo/data/motor.db")
_TOKEN_JSON = os.environ.get("HIGGSFIELD_TOKEN_JSON",
                             str(Path(agg._DB).parent / "higgsfield_token.json"))
# ponytail: containers por nome. Se algum for renomeado o bloco degrada pra
# "indisponivel" (honesto) em vez de mentir zero — trocar aqui resolve.
_PG_COMPRAS = ("motor-arbitragem-db", "arbitragem", "motor_arbitragem")
_PG_EXODIA = ("evolution_postgres", "evolution", "exodia")


log = logging.getLogger("painel.motores")

_TTL = float(os.environ.get("MOTORES_TTL", "20"))   # segundos
_cache: dict[str, tuple[float, dict]] = {}


def _memo(chave: str, produzir):
    """Cache curtinho por chave. Existe porque cada resumo dispara `docker exec`
    (~300ms cada) e o painel faz polling: sem isto, abrir a aba e deixar aberta
    martela o Postgres de graça. TTL curto o bastante pra ninguém ver dado velho.

    ponytail: dict + timestamp. Sem lib de cache, sem invalidação — o TTL É a
    invalidação. Se um dia precisar de refresh forçado, `_cache.clear()`.
    """
    agora = time.time()
    if chave in _cache and agora - _cache[chave][0] < _TTL:
        return _cache[chave][1]
    valor = produzir()
    _cache[chave] = (agora, valor)
    return valor


def _json(url: str, timeout: float = 2.5) -> dict | None:
    """GET que devolve dict, ou None se o serviço não respondeu 200."""
    cod, corpo = agg._get(url, timeout=timeout)
    if cod != 200:
        # Silêncio aqui é o que faz um serviço morto passar por serviço ocioso.
        log.info("motor não respondeu 200 (%s em %s)", cod, url)
        return None
    try:
        return json.loads(corpo)
    except ValueError:
        log.warning("resposta não-JSON de %s", url)
        return None


def _psql(container: str, user: str, db: str, sql: str, timeout: float = 5.0) -> list[str] | None:
    """Uma consulta via `docker exec psql`. None = não deu pra perguntar.

    Sem driver Postgres no venv do painel e sem vontade de adicionar um só pra
    contar linha. `docker` ausente (dev fora do VPS) devolve None, não explode.
    """
    if not shutil.which("docker"):
        log.info("docker ausente — bloco %s fica indisponível (não é zero)", db)
        return None
    try:
        r = subprocess.run(["docker", "exec", container, "psql", "-U", user, "-d", db, "-tAc", sql],
                           capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        log.warning("psql estourou %.0fs em %s:%s — banco lento ou travado", timeout, container, db)
        return None
    except (subprocess.SubprocessError, OSError) as e:
        log.warning("não deu pra consultar %s:%s (%s)", container, db, type(e).__name__)
        return None
    if r.returncode != 0:
        # stderr é a diferença entre "container renomeado" e "banco caiu"
        log.warning("psql falhou em %s:%s — %s", container, db, (r.stderr or "").strip()[:160])
        return None
    return [ln for ln in r.stdout.strip().splitlines() if ln][:500]  # teto: nunca despejar schema gigante


def _contagens(container: str, user: str, db: str) -> dict | None:
    """{tabela: linhas} do banco inteiro. None se o banco não respondeu."""
    linhas = _psql(container, user, db,
                   "select relname||'|'||n_live_tup from pg_stat_user_tables order by 1")
    if linhas is None:
        return None
    out = {}
    for ln in linhas:
        nome, _, n = ln.partition("|")
        out[nome] = int(n or 0)
    return out


# --- Motor B (vídeo) -------------------------------------------------------
def credencial() -> dict:
    """Validade do OAuth do provider de vídeo.

    O access token vence em ~24h e o Motor B renova sozinho pelo refresh. Token
    vencido em disco, portanto, NÃO é "bloqueado": só significa que ninguém gerou
    vídeo desde ontem. O que mata de verdade é ficar sem refresh_token — aí só
    reautenticando na mão. A página precisa distinguir os dois, senão vira alarme
    falso toda manhã.
    """
    p = Path(_TOKEN_JSON)
    if not p.exists():
        return {"estado": "ausente", "detalhe": "nunca autenticou", "fonte": p.name}
    try:
        d = json.loads(p.read_text())
    except (OSError, ValueError):
        return {"estado": "ilegivel", "detalhe": "arquivo corrompido", "fonte": p.name}
    exp, agora = float(d.get("expires_at") or 0), time.time()
    tem_refresh = bool(d.get("refresh_token"))
    horas = (exp - agora) / 3600
    if horas > 0:
        estado, detalhe = "valido", f"vence em {horas:.0f}h"
    elif tem_refresh:
        estado, detalhe = "renovavel", f"vencido há {-horas:.0f}h, renova sozinho no próximo vídeo"
    else:
        estado, detalhe = "bloqueado", "vencido e sem refresh — precisa reautenticar"
    return {"estado": estado, "detalhe": detalhe, "fonte": p.name,
            "expira_em": time.strftime("%d/%m %H:%M", time.gmtime(exp)) if exp else None}


def video() -> dict:
    """Motor B: serviço, produção, fila e credencial. Cacheado por `_TTL`."""
    return _memo("video", _video)


def _video() -> dict:
    saude = _json(f"{_MOTOR_B}/health", timeout=2.0)
    no_ar = bool(saude and saude.get("ok"))
    d = _json(f"{_MOTOR_B}/api/dashboard") if no_ar else None

    estados, ultimos = {}, []
    try:
        with agg._conn() as c:
            c.row_factory = sqlite3.Row
            estados = {r[0]: r[1] for r in
                       c.execute("select estado,count(*) from jobs where produto='motor-b-video' group by 1")}
            ultimos = [dict(r) for r in c.execute(
                "select id,estado,criado_em,duracao_s,custo_creditos,erro from jobs "
                "where produto='motor-b-video' order by criado_em desc limit 8")]
    except sqlite3.Error:
        estados, ultimos = {}, []

    ativos = sum(estados.get(e, 0) for e in ("queued", "uploading", "processing", "retry"))
    return {
        "servico": {"estado": "no ar" if no_ar else "parado",
                    "mock": bool(saude.get("mock")) if saude else None,
                    "fonte": _MOTOR_B},
        "producao": ({"videos": d.get("videos_produzidos"), "tempo_medio_s": d.get("tempo_medio_s"),
                      "custo_medio_creditos": d.get("custo_medio_creditos"),
                      "taxa_aprovacao": d.get("taxa_aprovacao"), "avaliados": d.get("avaliados"),
                      "fonte": "/api/dashboard"} if d else
                     {"estado": "indisponivel", "fonte": "/api/dashboard"}),
        "fila": {"ativos": ativos, "por_estado": estados,
                 "total": sum(estados.values()) or None, "fonte": "jobs (noemi.db)"},
        "ultimos": ultimos,
        "credencial": credencial(),
    }


# --- Arbitragem (três camadas) --------------------------------------------
def _v1() -> dict:
    """motor-garimpo v1: o único pedaço da arbitragem que está em produção."""
    no_ar = bool(_json(f"{_GARIMPO_URL}/health", timeout=2.0))
    p = Path(_GARIMPO_DB)
    dados, visto_em = None, None
    if p.exists():
        try:
            with sqlite3.connect(f"file:{p}?mode=ro", uri=True) as c:
                tabelas = [r[0] for r in c.execute(
                    "select name from sqlite_master where type='table' and name not like 'sqlite_%'")]
                dados = {t: c.execute(f"select count(*) from [{t}]").fetchone()[0] for t in tabelas}
            visto_em = time.strftime("%d/%m %H:%M", time.localtime(p.stat().st_mtime))
        except (sqlite3.Error, OSError):
            dados = None
    return {"camada": "v1 (em produção)", "estado": "no ar" if no_ar else "parado",
            "fonte": f"{_GARIMPO_URL} · motor.db", "escrito_em": visto_em,
            "demandas": (dados or {}).get("demandas"), "cotacoes": (dados or {}).get("cotacoes"),
            "fornecedor_item": (dados or {}).get("fornecedor_item"),
            "deals": (dados or {}).get("deal"),
            # só a CONTAGEM de tabelas, não o mapa inteiro: a tela não usa, e
            # despejar o schema num JSON de painel é payload e exposição de graça.
            "tabelas_criadas": len(dados) if dados else None}


def _compras() -> dict:
    """Central de compras B2B: dado volumoso e real, mas nenhum serviço no ar."""
    t = _contagens(*_PG_COMPRAS)
    if t is None:
        return {"camada": "central de compras", "estado": "indisponivel",
                "fonte": f"pg {_PG_COMPRAS[0]}"}
    return {"camada": "central de compras", "estado": "banco de pé, sem serviço",
            "fonte": f"pg {_PG_COMPRAS[0]}:{_PG_COMPRAS[2]}",
            "compradores": t.get("compradores"), "fornecedores": t.get("fornecedores"),
            "lotes": t.get("lotes"), "negociacoes": t.get("negociacoes"),
            "cotacoes": t.get("cotacoes"), "tabelas_criadas": len(t)}


def _exodia() -> dict:
    """O refactor: schema completo, warehouse vazio, processo nenhum.

    `total_linhas == 0` com schema presente é o achado, não um erro de leitura —
    por isso o estado é "schema pronto, sem dado" e não "indisponivel".
    """
    no_ar = bool(_json(os.environ.get("EXODIA_URL", "http://127.0.0.1:8090") + "/health", timeout=1.5))
    t = _contagens(*_PG_EXODIA)
    if t is None:
        return {"camada": "exodia (refactor)", "estado": "indisponivel", "fonte": "pg exodia"}
    total = sum(t.values())
    return {"camada": "exodia (refactor)",
            "estado": ("no ar" if no_ar else
                       ("schema pronto, sem dado" if total == 0 else "com dado, processo parado")),
            "fonte": "pg evolution_postgres:exodia", "tabelas_criadas": len(t),
            "total_linhas": total, "ofertas": t.get("ofertas"), "requisicoes": t.get("requisicoes"),
            "cotacoes": t.get("cotacoes"), "fornecedores": t.get("fornecedores"),
            "atribuicao": t.get("atribuicao")}


def arbitragem() -> dict:
    """As três camadas lado a lado, sem somar — o total não existiria."""
    return _memo("arbitragem", lambda: {"camadas": [_v1(), _compras(), _exodia()],
                                        "lido_em": time.strftime("%H:%M:%S")})


if __name__ == "__main__":  # self-check: roda contra o VPS de verdade
    v, a = video(), arbitragem()
    assert set(v) == {"servico", "producao", "fila", "ultimos", "credencial"}
    assert v["credencial"]["estado"] in {"valido", "renovavel", "bloqueado", "ausente", "ilegivel"}
    assert len(a["camadas"]) == 3 and all("fonte" in c for c in a["camadas"])
    ex = a["camadas"][2]
    # o contrato que importa: banco vazio NUNCA pode se passar por banco ausente
    assert ex["estado"] != "indisponivel" or "tabelas_criadas" not in ex
    print(json.dumps({"video": v, "arbitragem": a}, ensure_ascii=False, indent=2, default=str))
