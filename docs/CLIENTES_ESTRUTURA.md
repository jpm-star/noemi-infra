# Estrutura de pasta por cliente (JPOS)

Convenção para cada **lead fechado** (contrato assinado). Reusa infra existente — **Google Drive
do JPOS** (onde já vivem apostila/contratos/planilhas), sem duplicar sistema.

## Local e nome
```
Drive do JPOS/
└── Clientes/
    └── <cidade>_<slug-do-negocio>/          ← 1 pasta por cliente fechado
        ├── 00_CONTRATO_assinado.pdf         ← contrato (template docs/CONTRATO_JPOS_template.md) assinado
        ├── 01_ACESSOS.md                     ← login/senha do painel dele (ver segurança abaixo)
        ├── 02_DEMO_que_fechou.md             ← link + print da demo que fechou a venda
        ├── 03_NEGOCIACAO.md                  ← histórico da conversa (data, o que foi acordado, valor)
        └── 04_ONBOARDING.md                  ← cartucho usado, domínio, integrações (Calendar/planilha)
```
- **slug** = nome do negócio em minúsculas, sem acento, `-` no lugar de espaço
  (ex.: `bauru_clinica-sorriso-vivo`). Mesmo padrão do `_slug` do motor-site — consistência.
- Pasta-mãe `Clientes/` **privada** (só o JP). Nunca compartilhar a pasta inteira; se precisar
  mandar algo pro cliente, compartilha o arquivo específico.

## Segurança da senha do painel
- **Nunca** senha fraca ou reaproveitada entre clientes. Gera uma por cliente com
  `docs/gen_senha.py` (usa `secrets`, 20 chars, alta entropia).
- Onde guardar: no `01_ACESSOS.md` **dentro da pasta privada do cliente no Drive** (acesso só do
  JP). Ideal: migrar pra um gerenciador de senhas (Bitwarden/1Password) quando a base crescer —
  o `.md` no Drive privado é o mínimo viável hoje, não o ideal a longo prazo.
- **Não** commitar `01_ACESSOS.md` em repositório git. Não colar senha em chat/e-mail.

## Modelo de `01_ACESSOS.md`
```
# Acessos — [Nome do Cliente]
- Painel: <url>
- Usuário: <login>
- Senha: <gerada por gen_senha.py — trocar no 1º acesso do cliente>
- Gerada em: <data>  ·  Rotacionar a cada: 6 meses
```

## Fluxo ao fechar (checklist)
1. Cria `Clientes/<cidade>_<slug>/` no Drive.
2. Sobe contrato assinado (00).
3. `python docs/gen_senha.py "<slug>"` → cola no 01_ACESSOS.md.
4. Salva link+print da demo que fechou (02) e o histórico da call (03).
5. Registra o cartucho/domínio/integrações no 04.
