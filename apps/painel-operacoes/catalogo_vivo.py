"""Catálogo que cresce com o uso — nicho e estrutura viram candidatos, não exceções.

O PROBLEMA QUE ISTO RESOLVE. `estilos.PERFIS` conhece 7 nichos. Um cliente de
"loja de bicicletas" não casa com nenhum, e `escolher()` cai num perfil VAZIO: sem
principal, sem acento, composição genérica — e ninguém fica sabendo. O site sai, o
JP não vê aviso, e o nicho nunca entra no catálogo porque nada registrou que ele
apareceu. Lista estática só cresce quando alguém lembra de crescer.

COMO CRESCE. Duas fontes, os dois com o MESMO critério que o aprendizado de estilo já
usa (2+ ocorrências — ver MIN_REJEICOES em memoria_estilo):

  NICHO      — toda geração com segmento fora de PERFIS incrementa um contador.
               2+ vezes = o nicho é real, não digitação de uma vez só.
  ESTRUTURA  — composições que SOBREVIVERAM (o operador não pediu outra) e se
               repetiram. Não há caminho de escrita novo: sai de `estilo_decisoes`,
               que já grava tudo desde a Frente 2.

POR QUE 2 E NÃO 1: um nicho digitado errado ("clinica de esteticaa") apareceria uma
vez e poluiria o catálogo pra sempre. Duas vezes já é padrão, não acidente.

POR QUE NÃO PROMOVE SOZINHO: promover é decidir que o motor passa a ter uma OPINIÃO
estética sobre aquele nicho — quais morfismos, com que justificativa comercial. Isso
é escrita de vocabulário, não contagem. O mecanismo sinaliza; quem escreve o perfil
é gente. Promover sozinho encheria PERFIS de entradas sem justificativa, que é
exatamente o que faz o motor devolver composição genérica com cara de intencional.

`promovido` marca o que já virou perfil de verdade, pra parar de aparecer na fila.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from collections import Counter
from datetime import datetime, timezone

log = logging.getLogger("catalogo_vivo")

MIN_PROMOCAO = 2

_DDL = """
CREATE TABLE IF NOT EXISTS catalogo_candidatos (
  tipo        TEXT    NOT NULL,
  chave       TEXT    NOT NULL,
  rotulo      TEXT    NOT NULL DEFAULT '',
  ocorrencias INTEGER NOT NULL DEFAULT 0,
  promovido   INTEGER NOT NULL DEFAULT 0,
  primeira    TEXT    NOT NULL,
  ultima      TEXT    NOT NULL,
  PRIMARY KEY (tipo, chave)
);
"""


def _conn():
    import memoria_estilo
    c = memoria_estilo._conn()
    c.executescript(_DDL)
    return c


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalizar(txt: str) -> str:
    """Sem acento, minúsculo, espaço colapsado. 'Clínica  Estética' e 'clinica
    estetica' são o MESMO nicho — contar separado nunca chegaria a 2."""
    t = unicodedata.normalize("NFKD", str(txt or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()


def conhecido(segmento: str) -> str:
    """A chave de PERFIS que casa com este segmento, ou "" se nenhuma.

    Mesma regra de casamento que `estilos.escolher` usa (substring), pra o candidato
    nunca discordar da composição que saiu de fato.
    """
    try:
        import estilos
        seg = normalizar(segmento)
        return next((k for k in estilos.PERFIS if k in seg), "")
    except Exception:  # noqa: BLE001
        return ""


def registrar_nicho(segmento: str) -> dict:
    """Conta o nicho se ele for desconhecido. Nunca levanta.

    Devolve {novo, chave, ocorrencias, pronto} — `pronto` = já bateu o mínimo e está
    esperando alguém escrever o perfil.
    """
    chave = normalizar(segmento)
    if not chave:
        return {"novo": False, "chave": "", "ocorrencias": 0, "pronto": False}
    if conhecido(segmento):
        return {"novo": False, "chave": chave, "ocorrencias": 0, "pronto": False}
    try:
        with _conn() as c:
            c.execute(
                "INSERT INTO catalogo_candidatos (tipo,chave,rotulo,ocorrencias,primeira,ultima) "
                "VALUES ('nicho',?,?,1,?,?) "
                "ON CONFLICT(tipo,chave) DO UPDATE SET "
                "  ocorrencias = ocorrencias + 1, ultima = excluded.ultima",
                (chave, str(segmento or "").strip()[:80], _agora(), _agora()))
            n = c.execute("SELECT ocorrencias FROM catalogo_candidatos "
                          "WHERE tipo='nicho' AND chave=?", (chave,)).fetchone()[0]
        return {"novo": True, "chave": chave, "ocorrencias": n,
                "pronto": n >= MIN_PROMOCAO}
    except Exception:  # noqa: BLE001 — catálogo é observabilidade, não caminho crítico
        log.warning("não consegui registrar o nicho %r", segmento, exc_info=True)
        return {"novo": False, "chave": chave, "ocorrencias": 0, "pronto": False}


def nomear_estrutura(decisoes: list[dict]) -> str:
    """Nome legível seguindo o padrão do catálogo ("Hero + X").

    O principal nomeia a página; cada acento entra como "+ <seção> <estilo>". Sem
    isso o candidato apareceria como um JSON, e ninguém promove o que não consegue ler.
    """
    principal = next((d.get("estilo") for d in (decisoes or [])
                      if d.get("alvo") == "página"), "")
    acentos = [f"{d.get('alvo')} {d.get('estilo')}" for d in (decisoes or [])
               if d.get("alvo") and d.get("alvo") != "página" and d.get("estilo")]
    if not principal and not acentos:
        return ""
    return " + ".join([principal or "sem principal"] + acentos)


def _assinatura(decisoes: list[dict]) -> str:
    """Chave estável da composição: ordem dos acentos não muda a identidade dela."""
    principal = next((d.get("estilo") for d in (decisoes or [])
                      if d.get("alvo") == "página"), "")
    acentos = sorted(f"{d.get('alvo')}:{d.get('estilo')}" for d in (decisoes or [])
                     if d.get("alvo") and d.get("alvo") != "página" and d.get("estilo"))
    return "|".join([principal] + acentos)


def candidatos_estrutura(minimo: int = MIN_PROMOCAO) -> list[dict]:
    """Composições que SOBREVIVERAM e se repetiram.

    Sai de `estilo_decisoes` — a mesma tabela do aprendizado por rejeição. Não existe
    escrita nova: sobreviver já é um fato registrado (rejeitada=0). Se eu criasse um
    segundo caminho de escrita, ele divergiria do primeiro no dia em que alguém
    mexesse só num deles.
    """
    import json
    try:
        with _conn() as c:
            linhas = c.execute(
                "SELECT nicho, composicao FROM estilo_decisoes WHERE rejeitada=0").fetchall()
    except Exception:  # noqa: BLE001
        return []
    contagem: Counter = Counter()
    exemplo: dict[str, dict] = {}
    for l in linhas:
        try:
            dec = json.loads(l["composicao"])
        except (ValueError, TypeError):
            continue
        assin = _assinatura(dec)
        if not assin.strip("|"):
            continue
        contagem[assin] += 1
        exemplo.setdefault(assin, {"nome": nomear_estrutura(dec), "nichos": set()})
        exemplo[assin]["nichos"].add(l["nicho"] or "?")
    fora = []
    for assin, n in contagem.most_common():
        if n < minimo:
            continue
        fora.append({"chave": assin, "nome": exemplo[assin]["nome"], "ocorrencias": n,
                     "nichos": sorted(exemplo[assin]["nichos"])})
    return fora


def candidatos_nicho(minimo: int = MIN_PROMOCAO, incluir_todos: bool = False) -> list[dict]:
    try:
        with _conn() as c:
            linhas = c.execute(
                "SELECT chave, rotulo, ocorrencias, promovido, primeira, ultima "
                "FROM catalogo_candidatos WHERE tipo='nicho' AND promovido=0 "
                "ORDER BY ocorrencias DESC, ultima DESC").fetchall()
    except Exception:  # noqa: BLE001
        return []
    return [dict(l) for l in linhas
            if incluir_todos or l["ocorrencias"] >= minimo]


def promover(tipo: str, chave: str) -> dict:
    """Marca como promovido — depois de ALGUÉM ter escrito o perfil de verdade.

    Não escreve em `estilos.PERFIS`: perfil pede justificativa comercial por morfismo,
    e isso é texto que uma contagem não sabe produzir.
    """
    try:
        with _conn() as c:
            cur = c.execute("UPDATE catalogo_candidatos SET promovido=1 "
                            "WHERE tipo=? AND chave=?", (tipo, normalizar(chave) if tipo == "nicho" else chave))
        return {"ok": bool(cur.rowcount), "tipo": tipo, "chave": chave}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "erro": str(e)[:160]}


def crescimento(minimo: int = MIN_PROMOCAO) -> dict:
    """O relatório: quanto o catálogo cresceu e o que está esperando decisão."""
    try:
        import estilos
        no_catalogo = len(estilos.PERFIS)
    except Exception:  # noqa: BLE001
        no_catalogo = 0
    vistos = candidatos_nicho(incluir_todos=True)
    prontos = [n for n in vistos if n["ocorrencias"] >= minimo]
    try:
        with _conn() as c:
            promovidos = c.execute("SELECT COUNT(*) FROM catalogo_candidatos "
                                   "WHERE promovido=1").fetchone()[0]
    except Exception:  # noqa: BLE001
        promovidos = 0
    estruturas = candidatos_estrutura(minimo)
    return {
        "minimo": minimo,
        "nichos_no_catalogo": no_catalogo,
        "nichos_vistos_fora": len(vistos),
        "nichos_prontos": prontos,
        "nichos_promovidos": promovidos,
        "estruturas_candidatas": estruturas,
        "leitura": (
            f"{len(prontos)} nicho(s) apareceram {minimo}+ vezes e ainda não têm perfil "
            f"— até escreverem, o site desses clientes sai com composição genérica."
            if prontos else
            f"nenhum nicho novo bateu {minimo} ocorrências ainda; "
            f"{len(vistos)} apareceram uma vez só (pode ser digitação)."),
    }


if __name__ == "__main__":  # self-check em banco TEMPORÁRIO
    import os
    import sys
    import tempfile
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    os.environ["NOEMI_DATA_DIR"] = tempfile.mkdtemp(prefix="catalogo-test-")

    assert normalizar("Clínica  Estética") == "clinica estetica"
    assert normalizar("Clínica Estética") == normalizar("clinica estetica")
    # nicho JÁ conhecido não vira candidato
    assert conhecido("clinica de estetica") == "clinica"
    assert registrar_nicho("clinica de estetica")["novo"] is False
    # nicho novo conta, e só fica "pronto" na 2ª vez
    r1 = registrar_nicho("loja de bicicletas")
    assert r1["novo"] and r1["ocorrencias"] == 1 and not r1["pronto"], r1
    r2 = registrar_nicho("Loja de Bicicletas")          # caixa/acento diferente
    assert r2["ocorrencias"] == 2 and r2["pronto"], r2  # mesma chave, não duplicou
    assert len(candidatos_nicho()) == 1
    # digitado uma vez só NÃO entra na fila
    registrar_nicho("floricultura")
    assert len(candidatos_nicho()) == 1, candidatos_nicho()
    assert len(candidatos_nicho(incluir_todos=True)) == 2
    # nome de estrutura legível
    dec = [{"alvo": "página", "estilo": "minimal"},
           {"alvo": "cta-final", "estilo": "brutalism"}]
    assert nomear_estrutura(dec) == "minimal + cta-final brutalism", nomear_estrutura(dec)
    # assinatura ignora a ORDEM dos acentos
    a = [{"alvo": "página", "estilo": "minimal"}, {"alvo": "faq", "estilo": "skeuo"},
         {"alvo": "cta", "estilo": "brutal"}]
    b = [{"alvo": "página", "estilo": "minimal"}, {"alvo": "cta", "estilo": "brutal"},
         {"alvo": "faq", "estilo": "skeuo"}]
    assert _assinatura(a) == _assinatura(b)
    # promover tira da fila
    assert promover("nicho", "Loja de Bicicletas")["ok"]
    assert candidatos_nicho() == []
    rel = crescimento()
    assert rel["nichos_promovidos"] == 1 and rel["nichos_no_catalogo"] >= 7, rel
    print(f"catalogo_vivo OK — chave normalizada (acento/caixa não duplicam), "
          f"1 ocorrência não promove, {rel['nichos_no_catalogo']} nichos no catálogo, "
          f"assinatura estável à ordem dos acentos")
