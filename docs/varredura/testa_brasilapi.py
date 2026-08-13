"""Testa BrasilAPI contra os gaps MEDIDOS do JPOS. Sandbox: nada toca produção."""
import json
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, "/root/noemi-infra/packages")
from shared_core.ai import http_llm  # reusa o UA que resolveu o 403 do Groq

BASE = "https://brasilapi.com.br/api"


def get(rota, timeout=20):
    req = urllib.request.Request(BASE + rota, headers={"User-Agent": http_llm.UA})
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read())
    return d, round((time.monotonic() - t0) * 1000)


print("=" * 66)
print("GAP 1 — CEP estruturado (antipadrão: não gerar mapa sem CEP e número)")
print("=" * 66)
try:
    d, ms = get("/cep/v2/16400-000")          # Lins/SP, onde a Pé Di produz
    print(f"  {ms}ms  {d.get('city')}/{d.get('state')} · {d.get('street') or '(sem rua)'} "
          f"· bairro {d.get('neighborhood') or '-'}")
    print(f"  coordenadas: {(d.get('location') or {}).get('coordinates')}")
    print("  -> serve: valida o endereço do briefing E devolve lat/long pro mapa")
except Exception as e:  # noqa: BLE001
    print("  FALHOU:", type(e).__name__, str(e)[:120])

print()
print("=" * 66)
print("GAP 2 — feriados (a estrutura 'aberto agora' mente sem isso)")
print("=" * 66)
try:
    d, ms = get("/feriados/v1/2026")
    print(f"  {ms}ms  {len(d)} feriados nacionais de 2026")
    for f in d[:4]:
        print(f"    {f['date']}  {f['name']}")
    print("  -> serve: 'aberto agora' que não diz aberto no dia 25/12")
except Exception as e:  # noqa: BLE001
    print("  FALHOU:", type(e).__name__, str(e)[:120])

print()
print("=" * 66)
print("GAP 3 — CNPJ (hoje o JPOS usa cnpja, que exige chave)")
print("=" * 66)
try:
    d, ms = get("/cnpj/v1/33000167000101")     # Petrobras, CNPJ público
    print(f"  {ms}ms  {d.get('razao_social')}")
    print(f"  atividade: {str(d.get('cnae_fiscal_descricao'))[:60]}")
    print(f"  município: {d.get('municipio')} · situação: {d.get('descricao_situacao_cadastral')}")
    print("  -> serve: enriquecimento sem chave; compara com o cnpja pago")
except Exception as e:  # noqa: BLE001
    print("  FALHOU:", type(e).__name__, str(e)[:120])

print()
print("=" * 66)
print("GAP 4 — DDD -> cidades (raio de atendimento sem geocoder pago)")
print("=" * 66)
try:
    d, ms = get("/ddd/v1/14")                  # DDD de Lins/Bauru/Marília
    cid = d.get("cities") or []
    print(f"  {ms}ms  DDD 14 = {d.get('state')} · {len(cid)} cidades")
    print(f"  amostra: {', '.join(cid[:8])}")
    print("  -> serve: 'atendemos toda a região' com lista real, não chute")
except Exception as e:  # noqa: BLE001
    print("  FALHOU:", type(e).__name__, str(e)[:120])
