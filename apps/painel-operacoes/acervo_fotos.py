"""Fotos REAIS do segmento — buscadas, julgadas pela visão e guardadas uma vez.

O PROBLEMA (visto na demo Rações & Cia, 2026-08-06): o motor ilustrava os serviços com
`loremflickr.com/600/420/<keyword>`, que devolve uma foto ALEATÓRIA do Flickr para a
palavra. Corrigir a palavra-chave (de `service,professional` pra `dog,grooming,bath`)
melhorou a busca e não resolveu o resultado: a demo saiu com um clipart de banheira e
uma ESTÁTUA de urso ilustrando "Acessórios". Foto errada num site de venda é pior que
foto genérica — parece amador, e é a primeira coisa que o dono do negócio vê.

A CORREÇÃO: parar de confiar na busca e passar a JULGAR o resultado. Openverse dá busca
de verdade (com filtro de licença comercial, sem chave); a visão que já roda em produção
(`shared_core.ai.visao`, Groq multimodal) olha cada candidata e diz se ela realmente
mostra aquele serviço. Sobra foto de banco de imagem de verdade.

A ECONOMIA: o acervo é por SEGMENTO, não por cliente. As 4 fotos de pet shop servem os
99 leads de pet shop. Buscar+julgar custa uma vez na vida do segmento; da segunda demo
em diante é leitura de disco. Por isso o cache mora em `/var/www/sites/_acervo/`, que o
Caddy já serve — sem rota nova, sem copiar bytes pra dentro de cada site.

ponytail: funções puras + um diretório. Sem tabela, sem fila, sem worker.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

log = logging.getLogger(__name__)

# TETO DE TEMPO do acervo inteiro. Sem ele a busca é um loop aninhado
# (serviços x candidatas) e cada julgamento de visão pode levar 20-60s quando o Groq
# está em rate limit ou devolve só raciocínio sem resposta — medido: uma geração T1 de
# nicho novo passou de 400s e o cliente do outro lado da mesa esperando. O acervo é
# ENFEITE: estourou o orçamento, entrega o que já julgou e o motor completa o resto com
# o banco de imagem. Melhor site em 60s com 2 fotos do que 7 minutos com 4.
ORCAMENTO_S = float(os.environ.get("ACERVO_ORCAMENTO_S", "75"))
RAIZ = Path(os.environ.get("ACERVO_DIR", "/var/www/sites/_acervo"))
URL_BASE = os.environ.get("ACERVO_URL", "/_acervo")   # o Caddy já serve /var/www/sites
_UA = "noemi-motor-site/1.0 (+https://jpos.com.br)"    # WAF do Groq/Flickr recusa o UA do urllib
_OPENVERSE = "https://api.openverse.org/v1/images/"

# Abaixo disto é ícone, clipart ou thumbnail — descarta antes de gastar visão.
MIN_BYTES = 45_000
CANDIDATAS = 8      # quantas o Openverse traz por serviço
TENTATIVAS_VISAO = 5  # quantas a visão chega a julgar (as demais são reserva)


def _slug(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (t or "").lower()).strip("-") or "generico"


def _servicos(nicho: str) -> list[tuple[str, str, str]]:
    """Reusa o catálogo do motor — a ORDEM tem que ser a mesma, senão a foto de banho
    e tosa vai parar no card de ração."""
    raiz = "/root/motor-site"
    if raiz not in sys.path:
        sys.path.insert(0, raiz)
    from app.servicos import servicos_do_segmento
    return servicos_do_segmento(nicho)


def _http(url: str, timeout: int = 25) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def buscar(termo: str, quantas: int = CANDIDATAS) -> list[str]:
    """URLs candidatas no Openverse. Só licença comercial — o site é de um cliente
    pagante, não dá pra ilustrar com foto que proíbe uso comercial."""
    q = urllib.parse.urlencode({
        "q": termo.replace(",", " "), "license_type": "commercial", "mature": "false",
        "page_size": str(quantas), "extension": "jpg"})
    try:
        d = json.loads(_http(f"{_OPENVERSE}?{q}"))
    except Exception as e:  # noqa: BLE001 — Openverse fora do ar não pode matar a geração
        log.warning("Openverse falhou para %r: %s", termo, e)
        return []
    return [r["url"] for r in d.get("results", []) if r.get("url")]


_PROMPT = (
    "Você avalia se uma FOTO serve de ilustração para o site de um negócio.\n"
    "A foto deve ilustrar: {servico} — num(a) {nicho}.\n"
    "Responda APROVADO se for uma fotografia real, nítida, do assunto certo, que caiba "
    "num site profissional. Responda REPROVADO se for desenho/clipart/ilustração, se o "
    "assunto estiver errado, se for escura, borrada, amadora, ou se tiver texto/marca "
    "d'água por cima. Na dúvida, REPROVADO.\n"
    "Formato: uma palavra (APROVADO ou REPROVADO), depois 5 palavras de motivo.")


def _visao_aprova(imagem: bytes, servico: str, nicho: str) -> tuple[bool, str]:
    """A visão olha a foto e decide.

    SEM JUIZ É REPROVAÇÃO, não aprovação. A primeira versão aprovava quando a visão não
    respondia — e como ela falhava justamente em rajada (TPM), o resultado era o pior
    dos mundos: as fotos que ENTRARAM no site foram exatamente as que ninguém olhou.
    Foto não julgada não pode virar material de venda; se sobrar sem acervo, o motor
    volta pro banco de imagem, que é o comportamento honesto.

    O TPM da visão se recompõe em 60s, e isto roda uma vez por segmento na vida —
    esperar é o recurso mais barato que existe aqui."""
    raiz = str(Path(__file__).resolve().parents[2] / "packages")
    if raiz not in sys.path:
        sys.path.insert(0, raiz)
    from shared_core.ai import visao
    for tentativa in range(3):
        try:
            txt, fonte = visao.analisar_frames(
                [imagem], prompt=_PROMPT.format(servico=servico, nicho=nicho))
        except Exception as e:  # noqa: BLE001
            txt, fonte = "", f"erro:{type(e).__name__}"
        if fonte == "groq" and txt.strip():
            t = txt.strip()
            return ("REPROVADO" not in t.upper()[:400], t[:90])
        if tentativa < 2:  # janela de TPM é por minuto — espera e tenta de novo
            time.sleep(20 + tentativa * 20)
    return False, f"SEM JUIZ após 3 tentativas (fonte={fonte}) — não entra"


def _garante_chave_groq() -> None:
    """A visão exige GROQ_API_KEY em os.environ; o painel roda sem ela exportada."""
    if os.environ.get("GROQ_API_KEY", "").strip():
        return
    for env in ("/root/noemi-infra/.env", "/root/sdr-motor/.env"):
        p = Path(env)
        if not p.is_file():
            continue
        for l in p.read_text(errors="ignore").splitlines():
            if l.strip().startswith("GROQ_API_KEY="):
                os.environ["GROQ_API_KEY"] = l.split("=", 1)[1].strip().strip('"').strip("'")
                return


def garantir(nicho: str, forcar: bool = False) -> list[str]:
    """URLs das fotos do segmento, na MESMA ordem dos serviços. [] se nada aprovou.

    Primeira chamada de um segmento: busca, julga e grava. Da segunda em diante: disco.
    Nunca levanta — sem fotos o motor volta ao banco de imagem de antes."""
    seg = _slug(nicho)
    destino = RAIZ / seg
    manifesto = destino / "manifesto.json"
    if manifesto.is_file() and not forcar:
        try:
            return json.loads(manifesto.read_text())["urls"]
        except (OSError, ValueError, KeyError):
            pass
    _garante_chave_groq()
    try:
        servicos = _servicos(nicho)
    except Exception as e:  # noqa: BLE001
        log.warning("catálogo de %r indisponível: %s", nicho, e)
        return []
    destino.mkdir(parents=True, exist_ok=True)
    urls, diario = [], []
    _fim = time.monotonic() + ORCAMENTO_S
    for i, (nome, _desc, kw) in enumerate(servicos):
        escolhida = ""
        if time.monotonic() >= _fim:
            # não faz break: as posições restantes precisam existir como "" pra o
            # motor casar foto com serviço pelo ÍNDICE. Lista curta desalinharia tudo.
            diario.append(f"{nome}: pulada — orçamento de {ORCAMENTO_S:.0f}s do acervo estourou")
            urls.append("")
            continue
        for j, cand in enumerate(buscar(kw)):
            if j >= TENTATIVAS_VISAO or time.monotonic() >= _fim:
                break
            try:
                b = _http(cand)
            except Exception:  # noqa: BLE001 — link morto no Flickr é comum
                continue
            if len(b) < MIN_BYTES:
                diario.append(f"{nome}: descartada por tamanho ({len(b)}B) — {cand[:70]}")
                continue
            ok, motivo = _visao_aprova(b, nome, nicho)
            diario.append(f"{nome}: {'APROVADA' if ok else 'reprovada'} — {motivo} — {cand[:70]}")
            if ok:
                arq = destino / f"{i + 1}.jpg"
                arq.write_bytes(b)
                escolhida = f"{URL_BASE}/{seg}/{arq.name}"
                break
        urls.append(escolhida)
    # ACERVO PARCIAL É VÁLIDO. A primeira versão exigia foto pra TODOS os serviços e
    # zerava a lista se faltasse uma — na prática o Flickr CC tem foto boa de "banho e
    # tosa" e nenhuma de "consulta veterinária", então 2 fotos reais viravam 0. O motor
    # aceita buraco: posição vazia cai no banco de imagem, posição preenchida usa a foto
    # julgada. 2 reais + 2 de banco é melhor que 4 de banco.
    _estourou = sum(1 for d in diario if "orçamento" in d)
    log.info("acervo de %r: %d/%d posições com foto julgada%s",
             nicho, sum(1 for u in urls if u), len(urls),
             f" ({_estourou} pulada(s) por tempo)" if _estourou else "")
    try:
        manifesto.write_text(json.dumps(
            {"nicho": nicho, "urls": urls, "diario": diario}, ensure_ascii=False, indent=1))
    except OSError:
        pass
    return urls


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Popula o acervo de fotos de um segmento.")
    ap.add_argument("nicho", nargs="?", default="pet shop")
    ap.add_argument("--forcar", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    # self-check das partes puras (sem rede)
    assert _slug("Pet Shop") == "pet-shop" and _slug("") == "generico"
    us = garantir(a.nicho, forcar=a.forcar)
    print(f"\n{a.nicho}: {len(us)} fotos → {us}")
    m = RAIZ / _slug(a.nicho) / "manifesto.json"
    if m.is_file():
        for l in json.loads(m.read_text()).get("diario", []):
            print("  ·", l)
