"""Prompt Builder do Higgsfield (Motor B) — a peça de maior ROI.

Combina classificação + template + Auto Director + Brand Kit num prompt ESPECÍFICO
do segmento (movimento de câmera, ritmo, iluminação, estilo, transições, proporção,
duração, cor de marca, CTA de encerramento) — substitui o prompt manual/genérico.
Lógica pura, sem LLM (o raciocínio de LLM foi a classificação); aqui é composição
determinística.

Auto Director (Onda 1): o template dá o ESTILO de câmera; o Auto Director escolhe o
MOVIMENTO concreto (push-in / dolly / orbit / tilt / aéreo) por objetivo/cômodo, ou
pela classificação quando o cômodo não é informado. É extensão do builder, não
sistema novo.
"""
from __future__ import annotations

# Auto Director: movimento de câmera por CÔMODO/objetivo (o que a cena pede).
# Chave = palavra que aparece em entrada["comodo"] ou entrada["objetivo"].
_MOVIMENTO_POR_COMODO = {
    "fachada": "push-in lento de estabelecimento, revelando a fachada inteira",
    "entrada": "push-in lento de estabelecimento, revelando a fachada inteira",
    "sala": "órbita suave contornando o ambiente, mostrando a amplitude",
    "estar": "órbita suave contornando o ambiente, mostrando a amplitude",
    "cozinha": "dolly lateral acompanhando a bancada, foco nos acabamentos",
    "quarto": "tilt-up suave da cama para o pé-direito, sensação de aconchego",
    "suite": "tilt-up suave revelando a suíte, do detalhe ao todo",
    "banheiro": "dolly de aproximação nos acabamentos e metais",
    "area": "crane ascendente abrindo a área externa e o entorno",
    "externa": "crane ascendente abrindo a área externa e o entorno",
    "piscina": "aéreo baixo deslizando sobre a piscina e o lazer",
    "varanda": "dolly de saída da varanda pra vista, revelando o horizonte",
}

# fallback pela classificação quando o cômodo não é informado
_MOVIMENTO_POR_PADRAO = {
    "luxo": "dolly e crane lentos, reveals amplos e contemplativos",
    "rural": "aéreo panorâmico sobre o terreno, depois push-in na sede",
    "economico": "push-in dinâmico em POV de quem caminha pela casa",
    "lancamento": "push-in dramático crescente com aéreos de impacto",
    "comercial": "travelling preciso e estático, sem movimento excessivo",
}


def escolher_movimento(classificacao: dict, entrada: dict) -> str:
    """Movimento de câmera concreto. Objetivo/cômodo explícito vence; senão,
    deriva da classificação. Uma frase pronta pra entrar no prompt."""
    pista = f"{entrada.get('comodo', '')} {entrada.get('objetivo', '')}".lower()
    for chave, mov in _MOVIMENTO_POR_COMODO.items():
        if chave in pista:
            return mov
    return _MOVIMENTO_POR_PADRAO.get(classificacao.get("padrao"), _MOVIMENTO_POR_PADRAO["economico"])


# Hook (item 3): abertura que prende nos 2 primeiros segundos, por padrão do imóvel.
# Estende o Auto Director — decide especificamente a CENA DE ABERTURA.
_HOOK_POR_PADRAO = {
    "luxo": "Abertura de impacto: reveal aéreo/dolly amplo do destaque mais impressionante, com luz de realce.",
    "economico": "Abertura acolhedora: já entra no ambiente mais convidativo, sensação de lar nos primeiros segundos.",
    "lancamento": "Abertura estilo trailer: texto/contagem de impacto e movimento crescente prendendo em 2s.",
    "rural": "Abertura panorâmica: plano aéreo amplo do terreno e da paisagem ao redor.",
    "comercial": "Abertura corporativa: fachada/letreiro em plano firme, transmitindo solidez.",
}


def escolher_hook(classificacao: dict) -> str:
    """Direção da cena de abertura (hook), por padrão do imóvel."""
    return _HOOK_POR_PADRAO.get(classificacao.get("padrao"), _HOOK_POR_PADRAO["economico"])


# Encerramento (item 4): última cena antes do CTA, por padrão do imóvel.
_ENCERRAMENTO_POR_PADRAO = {
    "luxo": "Encerramento: plano contemplativo e amplo do ambiente premium, luz suave, antes do CTA.",
    "economico": "Encerramento: fecha no clima de lar realizado, aconchego, antes do CTA.",
    "lancamento": "Encerramento: logo/nome do empreendimento em destaque com o slogan, antes do CTA.",
    "rural": "Encerramento: pôr do sol / paisagem ampla do terreno, antes do CTA.",
    "comercial": "Encerramento: plano limpo e firme da fachada/marca, transmitindo solidez, antes do CTA.",
}


def escolher_encerramento(classificacao: dict) -> str:
    """Direção da cena de fechamento (antes do CTA), por padrão do imóvel."""
    return _ENCERRAMENTO_POR_PADRAO.get(classificacao.get("padrao"), _ENCERRAMENTO_POR_PADRAO["economico"])


def construir_prompt(classificacao: dict, template: dict, entrada: dict,
                     brand: dict | None = None, papel: str = "completo") -> dict:
    """`papel` posiciona a cena no vídeo: 'completo' (clipe único), 'abertura'
    (1ª cena do storyboard → ganha o hook), 'meio', 'encerramento' (última → CTA)."""
    tipo = classificacao.get("tipo", "imóvel")
    padrao = classificacao.get("padrao", "economico")
    desc = (entrada.get("descricao") or "").strip()
    movimento = escolher_movimento(classificacao, entrada)  # Auto Director
    hook = escolher_hook(classificacao)
    partes = [
        f"Vídeo imobiliário de {tipo} — padrão {padrao}.",
        f"Câmera: {template['camera']}.",
        f"Movimento de câmera: {movimento}.",  # Auto Director
        f"Ritmo: {template['ritmo']}.",
        f"Iluminação: {template['iluminacao']}.",
        f"Estilo: {template['estilo']}.",
        f"Transições: {template['transicoes']}.",
        f"Tom geral: {classificacao.get('tom', 'atraente')}.",
    ]
    if desc:
        partes.insert(1, f"Destaques do imóvel: {desc}.")
    if papel in ("completo", "abertura"):  # hook só na abertura (ou clipe único)
        partes.insert(1, hook)

    # iluminação/ambiente detectados (classificação vision-capable) refinam a cena —
    # o vídeo respeita a luz e o espaço reais do imóvel, não um genérico do template.
    if classificacao.get("iluminacao"):
        partes.append(f"Respeite a iluminação real do imóvel: {classificacao['iluminacao']}.")
    if classificacao.get("ambiente"):
        partes.append(f"Ambiente predominante: {classificacao['ambiente']}.")

    # encerramento (item 4): direção da última cena, só no fechamento (ou clipe único)
    encerramento = escolher_encerramento(classificacao)
    no_fim = papel in ("completo", "encerramento")
    if no_fim:
        partes.append(encerramento)

    # Brand Kit: cor de acento entra como direção de arte; CTA de encerramento
    # usa o nome da marca (nunca genérico quando a marca é conhecida). CTA só no
    # fechamento — no storyboard, cenas do meio não levam CTA.
    marca_nome = (brand or {}).get("nome")
    tem_marca = bool(marca_nome) and marca_nome != "Noemi"
    if brand and brand.get("cor_acento"):
        partes.append(f"Paleta com acento da marca {brand['cor_acento']} em detalhes e textos na tela.")
    if no_fim and (template.get("cta") or classificacao.get("cta")):
        if tem_marca:
            partes.append(f"Encerrar com cartela da marca \"{marca_nome}\" e chamada para ação "
                          "clara (fale no WhatsApp / agende visita).")
        else:
            partes.append("Encerrar com chamada para ação clara (fale no WhatsApp / agende visita).")

    # duração/proporção: override explícito do briefing vence o preset do template
    duration = int(entrada.get("duration") or template["duracao"])
    aspect = entrada.get("aspect_ratio") or template["aspect_ratio"]
    partes.append(f"Proporção {aspect}, cerca de {duration}s.")

    return {
        "prompt": " ".join(partes),
        "duration": duration,
        "aspect_ratio": aspect,
        "template_id": template["id"],
        "movimento": movimento,
        "hook": hook,
        "encerramento": encerramento,
        "papel": papel,
        "classificacao": classificacao,
    }
