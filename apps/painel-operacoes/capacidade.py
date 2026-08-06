"""Dimensiona o disparo: quantas mensagens por dia, em quantas instâncias, por quanto tempo.

POR QUE ESTE MÓDULO EXISTE: o funil real é 27.107 leads nunca trabalhados — 25x o número
sobre o qual a meta foi calculada. Com `PROSPECCAO_LIMITE_TETO=10` em produção, esgotar
essa base levaria 7,4 anos. O gargalo deixou de ser persuasão e virou throughput, e
throughput em WhatsApp tem um teto físico que nenhuma copy melhora.

O QUE ESTE MÓDULO **NÃO** FAZ: dizer quantos leads convertem. Não há um único cliente
fechado, então taxa de conversão aqui é PREMISSA declarada, nunca previsão. Por isso a
saída principal é a conta INVERSA — "com esta capacidade, qual conversão a meta exigiria"
— que é verificável, em vez de "vai vender X", que não é.

O TETO POR CHIP é a premissa mais cara e a mais incerta. Os valores default são
conservadores de propósito: chip banido não volta, e a operação já perdeu uma instância
por desconexão. Ajuste com dado seu, não com otimismo.

ponytail: funções puras. Recebe premissas, devolve plano. Sem estado, sem banco.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Teto diário por instância, por fase de aquecimento. Números conservadores: disparo FRIO
# (o destinatário não pediu contato) é o pior caso para reputação de número, e o custo de
# errar pra cima é perder o chip — não é uma métrica que se otimiza tentando.
RAMPA_PADRAO: tuple[int, ...] = (10, 15, 25, 40, 60, 80, 100, 120, 150, 180, 200, 250)
# O teto É o último degrau da rampa. Antes era um 250 solto que a rampa (terminando em
# 200) nunca alcançava — um número que parecia limite e não limitava nada.
TETO_MADURO = RAMPA_PADRAO[-1]
DIAS_POR_DEGRAU = 2        # cada degrau da rampa dura N dias antes de subir

# Fração dos disparos que NÃO vira conversa por motivo técnico (número sem WhatsApp que
# passou pelo filtro, bloqueio, silêncio total). Medido em campo: 39% dos envios do
# post-mortem foram pra número sem WhatsApp — o portão da Evolution corta a maior parte
# disso hoje, então 15% é o resíduo estimado.
PERDA_TECNICA = 0.15


@dataclass
class Plano:
    instancias: int
    dias_uteis: int
    capacidade_total: int = 0
    por_dia_final: int = 0
    curva: list[int] = field(default_factory=list)
    alcance_liquido: int = 0

    def conversao_exigida(self, fechamentos: int) -> float:
        """% dos contatos ÚTEIS que precisa fechar pra bater a meta. É a conta que dá
        pra verificar contra a realidade — ao contrário de projetar receita."""
        return 100.0 * fechamentos / self.alcance_liquido if self.alcance_liquido else float("inf")


def curva_aquecimento(dias: int, rampa: tuple[int, ...] = RAMPA_PADRAO,
                      dias_por_degrau: int = DIAS_POR_DEGRAU, teto: int = TETO_MADURO) -> list[int]:
    """Mensagens/dia de UMA instância, dia a dia, subindo pela rampa.

    A rampa não é decoração: número novo que dispara 200 no primeiro dia é o padrão que
    os antifraudes procuram. Subir devagar é o que separa um canal que dura de um chip
    queimado na primeira semana."""
    return [min(rampa[min(d // dias_por_degrau, len(rampa) - 1)], teto) for d in range(max(dias, 0))]


def dimensionar(leads: int, dias_uteis: int, instancias: int, fechamentos_meta: int = 42,
                rampa: tuple[int, ...] = RAMPA_PADRAO, dias_por_degrau: int = DIAS_POR_DEGRAU,
                perda: float = PERDA_TECNICA) -> Plano:
    """Quanto essa configuração alcança na janela — e o que a meta exigiria dela."""
    curva = curva_aquecimento(dias_uteis, rampa, dias_por_degrau)
    total = sum(curva) * instancias
    p = Plano(instancias=instancias, dias_uteis=dias_uteis, curva=curva,
              capacidade_total=min(total, leads),        # não dispara mais do que existe
              por_dia_final=(curva[-1] * instancias) if curva else 0)
    p.alcance_liquido = int(p.capacidade_total * (1 - perda))
    return p


def instancias_para(leads: int, dias_uteis: int, alvo_contatos: int,
                    teto_instancias: int = 12, **kw) -> int:
    """Menor número de instâncias que alcança `alvo_contatos` na janela. 0 se nem o teto
    chega lá — devolver um número que não existe seria pior que admitir o limite."""
    for n in range(1, teto_instancias + 1):
        if dimensionar(leads, dias_uteis, n, **kw).alcance_liquido >= alvo_contatos:
            return n
    return 0


def relatorio(leads: int, dias_uteis: int, fechamentos_meta: int = 42,
              opcoes: tuple[int, ...] = (1, 2, 3, 4, 6, 8)) -> str:
    L = [f"# Capacidade de disparo — {leads:,} leads / {dias_uteis} dias úteis".replace(",", "."),
         "",
         f"Premissas declaradas: rampa {RAMPA_PADRAO[0]}→{TETO_MADURO} msg/dia por instância "
         f"(sobe a cada {DIAS_POR_DEGRAU} dias), perda técnica {PERDA_TECNICA:.0%}.",
         "Conversão NÃO é premissa aqui: a coluna final diz o que a meta exigiria, não o que vai acontecer.",
         "",
         "| Instâncias | Alcance na janela | Msg/dia no fim | % da base | Conversão exigida p/ 42 |",
         "|---:|---:|---:|---:|---:|"]
    for n in opcoes:
        p = dimensionar(leads, dias_uteis, n, fechamentos_meta)
        L.append(f"| {n} | {p.alcance_liquido:,} | {p.por_dia_final:,} | "
                 f"{100*p.capacidade_total/max(leads,1):.1f}% | {p.conversao_exigida(fechamentos_meta):.2f}% |"
                 .replace(",", "."))
    return "\n".join(L)


if __name__ == "__main__":
    # self-check das partes puras
    c = curva_aquecimento(10)
    assert c[0] == 10 and c[-1] >= c[0] and len(c) == 10, c
    assert curva_aquecimento(0) == []
    assert max(curva_aquecimento(400)) == TETO_MADURO, "a rampa tem que parar no teto"
    p = dimensionar(27107, 26, 1)
    assert p.alcance_liquido < 27107, "1 instância não cobre a base em 26 dias"
    assert dimensionar(100, 26, 8).capacidade_total == 100, "não dispara mais do que existe"
    assert instancias_para(27107, 26, 10**9) == 0, "admite quando nem o teto alcança"
    assert dimensionar(27107, 26, 2).alcance_liquido > dimensionar(27107, 26, 1).alcance_liquido
    print("capacidade OK — rampa, teto, saturação e limite conferem\n")
    print(relatorio(27107, 26))
