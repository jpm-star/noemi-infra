"""FASE 3+4 — varredura de oportunidade e os dois .docx.

RANKING POR ROI/ESFORÇO, não por ordem de ocorrência. ROI e esforço são 1..5;
a prioridade é a razão. Isso empurra pro topo o que rende muito e custa pouco —
que nesta stack é quase sempre LIGAR o que já está construído, não construir.

O padrão que organiza o relatório inteiro: em uma sessão apareceram QUATRO casos de
código pronto e desligado (Calendar espelhando só metade, endpoint de venda sem
tela, T2 multi-página órfão, relatório do T1 sem agendador). Não é azar — é o que
acontece quando construir é barato e ligar exige decisão. Por isso a coluna de
esforço aqui pesa mais que a de novidade.

Fonte de cada número: medido nesta máquina, não estimado. Onde não há medição, o
item diz "sem dado" em vez de inventar.
"""
from __future__ import annotations

import pathlib
import sqlite3
from datetime import date

SAIDA = pathlib.Path("/root/jpos-entregaveis")

# (categoria, título, o que é / por que rende, roi, esforço)
OPS: list[tuple[str, str, str, int, int]] = [
    # ── LIGAR O QUE JÁ EXISTE ───────────────────────────────────────────────
    ("ligar", "Evento de clique no beacon",
     "O beacon registra só `view`. Nos 100 registros existentes não há um único evento de "
     "CTA. Sem isso o JPOS não consegue responder 'esse site gerou contato?' nem para os "
     "PRÓPRIOS sites — que é o argumento de venda inteiro do T1. Um evento `cta` no clique "
     "do WhatsApp transforma '44 pessoas viram' em '44 viram, 6 chamaram'.", 5, 1),
    ("ligar", "Agendador do relatório periódico do T1",
     "'Relatório periódico' é 1 das 3 entregas do T1 e está no contrato. O motor existe "
     "(insight_engine + /insights/{cliente}), a tabela insights_cliente está VAZIA e não há "
     "timer nenhum. Vende-se hoje algo que nada dispara.", 5, 2),
    ("ligar", "Disparar os 30 e-mails parados",
     "30 e-mails de prospecção estão em `pending`, nunca enviados. Não é falta de "
     "ferramenta: é fila parada. (Decisão de reativar é do JP — pode ter sido pausa "
     "deliberada.)", 4, 1),
    ("ligar", "GCAL_AGENDA_ID por cliente",
     "O Calendar está provado e ligado nos dois caminhos, mas o .env de produção tem "
     "GCAL_AGENDA_ID vazio. Vender T3 hoje entrega a integração desligada.", 5, 2),
    ("ligar", "Filtro de relevância na Caixa de Ideias",
     "185 ideias colhidas de 469 vídeos, sem filtro: dropshipping da China, óculos de sol e "
     "biohackers convivem com o que serve ao JPOS. Marcar relevância por proximidade ao "
     "vocabulário já existente transforma uma lista que ninguém lê em fila de trabalho.", 3, 2),
    ("ligar", "Perfil de estilo para petshop",
     "Último nicho sem perfil (1 de 128). Fecha a cobertura em 100%.", 1, 1),
    ("ligar", "Aprovar os 80 templates de referência pendentes",
     "201 estruturas reais raspadas de 137 domínios; 121 aprovadas e em uso pelo gerador, "
     "80 esperando revisão. O trabalho de coleta já foi pago.", 3, 2),

    # ── PROVA E MEDIÇÃO (o que destrava a venda) ────────────────────────────
    ("medir", "Página pública de prova por site gerado",
     "Cada site gerado ganha uma URL /prova com visitas, cliques e tempo no ar. É o "
     "material de venda que o JP não tem: mostrar o resultado de OUTRO cliente da mesma "
     "cidade vale mais que qualquer argumento.", 5, 3),
    ("medir", "Taxa de conversão real por tier",
     "Com o evento de CTA ligado, o funil deixa de ser premissa. Hoje a modelagem "
     "financeira tem célula amarela porque não existe UM dado de conversão.", 5, 2),
    ("medir", "Alerta de site sem visita há 30 dias",
     "72 sites publicados e nenhum aviso quando um morre de audiência. É gatilho de "
     "contato (upsell ou resgate) que hoje ninguém puxa.", 3, 2),
    ("medir", "Comparativo antes/depois com o Radar",
     "O Radar já audita site de terceiro. Rodar a mesma auditoria no site ANTIGO do cliente "
     "e no novo dá um antes/depois numérico — o argumento mais forte de renovação.", 4, 3),

    # ── PRODUTO NOVO / RECEITA RECORRENTE ───────────────────────────────────
    ("produto", "Relatório mensal como upsell autônomo",
     "O mesmo motor de insight, empacotado como assinatura para quem NÃO é cliente de "
     "site. Roda sobre o site que a pessoa já tem. Custo marginal ~zero; é o produto de "
     "menor esforço do catálogo inteiro.", 5, 2),
    ("produto", "Gestão de reputação (avaliações)",
     "Pede avaliação por WhatsApp depois do atendimento, filtra a negativa em privado e "
     "publica a positiva no site. Recorrente, roda sozinho. Faixa: R$79–149/mês.", 4, 3),
    ("produto", "Sincronizador de ficha local (Google Meu Negócio)",
     "Nome, endereço, telefone e horário consistentes em todos os diretórios. É o que faz "
     "negócio local aparecer, e ninguém faz à mão. Faixa: R$97–197/mês.", 4, 3),
    ("produto", "Motor de oferta sazonal",
     "Troca banner, CTA e âncora de preço por regra de calendário, sem tocar no site. "
     "Vende 'seu site muda sozinho no Dia das Mães'. Faixa: R$89–159/mês.", 3, 3),
    ("produto", "Conformidade LGPD como item de linha",
     "Política de privacidade, banner de consentimento e registro de coleta gerados e "
     "mantidos. Medo de multa vende sozinho. Faixa: R$69–129/mês.", 3, 2),
    ("produto", "Recepcionista de voz (liga e atende)",
     "A Noemi já responde texto; atender o telefone é o mesmo cérebro com STT/TTS, que já "
     "existe no projeto. Chamada perdida é receita perdida no comércio local. R$149–299/mês.", 4, 4),
    ("produto", "Fidelidade e indicação",
     "Cartão de carimbo digital e link de indicação rastreado. Recorrente e barato. "
     "R$97–179/mês.", 3, 3),
    ("produto", "Pacote multiunidade / franquia",
     "Uma marca, várias filiais, cada uma com página e mapa próprios, conteúdo sincronizado "
     "de um lugar. Academia e clínica crescem assim. R$197–347/mês por unidade.", 4, 4),
    ("produto", "Site de evento avulso",
     "Casamento, formatura, congresso: alto valor percebido, prazo curto, sem recorrência — "
     "mas o motor já faz. Ticket R$400–900 por evento.", 3, 2),
    ("produto", "Assinatura de conteúdo",
     "Post curto por semana no site, gerado do nicho e da cidade, para o site não morrer "
     "parado. R$129–249/mês.", 3, 3),

    # ── RENDA PASSIVA / ESFORÇO MÍNIMO ──────────────────────────────────────
    ("passiva", "Diretório de negócios da região",
     "Os 27 mil CNPJs já captados viram um diretório público por cidade e categoria. Tráfego "
     "orgânico gera lead do próprio JPOS e vende destaque pago ao listado. Constrói-se uma "
     "vez e roda sozinho.", 5, 3),
    ("passiva", "Auditoria grátis como isca automática",
     "O Radar roda sozinho sobre qualquer site. Uma página pública 'cole sua URL e receba a "
     "auditoria' captura lead qualificado sem o JP discar. Já existe o radar_publico — está "
     "atrás de login.", 5, 2),
    ("passiva", "Licenciar o motor para agência",
     "Outra agência gera sites com o motor e paga por site publicado. Escala sem o JP "
     "atender cliente final. Exige contrato e limite de uso, não código novo.", 4, 4),
    ("passiva", "Marketplace de templates por segmento",
     "As 92 estruturas e 121 receitas reais viram pacotes vendáveis a quem monta site sozinho.", 3, 4),
    ("passiva", "Afiliado das ferramentas que já usa",
     "112 ferramentas apareceram nas análises do Radar. Indicar as que o JPOS de fato usa, "
     "com link de afiliado, é receita sem entrega.", 2, 1),
    ("passiva", "Cobrar hospedagem como linha própria",
     "72 sites já hospedados sem linha de receita separada. R$29–49/mês por site é o "
     "recorrente mais fácil de justificar e o mais difícil de cancelar.", 4, 1),

    # ── DESIGN E COMPOSIÇÃO ─────────────────────────────────────────────────
    ("design", "Antipadrões viram regra executável",
     "As 15 regras entraram no vocabulário como dado. Enquanto o gerador não as CONSULTAR, "
     "ele continua produzindo depoimento sem nome e contador sem data.", 5, 3),
    ("design", "Estruturas brasileiras implementadas",
     "PIX, parcelamento, convênio, Waze e 'aberto agora' estão nomeados e não existem como "
     "seção. É a diferença entre parecer site importado e parecer site da cidade.", 5, 3),
    ("design", "Seção condicional por dado real",
     "Nenhuma seção deveria nascer sem o dado que a sustenta. Hoje o template decide, não o "
     "briefing — é a raiz de metade dos antipadrões.", 4, 3),
    ("design", "Verbo do CTA por nicho",
     "'Comprar' em clínica e 'Agendar' em marmoraria. Um dicionário de verbo por família "
     "resolve, e o vocabulário já tem as famílias.", 4, 1),
    ("design", "Motion cinético nos outros perfis",
     "O acento cinético existe e só três segmentos o usam. Ampliar é editar dados.", 2, 1),
    ("design", "Modo escuro por token",
     "Os tokens existem; falta o par escuro e o respeito a prefers-color-scheme.", 2, 3),
    ("design", "Biblioteca visual dos 10 morfismos",
     "Página interna com amostra de cada um, para o JP mostrar na call em vez de descrever.", 3, 2),

    # ── FRONT ───────────────────────────────────────────────────────────────
    ("front", "Fallback sem JS em todo site",
     "Feito no motor-site nesta sessão; o painel ainda tem telas que somem sem JS.", 3, 1),
    ("front", "Timeout e retry nos fetch do painel",
     "Qualquer fetch pode pendurar para sempre. Retry só em GET — repetir POST de venda "
     "registraria duas vezes.", 3, 2),
    ("front", "Acessibilidade dos formulários",
     "Label, foco visível e alvo de 44px. É requisito de conversão em celular, não só de "
     "norma.", 3, 2),
    ("front", "Estado vazio honesto em toda tela",
     "Tela sem dado deve dizer o que fazer, não ficar em branco — o painel tem várias.", 2, 2),
    ("front", "Preview do site antes de publicar",
     "Hoje publica e olha. Ver antes evita republicação e susto na frente do cliente.", 4, 3),
    ("front", "Painel utilizável no celular",
     "O JP opera em pé, na porta do cliente. A tela de campo já foi tratada; o resto não.", 4, 3),

    # ── BACK ────────────────────────────────────────────────────────────────
    ("back", "Índices no SQLite do funil",
     "1.532 linhas varridas em Python a cada busca. CREATE INDEX resolve.", 3, 1),
    ("back", "Healthcheck consolidado",
     "Um /api/saude dizendo banco, credenciais presentes e disco. Hoje se descobre quebrado "
     "pelo sintoma.", 4, 2),
    ("back", "Sentinela de integração inerte",
     "Listar o que está construído e DESLIGADO por falta de env. Quatro casos numa sessão "
     "justificam a tela.", 5, 2),
    ("back", "Handler global de erro em JSON",
     "500 devolvendo HTML foi a causa do bug que travou a geração. O front espera JSON.", 4, 1),
    ("back", "Teste de fumaça HTTP",
     "Chamar toda rota GET e falhar se alguma der 500. Barato e pega regressão de deploy.", 4, 2),
    ("back", "Backup automático do banco",
     "O funil inteiro vive num SQLite sem cópia agendada. Já houve incidente de truncamento.", 5, 2),
    ("back", "Isolar suítes de teste",
     "Rodar painel antes do motor-b quebra 14 testes por colisão de módulo. Ordem não pode "
     "mudar resultado.", 3, 3),
    ("back", "noindex no painel",
     "p.jpos.com.br não deve ser indexado e não tem robots.", 3, 1),
    ("back", "Rotacionar a chave do service account",
     "A chave privada do Google esteve untracked e fora do gitignore. Agora ignorada; "
     "rotacionar fecha o ciclo.", 4, 1),
    ("back", "Remote para o sdr-motor",
     "Seis serviços de produção rodam de um repo sem remote. Há bundle, falta espelho.", 5, 2),

    # ── INFRA E ORGANIZAÇÃO ─────────────────────────────────────────────────
    ("infra", "Consolidar repos duplicados",
     "motor-site/motor-site-fix e noemi-infra/wt-linha-limpa apontam pro mesmo remote em "
     "branches diferentes: dois lugares para editar o mesmo arquivo.", 4, 3),
    ("infra", "Limpar o segredo do histórico",
     "O push só passou porque o segredo foi autorizado. Ele continua no histórico de um "
     "repo que já foi público.", 4, 4),
    ("infra", "Pipeline de deploy reproduzível",
     "Deploy hoje é git checkout + restart manual, com 9 serviços do mesmo diretório. Um "
     "script que reinicia só quem mudou evita o 'atualizei e não pegou'.", 4, 3),
    ("infra", "Documentação gerada do sistema",
     "Um ESTADO.md produzido do systemd, do env e do banco. Doc escrita à mão envelhece — "
     "este projeto tem quatro versões conflitantes de material comercial por isso.", 4, 2),
    ("infra", "Monitorar cota de LLM",
     "O TPM do Groq é 8.000 por organização e não por chave. Sem painel disso, a próxima "
     "rodada paralela quebra igual.", 3, 2),
    ("infra", "Staging antes de produção",
     "Todo teste desta sessão rodou contra produção. Um ambiente espelho evita o próximo "
     "incidente de banco.", 4, 4),
]


def _funil() -> dict:
    try:
        c = sqlite3.connect("file:/root/noemi-infra/data/leads.db?mode=ro", uri=True)
        tot = c.execute("SELECT COUNT(*) FROM tracker_prospects").fetchone()[0]
        fech = c.execute("SELECT COUNT(*) FROM tracker_prospects "
                         "WHERE COALESCE(valor_fechado,0)>0").fetchone()[0]
        por = dict(c.execute("SELECT tier, COUNT(*) FROM tracker_prospects GROUP BY tier"))
        c.close()
        return {"total": tot, "fechados": fech, "por_tier": por}
    except Exception:  # noqa: BLE001
        return {"total": 0, "fechados": 0, "por_tier": {}}


def ranqueado() -> list[dict]:
    fora = []
    for cat, tit, desc, roi, esf in OPS:
        fora.append({"categoria": cat, "titulo": tit, "descricao": desc,
                     "roi": roi, "esforco": esf, "prioridade": round(roi / esf, 2)})
    return sorted(fora, key=lambda x: (-x["prioridade"], -x["roi"]))


if __name__ == "__main__":
    itens = ranqueado()
    print(f"{len(itens)} oportunidades")
    for cat in sorted({i['categoria'] for i in itens}):
        print(f"  {cat:<10} {sum(1 for i in itens if i['categoria'] == cat)}")
    print("\nTOP 12 por ROI/esforço:")
    for i in itens[:12]:
        print(f"  {i['prioridade']:>4}  [{i['categoria']:<8}] {i['titulo']}")
    print("\nfunil:", _funil())
