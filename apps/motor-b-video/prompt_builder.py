"""Prompt Builder do Higgsfield (Motor B v1.1) — a peça de maior ROI.

Combina classificação + template num prompt ESPECÍFICO do segmento (movimento de
câmera, ritmo, iluminação, estilo, transições, proporção, duração) — substitui o
prompt manual/genérico. Lógica pura, sem LLM (o raciocínio de LLM foi a
classificação); aqui é só composição determinística.
"""
from __future__ import annotations


def construir_prompt(classificacao: dict, template: dict, entrada: dict) -> dict:
    tipo = classificacao.get("tipo", "imóvel")
    padrao = classificacao.get("padrao", "economico")
    desc = (entrada.get("descricao") or "").strip()
    partes = [
        f"Vídeo imobiliário de {tipo} — padrão {padrao}.",
        f"Câmera: {template['camera']}.",
        f"Ritmo: {template['ritmo']}.",
        f"Iluminação: {template['iluminacao']}.",
        f"Estilo: {template['estilo']}.",
        f"Transições: {template['transicoes']}.",
        f"Tom geral: {classificacao.get('tom', 'atraente')}.",
    ]
    if desc:
        partes.insert(1, f"Destaques do imóvel: {desc}.")
    if template.get("cta") or classificacao.get("cta"):
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
        "classificacao": classificacao,
    }
