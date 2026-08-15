"""Trava a SINCRONIA ESTRUTURAL entre endpoint HTTP e a função que ele chama.

POR QUE EXISTE: a geração de site caiu em produção com

    TypeError: gerar() takes from 2 to 18 positional arguments but 19 were given

`variacao` ("Gerar outro") foi implementado no front e no endpoint, e nunca chegou
na assinatura de `criacao.gerar`. Nenhum teste falhou, porque nenhum teste olhava
os dois arquivos ao mesmo tempo — é o quinto caso desse padrão no ecossistema:
dois arquivos que PRECISAM concordar, sem nada que force a concordância.

O TypeError foi o desfecho bom. Com o parâmetro inserido no MEIO da lista posicional
em vez do fim, `cidade` teria virado `receita_nome` sem erro nenhum, e o site sairia
publicado com os campos trocados — descoberto pelo dono, não pelo log.
"""
import inspect
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))


def _main_do_painel():
    """Carrega `main.py` DESTE app pelo caminho, nunca por `import main`.

    `apps/motor-b-video/main.py` e `apps/painel-operacoes/main.py` disputam a mesma
    chave em sys.modules. Rodando as duas suítes no mesmo processo, quem importasse
    primeiro vencia, e este teste passava a inspecionar o endpoint do app ERRADO.
    Deu AttributeError e ficou óbvio — mas o desfecho ruim era pior e silencioso: se os
    dois módulos tivessem um atributo de mesmo nome, o guard aprovaria a comparação de
    um arquivo com outro que não tem nada a ver, e continuaria verde para sempre.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location("main_painel_operacoes", RAIZ / "main.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _campos_do_endpoint(fn) -> set[str]:
    """Nomes que o endpoint recebe de fato — menos os de infra do FastAPI."""
    return {n for n in inspect.signature(fn).parameters if n != "request"}


def test_gerar_aceita_tudo_que_o_endpoint_recebe():
    import criacao

    main = _main_do_painel()
    endpoint = _campos_do_endpoint(main.criacao_gerar)
    alvo = set(inspect.signature(criacao.gerar).parameters)

    # o endpoint renomeia 3 campos ao repassar: são os únicos apelidos permitidos.
    apelidos = {"foto": "foto", "video": "video", "fotos": "fotos", "autofill": "autofill"}
    faltando = {c for c in endpoint if apelidos.get(c, c) not in alvo}

    assert not faltando, (
        f"o endpoint /api/criacao/gerar recebe {sorted(faltando)} mas criacao.gerar() "
        f"não aceita — a geração vai estourar TypeError em produção. "
        f"Adicione o parâmetro na assinatura de gerar().")


def test_chamada_e_por_nome_nao_por_posicao():
    """Passar 19 posicionais é o que torna o desalinhamento silencioso.

    Lido por AST, não por texto: a função é passada como VALOR (`to_thread(gerar, ...)`,
    `partial(gerar, ...)`), então não basta procurar `criacao.gerar(`. A pergunta é se
    sobra algum argumento posicional depois dela — e só a árvore responde isso.
    """
    import ast
    arvore = ast.parse((Path(__file__).resolve().parents[1] / "main.py").read_text())

    def e_o_alvo(no) -> bool:
        return (isinstance(no, ast.Attribute) and no.attr == "gerar"
                and getattr(no.value, "id", "") == "criacao")

    achou = False
    for no in ast.walk(arvore):
        if not isinstance(no, ast.Call):
            continue
        # forma 1: criacao.gerar(...) — args são dela
        if e_o_alvo(no.func):
            achou, posicionais, onde = True, len(no.args), no.lineno
        # forma 2: envolvida — to_thread(criacao.gerar, a, b) / partial(criacao.gerar, a)
        elif no.args and e_o_alvo(no.args[0]):
            achou, posicionais, onde = True, len(no.args) - 1, no.lineno
        else:
            continue
        assert posicionais == 0, (
            f"criacao.gerar recebe {posicionais} argumento(s) posicional(is) na linha "
            f"{onde} de main.py. Um parâmetro novo no meio da lista troca os valores em "
            f"silêncio — passe tudo por nome.")

    assert achou, "não achei a chamada de criacao.gerar em main.py — o teste ficou cego"


def test_semente_e_estavel_e_variacao_anda_uma_casa():
    import criacao
    assert criacao._semente("Ferreira e Rachid") == criacao._semente("Ferreira e Rachid")
    assert criacao._semente("X", 0, 0) == criacao._semente("X"), \
        "variacao=0 tem que devolver o MESMO site que o operador acabou de ver"
    assert criacao._semente("X", 0, 1) == criacao._semente("X") + 1
    assert criacao._semente("X", 0, -5) == criacao._semente("X"), "variação negativa não anda pra trás"


def test_painel_nao_pode_esquecer_um_estagio_do_motor():
    """O painel REIMPLEMENTA pipeline.montar_site pra encaixar o QA de copy no meio.

    Isso já custou caro: quando o motor ganhou o estágio T2 (páginas irmãs), o painel
    não acompanhou — vendia multi-página e publicava uma só, sem erro nenhum. O
    comentário `ponytail:` no código previa exatamente isso e não tinha teste atrás.

    Este é o teste atrás dele: todo estágio que o motor executa entre sintetizar e
    gerar precisa aparecer também no painel. Quando divergirem de novo, falha aqui —
    não na frente do cliente.
    """
    import ast

    fonte_painel = (Path(__file__).resolve().parents[1] / "criacao.py").read_text()
    corpo_painel = fonte_painel[fonte_painel.index("def gerar("):]

    motor = Path("/root/motor-site/app/pipeline.py")
    if not motor.is_file():          # motor fora do disco = nada a comparar
        return
    arvore = ast.parse(motor.read_text())
    fn = next(n for n in ast.walk(arvore)
              if isinstance(n, ast.FunctionDef) and n.name == "montar_site")
    # funções do MÓDULO que montar_site chama — são os estágios que o painel copiou
    do_modulo = {n.name for n in ast.walk(arvore) if isinstance(n, ast.FunctionDef)}
    estagios = {n.func.id for n in ast.walk(fn)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id in do_modulo and not n.func.id.startswith("_")}

    faltando = sorted(e for e in estagios if e not in corpo_painel)
    assert not faltando, (
        f"pipeline.montar_site executa {faltando} e criacao.gerar não — o painel vai "
        f"publicar um site sem esse estágio, calado. Chame a MESMA função no painel.")


def test_catalogo_calcula_o_primeiro_pagamento_da_fonte_unica():
    """R$1.397 (T2) tem que SAIR de precos.json, nunca ser digitado.

    A mesma venda já foi citada como "1.500" e como "1.397" na mesma semana — um era
    chute de âncora, o outro o primeiro pagamento real (setup 1000 + mensal 397).
    Preço que muda conforme quem conta não é preço, e o dono percebe.
    """
    import precos
    tiers = {t["id"]: t for t in precos.tudo()["tiers"]}
    assert precos._primeiro_pagamento(tiers["T2"]) == 1397, \
        "primeiro pagamento do T2 divergiu de setup+mensal do precos.json"
    # T1 não tem mensalidade: o primeiro pagamento É o setup. Testar a REGRA e não o
    # número — este teste existe justamente contra preço digitado à mão (o 497 de
    # 2026-08-15 quebrou a versão que trazia "500" cravado aqui).
    assert tiers["T1"]["mensal"] is None
    assert precos._primeiro_pagamento(tiers["T1"]) == tiers["T1"]["setup"]

    html = precos.catalogo_html()
    assert "1.397,00" in html, "o catálogo não mostra o primeiro pagamento do T2"
    # a recorrência precisa aparecer SEPARADA: é a confusão que gerou o 1500 vs 1397
    assert "397,00/mês" in html
    for t in precos.tudo()["tiers"]:          # nenhum tier some do papel
        assert t["nome"] in html, f"{t['id']} fora do catálogo"


def test_catalogo_nao_inventa_preco_fora_do_json():
    """Todo valor impresso tem que existir no precos.json ou ser soma de dois que existem."""
    import re

    import precos
    d = precos.tudo()
    validos = {0}
    for t in d["tiers"]:
        validos |= {t.get("setup") or 0, t.get("mensal") or 0,
                    precos._primeiro_pagamento(t) or 0}
    for u in d["upsells"]:
        validos |= {u.get("setup") or 0, u.get("mensal") or 0}

    impressos = {int(m.replace(".", "")) for m in
                 re.findall(r"R\$\s*([\d.]+),00", precos.catalogo_html())}
    intrusos = sorted(impressos - validos)
    assert not intrusos, f"o catálogo mostra preço que não existe no precos.json: {intrusos}"
