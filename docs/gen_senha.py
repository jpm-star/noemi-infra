#!/usr/bin/env python3
"""Gera senha forte por cliente (secrets, alta entropia). Uso:
    python docs/gen_senha.py "bauru_clinica-sorriso-vivo"
NUNCA reusa entre clientes; NÃO commitar a saída. Guardar no 01_ACESSOS.md privado.
ponytail: secrets.choice sobre alfabeto sem ambíguos — nada de lib externa."""
import secrets
import sys

# alfabeto sem caracteres ambíguos (0/O, 1/l/I) — menos erro de digitação
_ALFA = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789!@#%&*?"


def gerar(n: int = 20) -> str:
    # garante variedade (1 minúscula, 1 maiúscula, 1 dígito, 1 símbolo) e preenche o resto
    base = [secrets.choice("abcdefghijkmnopqrstuvwxyz"),
            secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ"),
            secrets.choice("23456789"),
            secrets.choice("!@#%&*?")]
    base += [secrets.choice(_ALFA) for _ in range(max(0, n - len(base)))]
    # embaralha sem viés (Fisher-Yates via secrets)
    for i in range(len(base) - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        base[i], base[j] = base[j], base[i]
    return "".join(base)


if __name__ == "__main__":
    cliente = sys.argv[1] if len(sys.argv) > 1 else "(sem-slug)"
    print(f"cliente: {cliente}")
    print(f"senha  : {gerar()}")
    print("→ cole no 01_ACESSOS.md privado do cliente; peça troca no 1º acesso; NÃO commitar.")

    # self-check: entropia mínima e variedade
    s = gerar()
    assert len(s) == 20 and any(c.islower() for c in s) and any(c.isupper() for c in s) \
        and any(c.isdigit() for c in s) and any(c in "!@#%&*?" for c in s), "senha fraca"
