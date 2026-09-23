"""Encoder em quadratura (requisito 6)."""
from src.gpio import pinos
from src.gpio.encoder import EncoderQuadratura

# Ciclo de Gray da quadratura, (A, B), partindo de (0, 0) nos dois sentidos.
SUBINDO = [(0, 1), (1, 1), (1, 0), (0, 0)]
DESCENDO = [(1, 0), (1, 1), (0, 1), (0, 0)]


def passo(backend, a, b):
    if backend.le(pinos.ENC_A) != a:
        backend.provoca(pinos.ENC_A, a)
    if backend.le(pinos.ENC_B) != b:
        backend.provoca(pinos.ENC_B, b)


def test_conta_subindo(backend):
    encoder = EncoderQuadratura(backend)
    for _ in range(3):
        for a, b in SUBINDO:
            passo(backend, a, b)
    assert encoder.contagem == 12          # 4 transicoes por ciclo: quadratura 4x
    assert encoder.transicoes_invalidas == 0


def test_conta_descendo(backend):
    encoder = EncoderQuadratura(backend)
    for _ in range(3):
        for a, b in DESCENDO:
            passo(backend, a, b)
    assert encoder.contagem == -12
    assert encoder.transicoes_invalidas == 0


def test_ida_e_volta_volta_a_zero(backend):
    encoder = EncoderQuadratura(backend)
    for a, b in SUBINDO:
        passo(backend, a, b)
    for a, b in DESCENDO:
        passo(backend, a, b)
    assert encoder.contagem == 0


def test_salto_impossivel_vira_transicao_invalida(backend):
    """00 -> 11 e salto de dois estados: borda perdida, nao contagem."""
    encoder = EncoderQuadratura(backend)
    backend.niveis[pinos.ENC_A] = 1
    backend.provoca(pinos.ENC_B, 1)        # 00 -> 11 de uma vez
    assert encoder.contagem == 0, "nao se deve chutar contagem"
    assert encoder.transicoes_invalidas == 1


def test_contador_satura_em_32_bits(backend):
    encoder = EncoderQuadratura(backend)
    encoder.zera(2 ** 31 - 2)
    for a, b in SUBINDO:
        passo(backend, a, b)
    assert encoder.contagem == 2 ** 31 - 1

    encoder.zera(-(2 ** 31) + 1)
    for a, b in DESCENDO:
        passo(backend, a, b)
    assert encoder.contagem == -(2 ** 31)


def test_interrupcao_nos_dois_canais(backend):
    """O enunciado exige interrupcao em AMBOS os canais, nao so em um."""
    EncoderQuadratura(backend)
    assert pinos.ENC_A in backend.interrupcoes
    assert pinos.ENC_B in backend.interrupcoes
