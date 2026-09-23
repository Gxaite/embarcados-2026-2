"""Conversoes de posicao, nivelamento e limites do poco."""

CONTAGENS_POR_MM = 1          # quadratura 4x sobre 1000 pulsos/m
MM_POR_ANDAR = 3000
ANDARES = (0, 1, 2)
TOLERANCIA_MM = 10            # +-10 mm exigidos pelo enunciado

FUNDO_MM = 0
TOPO_MM = 6000


def mm_do_andar(andar):
    if andar not in ANDARES:
        raise ValueError("andar invalido: %r (validos: %s)"
                         % (andar, ", ".join(str(a) for a in ANDARES)))
    return andar * MM_POR_ANDAR


def mm_de_contagem(contagem):
    return contagem / CONTAGENS_POR_MM


def contagem_de_mm(mm):
    return int(round(mm * CONTAGENS_POR_MM))


def andar_estimado(mm):
    """Andar mais proximo, ou None se estiver claramente entre andares."""
    candidato = min(ANDARES, key=lambda a: abs(mm - mm_do_andar(a)))
    if abs(mm - mm_do_andar(candidato)) <= MM_POR_ANDAR / 2.0:
        return candidato
    return None


def nivelado(mm, andar):
    return abs(mm - mm_do_andar(andar)) <= TOLERANCIA_MM


def dentro_do_poco(mm):
    return FUNDO_MM <= mm <= TOPO_MM


def limita(mm):
    return max(float(FUNDO_MM), min(float(TOPO_MM), float(mm)))
