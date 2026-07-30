# BACKLOG JPOS — gaps acumulados (pra decidir com cabeça descansada)

Compilado 2026-07-30 (fim de um dia de call). NÃO executar às pressas — material de decisão.

## Risco / segurança (topo)
1. **Allowlist `EVERYTHING` + `defaultMode: auto`** no `settings.json` — ✅ ENDURECIDO (2026-07-30): adicionada `permissions.deny` com 21 padrões destrutivos (`rm -rf`, force-push, `git reset --hard`, `systemctl stop/disable/mask`, `docker rm/stop/kill/down`, `dd`, `chmod 777`, `| sh|bash`). Mantido `auto` p/ não travar operação. PENDENTE fuller: trocar `EVERYTHING` por allowlist positiva tool-a-tool (exige sessão interativa).
2. **Restore do Postgres (WAL) nunca testado ponta-a-ponta** — ✅ FERRAMENTA PRONTA: `infra/test_wal_restore.sh` (restaura em cluster scratch isolado, compara contagens; não toca prod). Falta rodar com o base backup real.
3. **Guard no `conftest.py`** — ✅ FEITO: `conftest.py` raiz aborta a suíte se env de banco aponta pra prod (sem `_test`); escape hatch `ALLOW_PROD_DB=1`.
4. **Isolamento do `sdr_motor_papai`** em instância própria (hoje divide cluster com Evolution — se o disco enche, os dois entram em read-only juntos). Pendente.
5. **Key CNPJá exposta 3× no chat** — revogar no painel CNPJá e gerar nova (ação do JP). Removida do `.env` por higiene.

## Radar
6. **Teto de token Groq (100k/dia POR ORG)** — as 2 keys dividem o mesmo limite. Insight agora cai no Claude (fallback configurado hoje), mas isso gasta crédito Anthropic nos dias pesados. Avaliar: Groq tier pago, ou 8b como fallback barato antes do Claude.
7. **116 vídeos que dependem de re-download** — não re-analisados (frágil: IG/cookies). Fica pra outro dia.
8. **Radar ao vivo ainda usa o schema antigo** — só os 188 re-insightados hoje usam o schema novo de 10 campos. Alinhar o prompt do radar ao vivo ao schema novo (follow-up pequeno).

## Motor-site / demos
9. **Motion NÃO é gerado pelo motor** — as animações dos demos (`demo-*-motor`) são hand-crafted nos arquivos, não estão no código do gerador. O motor não sustenta motion reproduzível em escala. Confirmar/construir template com motion antes de prometer demo com motion pros leads.
10. **Personalização por querystring (`?nome=X`) não existe** — hoje é build-por-lead via formulário. Gerar demo único por lead em massa = trabalho de dias, não parametrização.
11. **Divergência de tier** — a apostila define T1=Site+IA, T2=SEO/AEO; "T3" na doc = cliente externo self-serve (modelo de negócio), NÃO "tier de motion". O framing "motion=T3" do handoff não bate com a apostila. Alinhar vocabulário.

## Enriquecimento
12. **CNPJ em massa por nome = ~0% de acerto** (falso positivo). Manter só enrich sob demanda (BrasilAPI grátis / CNPJá quando tiver o CNPJ real).

## DECISÕES PENDENTES (amanhã, cabeça descansada)
- **[DECIDIR] Nenhum demo bate com a definição de T2 hoje.** Os `demo-*-motion` têm animação mas `schema.org=0` (não são AEO/T2); os `demo-*-motor` têm motion+schema mas motion não é gerado pelo motor (hand-crafted). Decidir: (a) é **vitrine consciente** (bonito vende mais, aceita divergir do tier), ou (b) **ajustar** — separar um demo T2 real (schema/AEO, sem motion pesado) do demo-vitrine T3. NÃO corrigir sem essa decisão.
- **[DECIDIR/ROADMAP] Visão "Radar = SO de Conhecimento"** — ver `docs/VISAO_RADAR_KNOWLEDGE_OS.md`. Iniciativa grande (Supervisor + ~20 agentes + Workspaces isolados + RAG/embeddings/vetorial + QA + distribuição automática). Gated atrás de: (1) itens de risco acima resolvidos, (2) decisão sobre Ruflo (hoje travado). NÃO construir sem planejamento próprio — é semanas, não um handoff.
