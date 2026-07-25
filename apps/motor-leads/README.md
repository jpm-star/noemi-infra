# Motor de Captação de Leads (Noemi Digital)

Pipeline determinístico (**ZERO LLM**) em 4 camadas, pra cron semanal:

1. **coleta.py** — Google Places API (Text Search + Place Details). Dedupe por
   place_id, multi-unidade, reclamação de demora, atividade recente.
2. **enriquecimento.py** — fetch + regex no HTML: SSL, responsivo, plataforma,
   ano do rodapé (abandonado <2023), botão WhatsApp, chat/widget, sem_site.
3. **scoring.py** — fórmula pura: `score_movimento × score_dor`, tier T1-T4,
   corte de fila (reviews≥80 OU rating≥4.3+atividade, E ≥1 sinal de dor).
4. **saida.py** — banco (SQLite padrão / Postgres via DSN) + CSV + Google Sheet.

## Dependências humanas (o motor não roda sem)
- **`GOOGLE_PLACES_API_KEY`** — Google Cloud Console → ativar **Places API** →
  criar chave. **Obrigatória** pro modo real.
- **Google Sheet** (opcional, pro time acompanhar): `GOOGLE_SHEET_ID` +
  `GOOGLE_SA_JSON` (service account json com acesso à planilha) + `pip install gspread`.
- **Postgres** (opcional): `LEADS_PG_DSN` + `pip install 'psycopg[binary]'`.
  Sem DSN, grava em SQLite (`data/leads.db`) — não toca o Postgres de prod.

## Rodar
```bash
# prova offline da cadeia inteira (sem key):
python apps/motor-leads/captacao.py --demo

# PILOTO — 1 cidade, valida amostra de 20 antes das 500:
export GOOGLE_PLACES_API_KEY=...
python apps/motor-leads/captacao.py --cidades "Lins" --limite 20

# stress-test 5 cidades separadas (cada uma grava cidade_origem):
for c in "Araçatuba" "Bauru" "Marília" "São José do Rio Preto" "Campinas"; do
  python apps/motor-leads/captacao.py --cidades "$c" --limite 20
done

# produção — região Lins (raio ~60km), 500 leads:
python apps/motor-leads/captacao.py --cidades "Lins,Birigui,Araçatuba,Promissão,Getulina,Guaiçara" --limite 100
```

## Colunas na Google Sheet (pro Lincon/Rodrigo)
nome · telefone · tier_sugerido · score · motivo_da_dor · status(novo/ligado/agendado/fechado/hostil)

O `status` é preservado no upsert — re-rodar o cron **não** reseta um lead já
trabalhado. LLM só entra DEPOIS, na abordagem personalizada da fila (outro prompt).
