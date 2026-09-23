"""Geometria do poco da Entrega 1: conversoes e limites.

Modelo reduzido: 3 andares nas posicoes nominais 0, 3000 e 6000 mm.
Resolucao do encoder: 1000 contagens por metro em quadratura -> 1 contagem = 1 mm.
"""

CONTAGENS_POR_MM = 1.0

POSICAO_ANDAR_MM = {0: 0.0, 1: 3000.0, 2: 6000.0}
ANDARES = sorted(POSICAO_ANDAR_MM)
ANDAR_MINIMO, ANDAR_MAXIMO = ANDARES[0], ANDARES[-1]

TOLERANCIA_MM = 10.0            # +-10 mm de nivelamento
LIMITE_INFERIOR_MM = 0.0        # protecao de fim de curso da bancada
LIMITE_SUPERIOR_MM = 6000.0


def contagem_para_mm(contagem):
    return contagem / CONTAGENS_POR_MM


def mm_para_contagem(mm):
    return int(round(mm * CONTAGENS_POR_MM))


def posicao_do_andar(andar):
    return POSICAO_ANDAR_MM[andar]


def andar_valido(andar):
    return andar in POSICAO_ANDAR_MM


def andar_mais_proximo(mm):
    return min(ANDARES, key=lambda a: abs(POSICAO_ANDAR_MM[a] - mm))


def erro_para_andar(mm, andar):
    return mm - POSICAO_ANDAR_MM[andar]


def nivelado(mm, andar=None):
    """Verdadeiro se a cabine esta dentro dos +-10 mm de um andar."""
    if andar is None:
        andar = andar_mais_proximo(mm)
    return abs(erro_para_andar(mm, andar)) <= TOLERANCIA_MM


def dentro_dos_limites(mm):
    return LIMITE_INFERIOR_MM <= mm <= LIMITE_SUPERIOR_MM
