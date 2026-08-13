"""Cliente HTTP dos provedores de LLM — com o User-Agent que NÃO pode faltar.

POR QUE ESTE ARQUIVO EXISTE. Em 13/08/2026 as 7 chaves Groq do projeto falharam ao
mesmo tempo com `HTTP 403 error code 1010`. Sete chaves falhando juntas parece chave
revogada, e o caminho natural dali é rotacionar tudo — meia hora de trabalho e um
susto, resolvendo nada.

Não era chave. Era falta de `User-Agent`: o Cloudflare na frente da API do Groq
recusa requisição sem UA por integridade de navegador, e o 1010 não diz isso.
A urllib do Python manda `Python-urllib/3.x` por padrão, que é exatamente o que
esse filtro derruba.

O QUE TORNA ISSO CARO É A REDESCOBERTA. O conhecimento JÁ EXISTIA no repositório:
`shared-core/ai/visao.py` mandava "curl/8.5.0" e `motor-site/app/providers/
llm_orquestrador.py` tinha um `_UA` — cada um resolveu sozinho, em silêncio, sem
deixar o motivo escrito. Quem escreveu o oitavo chamador não tinha como saber, e
pagou o mesmo pedágio. Um default compartilhado com o porquê ao lado é a diferença
entre resolver uma vez e resolver toda vez.

USE `headers()` EM QUALQUER CHAMADA A PROVEDOR DE LLM. Se precisar de header extra,
passe em `extra` — não monte o dicionário na mão, porque montar na mão é como o UA
some de novo.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

# UA de cliente HTTP real e comum. Não é disfarce de navegador: é identificação
# honesta que o filtro de integridade aceita. `curl/8.5.0` é o que já estava em uso
# no visao.py e funciona há meses — trocar por algo "mais bonito" sem necessidade
# seria reabrir a mesma investigação.
UA = os.environ.get("LLM_USER_AGENT", "curl/8.5.0")

TIMEOUT = int(os.environ.get("LLM_TIMEOUT_S", "180"))


def headers(token: str = "", *, tipo: str = "bearer", extra: dict | None = None) -> dict:
    """Cabeçalhos padrão de chamada a LLM. `tipo`: bearer | goog | nenhum."""
    h = {"Content-Type": "application/json", "User-Agent": UA}
    if token and tipo == "bearer":
        h["Authorization"] = f"Bearer {token}"
    elif token and tipo == "goog":
        h["x-goog-api-key"] = token
    h.update(extra or {})
    return h


def post_json(url: str, corpo: dict, token: str = "", *, tipo: str = "bearer",
              timeout: int | None = None, extra: dict | None = None) -> dict:
    """POST JSON -> dict. Levanta HTTPError com o corpo do erro legível anexado.

    O anexo importa: o erro cru do Cloudflare vem como uma página HTML e o traceback
    padrão mostra só "HTTP Error 403: Forbidden", que foi metade do tempo perdido no
    incidente que originou este módulo.
    """
    req = urllib.request.Request(
        url, data=json.dumps(corpo).encode(),
        headers=headers(token, tipo=tipo, extra=extra))
    try:
        with urllib.request.urlopen(req, timeout=timeout or TIMEOUT) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        det = (e.read()[:400].decode(errors="replace") if e.fp else "")
        e.msg = f"{e.msg} — corpo: {det}"
        raise


def groq(mensagens: list[dict], token: str, *, modelo: str = "llama-3.3-70b-versatile",
         temperatura: float = 0.7, teto: int = 4000) -> str:
    """Uma chamada de chat ao Groq. O teto é generoso de propósito: modelo de
    RACIOCÍNIO (qwen, gpt-oss) gasta o orçamento pensando antes de responder, e um
    teto apertado devolve o raciocínio sem a resposta — desperdício silencioso que
    parece resposta ruim."""
    d = post_json("https://api.groq.com/openai/v1/chat/completions",
                  {"model": modelo, "messages": mensagens,
                   "temperature": temperatura, "max_tokens": teto}, token)
    return d["choices"][0]["message"]["content"]


if __name__ == "__main__":  # self-check offline
    h = headers("abc")
    assert h["User-Agent"] == UA and h["Authorization"] == "Bearer abc"
    assert "Python-urllib" not in h["User-Agent"], "o UA padrão do urllib é o que apanha"
    g = headers("k", tipo="goog")
    assert g["x-goog-api-key"] == "k" and "Authorization" not in g
    assert headers()["User-Agent"] == UA          # sem token, o UA continua
    assert headers("t", extra={"X-Teste": "1"})["X-Teste"] == "1"
    print(f"http_llm OK — UA={UA!r} em toda chamada, bearer/goog/sem token, extra preservado")
