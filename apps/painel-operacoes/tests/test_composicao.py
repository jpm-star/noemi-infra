"""A composição visual: o motor usa VÁRIOS morfismos e diz por quê.

Estes testes existem porque a versão anterior compunha no papel e não na tela.
Medido antes de reescrever:
  · 4 dos 7 perfis miravam `preco`/`antes-depois` — seções que o motor NUNCA emitiu.
    O CSS saía `section.preco{...}` e não casava com nada.
  · o perfil da clínica pedia vidro sobre neumorfismo. Neumorfismo chapa o body em
    #e8ecf2; vidro é branco a 10% => diferença de 2/2/1 por canal, invisível.
  · o morfismo era injetado SÓ na home; as 5 páginas irmãs do T2 saíam com outra cara.
Empilhar mais estilos sem travar isso teria multiplicado acento fantasma.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import estilos as est  # noqa: E402


def test_todo_acento_declarado_mira_secao_que_o_motor_emite():
    """Foi assim que 4 de 7 perfis viraram enfeite invisível."""
    ruins = [f"{n}: {a['estilo']} em {a['secao']}"
             for n, p in est.PERFIS.items() for a in p["acentos"]
             if a["secao"] not in est.SECOES_EMITIDAS]
    assert not ruins, f"acento mira seção inexistente (CSS não casa com nada): {ruins}"


def test_todo_acento_declarado_e_visivel_sobre_o_proprio_principal():
    ruins = []
    for nome, p in est.PERFIS.items():
        # cada acento tem que funcionar sobre PELO MENOS UM dos principais do segmento
        # (o "Gerar outro" alterna entre eles, e a regra de compatibilidade poda o resto)
        for a in p["acentos"]:
            if not any(est.compativel(pr, a["estilo"])[0] for pr, _ in p["principais"]):
                ruins.append(f"{nome}: {a['estilo']} em {a['secao']} não funciona sobre "
                             f"nenhum principal do segmento")
    assert not ruins, ruins


def test_vidro_sobre_fundo_chapado_e_recusado():
    """A regra saiu do CSS real, não de gosto — tem que continuar valendo."""
    ok, motivo = est.compativel("neumorphism", "glassmorphism")
    assert not ok and "invisível" in motivo, motivo
    # e o inverso é legítimo: neumorfismo tem sombra própria, aparece sobre qualquer coisa
    assert est.compativel("minimal", "neumorphism")[0]


def test_acento_do_mesmo_peso_nao_acentua():
    assert not est.compativel("glassmorphism", "spatial")[0], \
        "mesmo peso visual é troca lateral que ninguém percebe"
    assert est.compativel("minimal", "brutalism")[0]


def test_todo_perfil_tem_justificativa_em_cada_decisao():
    """Decisão que ninguém sabe defender é indistinguível de sorteio."""
    for nome, p in est.PERFIS.items():
        assert p["principais"], f"{nome}: sem principal"
        for est_nome, porque in p["principais"]:
            assert est_nome in est.ESTILOS, f"{nome}: principal {est_nome!r} não existe"
            assert porque.strip(), f"{nome}/{est_nome}: principal sem justificativa"
        for a in p["acentos"]:
            assert a["porque"].strip(), f"{nome}/{a['secao']}: acento sem justificativa"
    for c in est.escolher("advocacia", "T3")["decisoes"]:
        assert c["porque"] and c["comunica"], c


def test_composicao_escala_com_o_tier():
    """T1 é isca e não paga elaboração; T3/T4 podem ousar."""
    n = lambda t: len(est.escolher("academia", t, semente=0)["acento"])  # noqa: E731
    assert n("T1") == 0 and n("T2") == 1
    assert n("T3") >= 1 and n("T3") > n("T2"), "T3 paga mais elaboração que T2"
    assert n("T4") == n("T3"), "T4 herda o teto do T3 — acima de 3 morfismos vira bagunça"
    assert est.escolher("academia", "T1")["principal"] == "minimal"


def test_compor_usa_o_html_real_e_nao_uma_lista_estatica():
    esc = est.escolher("advocacia", "T3", semente=0)
    com_faq = '<section class="faq reveal">x</section>'
    sem_faq = '<section class="cta-final reveal">x</section>'
    assert "faq" in est.compor(esc, com_faq)["acento"]
    c = est.compor(esc, sem_faq)
    assert "faq" not in c["acento"]
    assert any("não existe nesta página" in d for d in c["descartes"])
    # o principal SEMPRE fica: é ele que dá coerência entre home e páginas irmãs
    assert c["principal"] == esc["principal"]


def test_teto_e_aplicado_depois_do_html_nao_antes():
    """A advocacia gastava um slot em `calc` (4% dos sites) e ficava com um acento a
    menos que o tier pagou. O teto vale sobre o que APARECE."""
    html = ('<section class="faq reveal">x</section>'
            '<section class="cta-final reveal">y</section>')
    assert len(est.compor(est.escolher("advocacia", "T2", 0), html)["acento"]) == 1
    assert len(est.compor(est.escolher("advocacia", "T3", 0), html)["acento"]) == 2

    # e o alvo raro não come vaga: `calc` sai em 4% dos sites. Antes o teto era
    # aplicado ANTES de saber o que aparece, e a advocacia ficava com um acento a
    # menos que o tier pagou.
    esc = est.escolher("advocacia", "T3", 2)
    assert any(c["alvo"] == "calc" for c in esc["candidatos"]), esc["candidatos"]
    assert len(est.compor(esc, html)["acento"]) == 2, "vaga desperdiçada em seção ausente"


def test_gerar_outro_muda_a_composicao_de_verdade():
    """Botão que devolve a mesma página envenena a memória: o operador clica de novo
    achando que rejeitou algo diferente, e o sistema conta duas rejeições da mesma
    composição. Foi o que aconteceu quando a semente girava só a ordem dos acentos."""
    vistas = {est.escolher("advocacia", "T3", s)["porque"] for s in range(4)}
    assert len(vistas) > 1, "'Gerar outro' tem que mudar algo que o operador VÊ"

    # mas nunca vira loteria entre os 9: só as alternativas declaradas do segmento
    declarados = {e for e, _ in est.PERFIS["advocacia"]["principais"]}
    usados = {est.escolher("advocacia", "T3", s)["principal"] for s in range(8)}
    assert usados <= declarados, f"principal fora do perfil: {usados - declarados}"

    # e regerar o MESMO lead tem que dar o MESMO site
    assert est.escolher("academia", "T2", 3) == est.escolher("academia", "T2", 3)


def test_nunca_repete_o_mesmo_morfismo_em_dois_alvos():
    """Dois blocos brutalistas não são duas ênfases — o visitante lê 'o site é assim'."""
    for seg in est.PERFIS:
        for s in range(6):
            c = est.escolher(seg, "T4", semente=s)
            usados = [d["estilo"] for d in c["decisoes"]]
            assert len(usados) == len(set(usados)), f"{seg}/s{s}: morfismo repetido {usados}"


def test_evitar_nunca_zera_a_composicao():
    """Memória que apaga o resultado é pior que memória nenhuma."""
    todos = [f"{a['secao']}:{a['estilo']}" for a in est.PERFIS["advocacia"]["acentos"]]
    c = est.escolher("advocacia", "T3", semente=0, evitar=todos)
    assert c["principal"], "o principal nunca sai — o site ficaria sem acabamento"
    assert c["acento"] == {} and c["recusados"]


def test_condicional_marcado_para_o_preview_nao_mentir():
    por_alvo = {d["alvo"]: d for d in est.escolher("advocacia", "T3", 2)["candidatos"]}
    assert por_alvo["calc"]["condicional"] is True, "calc sai em 4% dos sites"
    assert por_alvo["faq"]["condicional"] is False, "faq sai na maioria"
    # depoimento depende de o cliente ter mandado depoimento — 18% dos sites
    dep = {d["alvo"]: d for d in est.escolher("clinica", "T3", 0)["candidatos"]}
    assert dep["depo"]["condicional"] is True


def test_segmento_desconhecido_degrada_sem_quebrar():
    c = est.escolher("loja de parafuso", "T3")
    assert c["principal"] == "" and c["acento"] == {} and c["decisoes"] == []
    assert est.bloco(c["principal"], c["acento"]) == ""
