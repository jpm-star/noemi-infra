"""Troca a foto placeholder dos 12 demos de academia pela foto julgada do acervo.

O QUE ESTAVA ERRADO: estes 12 sites saíram da geração ANTERIOR do motor — a mesma que
escrevia o `<title>` curto e por isso deixou os leads órfãos (ver `recuperar_demos_lote.py`).
Aquela geração ilustrava serviço com `loremflickr.com/600/420/<keyword>`: foto ALEATÓRIA do
Flickr pra palavra. E o fallback do `onerror` era pior ainda — `picsum.photos`, que devolve
uma imagem aleatória de QUALQUER assunto: paisagem, gato, prédio, num card "Musculação".

O QUE JÁ EXISTE: `_acervo/academia/` tem 4 fotos ingeridas à mão e aprovadas na portaria do
`acervo_ingerir.py` (OCR limpo, nenhuma com texto). `acervo_fotos.garantir('academia')` só
lê esse manifesto — o trabalho caro do segmento já foi pago. Falta LIGAR as fotos aos sites
que ficaram pra trás, e é só isso que este script faz.

POR QUE NÃO REGERAR OS 12: regerar troca a copy, o layout e o endereço de sites que já estão
no ar, já casados com lead e já conferidos um a um. Trocar 4 URLs por card é o diff mínimo
que resolve o defeito real (foto errada), sem tocar em nada que já foi validado.

O BURACO QUE SOBRA: a geração antiga tinha 6 serviços, o catálogo de hoje tem 4. Dois cards
('Treino Funcional & Cross', 'Aula Experimental') não têm posição no acervo. Eles reusam a
foto semanticamente mais próxima em vez de manter placeholder — foto certa repetida é melhor
que foto aleatória errada. Ingerir 5.jpg/6.jpg no acervo desfaz o reuso sozinho (ver MAPA).

    python acervo_aplicar_demos.py            # mostra o que faria
    python acervo_aplicar_demos.py --aplicar  # grava (com backup)
    python acervo_aplicar_demos.py --check    # autoteste, sem rede e sem disco de produção
"""
from __future__ import annotations

import html as _html
import os
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import acervo_fotos as af  # noqa: E402

NICHO = "academia"
BACKUP = Path(os.environ.get("DEMOS_BACKUP_DIR", "/var/backups/noemi-demos"))

# keyword do loremflickr -> (serviço que o card anuncia, posição no acervo, reserva)
# A keyword é a chave porque aparece nos DOIS lugares que precisam mudar: o `src` do card e
# o `img` do JSON do lightbox. O nome do serviço vai junto só pra conferir — se o alt do
# card não bater com o esperado, o site não é o que eu li e o lote inteiro aborta.
# A "reserva" é o reuso quando o acervo não tem posição própria pro serviço; assim que
# alguém ingerir a foto daquela posição, ela ganha da reserva sem editar este arquivo.
MAPA = {
    "gym,weights,fitness":        ("Musculação",               1, None),
    "fitness,class,workout":      ("Aulas Coletivas",          3, None),
    "personal,trainer,gym":       ("Personal Trainer",         4, None),
    "fitness,assessment,measure": ("Avaliação Física",         2, None),
    # alta intensidade em grupo — a aula coletiva é o que mais se parece com isso
    "crossfit,training,workout":  ("Treino Funcional & Cross", 5, 3),
    # "conheça a estrutura, sinta o clima" — a sala de musculação MOSTRA a estrutura
    "gym,fitness,people":         ("Aula Experimental",        6, 1),
}

DEMOS = [
    "academia-body-express-botucatu", "academia-cia-bio-fit-jau", "ctm-academia-marilia",
    "espaco-vip-adamantina", "academia-forma-e-forca-marilia", "malibu-exclusive-aracatuba",
    "red-dragon-gym-presidente-prudente", "academia-ricodo-botucatu", "academia-tito-colo-jau",
    "academia-vidativa-birigui", "winner-academia-marilia", "academia-xploud-assis",
]

_LOREM = re.compile(r"https://loremflickr\.com/\d+/\d+/([a-z,]+)\?lock=\d+")
_THUMB = re.compile(r'src="https://loremflickr\.com/\d+/\d+/([a-z,]+)\?lock=\d+"'
                    r'[^>]*?alt="([^"]*)"', re.S)
_ONERROR = re.compile(r'\s*onerror="this\.onerror=null;this\.src=\'https://picsum\.photos/[^\']*\'"')
_FB = re.compile(r'"fb": "https://picsum\.photos/[^"]*"')


def destino(keyword: str, existe=None) -> str:
    """URL da foto do acervo pra uma keyword. `existe` permite testar sem disco real."""
    existe = existe or (lambda n: (af.RAIZ / NICHO / f"{n}.jpg").is_file())
    _, pos, reserva = MAPA[keyword]
    if not existe(pos):
        if reserva is None or not existe(reserva):
            raise KeyError(f"acervo de {NICHO!r} não tem {pos}.jpg nem reserva pra {keyword!r}")
        pos = reserva
    return f"{af.URL_BASE}/{NICHO}/{pos}.jpg"


def trocar(txt: str, existe=None) -> tuple[str, int]:
    """Troca placeholder por acervo. Devolve (html novo, quantas URLs mudaram).

    Some com o `onerror`/`fb` do picsum de propósito: com foto local o fallback não protege
    de nada (se o próprio Caddy caiu, o picsum não salva o card) e só mantém viva a chance de
    o site mostrar uma paisagem aleatória num card de musculação. É o que o motor de hoje já
    faz — os sites novos saem com `"fb": ""`."""
    for kw, alt in _THUMB.findall(txt):
        esperado = MAPA.get(kw, (None,))[0]
        if _html.unescape(alt) != esperado:
            raise ValueError(f"card {alt!r} usa a keyword {kw!r}, que eu li como {esperado!r}")
    novo, n = _LOREM.subn(lambda m: destino(m.group(1), existe), txt)
    novo = _FB.sub('"fb": ""', _ONERROR.sub("", novo))
    return novo, n


def rodar(aplicar: bool = False, pastas: list[str] | None = None) -> list[tuple[str, int, str]]:
    """Confere os 12 antes de escrever em qualquer um. Erro em um aborta todos: 12 sites no
    ar, metade com foto nova e metade não, é pior que 12 iguais — ninguém sabe quais mandar."""
    out, erros = [], []
    for slug in (pastas or DEMOS):
        arq = af.RAIZ.parent / slug / "index.html"
        if not arq.is_file():
            erros.append(f"{slug}: index.html não existe")
            continue
        txt = arq.read_text(errors="ignore")
        if "loremflickr" not in txt:
            out.append((slug, 0, "já aplicado — nada a fazer"))
            continue
        try:
            novo, n = trocar(txt)
        except (ValueError, KeyError) as e:
            erros.append(f"{slug}: {e}")
            continue
        if "loremflickr" in novo or "picsum" in novo:
            erros.append(f"{slug}: sobrou placeholder depois da troca")
            continue
        if aplicar:
            dest = BACKUP / slug
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copy2(arq, dest / "index.html")
            arq.write_text(novo)
        out.append((slug, n, "gravado" if aplicar else "pronto pra gravar"))
    if erros:
        raise SystemExit("ABORTADO, nada gravado:\n  " + "\n  ".join(erros))
    return out


def _autoteste() -> None:
    tem = {1, 2, 3, 4}.__contains__          # o acervo real de hoje: 4 posições
    todas = {1, 2, 3, 4, 5, 6}.__contains__  # o dia em que alguém ingerir as 2 que faltam

    assert destino("gym,weights,fitness", tem) == "/_acervo/academia/1.jpg"
    # sem 5.jpg o funcional cai na reserva (3); com 5.jpg ele para de cair sozinho
    assert destino("crossfit,training,workout", tem) == "/_acervo/academia/3.jpg"
    assert destino("crossfit,training,workout", todas) == "/_acervo/academia/5.jpg"
    assert destino("gym,fitness,people", todas) == "/_acervo/academia/6.jpg"

    card = ('<div class="thumb"><img loading="lazy" src="https://loremflickr.com/600/420/'
            'gym,weights,fitness?lock=1"\n onerror="this.onerror=null;this.src=\''
            'https://picsum.photos/seed/gym,weights,fitness1/600/420\'" alt="Musculação"></div>')
    js = ('{"nome": "Musculação", "img": "https://loremflickr.com/900/620/gym,weights,'
          'fitness?lock=1", "fb": "https://picsum.photos/seed/gym,weights,fitness1/900/620"}')
    novo, n = trocar(card + js, tem)
    assert n == 2, n
    assert "loremflickr" not in novo and "picsum" not in novo, novo
    assert novo.count("/_acervo/academia/1.jpg") == 2, novo
    assert 'onerror' not in novo, "o fallback picsum tem que sumir junto"
    assert '"fb": ""' in novo, novo

    # rodar de novo não muda mais nada
    assert trocar(novo, tem) == (novo, 0)

    # card cujo alt não bate com a keyword = site diferente do que eu li: para tudo
    trocado = card.replace('alt="Musculação"', 'alt="Natação"')
    try:
        trocar(trocado, tem)
        raise AssertionError("devia ter recusado alt trocado")
    except ValueError as e:
        assert "Natação" in str(e), e

    # acervo vazio não pode virar URL quebrada em site no ar
    try:
        destino("gym,weights,fitness", lambda n: False)
        raise AssertionError("devia ter recusado acervo vazio")
    except KeyError:
        pass
    print("autoteste ok")


if __name__ == "__main__":
    if "--check" in sys.argv[1:]:
        _autoteste()
        sys.exit(0)
    aplicar = "--aplicar" in sys.argv[1:]
    linhas = rodar(aplicar)
    for slug, n, estado in linhas:
        print(f"  {slug:<38} {n:>2} URLs  {estado}")
    print(f"\n{len(linhas)} demos · {sum(n for _, n, _ in linhas)} URLs de placeholder trocadas")
    if not aplicar:
        print("nada gravado. rode com --aplicar pra valer.")
