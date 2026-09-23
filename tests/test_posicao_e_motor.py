"""Conversoes de posicao e comando do motor (requisitos 3, 4 e 8)."""
import pytest

from src.controle import motor as mod_motor
from src.controle import posicao
from src.controle.motor import Motor
from src.gpio import pinos


def test_um_milimetro_por_contagem():
    """1000 pulsos/m em quadratura 4x -> 1 contagem = 1 mm."""
    assert posicao.mm_de_contagem(3000) == 3000
    assert posicao.contagem_de_mm(3000) == 3000


def test_posicoes_dos_andares():
    assert [posicao.mm_do_andar(a) for a in (0, 1, 2)] == [0, 3000, 6000]
    with pytest.raises(ValueError):
        posicao.mm_do_andar(3)


def test_tolerancia_de_nivelamento():
    assert posicao.nivelado(3010, 1) is True
    assert posicao.nivelado(2990, 1) is True
    assert posicao.nivelado(3011, 1) is False


def test_limites_do_poco():
    assert posicao.dentro_do_poco(0) and posicao.dentro_do_poco(6000)
    assert not posicao.dentro_do_poco(-1)
    assert not posicao.dentro_do_poco(6001)


def test_motor_escreve_a_tabela_de_direcao(backend):
    motor = Motor(backend)
    for acao, (v1, v2) in pinos.DIRECOES.items():
        motor.define_direcao(acao)
        assert (backend.le(pinos.DIR1), backend.le(pinos.DIR2)) == (v1, v2)


def test_duty_nao_fica_abaixo_do_arranque(backend):
    """Abaixo de 10% o motor parado so zumbe; zero continua sendo zero."""
    motor = Motor(backend)
    motor.define_alvo_de_duty(3.0)
    assert motor.alvo_de_duty == mod_motor.DUTY_MINIMO_DE_MOVIMENTO
    motor.define_alvo_de_duty(0.0)
    assert motor.alvo_de_duty == 0.0


def test_rampa_limita_a_taxa_de_variacao(backend):
    """Partida em rampa, nao em degrau (requisito 2 da Secao 3)."""
    motor = Motor(backend)
    motor.define_alvo_de_duty(100.0)
    depois_de_um_ciclo = motor.passo(0.050)
    assert depois_de_um_ciclo == pytest.approx(mod_motor.TAXA_RAMPA_POR_S * 0.050)
    assert depois_de_um_ciclo < 100.0

    for _ in range(100):
        motor.passo(0.050)
    assert motor.duty == pytest.approx(100.0)


def test_parada_poe_em_freio_com_pwm_zerado(backend):
    motor = Motor(backend)
    motor.aciona_direto(pinos.SUBIR, 50.0)
    motor.para()
    assert motor.duty == 0.0
    assert (backend.le(pinos.DIR1), backend.le(pinos.DIR2)) == (1, 1)
