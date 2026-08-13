"""O catálogo vive em 4 lugares. Este teste é o único motivo deles não divergirem.

    precos.json                  -> o que o cliente PAGA (fonte única de preço)
    tier_contrato.ESCOPO         -> o que o motor EXECUTA
    criacao.html (o seletor)     -> o que o JP LÊ na hora de escolher o tier
    sdr-motor site_chat._TIERS   -> o que a Noemi RESPONDE no site (outro repo)

Nada obriga os quatro a concordar. Já divergiram: de 11 a 13/08/2026 o precos.json
dizia "Calendar NAO entra no T3" enquanto tier_contrato e site_chat já entregavam
Calendar no T3 — o material de venda e o produto contando histórias diferentes sobre
o MESMO tier. Teste de unidade não pega: cada arquivo está certo sozinho.

A checagem é por CONCEITO (calendar, e-mail, multi-página...), não por texto igual:
as quatro fontes escrevem pra públicos diferentes e devem mesmo ter redações
diferentes. O que não pode divergir é EM QUAL TIER o conceito aparece.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

import precos            # noqa: E402
import tier_contrato     # noqa: E402

SDR_SITE_CHAT = Path("/root/sdr-motor/backend/app/site_chat.py")

# As variantes precisam ser ESPECÍFICAS o bastante pra não colidir com outro produto.
# "e-mail" sozinho não serve: o upsell `dominio_email` (@empresa.com.br) e o e-mail do
# T3 (notificação/relatório) são coisas diferentes que dividem a palavra — casar por ela
# acusava cobrança dupla onde não havia. Por isso o conceito do T3 ancora em "notifica",
# que só aparece no e-mail transacional.
CONCEITOS = {
    "T2": {"multi-página": ("multi-página", "multi-pagina"),
           "seo": ("seo",),
           "geo": ("geo",)},
    "T3": {"ia no site": ("ia nativa no site",),
           "calendar": ("calendar",),
           "e-mail de notificação": ("notifica",)},
    "T4": {"painel do cliente": ("painel de operações do cliente",
                                 "painel de operacoes do cliente")},
}
ORDEM_TIERS = ("T1", "T2", "T3", "T4")


def _norm(txt):
    return re.sub(r"\s+", " ", (txt or "").lower())


def _entrega_precos(tier_id):
    t = next(x for x in precos.tudo()["tiers"] if x["id"] == tier_id)
    return _norm(" ".join(t["entrega"]))


def _entrega_contrato(tier_id):
    return _norm(" ".join(tier_contrato.ESCOPO[tier_id]))


@pytest.mark.parametrize("tier_id,conceitos", sorted(CONCEITOS.items()))
def test_conceito_aparece_no_mesmo_tier_nas_duas_fontes(tier_id, conceitos):
    """precos.json (o que o cliente paga) e tier_contrato (o que o motor faz)
    precisam concordar sobre EM QUE TIER cada entrega entra."""
    pago, feito = _entrega_precos(tier_id), _entrega_contrato(tier_id)
    for nome, variantes in conceitos.items():
        no_pago = any(v in pago for v in variantes)
        no_feito = any(v in feito for v in variantes)
        assert no_pago == no_feito, (
            f"{tier_id}: o conceito '{nome}' está em "
            f"{'precos.json' if no_pago else 'tier_contrato'} e falta em "
            f"{'tier_contrato.ESCOPO' if no_pago else 'precos.json'}. "
            f"Ou o cliente paga por algo que o motor não faz, ou o motor entrega "
            f"algo que ninguém está cobrando.\n  precos.json: {pago}\n  contrato:   {feito}")


def test_upsell_nao_vende_o_que_o_tier_ja_entrega():
    """Cobrar de um T3 pelo Calendar que o T3 já inclui é cobrar duas vezes.

    É a razão do campo `disponivel_em` existir de verdade — antes de 13/08 ele era
    decorativo (nenhum renderizador lia) porque todo upsell valia pros 4 tiers.
    """
    for u in precos.tudo()["upsells"]:
        nome = _norm(u["nome"] + " " + u.get("resumo", ""))
        for tier_id in u.get("disponivel_em") or precos.TODOS_OS_TIERS:
            core = _entrega_contrato(tier_id)
            for conceitos in CONCEITOS.values():
                for conceito, variantes in conceitos.items():
                    if any(v in nome for v in variantes) and any(v in core for v in variantes):
                        pytest.fail(
                            f"upsell '{u['id']}' é oferecido ao {tier_id}, mas '{conceito}' "
                            f"já é entrega core desse tier — o cliente pagaria duas vezes. "
                            f"Tire {tier_id} de disponivel_em.")


def test_escopo_upsell_e_lido_pelos_materiais():
    """O campo existe; os materiais têm que MOSTRAR. Guard contra ele voltar a ser
    decorativo — que é como um upsell restrito vaza pro cliente errado."""
    restritos = [u for u in precos.tudo()["upsells"] if precos.escopo_upsell(u)]
    assert restritos, ("nenhum upsell restrito no catálogo — se isso é intencional, "
                       "apague este teste; se não, alguém zerou um disponivel_em")
    md = precos.tabela_markdown(cliente=True)
    html = precos.catalogo_html(cliente=True)
    for u in restritos:
        escopo = precos.escopo_upsell(u)
        assert escopo in md, f"a tabela markdown não diz que '{u['id']}' é {escopo}"
        assert escopo in html, f"o catálogo PDF não diz que '{u['id']}' é {escopo}"


def test_escopo_upsell_vazio_quando_vale_pra_todos():
    assert precos.escopo_upsell({"disponivel_em": ["T1", "T2", "T3", "T4"]}) == ""
    assert precos.escopo_upsell({}) == ""
    assert precos.escopo_upsell({"disponivel_em": ["T1", "T2"]}) == "só T1 e T2"
    assert precos.escopo_upsell({"disponivel_em": ["T4"]}) == "só T4"


def test_seletor_do_painel_nao_promete_o_que_o_tier_nao_entrega():
    """O rótulo do seletor é RESUMO, não contrato: omitir uma entrega é inofensivo,
    prometer uma que só existe num tier acima é a mentira que o JP repete na call.
    Por isso o teste guarda uma direção só.

    (A primeira versão exigia que o rótulo citasse toda entrega core — e reprovou
    "T2 — + multi-página, SEO, AEO, GEO" por escrever "SEO" e não "SEO técnico".
    Teste que reprova abreviação correta treina a gente a ignorar teste.)
    """
    html = (RAIZ / "criacao.html").read_text(encoding="utf-8")
    gt, lt = chr(62), chr(60)
    for pos, tier_id in enumerate(ORDEM_TIERS):
        padrao = 'option value="' + tier_id + '"[^' + gt + ']*' + gt + '(.*?)' + lt + '/option'
        m = re.search(padrao, html, re.S)
        if not m:
            continue
        rotulo = _norm(m.group(1))
        for tier_futuro in ORDEM_TIERS[pos + 1:]:
            for nome, variantes in CONCEITOS.get(tier_futuro, {}).items():
                achou = [v for v in variantes if v in rotulo]
                assert not achou, (
                    f"o rótulo do {tier_id} no painel ('{rotulo.strip()}') menciona "
                    f"'{nome}', que só entra no {tier_futuro}. O JP lê esse rótulo na "
                    f"call e promete uma entrega do tier de cima.")


def test_seletor_anuncia_o_calendar_no_t3():
    """Específico de propósito: Calendar é a entrega que saiu do core em 11/08 e voltou
    em 13/08. Se sumir do rótulo de novo, o JP para de vender o que o produto faz."""
    html = (RAIZ / "criacao.html").read_text(encoding="utf-8")
    gt, lt = chr(62), chr(60)
    padrao = 'option value="T3"[^' + gt + ']*' + gt + '(.*?)' + lt + '/option'
    m = re.search(padrao, html, re.S)
    assert m, "criacao.html não tem opção pro T3"
    assert "calendar" in _norm(m.group(1)), (
        f"o rótulo do T3 ('{m.group(1).strip()}') não menciona Calendar, que é entrega core")


@pytest.mark.skipif(not SDR_SITE_CHAT.exists(), reason="sdr-motor não está nesta máquina")
def test_sdr_motor_nao_divergiu_do_contrato():
    """Outro repo, outro deploy: a Noemi responde `_TIERS` no site. Se ela listar
    Calendar num tier diferente do contrato, o visitante ouve uma coisa e o cliente
    recebe outra. Lido do FONTE (não importado): o sdr-motor não está no sys.path."""
    txt = SDR_SITE_CHAT.read_text(encoding="utf-8")
    bloco = re.search(r"_TIERS = \[(.*?)\n\]", txt, re.S)
    assert bloco, "não achei _TIERS em site_chat.py — o formato mudou, ajuste o teste"
    tiers = dict(re.findall(r'\{"tier": "(T\d)",.*?"entrega": \[(.*?)\]\}', bloco.group(1), re.S))
    assert set(tiers) == set(tier_contrato.ORDEM), f"tiers do sdr-motor: {sorted(tiers)}"
    for tier_id, conceitos in CONCEITOS.items():
        la = _norm(tiers[tier_id])
        for nome, variantes in conceitos.items():
            aqui = any(v in _entrega_contrato(tier_id) for v in variantes)
            assert aqui == any(v in la for v in variantes), (
                f"{tier_id}: '{nome}' diverge entre tier_contrato (painel) e "
                f"site_chat._TIERS (sdr-motor). A Noemi promete no site o que o "
                f"motor não entrega, ou o contrário.")


# ---------------------------------------------------------------------------
# O CONTRATO é a quinta fonte — e a única que alguém ASSINA.
#
# Até 13/08/2026 o §1 prometia, no Tier 1 (R$500, sem mensalidade), "IA que monitora
# dados e integra Google Calendar e planilha de controle". Calendar é core do T3/T4 e
# módulo pago no T1/T2; planilha de controle NÃO EXISTE no produto — `sheets_append`
# vive em shared-core/google_integ.py com zero chamadores.
#
# Divergência em apostila custa uma call constrangida. Divergência em contrato assinado
# custa obrigação de entregar. Por isso este guard é separado e mais duro que os outros.
# ---------------------------------------------------------------------------
CONTRATO = Path("/root/noemi-infra/docs/CONTRATO_JPOS_template.md")


def _objeto() -> str:
    """A cláusula 1 (OBJETO) — só ela. Os módulos pagos vivem na 1.1 e podem, sim,
    citar Calendar: lá é o lugar CERTO de citar."""
    txt = CONTRATO.read_text(encoding="utf-8")
    i = txt.index("## 1. OBJETO")
    j = txt.index("## 1.1", i)
    return txt[i:j]


def _linha_do_tier(objeto: str, tier_id: str) -> str:
    """A entrada INTEIRA daquele tier, que quase sempre ocupa mais de uma linha.

    A primeira versão deste helper devolvia só a linha do marcador, e o teste reprovou
    o contrato por não citar "GEO" e "Calendar" — que estavam ali, na linha seguinte,
    porque o markdown quebra em 96 colunas. Teste que reprova texto correto por causa
    da largura da coluna treina a gente a ignorar teste.
    """
    rotulo = f"Tier {tier_id[1]}"
    linhas = objeto.splitlines()
    for i, linha in enumerate(linhas):
        if rotulo not in linha or "[[" not in linha:
            continue
        pedaco = [linha]
        for prox in linhas[i + 1:]:
            if not prox.strip() or prox.lstrip().startswith(("- [[", "#", ">")):
                break            # começou outro item / outra seção
            pedaco.append(prox)
        return " ".join(pedaco)
    return ""


# O contrato chama o cliente de CONTRATANTE — é a palavra juridicamente correta ali,
# não um sinônimo descuidado. O vocabulário do catálogo (voltado pro JP e pro material
# de venda) diz "cliente". Os dois estão certos no lugar deles.
SINONIMOS_CONTRATO = {"painel do cliente": ("painel de operações do contratante",
                                            "painel de operacoes do contratante")}


@pytest.mark.skipif(not CONTRATO.exists(), reason="template de contrato não está aqui")
def test_contrato_nao_promete_calendar_nem_planilha_no_t1():
    """O erro exato que foi corrigido. Se voltar, alguém assina obrigação inexistente."""
    linha = _norm(_linha_do_tier(_objeto(), "T1"))
    assert linha, "não achei a linha do Tier 1 no §1 do contrato"
    assert "calendar" not in linha, (
        f"o Tier 1 do CONTRATO voltou a prometer Calendar: {linha!r}. "
        f"Calendar é core do T3/T4 e módulo pago (cláusula 1.1) no T1/T2.")
    assert "planilha" not in linha, (
        f"o Tier 1 do CONTRATO promete planilha: {linha!r}. Planilha de controle NÃO "
        f"EXISTE no produto — sheets_append não tem nenhum chamador.")


@pytest.mark.skipif(not CONTRATO.exists(), reason="template de contrato não está aqui")
def test_contrato_planilha_nao_aparece_em_tier_nenhum():
    """Enquanto o produto não tiver Sheets ligado, nenhum tier pode prometer planilha."""
    obj = _norm(_objeto())
    assert "planilha" not in obj, (
        "alguma cláusula do OBJETO promete planilha de controle, e o produto não faz "
        "isso em lugar nenhum. Se Sheets for ligado de verdade, apague este teste junto.")


@pytest.mark.skipif(not CONTRATO.exists(), reason="template de contrato não está aqui")
@pytest.mark.parametrize("tier_id", ["T2", "T3", "T4"])
def test_contrato_bate_com_o_que_o_motor_executa(tier_id):
    """Cada tier do contrato tem que citar as entregas que o motor de fato executa
    naquele tier. O contrato é resumo, então só cobramos os conceitos do PRÓPRIO tier —
    não os herdados, que a linha cobre com "tudo do Tier anterior"."""
    linha = _norm(_linha_do_tier(_objeto(), tier_id))
    assert linha, f"não achei a linha do {tier_id} no §1 do contrato"
    for nome, variantes in CONCEITOS.get(tier_id, {}).items():
        variantes = tuple(variantes) + SINONIMOS_CONTRATO.get(nome, ())
        assert any(v in linha for v in variantes), (
            f"o {tier_id} do CONTRATO não menciona '{nome}', que tier_contrato.ESCOPO "
            f"lista como entrega desse tier. O cliente assina menos do que recebe — ou, "
            f"pior, discute depois o que estava incluído.\n  contrato: {linha}")


@pytest.mark.skipif(not CONTRATO.exists(), reason="template de contrato não está aqui")
def test_contrato_diz_que_calendar_ja_vem_no_t3_t4():
    """O módulo pago da 1.1 precisa avisar que T3/T4 JÁ TÊM. Sem essa frase, o mesmo
    template vende ao T3 uma peça que ele já paga — foi exatamente o erro que o campo
    `disponivel_em` passou a impedir no catálogo."""
    txt = CONTRATO.read_text(encoding="utf-8")
    bloco = txt[txt.index("## 1.1"):][:2500]
    achou = [l for l in bloco.splitlines() if "calendar" in _norm(l)]
    assert achou, "a cláusula 1.1 não lista o módulo Calendar"
    vizinhanca = _norm(" ".join(bloco.splitlines()[
        bloco.splitlines().index(achou[0]):bloco.splitlines().index(achou[0]) + 4]))
    assert "tiers 3 e 4" in vizinhanca or "t3" in vizinhanca, (
        "o módulo Calendar da cláusula 1.1 não avisa que T3/T4 já o incluem — "
        "assim dá pra vender duas vezes a mesma entrega.")
