"""Vocabulário do motor — nicho, estrutura de seção e princípio, num lugar só.

FORNECIDO PELO JP (2026-08-13): 80 nichos, 75 estruturas de seção, 75 princípios.
Taxonomia própria; nada copiado de marketplace ou template de terceiro.

POR QUE OS 80 NICHOS NÃO VIRARAM 80 SEGMENTOS. Segmento novo exige um perfil em
`estilos.PERFIS`, e perfil é opinião estética COM justificativa comercial por
morfismo — texto que só gente escreve. Oitenta perfis vazios devolveriam composição
genérica com cara de intencional, que é precisamente o defeito que o catálogo vivo
existe pra expor. Então cada nicho aponta pra família que o motor já sabe vestir:
"podólogo" resolve como clinica, "chaveiro" como servicos. O ganho é imediato — o
nicho deixa de cair no perfil VAZIO — e nada foi inventado.
Quando um desses ganhar perfil próprio (porque o catálogo vivo mostrou volume),
é só criar a entrada em PERFIS: o alias continua valendo e passa a ser específico.

AS ESTRUTURAS SÃO VOCABULÁRIO, NÃO MENU. Ninguém escolhe uma da lista: elas dão
NOME ao que o motor compõe, pra `catalogo_vivo.nomear_estrutura` batizar uma
combinação nova seguindo o mesmo padrão em vez de devolver um JSON que ninguém
promove porque ninguém lê.

OS PRINCÍPIOS NÃO ENTRAM EM `estilos.CONCEITOS`. Lá é sugestão por segmento
mostrada na tela; 75 princípios abstratos ali viram parede de texto que o operador
aprende a pular. Aqui ficam agrupados, como guia do gerador de copy e checklist de
QA — consultáveis por categoria.

Editar é editar este arquivo. Não há UI: são dados que mudam poucas vezes por ano.
"""
from __future__ import annotations

NICHOS: dict[str, tuple[str, ...]] = {
    "clinica": (
        "casa de repouso",
        "geriatria",
        "reabilitacao esportiva",
        "psicologia infantil",
        "pilates",
        "otica",
        "farmacia de manipulacao",
        "veterinaria de grandes animais",
        "haras",
        "oftalmologista",
        "clínica de olhos",
        "ortodontista",
        "fisioterapeuta",
        "fonoaudiólogo",
        "terapeuta ocupacional",
        "podólogo",
        "nutrólogo",
        "nutricionista",
        "clínica de reprodução humana",
        "laboratório de análises",
        "cirurgião plástico",
        "clínica de estética",
        "clínica de estética capilar",
        "psicólogo",
        "coach de carreira",
        "clínica veterinária",
        "spa",
        "bem-estar",
        "dentista",
    ),
    "advocacia": (
        "contabilidade",
        "escritório de contabilidade",
        "assessoria contábil",
        "corretora de seguros",
        "advocacia previdenciaria",
        "aposentadoria",
        "advocacia trabalhista",
        "advocacia criminal",
        "cartório",
        "despachante",
        "corretor de seguros",
        "contador digital",
        "consultoria empresarial",
    ),
    "salao": (
        "salão de beleza",
        "barbearia",
        "estúdio de tatuagem",
        "ateliê de costura",
    ),
    "academia": (
        "escola de natacao",
        "personal trainer",
        "crossfit",
        "box",
        "yoga",
        "pilates",
        "studio de yoga",
    ),
    "imobiliaria": (
        "construtora",
        "arquiteto",
        "paisagismo",
        "corretor de imóveis",
        "empresa de mudanças",
        "segurança eletrônica",
    ),
    "restaurante": (
        "pizzaria",
        "padaria",
        "lanchonete",
        "hamburgueria",
        "sorveteria",
        "acaiteria",
        "açaí",
        "cafeteria",
        "pastelaria",
        "marmitaria",
        "churrascaria",
        "espetinho",
        "food truck",
        "bar",
        "rotisseria",
        "buffet infantil",
        "personal chef",
        "buffet",
        "eventos",
        "confeitaria",
        "adega",
        "distribuidora de bebidas",
        "restaurante delivery",
    ),
    "petshop": (
        "pet shop",
    ),
    "ecommerce": (
        "mercado",
        "supermercado",
        "mercearia",
        "loja de roupas",
        "loja de calçados",
        "loja de chinelos",
        "tabacaria",
        "loja de presentes",
        "bercario",
        "creche",
        "reforco escolar",
        "e-commerce",
        "ecommerce",
        "loja de moda",
        "loja de eletrônicos",
        "loja de suplementos",
        "loja de roupas infantis",
        "floricultura",
        "papelaria",
        "auto peças",
        "loja virtual",
        "infoprodutor",
        "curso online",
    ),
    "servicos": (
        "auto center",
        "auto peças",
        "borracharia",
        "funilaria",
        "lavanderia",
        "revenda de tratores",
        "implementos agricolas",
        "maquinario agricola",
        "usina fotovoltaica",
        "energia solar",
        "marmoraria",
        "vidracaria",
        "gesso e drywall",
        "locacao de cacambas",
        "loja de tintas",
        "moveis planejados",
        "desentupidora",
        "pocos artesianos",
        "ar-condicionado",
        "cercas eletricas",
        "martelinho de ouro",
        "estetica automotiva",
        "blindagem",
        "som e acessorios",
        "despachante imobiliario",
        "regularizacao de terras",
        "funeraria",
        "fotógrafo",
        "videomaker",
        "fotógrafo de casamento",
        "cerimonial",
        "casamento",
        "dj",
        "som",
        "escola de idiomas",
        "agência de marketing",
        "saas",
        "startup",
        "empresa de ti",
        "oficina mecânica",
        "auto elétrica",
        "lavagem de carros",
        "lava rápido",
        "chaveiro",
        "marcenaria",
        "serralheria",
        "piscineiro",
        "dedetizadora",
        "assistência técnica de celular",
        "gráfica rápida",
        "limpeza residencial",
        "agência de turismo",
        "locadora de veículos",
        "mudanças",
    ),
}

# (chave, nome, família, o que é)
ESTRUTURAS: tuple[tuple[str, str, str, str], ...] = (
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
    ("hero-full-cta", "Hero full + CTA único", "hero", "tela inteira, título grande, um botão só"),
    ("hero-3-beneficios", "Hero + 3 benefícios em cards", "hero", "três cards que viram coluna no mobile"),
    ("hero-prova-social", "Hero + prova social imediata", "hero", "logo de clientes ou estrelas na dobra"),
    ("hero-video", "Hero com vídeo de fundo", "hero", "vídeo silencioso atrás do texto"),
    ("hero-split", "Hero split (texto + imagem)", "hero", "texto e foto lado a lado"),
    ("hero-contador", "Hero com contador regressivo", "hero", "urgência no primeiro olhar"),
    ("hero-form", "Hero + formulário embutido", "hero", "nome + WhatsApp já na dobra"),
    ("hero-depoimentos", "Hero + depoimentos em carrossel", "hero", "prova social deslizante"),
    ("hero-minimal", "Hero minimalista", "hero", "logo, título e botão — nada mais"),
    ("hero-mapa", "Hero com mapa interativo", "hero", "localização aberta de cara"),
    ("hero-gradiente", "Hero com gradiente animado", "hero", "cor em movimento, sem imagem nem vídeo"),
    ("hero-3d", "Hero com produto em 3D", "hero", "GLB real com a câmera orbitando"),
    ("hero-360", "Hero com produto em 360º", "hero", "sequência de fotos girando ao arrastar"),
    ("servicos-grid", "Serviços em grid 2x2", "servicos", "quatro cards que viram lista no mobile"),
    ("servicos-accordion", "Serviços em accordion", "servicos", "abre ao tocar; economiza tela"),
    ("servicos-preco", "Serviços com preço embutido", "servicos", "valor abaixo do nome, sem surpresa"),
    ("servicos-mais-pedidos", "Serviços + mais pedidos", "servicos", "badge nos três mais vendidos"),
    ("timeline-processo", "Timeline de processo", "processo", "passo a passo vertical"),
    ("tres-passos", "Como funciona em 3 passos", "processo", "três números grandes"),
    ("antes-depois", "Antes e depois", "prova", "duas fotos com slider"),
    ("galeria", "Galeria de trabalhos", "prova", "grid que abre em tela cheia"),
    ("cases-metricas", "Cases com métricas", "prova", "número grande + foto do cliente"),
    ("depo-video", "Depoimentos em vídeo", "prova", "thumbnail que toca sem sair da página"),
    ("depo-carrossel", "Depoimentos em carrossel infinito", "prova", "passa sozinho, arrasta com o dedo"),
    ("numeros-vivos", "Números vivos", "prova", "contador que sobe ao entrar na tela"),
    ("logos-imprensa", "Logos de imprensa", "prova", "como visto em"),
    ("bastidores", "Bastidores", "prova", "o processo, não só o resultado"),
    ("certificacao", "Selo de certificação", "prova", "CRM, OAB, ISO — por segmento"),
    ("resultado-video", "Resultado em vídeo curto", "prova", "antes/depois em movimento"),
    ("imprensa-fundador", "Imprensa e entrevistas", "prova", "o fundador citado fora"),
    ("faq-accordion", "FAQ em accordion", "faq", "perguntas fechadas que abrem ao tocar"),
    ("faq-busca", "FAQ com busca", "faq", "barra de pesquisa acima das perguntas"),
    ("faq-chat", "FAQ em formato de chat", "faq", "pergunta e resposta como conversa"),
    ("preco-3-planos", "Preço com 3 planos", "preco", "o do meio destacado"),
    ("preco-toggle", "Preço com toggle mensal/anual", "preco", "muda o valor na hora"),
    ("tabela-comparativa", "Tabela comparativa", "preco", "vira cards empilhados no mobile"),
    ("preco-recomendado", "Planos com recomendado dinâmico", "preco", "sugere o plano pelo perfil"),
    ("ancora-preco", "Âncora de preço", "preco", "de/por, com a régua explícita"),
    ("garantia", "Selo de garantia", "objecao", "satisfação ou dinheiro de volta"),
    ("objecao-antecipada", "Objeção antecipada", "objecao", "achou caro? veja o motivo"),
    ("nao-e-pra-voce", "Quem não é nosso cliente", "objecao", "filtro reverso que qualifica"),
    ("comparativo-generico", "Nós vs. concorrência genérica", "objecao", "sem citar nome"),
    ("politica-cancelamento", "Política de cancelamento", "objecao", "reagendamento sem letra miúda"),
    ("equipe", "Seção de equipe", "sobre", "fotos redondas, scroll horizontal no mobile"),
    ("sobre-foto-grande", "Sobre com foto grande", "sobre", "fundador ocupando meia tela"),
    ("linha-do-tempo", "Linha do tempo da empresa", "sobre", "marcos em ordem vertical"),
    ("missao-valores", "Missão e valores", "sobre", "institucional, mais usado em B2B"),
    ("para-quem", "Para quem é", "sobre", "três personas de cliente ideal"),
    ("mapa-horario-zap", "Mapa + horários + WhatsApp", "local", "tudo junto, para negócio local"),
    ("como-chegar", "Como chegar", "local", "transporte público e estacionamento"),
    ("disponibilidade", "Disponibilidade em tempo real", "local", "3 vagas essa semana"),
    ("emergencia", "Atendimento de urgência", "local", "24h, clínica e jurídico"),
    ("blog", "Últimas do blog", "conteudo", "três cards de post"),
    ("newsletter", "Newsletter embutida", "conteudo", "campo de e-mail no meio do scroll"),
    ("feed-social", "Feed social embutido", "conteudo", "Instagram ao vivo"),
    ("parceiros", "Parceiros e fornecedores", "conteudo", "carrossel de logos"),
    ("convite-grupo", "Convite para o grupo", "conteudo", "WhatsApp ou Telegram da comunidade"),
    ("recall", "Lembrete de retorno", "conteudo", "marque seu retorno"),
    ("cta-intermediario", "CTA intermediário", "cta", "botão forte depois de provar valor"),
    ("cta-rodape-fixo", "CTA fixo no rodapé", "cta", "grudado embaixo durante o scroll"),
    ("cta-bonus", "Bônus por fechar hoje", "cta", "feche hoje e ganhe X"),
    ("rodape-completo", "Rodapé completo", "rodape", "links, endereço, CNPJ, selos"),
    ("rodape-minimo", "Rodapé minimalista", "rodape", "logo e links principais"),
    ("menu-hamburguer", "Menu hambúrguer", "nav", "abre em tela cheia"),
    ("menu-inferior", "Menu inferior fixo", "nav", "ícones embaixo, como app"),
    ("sticky-header", "Header fixo", "nav", "menu acompanha o scroll"),
    ("one-page", "One-page com âncoras", "nav", "tudo numa página, menu leva às seções"),
    ("multi-pagina", "Multi-página clássica", "nav", "cada seção em URL própria"),
    ("landing-captura", "Landing de captura pura", "pagina", "título, formulário, prova social"),
    ("landing-webinar", "Landing de webinar", "pagina", "data, inscrição e contador"),
    ("obrigado", "Página de agradecimento", "pagina", "recebemos — agora faça X"),
    ("erro-404", "404 customizada", "pagina", "útil, com volta pro início"),
    ("manutencao", "Página de manutenção", "pagina", "voltamos em breve + e-mail"),
    ("portfolio-fullscreen", "Portfólio full-screen", "pagina", "um projeto por tela"),
    ("ecommerce-simples", "E-commerce simples", "pagina", "grade, filtro e comprar"),
    ("area-membros", "Área de membros", "pagina", "login limpo, painel depois"),
    ("chat-ia", "Chat de IA nativo", "pagina", "flutuante, responde em tempo real"),
)

ESTRUTURAS_LISTA = [{"chave": c, "nome": n, "familia": f, "oque": o}
                    for c, n, f, o in ESTRUTURAS]
_POR_CHAVE = {e['chave']: e for e in ESTRUTURAS_LISTA}

PRINCIPIOS: dict[str, tuple[str, ...]] = {
    "mobile": (
        "mobile-first",
        "thumb-friendly (zonas de toque)",
        "botões de no mínimo 48px",
        "tipografia legível em tela pequena",
        "navegação por gestos",
        "swipe patterns",
        "pull to refresh",
        "sticky elements",
        "floating action button",
        "bottom navigation",
        "feedback tátil ao tocar",
    ),
    "performance": (
        "consciência de 3G/4G instável (texto antes de imagem)",
        "velocidade de carregamento",
        "lazy load de imagens",
        "Core Web Vitals",
        "skeleton loading",
        "progressive enhancement (funciona sem JS)",
        "graceful degradation (falha não quebra a página)",
    ),
    "hierarquia": (
        "hierarquia visual",
        "espaçamento generoso",
        "contraste alto",
        "above the fold",
        "peso visual decrescente",
        "zona F de leitura",
        "regra dos 3 cliques",
        "progressive disclosure",
        "redução de carga cognitiva (uma decisão por tela)",
        "teste de hierarquia na dobra",
    ),
    "persuasao": (
        "fluxo WhatsApp-first (mensagem já preenchida)",
        "gaze cuing (o olhar da foto aponta pro CTA)",
        "micro-copy regionalista (falar como a região fala)",
        "CTA único por tela",
        "prova social acima da dobra",
        "microcopy",
        "urgência e escassez",
        "reciprocidade",
        "autoridade",
        "prova social",
        "aversão à perda",
        "ancoragem de preço",
        "ancoragem dupla (de/por)",
        "efeito von Restorff (o que destoa é lembrado)",
        "paradoxo da escolha (menos opções converte mais)",
        "compromisso e coerência (micro-sim leva a macro-sim)",
        "curva de atenção (pico no início e no fim)",
        "redundância de CTA ao longo do scroll",
        "prova social em camadas (número + depoimento + selo)",
        "fricção positiva (a pergunta que qualifica)",
        "sequência de seções (AIDA / PAS)",
        "conversão por micro-compromissos",
        "exit-intent capture",
        "personalização de visitante recorrente",
        "Fitts's Law",
    ),
    "acessibilidade": (
        "prova de autoridade física (CNPJ e endereço visíveis)",
        "acessibilidade (WCAG)",
        "contraste de cor",
        "tamanho de fonte mínimo",
        "affordance clara (botão parece clicável)",
        "foco visível por teclado",
        "design de erro gentil (ajuda, não culpa)",
    ),
    "sistema": (
        "sistema de design tokens",
        "componentização",
        "atomic design",
        "design system",
        "escala de espaçamento consistente",
        "paleta de cor limitada",
        "iconografia clara",
        "card-based design",
        "bento grid",
        "glassmorphism",
        "neumorphism (quando faz sentido)",
        "dark mode",
        "light mode",
        "consistência de marca entre páginas",
    ),
    "conteudo": (
        "content-first design (texto antes do layout)",
        "storytelling visual",
        "ilustrações vs fotos reais",
        "empty states",
        "feedback visual imediato",
        "estimativa de tempo de leitura",
    ),
}



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

def _sem_acento(txt: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFKD", str(txt or "")).encode("ascii", "ignore").decode()
    return " ".join(t.lower().split())


# termo -> família, do MAIS LONGO pro mais curto (ver segmento_do_nicho)
# A CHAVE DA FAMÍLIA TAMBÉM É TERMO. Sem isso (até 2026-08-15), "academia",
# "advocacia" e "restaurante" não casavam com as famílias de mesmo nome: as listas
# guardavam só as variações exóticas ("personal chef", "buffet infantil") e o nome
# genérico ficava de fora. O nicho mais óbvio do ramo caía no estilo genérico
# calado — e são justamente os que mais aparecem (14 academias no acervo).
_POR_TERMO = sorted(
    ({(_sem_acento(t), seg) for seg, termos in NICHOS.items() for t in termos}
     | {(_sem_acento(seg), seg) for seg in NICHOS}),
    key=lambda x: -len(x[0]))


def segmento_do_nicho(nicho: str) -> str:
    """Nicho livre -> família que o motor sabe vestir. "" se nenhuma casa.

    Casa por SUBSTRING e do termo mais longo pro mais curto: "clínica veterinária"
    tem que resolver como clinica antes de "clinica" casar por acaso com outra
    entrada. Sem a ordenação, o resultado dependeria da ordem do dicionário.
    """
    n = _sem_acento(nicho)
    if not n:
        return ""
    for termo, seg in _POR_TERMO:
        if termo in n:
            return seg
    return ""


def estrutura(chave: str) -> dict | None:
    return _POR_CHAVE.get(chave)


def estruturas_da_familia(familia: str) -> list[dict]:
    return [e for e in ESTRUTURAS_LISTA if e["familia"] == familia]


def principios(categoria: str = "") -> list[str]:
    if categoria:
        return list(PRINCIPIOS.get(categoria, []))
    return [p for lista in PRINCIPIOS.values() for p in lista]


def resumo() -> dict:
    return {"nichos": sum(len(v) for v in NICHOS.values()),
            "familias": sorted(NICHOS),
            "estruturas": len(ESTRUTURAS_LISTA),
            "familias_de_estrutura": sorted({e["familia"] for e in ESTRUTURAS_LISTA}),
            "antipadroes": len(ANTIPADROES),
            "principios": len(principios()),
            "categorias_de_principio": sorted(PRINCIPIOS)}


if __name__ == "__main__":  # self-check
    r = resumo()
    assert r["nichos"] >= 80, r
    assert r["estruturas"] >= 75, r
    assert r["principios"] >= 75, r
    assert r["antipadroes"] >= 15, r
    # a regra do antipadrão tem que ser CONDIÇÃO verificável, não conselho
    for a in antipadroes():
        assert a["regra"] and len(a["regra"]) > 12, a
    assert antipadrao("form-longo")["regra"].startswith("no máximo")
    # os nichos do interior entraram e resolvem
    assert segmento_do_nicho("marmoraria em Lins") == "servicos"
    assert segmento_do_nicho("casa de repouso") == "clinica"
    assert segmento_do_nicho("revenda de tratores") == "servicos"
    assert estrutura("pix-qr")["familia"] == "pagamento"
    # o mapeamento resolve os casos que antes caíam no vazio
    assert segmento_do_nicho("podólogo em Bauru") == "clinica"
    assert segmento_do_nicho("Chaveiro 24h") == "servicos"
    assert segmento_do_nicho("loja de suplementos") == "ecommerce"
    assert segmento_do_nicho("Advocacia Trabalhista") == "advocacia"
    # sem acento e sem caixa
    assert segmento_do_nicho("CLINICA VETERINARIA") == segmento_do_nicho("clínica veterinária")
    # o mais longo ganha: "clínica veterinária" não pode virar petshop por causa de "veterin"
    assert segmento_do_nicho("clínica veterinária") == "clinica"
    # nicho fora do vocabulário continua devolvendo "" (o catálogo vivo conta)
    assert segmento_do_nicho("loja de bicicletas") == ""
    assert segmento_do_nicho("") == ""
    # chaves de estrutura são únicas
    chaves = [e["chave"] for e in ESTRUTURAS_LISTA]
    assert len(chaves) == len(set(chaves)), "chave de estrutura duplicada"
    assert estrutura("hero-360")["familia"] == "hero"
    assert len(estruturas_da_familia("hero")) >= 10
    assert "mobile-first" in principios("mobile")
    print(f"vocabulario OK — {r['nichos']} nichos em {len(r['familias'])} famílias, "
          f"{r['estruturas']} estruturas, {r['principios']} princípios, "
          f"{r['antipadroes']} antipadrões")
