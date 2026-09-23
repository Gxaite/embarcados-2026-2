"""Pinagem, tabela de direcao e saidas (requisitos 3 e 4)."""
import pytest

from src.gpio import pinos
from src.gpio.saidas import SaidaDigital, SaidaPWM


def test_pinagem_nova_e_o_padrao():
    """Tabela 1 atualizada: a Cabine 1 herdou a coluna que era da Cabine 2."""
    assert pinos.pinagem_em_uso == "nova"
    assert (pinos.PWM, pinos.DIR1, pinos.DIR2) == (13, 22, 23)
    assert (pinos.ENC_A, pinos.ENC_B) == (20, 21)
    assert (pinos.CORTINA, pinos.SENSOR_ANDAR) == (26, 0)


def test_pinagem_antiga_continua_disponivel():
    """O dashboard ainda rotula o Sensor de Andar como BCM 11."""
    try:
        pinos.aplica("antiga")
        assert (pinos.PWM, pinos.DIR1, pinos.DIR2) == (12, 17, 27)
        assert (pinos.ENC_A, pinos.ENC_B) == (5, 6)
        assert (pinos.CORTINA, pinos.SENSOR_ANDAR) == (16, 11)
    finally:
        pinos.aplica("nova")


def test_pinagem_desconhecida_e_recusada():
    with pytest.raises(ValueError):
        pinos.aplica("inventada")


def test_bcm_nao_e_pino_fisico():
    """O numero BCM nao e a posicao no conector."""
    assert pinos.PINO_FISICO[pinos.DIR1] == 15           # BCM 22
    assert pinos.PINO_FISICO[pinos.SENSOR_ANDAR] == 27   # BCM 0


def test_tabela_de_direcao():
    assert pinos.DIRECOES[pinos.LIVRE] == (0, 0)
    assert pinos.DIRECOES[pinos.SUBIR] == (1, 0)
    assert pinos.DIRECOES[pinos.DESCER] == (0, 1)
    assert pinos.DIRECOES[pinos.FREIO] == (1, 1)


def test_saida_digital(backend):
    saida = SaidaDigital(backend, pinos.DIR1)
    assert backend.modos[pinos.DIR1] == "saida"
    saida.escreve(1)
    assert backend.le(pinos.DIR1) == 1 and saida.valor == 1
    saida.escreve(0)
    assert backend.le(pinos.DIR1) == 0


def test_pwm_a_1_khz(backend):
    SaidaPWM(backend, pinos.PWM)
    assert backend.pwms[0].frequencia_hz == 1000


def test_pwm_satura_a_faixa(backend):
    pwm = SaidaPWM(backend, pinos.PWM)
    assert pwm.ajusta(150.0) == 100.0
    assert pwm.ajusta(-20.0) == 0.0
    assert pwm.ajusta(37.5) == 37.5
