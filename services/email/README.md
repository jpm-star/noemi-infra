# Módulo de E-mail Outbound (Gmail API, sem n8n)

Fila no BD + throttle diário (warm-up) + template em arquivo. Envio via Gmail API
com service account (domain-wide delegation). Separado do motor de leads.

## Setup (o que você faz uma vez)
1. **Habilitar Gmail API** no MESMO projeto Google Cloud da Places (`486225946387`):
   Console → APIs & Services → habilitar **Gmail API**.
2. **Service Account** com domain-wide delegation:
   Console → IAM → Service Accounts → criar → "Enable domain-wide delegation" →
   baixar o JSON da chave.
3. **Workspace Admin** (admin.google.com) → Security → API Controls →
   Domain-wide Delegation → adicionar o **Client ID** da service account com os
   escopos: `https://www.googleapis.com/auth/gmail.send,https://www.googleapis.com/auth/gmail.readonly`
4. Caixa de envio: `vendas@noemi.digital` (ou a que você definir).
5. `pip install google-auth google-api-python-client` no venv.

## Env (no infra/.env)
```
EMAIL_FROM=vendas@noemi.digital
EMAIL_SA_JSON=/root/noemi-infra/infra/gmail-sa.json
EMAIL_DAILY_LIMIT=25          # warm-up de domínio novo
EMAIL_TEMPLATE=/root/noemi-infra/infra/email_template.txt   # opcional; senão usa o padrão
```
Sem `EMAIL_SA_JSON` o módulo roda em **dry-run** (grava 'sent' com id fake, NÃO
manda) — dá pra testar fila/throttle sem enviar nada.

## Testar com 1 lead (antes do lote)
```python
from services.email import outbound
# 1) template renderizado
print(outbound.render_template({"nome":"Clínica X","link":"https://go.noemi.digital/demo-x"}))
# 2) envia 1 (dry-run sem SA; real com SA). Grava no BD: lead_id/status/message_id/ts
print(outbound.send_email("teste@gmail.com","Um site pra você","corpo aqui","place_id_123"))
```

## Rodar o lote (cron/worker, respeita o throttle)
```
python -c "from services.email import outbound; print(outbound.processar_fila(10))"
```
`enfileirar(to,subject,body,lead_id)` põe na fila; `processar_fila(N)` envia até N
respeitando `EMAIL_DAILY_LIMIT`/dia. Um cron de hora em hora resolve.

## Fase 2 (hook pronto)
`checar_respostas()` — consulta as threads dos enviados (gmail.readonly) e marca
o lead como respondeu. Placeholder `_tem_resposta()` a implementar quando ligar.

## NÃO faz
n8n, orquestrador visual, scraper de e-mail (assume que a coluna e-mail já existe
na tabela de leads — outro prompt).
