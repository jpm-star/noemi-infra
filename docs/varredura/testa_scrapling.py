"""Scrapling — teste TÉCNICO, só contra domínio do JP.

ESCOPO, cravado em código e não só na conversa: a lista de alvos tem exatamente os
domínios que o JP controla. Qualquer outro levanta antes de tocar a rede. Isto não é
teatro — é o que impede o script de virar ferramenta de raspagem de terceiro quando
alguém copiar e colar daqui.

A pergunta que este teste responde: o Scrapling recupera as 25 referências que hoje
voltam RASAS (casca de página renderizada por JS)? Não testo as 18 bloqueadas por
anti-bot: contornar proteção de site que não é do JP está fora de escopo por decisão
dele, e é a parte do Scrapling que existe justamente pra isso.
"""
import sys
import time

sys.path.insert(0, "/root/.claude/jobs/6e8fe3a5/tmp/sandbox/libs")
sys.path.insert(0, "/root/noemi-infra/apps/painel-operacoes")

PERMITIDOS = ("jpos.com.br", "landing.jpos.com.br", "p.jpos.com.br", "chinelospedi.com")


def guarda(url: str) -> str:
    from urllib.parse import urlparse
    host = (urlparse(url).hostname or "").lower()
    if host not in PERMITIDOS:
        raise SystemExit(f"RECUSADO: {host!r} não é domínio do JP. Permitidos: {PERMITIDOS}")
    return url


ALVO = guarda("https://jpos.com.br/")

print("=" * 66)
print("A) fetch atual do motor (ingestao._buscar) — a linha de base")
print("=" * 66)
try:
    import ingestao
    t0 = time.monotonic()
    html = ingestao._buscar(ALVO)
    ms = round((time.monotonic() - t0) * 1000)
    print(f"  {ms}ms · {len(html):,} chars")
    import referencias_scrap as rs
    blocos = rs._blocos_do_html(html)
    print(f"  blocos de estrutura extraídos: {len(blocos)}")
    print(f"  -> {'SALVA' if len(blocos) >= 3 else 'RASA'} pelo critério do motor (>=3)")
except Exception as e:  # noqa: BLE001
    print("  FALHOU:", type(e).__name__, str(e)[:150])

print()
print("=" * 66)
print("B) Scrapling Fetcher (HTTP, sem navegador)")
print("=" * 66)
try:
    from scrapling.fetchers import Fetcher
    t0 = time.monotonic()
    p = Fetcher.get(ALVO, timeout=30)
    ms = round((time.monotonic() - t0) * 1000)
    corpo = p.html_content if hasattr(p, "html_content") else str(p)
    print(f"  {ms}ms · status {getattr(p, 'status', '?')} · {len(corpo):,} chars")
    # o diferencial de API: seletor adaptativo, não só parser
    h1 = p.css_first("h1")
    print(f"  h1: {(h1.text if h1 else '(nenhum)')[:70]}")
    print(f"  links: {len(p.css('a'))} · seções: {len(p.css('section'))}")
except Exception as e:  # noqa: BLE001
    print("  FALHOU:", type(e).__name__, str(e)[:200])

print()
print("=" * 66)
print("C) Scrapling DynamicFetcher (navegador, renderiza JS) — o ponto do teste")
print("=" * 66)
try:
    from scrapling.fetchers import DynamicFetcher
    t0 = time.monotonic()
    p = DynamicFetcher.fetch(ALVO, headless=True, network_idle=True, timeout=60000)
    ms = round((time.monotonic() - t0) * 1000)
    corpo = p.html_content if hasattr(p, "html_content") else str(p)
    print(f"  {ms}ms · {len(corpo):,} chars")
    print(f"  seções após render: {len(p.css('section'))}")
    print("  -> é ESTE modo que recuperaria as 25 referências 'rasas'")
except Exception as e:  # noqa: BLE001
    print("  FALHOU:", type(e).__name__, str(e)[:220])
