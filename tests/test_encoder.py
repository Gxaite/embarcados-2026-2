"""Encoder em quadratura: sentido, contagem e robustez."""
from src.gpio import pinos
from src.gpio.encoder import EncoderQuadratura, _como_int32

# Um ciclo completo subindo: 00 -> 01 -> 11 -> 10 -> 00  (4 contagens = 4 mm)
CICLO_SUBINDO = [(0, 1), (1, 1), (1, 0), (0, 0)]


def _anda(gpio, enc, passos):
    """Aplica `passos` transicoes de quadratura (positivo = subindo)."""
    sequencia = CICLO_SUBINDO if passos > 0 else list(reversed(
        [(0, 0), (0, 1), (1, 1), (1, 0)]))
    for i in range(abs(passos)):
        a, b = sequencia[i % 4] if passos > 0 else sequencia[i % 4]
        gpio.muda(pinos.ENC_A, a)
        gpio.muda(pinos.ENC_B, b)


def test_conta_subida_uma_contagem_por_transicao(gpio):
    enc = EncoderQuadratura(gpio, pinos.ENC_A, pinos.ENC_B)
    for a, b in CICLO_SUBINDO:
        gpio.muda(pinos.ENC_A, a)
        gpio.muda(pinos.ENC_B, b)
    # 4 transicoes de um ciclo completo = 4 contagens = 4 mm
    assert enc.contagem == 4
    assert enc.transicoes_invalidas == 0


def test_conta_descida_com_sinal_negativo(gpio):
    enc = EncoderQuadratura(gpio, pinos.ENC_A, pinos.ENC_B)
    for a, b in [(1, 0), (1, 1), (0, 1), (0, 0)]:  # ordem inversa
        gpio.muda(pinos.ENC_A, a)
        gpio.muda(pinos.ENC_B, b)
    assert enc.contagem == -4


def test_sobe_e_desce_volta_a_origem(gpio):
    enc = EncoderQuadratura(gpio, pinos.ENC_A, pinos.ENC_B)
    for _ in range(10):
        for a, b in CICLO_SUBINDO:
            gpio.muda(pinos.ENC_A, a)
            gpio.muda(pinos.ENC_B, b)
    assert enc.contagem == 40
    for _ in range(10):
        for a, b in [(1, 0), (1, 1), (0, 1), (0, 0)]:
            gpio.muda(pinos.ENC_A, a)
            gpio.muda(pinos.ENC_B, b)
    assert enc.contagem == 0


def test_transicao_impossivel_e_registrada_e_nao_conta(gpio):
    enc = EncoderQuadratura(gpio, pinos.ENC_A, pinos.ENC_B)
    # Salto direto de 00 para 11: os dois canais mudam "ao mesmo tempo".
    gpio.valores[pinos.ENC_A] = 1
    gpio.muda(pinos.ENC_B, 1)
    assert enc.transicoes_invalidas == 1
    assert enc.contagem == 0


def test_contador_e_int32_com_sinal():
    assert _como_int32(2**31 - 1) == 2**31 - 1
    assert _como_int32(2**31) == -2**31
    assert _como_int32(-2**31 - 1) == 2**31 - 1


def test_zera_define_posicao(gpio):
    enc = EncoderQuadratura(gpio, pinos.ENC_A, pinos.ENC_B)
    enc.zera(3000)
    assert enc.contagem == 3000
