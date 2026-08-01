"""Motor de e-mail — gera e-mail de prospecção PERSONALIZADO POR SEGMENTO.

Alvo: empresas COM e-mail (tabela leads_t3t4). Cada e-mail é escrito pela IA
(Groq, via llm_proxy sancionado) ancorado no SEGMENTO do lead + na DOR concreta
(sem site / só rede social / site morto) + cidade + nome. Sem template genérico.

Gera/preview aqui; o ENVIO em si é gated no domínio Resend verificado (ver
prospecção Resend já existente) — este módulo produz assunto+corpo, não dispara.
Degrada honesto: LLM fora → None (nunca inventa e-mail vazio).
"""
from __future__ import annotations

import os
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parents[1] / "packages"))

_DOR = {
    "sem_website": "não tem site nenhum — quem procura pela empresa no Google não acha nada",
    "social_only": "só tem Instagram/rede social — sem site próprio, perde quem pesquisa no Google e quem quer algo mais sério",
    "site_morto": "tinha um site que hoje está fora do ar/quebrado — passa impressão de empresa fechada",
}

_SYS = (
    "Você escreve e-mails de prospecção B2B curtos, humanos e ESPECÍFICOS por segmento — nada de "
    "'espero que esteja bem' nem template genérico. Regras: (1) assunto de até 6 palavras que fala da "
    "DOR ou do resultado, não da JPOS; (2) corpo de 4-6 frases, 1ª frase mostra que você olhou o negócio "
    "DELE (cita o segmento e a dor concreta); (3) oferece um site institucional de 1 página feito rápido, "
    "sem jargão técnico; (4) 1 CTA leve (responder ou WhatsApp), sem pressão; (5) PT-BR, tom de gente, "
    "não de robô. PROIBIDO: 'somos uma empresa que', 'no cenário atual', promessa vazia, e NUNCA "
    "invente URL/link (o link do demo real entra depois; o CTA é só responder ou WhatsApp). "
    'Responda SOMENTE JSON: {"assunto":"...","corpo":"..."}.'
)


def _db() -> sqlite3.Connection:
    p = Path(os.environ.get("LEADS_DB", str(Path(__file__).resolve().parents[2] / "data" / "leads.db")))
    c = sqlite3.connect(p, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def gerar_email(nome: str, segmento: str, cidade: str = "", motivo: str = "sem_website",
                remetente: str = "JP, da JPOS") -> dict | None:
    """IA escreve o e-mail personalizado (assunto+corpo). None se o LLM estiver fora."""
    from shared_core.ai import llm_proxy
    dor = _DOR.get(motivo, _DOR["sem_website"])
    ctx = (f"Empresa: {nome or 'a empresa'}\nSegmento: {segmento or 'negócio local'}\n"
           f"Cidade: {cidade or 'não informada'}\nSituação (dor): {dor}\n"
           f"Assine como: {remetente}")
    txt = llm_proxy.completar(f"{_SYS}\n\nLEAD:\n{ctx}", model="analise", max_tokens=500, temperature=0.6)
    if not txt:
        return None
    m = re.search(r"\{.*\}", txt, re.S)
    if not m:
        return None
    try:
        import json
        d = json.loads(m.group(0))
    except (ValueError, TypeError):
        return None
    assunto = str(d.get("assunto", "")).strip()[:120]
    corpo = str(d.get("corpo", "")).strip()[:2000]
    if not assunto or not corpo:
        return None
    return {"assunto": assunto, "corpo": corpo, "para": nome, "segmento": segmento, "motivo": motivo}


def amostra_por_segmento(n_por_segmento: int = 1, limite_segmentos: int = 6) -> list[dict]:
    """Puxa leads_t3t4 (com email), agrupa por segmento e gera 1 e-mail-amostra por
    segmento — a PROVA de que personaliza por segmento. Read-only, não envia."""
    with _db() as c:
        if not c.execute("SELECT 1 FROM sqlite_master WHERE name='leads_t3t4'").fetchone():
            return []
        segs = [r[0] for r in c.execute(
            "SELECT categoria, COUNT(*) n FROM leads_t3t4 WHERE TRIM(COALESCE(categoria,''))<>'' "
            "GROUP BY categoria ORDER BY n DESC LIMIT ?", (limite_segmentos,))]
        out = []
        for seg in segs:
            for r in c.execute("SELECT nome, categoria, cidade_origem FROM leads_t3t4 "
                               "WHERE categoria=? LIMIT ?", (seg, n_por_segmento)):
                em = gerar_email(r["nome"], r["categoria"], r["cidade_origem"] or "", "sem_website")
                if em:
                    out.append({**em, "cidade": r["cidade_origem"]})
    return out


if __name__ == "__main__":  # self-check offline (LLM mockado, sem rede/DB de produção)
    import json as _json
    from shared_core.ai import llm_proxy
    llm_proxy.completar = lambda *a, **k: _json.dumps({
        "assunto": "Sua clínica some no Google", "corpo": "Oi, vi que a Clínica X de odontologia em Bauru "
        "só tem Instagram — quem pesquisa no Google não te acha. Faço um site de 1 página rápido. Topa ver?"})
    e = gerar_email("Clínica X", "clínica odontológica", "Bauru", "social_only")
    assert e and e["assunto"] and "clínica" in e["corpo"].lower(), e
    assert len(e["assunto"]) <= 120
    # LLM fora → None (não inventa)
    llm_proxy.completar = lambda *a, **k: None
    assert gerar_email("Y", "pet shop") is None
    # JSON ilegível → None
    llm_proxy.completar = lambda *a, **k: "isso não é json"
    assert gerar_email("Z", "academia") is None
    print("email_motor OK — gera assunto+corpo por segmento, degrada p/ None sem LLM/JSON")
