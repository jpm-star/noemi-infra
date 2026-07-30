# PLAYBOOK — Seleção e ativação de lote de leads (board de prospecção)

Como transformar a base bruta de leads (`data/leads.db` → `leads_clinicas`) num board
prospectável no painel p.jpos. Repetir a cada novo corte (500 ou outro N).

## 1. Score / seleção
- Fonte: `leads_clinicas` (raspagem Google Places + scoring). Campos: nome, telefone,
  cidade, categoria, `tier_sugerido` (T1–T4), `score_final`, `passa_corte`, `motivo_da_dor`.
- Critério de corte aplicado: `passa_corte=1` **e** telefone ligável (≥10 dígitos),
  ordenado **T1→T2→T3→T4** e depois maior `score_final`. T3/T4 ficam para o fim.
- Números reais desta base (2026-07-30): 1961 leads, 1915 ligáveis; T1=495, T2=1345,
  T3=68, T4=7. Os 500 do topo = ~419 T1 + ~81 T2 (dedup por últimos-8-dígitos reduz T1).

## 2. Trazer pro board
- Painel p.jpos → seção CRM → card **📋 Tracker de prospecção** → botão **⬇ puxar leads**
  (default 500, máx 500). API: `POST /api/tracker/importar {"limite":500}`.
- Idempotência: pula telefones já no board (dedup por últimos 8 dígitos). Re-clicar
  **puxa os próximos** ainda não importados (não duplica). Teto conhecido: dois números
  reais que terminem nos mesmos 8 dígitos são tratados como o mesmo lead (raro).
- Reset limpo (pra fechar exatamente em N/páginas de 50): `DELETE FROM tracker_prospects`
  antes de reimportar — só se o board ainda não tiver anotação/contato.

## 3. CNPJ → Razão social + QSA (sócios)  ⚠️ ponto que mais confunde
- **A base NÃO tem CNPJ nem razão social** — Google Places só dá nome fantasia.
- **Nome→CNPJ não tem API pública gratuita.** BrasilAPI/ReceitaWS são CNPJ→dados.
  Casa dos Dados (busca por nome) fica atrás de Cloudflare — não automatiza. Rota livre
  = dump da Receita Federal (pesado + match fuzzy por nome fantasia, recall baixo).
- **O que funciona (grátis, no ar):** enriquecimento **sob demanda por lead**. No card
  do lead (📝), cola o CNPJ (do site/nota fiscal/rodapé do lead) e **🔍 buscar razão +
  sócios** → BrasilAPI preenche razão social + adiciona o QSA como sócios, marcando quem
  decide (heurística: Administrador/Presidente/Diretor/Titular → "Sim").
  API: `POST /api/tracker/enriquecer {"id":<lead>,"cnpj":"..."}`. MEI/simplificado às
  vezes não têm QSA público → retorna "QSA não disponível via API" (não é erro).
- **Para CNPJ em massa (todos os 500):** decisão do JP — (a) API paga de busca por nome
  (CNPJá/Econodata), reliable, custo por lookup; (b) dump Receita + match fuzzy, grátis
  mas dias de eng e recall parcial; (c) preencher só os leads que vai pitchar (recomendado
  — o gargalo é ativação, não ter 500 CNPJs).

## 4. Tier T1/T2 (decisão automática)
- Já vem do scoring (`tier_sugerido`). Board ordena e mostra a coluna Tier (editável).
- Regra da apostila: sinal 1 (aparece no Google hoje?) + sinal 2 (depende de percepção
  visual?) → T1 (invisível/sem site) vs T2 (site fraco). Aplicada no pipeline de scoring.

## 5. Onde ficou
- Painel: p.jpos.com.br → CRM → 📋 Tracker de prospecção (50/página, editável, card de
  anotação por lead, contato preenchido sozinho pelo histórico). Serviço `noemi-painel-obs`.
- Dados: `data/leads.db` → `tracker_prospects`, `tracker_socios` (aditivo, não toca `leads_clinicas`).

## 6. O que travou / mais rápido no próximo lote
- Travou: CNPJ em massa (sem rota grátis nome→CNPJ). Não travar o board nisso.
- Mais rápido: se o JP conseguir uma lista de CNPJs (planilha/paga), o enrich em massa é
  trivial (loop no `/api/tracker/enriquecer`) — o lado CNPJ→razão+QSA já está pronto e grátis.
- Demos T1/T2 em lote: depende de confirmar geração parametrizada do motor-site
  (`MOTOR_SITE_CAPACIDADES.md`) antes — não buildar 500 no escuro.
