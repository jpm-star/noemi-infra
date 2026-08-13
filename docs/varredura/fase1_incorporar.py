"""FASE 1 (parte 2) — incorpora ao vocabulário só o que o ensemble achou de NOVO.

Critério de corte: entra se (a) não existe no vocabulário, nem como sinônimo, e
(b) muda o que o gerador FAZ. Ideia bonita que não vira regra de geração fica no
relatório, não no código.

Descartado de propósito: a lane llama-3.3-70b devolveu "galeria de trabalhos",
"cardápio online", "tabela de horários" — os três já estão nas 77 estruturas. Uma
das quatro lanes não agregou; registrar isso vale mais que inflar o número.
"""
import ast
import pathlib

V = pathlib.Path("/root/noemi-infra/apps/painel-operacoes/vocabulario.py")
s = V.read_text(encoding="utf-8")

# ── NICHOS NOVOS ────────────────────────────────────────────────────────────
# O interior paulista é agro, construção e manutenção — e o vocabulário original,
# escrito de fora, não tinha NENHUM dos três. É a lacuna mais cara da lista: são os
# negócios com dinheiro na região onde o JP efetivamente bate na porta.
NOVOS = {
    "servicos": [
        "revenda de tratores", "implementos agricolas", "maquinario agricola",
        "usina fotovoltaica", "marmoraria", "vidracaria", "gesso e drywall",
        "locacao de cacambas", "loja de tintas", "moveis planejados",
        "desentupidora", "pocos artesianos", "ar-condicionado",
        "cercas eletricas", "martelinho de ouro", "estetica automotiva",
        "blindagem", "som e acessorios", "despachante imobiliario",
        "regularizacao de terras", "funeraria",
    ],
    "clinica": [
        "casa de repouso", "geriatria", "reabilitacao esportiva",
        "psicologia infantil", "pilates", "otica", "farmacia de manipulacao",
        "veterinaria de grandes animais", "haras",
    ],
    "academia": ["escola de natacao"],
    "advocacia": ["advocacia previdenciaria", "aposentadoria"],
    "restaurante": ["buffet infantil"],
    "ecommerce": ["bercario", "creche", "reforco escolar"],
}

for fam, termos in NOVOS.items():
    alvo = f'    "{fam}": (\n'
    i = s.index(alvo) + len(alvo)
    bloco = "".join(f'        "{t}",\n' for t in termos)
    s = s[:i] + bloco + s[i:]

# ── ESTRUTURAS NOVAS: a "brasilidade" que a lista original ignorou ──────────
# Nenhuma das 77 originais cobria PIX, parcelamento, convênio ou Waze. O
# vocabulário foi escrito com vocabulário de web internacional; o cliente do JP
# decide compra por parcela e chega no lugar pelo Waze.
ESTR = [
    ("pix-qr", "QR Code PIX com copiar chave", "pagamento", "chave estática, sem gateway"),
    ("parcelamento", "Calculadora de parcelamento", "pagamento", "12x de R$ — como o brasileiro decide"),
    ("bandeiras", "Selos de bandeira e vale-refeição", "pagamento", "aceita VR/VA muda a decisão do almoço"),
    ("convenios", "Convênios aceitos", "confianca", "carrossel de planos — a 1ª pergunta em clínica"),
    ("regiao-atendida", "Atendemos toda a região", "confianca", "cidade + raio, para busca local"),
    ("cnpj-rodape", "CNPJ e endereço no rodapé", "confianca", "contra o medo de golpe, não por lei"),
    ("humano-garantido", "Você fala com uma pessoa", "confianca", "selo anti-robô — vale mais em T1/T2"),
    ("abrir-waze", "Abrir no Waze / Maps", "local", "botão de rota, não endereço em texto"),
    ("aberto-agora", "Status aberto agora", "local", "calculado do horário, não escrito à mão"),
    ("ligar-agora", "Ligar agora (tel:)", "cta", "no interior, ligação ainda fecha mais que form"),
    ("print-whatsapp", "Print de elogio no WhatsApp", "prova", "a prova social que o dono REALMENTE tem"),
    ("feed-gmn", "Avaliações do Google Meu Negócio", "prova", "puxa do GMN, com filtro de data"),
    ("cardapio-pdf", "Catálogo ou cardápio em PDF", "conteudo", "o que o dono já manda no WhatsApp"),
    ("retire-na-loja", "Retire na loja", "objecao", "para quem não entrega — no lugar de frete grátis"),
    ("horario-detalhado", "Horários por dia da semana", "local", "com folga marcada, não '9h-18h'"),
]
anc = "ESTRUTURAS: tuple[tuple[str, str, str, str], ...] = (\n"
i = s.index(anc) + len(anc)
s = s[:i] + "".join(f'    ("{c}", "{n}", "{f}", "{o}"),\n' for c, n, f, o in ESTR) + s[i:]

# ── PRINCÍPIOS NOVOS ────────────────────────────────────────────────────────
PRINC = {
    "persuasao": ["fluxo WhatsApp-first (mensagem já preenchida)",
                  "gaze cuing (o olhar da foto aponta pro CTA)",
                  "micro-copy regionalista (falar como a região fala)"],
    "performance": ["consciência de 3G/4G instável (texto antes de imagem)"],
    "acessibilidade": ["prova de autoridade física (CNPJ e endereço visíveis)"],
}
for cat, itens in PRINC.items():
    alvo = f'    "{cat}": (\n'
    i = s.index(alvo) + len(alvo)
    s = s[:i] + "".join(f'        "{x}",\n' for x in itens) + s[i:]

# ── ANTIPADRÕES: categoria que NÃO EXISTIA ─────────────────────────────────
ANTI = '''

# ── ANTIPADRÕES ────────────────────────────────────────────────────────────
# A categoria que faltava, e a mais acionável das três: as outras descrevem o que
# PODE existir; esta descreve o que o gerador não pode produzir sozinho. Um gerador
# automático reproduz esses erros justamente por ser automático — ele preenche a
# seção porque a seção existe no template, não porque o cliente tem o dado.
#
# Cada entrada é (chave, o erro, a regra que o gerador deve seguir). A regra é
# escrita como CONDIÇÃO, não como conselho: "não gerar X sem Y" é verificável;
# "usar bom senso" não é.
ANTIPADROES: tuple[tuple[str, str, str], ...] = (
    ("form-longo", "formulário com 8+ campos na primeira dobra",
     "no máximo 2 campos (nome e telefone); o CTA primário é WhatsApp ou ligar"),
    ("form-duplicado", "formulário repetido no hero, no meio e no rodapé",
     "um formulário por página; os outros pontos viram link pro mesmo destino"),
    ("depo-generico", "depoimento sem nome, foto ou cidade",
     "não gerar a seção sem depoimento real; melhor ausente que inventado"),
    ("logo-imprensa-falso", "'como visto em' com logo que o cliente não tem",
     "só com logo enviado pelo cliente; nunca preencher por conta"),
    ("telefone-escondido", "telefone só no rodapé, em texto, sem link tel:",
     "botão fixo com tel: e alvo de 48px"),
    ("endereco-texto", "endereço como texto plano, sem rota",
     "sem CEP e número estruturados, não gerar a seção de mapa"),
    ("promo-sem-prazo", "'desconto de 10%' sem data de validade",
     "contador só com data real; sem data, oferta sem contador"),
    ("frete-gratis-sem-entrega", "'frete grátis' em negócio que não entrega",
     "checar se o negócio entrega; se não, 'retire na loja'"),
    ("menu-generico", "Sobre/Serviços/Blog/Contato em quem só precisa agendar",
     "menu derivado do objetivo do nicho; sem blog, sem página de blog"),
    ("foto-stock", "foto genérica de gente sorrindo que não é o negócio",
     "placeholder que PEDE a foto, com instrução do que fotografar"),
    ("cta-conflitante", "dois botões primários na mesma dobra",
     "um CTA primário por dobra; o resto vira link de texto"),
    ("cta-errado-pro-nicho", "'Comprar' em clínica, 'Agendar' em loja",
     "verbo do CTA vem do objetivo do nicho, não do template"),
    ("sobre-duplicado", "o mesmo parágrafo institucional em 3 lugares",
     "um bloco 'sobre' por site; na home, só o resumo"),
    ("horario-sem-folga", "'9h-18h' sem dizer que dia fecha",
     "tabela por dia da semana, com folga explícita"),
    ("lgpd-ausente", "coleta dados sem política nem consentimento",
     "página com coleta gera aviso de privacidade legível (14px+)"),
)
_POR_ANTI = {a[0]: {"erro": a[1], "regra": a[2]} for a in ANTIPADROES}


def antipadrao(chave: str) -> dict | None:
    return _POR_ANTI.get(chave)


def antipadroes() -> list[dict]:
    return [{"chave": c, "erro": e, "regra": r} for c, e, r in ANTIPADROES]
'''
marca = "\ndef _sem_acento(txt: str) -> str:"
s = s.replace(marca, ANTI + marca, 1)

# resumo() passa a contar a categoria nova
s = s.replace(
    '            "principios": len(principios()),',
    '            "antipadroes": len(ANTIPADROES),\n'
    '            "principios": len(principios()),', 1)
s = s.replace(
    '    assert r["principios"] >= 75, r',
    '    assert r["principios"] >= 75, r\n'
    '    assert r["antipadroes"] >= 15, r\n'
    '    # a regra do antipadrão tem que ser CONDIÇÃO verificável, não conselho\n'
    '    for a in antipadroes():\n'
    '        assert a["regra"] and len(a["regra"]) > 12, a\n'
    '    assert antipadrao("form-longo")["regra"].startswith("no máximo")\n'
    '    # os nichos do interior entraram e resolvem\n'
    '    assert segmento_do_nicho("marmoraria em Lins") == "servicos"\n'
    '    assert segmento_do_nicho("casa de repouso") == "clinica"\n'
    '    assert segmento_do_nicho("revenda de tratores") == "servicos"\n'
    '    assert estrutura("pix-qr")["familia"] == "pagamento"', 1)
s = s.replace(
    'print(f"vocabulario OK — {r[\'nichos\']} nichos em {len(r[\'familias\'])} famílias, "\n'
    '          f"{r[\'estruturas\']} estruturas, {r[\'principios\']} princípios em "\n'
    '          f"{len(r[\'categorias_de_principio\'])} categorias")',
    'print(f"vocabulario OK — {r[\'nichos\']} nichos em {len(r[\'familias\'])} famílias, "\n'
    '          f"{r[\'estruturas\']} estruturas, {r[\'principios\']} princípios, "\n'
    '          f"{r[\'antipadroes\']} antipadrões")', 1)

ast.parse(s)
V.write_text(s, encoding="utf-8")
print("vocabulario.py: nichos do interior, estruturas brasileiras, antipadrões")
