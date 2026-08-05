#!/usr/bin/env bash
# Instala o pre-commit hook que roda verificar-chaves.sh nos repos da JPOS.
#
# Por que pre-commit e não só gate de deploy (#2): o gate de deploy pega o erro
# quando ele JÁ ESTÁ na branch — alguém commitou, revisou, mergeou, e só na subida
# descobre. O hook pega antes de virar commit, que é onde custa 5 segundos consertar.
# O caso real: GROQ_KEY_1==KEY_2==KEY_3 em dois deploys viveu semanas assim.
#
# Instala em: noemi-infra, sdr-motor, motor-site (os que têm .env).
# Bypass consciente: `git commit --no-verify` (fica registrado que foi pulado).
set -euo pipefail

VERIF="/root/noemi-infra/deploy/verificar-chaves.sh"
[ -f "$VERIF" ] || { echo "ERRO: $VERIF não existe"; exit 1; }

instalar() {
  local repo="$1"
  local gitdir="$repo/.git"
  [ -d "$gitdir" ] || { echo "  ⏭️  $repo (não é repo git)"; return; }
  local hooks="$gitdir/hooks"
  mkdir -p "$hooks"
  cat > "$hooks/pre-commit" <<HOOK
#!/usr/bin/env bash
# Gerado por deploy/instalar-hooks.sh — guarda de segredo antes do commit.
# Só roda quando o commit MEXE em .env (rodar sempre viraria atrito e o dev
# começaria a usar --no-verify por reflexo, o que mata a guarda).
set -uo pipefail
if git diff --cached --name-only | grep -qE '\.env$|\.env\.'; then
  echo "🔑 .env no commit — verificando segredos…"
  bash "$VERIF" "\$(git rev-parse --show-toplevel)" || {
    echo
    echo "COMMIT BLOQUEADO. Corrija acima, ou use 'git commit --no-verify' se souber o que está fazendo."
    exit 1
  }
fi
exit 0
HOOK
  chmod +x "$hooks/pre-commit"
  echo "  ✅ $repo"
}

echo "instalando pre-commit hook (verificar-chaves.sh):"
for r in /root/noemi-infra /root/sdr-motor /root/motor-site; do
  instalar "$r"
done
echo
echo "Testar:  cd /root/sdr-motor && git commit --allow-empty -m teste"
echo "Pular:   git commit --no-verify"
