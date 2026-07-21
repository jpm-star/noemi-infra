# Sites (motor-isca) — ponteiro

O produto vive em **`/root/motor-site`** (repo próprio, anterior ao monorepo) e está
NO AR em `videoshiggs.noemi.digital` (estáticos em `/var/www/sites` + widget IA).
`sites.noemi.digital` é alias do mesmo bloco no Caddy (DNS A pendente).

**Não recriar nem migrar agora** — regra da SPEC: só vira código aqui quando houver
mudança real a fazer. Upgrade futuro: consumir `apps/painel-operacoes/analista.py`
pra escolher template/copy por segmento.
