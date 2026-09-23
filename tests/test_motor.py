"""Direcao conforme a Tabela 2 e rampa de duty."""
from src.controle.motor import DUTY_MINIMO, TAXA_RAMPA, Motor
from src.gpio import pinos


def test_tabela_de_direcao(gpio):
    motor = Motor(gpio)
    esperado = {"livre": (0, 0), "subir": (1, 0),
                "descer": (0, 1), "freio": (1, 1)}
    for direcao, (d1, d2) in esperado.items():
        motor.define_direcao(direcao)
        assert (gpio.le(pinos.DIR1), gpio.le(pinos.DIR2)) == (d1, d2), direcao


def test_pwm_criado_na_frequencia_certa(gpio):
    Motor(gpio)
    assert pinos.PWM in gpio.pwm


def test_rampa_nao_salta_para_o_alvo(gpio):
    motor = Motor(gpio)
    dt = 0.05
    novo = motor.rampa_para(100.0, dt)
    assert novo == TAXA_RAMPA * dt          # avancou so um passo de rampa
    assert novo < 100.0


def test_rampa_chega_ao_alvo_em_varios_passos(gpio):
    motor = Motor(gpio)
    for _ in range(100):
        motor.rampa_para(60.0, 0.05)
    assert motor.duty == 60.0


def test_duty_abaixo_do_arranque_sobe_para_o_minimo(gpio):
    motor = Motor(gpio)
    for _ in range(100):
        motor.rampa_para(4.0, 0.05)
    assert motor.duty == DUTY_MINIMO


def test_duty_zero_e_permitido(gpio):
    motor = Motor(gpio)
    for _ in range(100):
        motor.rampa_para(0.0, 0.05)
    assert motor.duty == 0.0


def test_para_com_freio_zera_pwm_e_trava(gpio):
    motor = Motor(gpio)
    motor.aplica_duty(80.0)
    motor.para_com_freio()
    assert motor.duty == 0.0
    assert (gpio.le(pinos.DIR1), gpio.le(pinos.DIR2)) == (1, 1)
