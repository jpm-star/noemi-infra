"""Demos de venda nomeados — Lins. Reusa o template de gen_demo_motion.

Diferença pros demos genéricos que já existiam: aqueles abrem com
"[Nome do Consultório]" e foto de banco. Estes abrem com o nome real, a cor real
da marca e o serviço que o negócio realmente vende. Numa call isso muda a primeira
frase do dono de "entendi o conceito" pra "esse é o meu".

De onde vieram os dados (pasta do Drive de cada negócio, conferida à mão):
  - Charles Cabeleireiros  → @charlescabelos, barbearia masculina clássica,
    identidade amarelo/preto, avaliação pública 5★ citando o degradê.
    Último post do Instagram: 2018 — o argumento de venda é presença parada.
  - OligoFlora             → @oligofloralins, "Estética Funcional", desde 1999,
    verde escuro + verde limão, lipo enzimática, atende homem e mulher.
    Instagram ATIVO (junho) — aqui o argumento é converter quem já segue.
  - Vitor Canevaroli       → @vitorcanevaroliadv, Direito Bancário, atendimento
    online, 4.7k seguidores e só 19 publicações.

ponytail: as fotos do Drive são SCREENSHOT de celular (barra de status, UI do
Instagram/Maps) — servem como fonte de informação da marca, não como imagem de
site. Por isso o card segue no banco temático do template. Trocar por foto real
quando o dono mandar as dele é editar `img` — o resto não muda.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, "/root/motor-site")

import gen_demo_motion as motor  # noqa: E402

DEMOS_LINS = {
    "charles-cabeleireiros": {
        "negocio": "Charles Cabeleireiros",
        "cor": "#f5c518", "cor2": "#1a1a1a",
        "tagline": "Barbearia em Lins · agende seu horário pelo WhatsApp",
        "servicos": [
            {"nome": "Corte Degradê", "preco": "a partir de R$ 45", "img": "barber,fade,haircut",
             "desc": "O corte que virou a assinatura da casa. Degradê no precision, acabamento na navalha e finalização que dura a semana toda."},
            {"nome": "Barba Completa", "preco": "a partir de R$ 35", "img": "barber,beard,shave",
             "desc": "Toalha quente, navalha e alinhamento do contorno. Sai com a pele tratada, não só aparado."},
            {"nome": "Corte + Barba", "preco": "a partir de R$ 70", "img": "barbershop,men,grooming",
             "desc": "O combo de sempre, num horário só. Reserve pelo WhatsApp e não espere na fila."},
            {"nome": "Pigmentação e Disfarce", "preco": "consulte", "img": "barber,hair,styling",
             "desc": "Preenchimento de falhas na barba e no cabelo com acabamento natural, sem efeito borrado."},
            {"nome": "Sobrancelha Masculina", "preco": "a partir de R$ 20", "img": "barber,men,face",
             "desc": "Limpeza no formato do rosto, discreta. Diferença que aparece na foto e ninguém sabe explicar."},
            {"nome": "Corte Infantil", "preco": "a partir de R$ 40", "img": "kids,haircut,barber",
             "desc": "Paciência com criança e cadeira na altura certa. Primeiro corte com foto pra levar pra casa."},
        ]},
    "oligoflora": {
        "negocio": "OligoFlora Estética Funcional",
        "cor": "#a3e635", "cor2": "#14532d",
        "tagline": "Estética funcional em Lins desde 1999 · avaliação pelo WhatsApp",
        "servicos": [
            {"nome": "Lipo Enzimática", "preco": "consulte protocolo", "img": "aesthetics,body,treatment",
             "desc": "Protocolo aplicado em sessões para gordura localizada, com acompanhamento e registro de antes e depois."},
            {"nome": "Reposição de Colágeno", "preco": "a partir de R$ 250", "img": "skincare,collagen,face",
             "desc": "Estímulo de colágeno para firmeza e viço. Indicado quando a pele começa a perder sustentação."},
            {"nome": "Estética Masculina", "preco": "consulte", "img": "men,skincare,treatment",
             "desc": "Homem também se cuida: protocolos de gordura localizada, pele e definição, com a mesma discrição."},
            {"nome": "Limpeza de Pele Profunda", "preco": "a partir de R$ 160", "img": "facial,cleaning,spa",
             "desc": "Extração, higienização e hidratação. Pele limpa de verdade, sem irritar."},
            {"nome": "Drenagem Linfática", "preco": "a partir de R$ 120", "img": "massage,drainage,spa",
             "desc": "Reduz inchaço e retenção. Muito procurada em pós-operatório e antes de datas importantes."},
            {"nome": "Avaliação Funcional", "preco": "gratuita", "img": "consultation,aesthetics",
             "desc": "26 anos de casa começam aqui: avaliação sem compromisso e protocolo montado pro seu caso."},
        ]},
    "vitor-canevaroli-advocacia": {
        "negocio": "Vitor Canevaroli · Advocacia",
        "cor": "#c9a227", "cor2": "#0f2740",
        "tagline": "Direito Bancário · atendimento online, resposta pelo WhatsApp",
        "servicos": [
            {"nome": "Busca e Apreensão de Veículo", "preco": "consulta inicial", "img": "law,car,contract",
             "desc": "Recebeu notificação extrajudicial? Existe prazo para agir e caminho para manter o carro. Fale antes de perder a data."},
            {"nome": "Bloqueio Indevido de Conta", "preco": "consulta inicial", "img": "bank,justice,money",
             "desc": "Nem todo valor da sua conta pode ser bloqueado. Salário e verba alimentar têm proteção — dá para reverter."},
            {"nome": "Golpe Bancário e Estorno", "preco": "consulta inicial", "img": "security,bank,fraud",
             "desc": "Falsa central de atendimento, PIX induzido, cartão clonado. O banco tem responsabilidade em boa parte dos casos."},
            {"nome": "Revisão de Juros e Contrato", "preco": "análise do contrato", "img": "contract,law,documents",
             "desc": "Juros acima do praticado no mercado e tarifas embutidas podem ser revistos judicialmente."},
            {"nome": "Superendividamento", "preco": "consulta inicial", "img": "debt,law,help",
             "desc": "Renegociação global das dívidas com preservação do mínimo existencial, prevista em lei."},
            {"nome": "Consulta Online", "preco": "agende pelo WhatsApp", "img": "lawyer,online,consultation",
             "desc": "Atendimento à distância, sem precisar sair do trabalho. Documento por WhatsApp e retorno com a análise."},
        ]},
}


def main() -> None:
    motor.DEMOS.update(DEMOS_LINS)
    motor.main(list(DEMOS_LINS))


if __name__ == "__main__":
    if "--selfcheck" in sys.argv:
        # o valor do demo é ser NOMEADO: placeholder aqui é regressão, não estilo
        for slug, d in DEMOS_LINS.items():
            assert "[" not in d["negocio"], slug
            assert len(d["servicos"]) == 6, slug
            assert d["cor"] != d["cor2"], slug
            for s in d["servicos"]:
                assert s["desc"] and s["nome"] and s["img"], (slug, s)
        html = motor.render(DEMOS_LINS["charles-cabeleireiros"])
        assert "Charles Cabeleireiros" in html and "Degradê" in html
        print("OK — self-check dos demos passou.")
    else:
        main()
