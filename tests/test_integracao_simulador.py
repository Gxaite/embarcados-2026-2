"""Integracao ponta a ponta contra o modelo de poco em software.

Estes testes exercitam o caminho completo - malha de controle, motor, encoder
por interrupcao, sensor de andar e cortina - e sao os que mais se aproximam do
que o video da entrega precisa mostrar. Rodam em tempo real, entao sao lentos.
"""
import time

import pytest

from src.controle import posicao
from src.controle.cabine import Cabine
from src.gpio.sim_backend import BackendSimulado


@pytest.fixture
def cabine():
    sim = BackendSimulado(posicao_inicial_mm=0.0)
    c = Cabine(sim, posicao_inicial_mm=0.0)
    c.simulador = sim
    yield c
    c.finaliza()


def _viaja(cabine, andar, timeout=25.0):
    cabine.vai_para_andar(andar)
    assert cabine.espera_chegada(timeout), "nao chegou ao andar %d a tempo" % andar


def test_sobe_do_andar_0_ao_1_e_para_nivelado(cabine):
    _viaja(cabine, 1)
    erro = posicao.erro_para_andar(cabine.posicao_mm, 1)
    assert abs(erro) <= posicao.TOLERANCIA_MM, "erro de %.1f mm" % erro
    assert cabine.nivelado


def test_desce_de_volta_ao_andar_0(cabine):
    _viaja(cabine, 1)
    _viaja(cabine, 0)
    assert abs(posicao.erro_para_andar(cabine.posicao_mm, 0)) <= posicao.TOLERANCIA_MM


def test_contagem_do_encoder_acompanha_a_posicao_real(cabine):
    _viaja(cabine, 1)
    real = cabine.simulador.posicao_real_mm()
    assert abs(cabine.posicao_mm - real) <= 5.0, (
        "encoder marcou %.1f mm, poco esta em %.1f mm"
        % (cabine.posicao_mm, real))


def test_travessia_mede_a_bandeirola_do_andar_1(cabine):
    """Ao passar pela bandeirola do andar 1 sem parar, o centro sai medido."""
    _viaja(cabine, 2)
    medicoes = [m for m in cabine.sensor_andar.medicoes if m.andar == 1]
    assert medicoes, "nenhuma bandeirola do andar 1 medida na subida"
    m = medicoes[0]
    assert m.largura > posicao.TOLERANCIA_MM * 2, (
        "bandeirola deveria ser bem mais larga que a tolerancia")
    assert abs(m.erro) <= 15.0, "centro estimado errou %.1f mm" % m.erro


def test_fim_de_curso_satura_o_destino(cabine):
    cabine.vai_para_mm(99000.0)
    assert cabine.espera_chegada(40.0)
    assert cabine.posicao_mm <= posicao.LIMITE_SUPERIOR_MM + posicao.TOLERANCIA_MM


def test_cortina_com_repique_conta_uma_unica_obstrucao(cabine):
    cabine.simulador.obstruir_porta()
    time.sleep(0.25)
    assert cabine.cortina.obstruida
    assert cabine.cortina.obstrucoes == 1

    cabine.simulador.liberar_porta()
    time.sleep(0.25)
    assert not cabine.cortina.obstruida
    assert cabine.cortina.obstrucoes == 1


def test_sigint_deixa_o_motor_em_freio_e_pwm_zerado(cabine):
    cabine.vai_para_andar(2)
    time.sleep(0.5)
    cabine.finaliza()          # e o que o tratador de SIGINT chama
    assert cabine.motor.duty == 0.0
    assert cabine.motor.direcao == "freio"


def test_acionamento_manual_respeita_o_fim_de_curso(cabine):
    """Requisito 5 da Secao 3: nada pode passar dos 0..6000 mm.

    O comando `motor` nao passa pela malha fechada, entao a protecao tem de
    valer tambem para ele.
    """
    cabine.aciona_manual("subir", 90.0)
    limite = time.monotonic() + 30.0
    while time.monotonic() < limite and cabine.motor.duty > 0.0:
        time.sleep(0.05)

    assert cabine.motor.duty == 0.0, "o motor continuou acionado fora do curso"
    assert cabine.motor.direcao == "freio"
    assert cabine.posicao_mm <= posicao.LIMITE_SUPERIOR_MM + 100.0, (
        "cabine chegou a %.0f mm" % cabine.posicao_mm)


def test_acionamento_manual_descendo_para_no_limite_inferior(cabine):
    cabine.aciona_manual("descer", 90.0)
    limite = time.monotonic() + 15.0
    while time.monotonic() < limite and cabine.motor.duty > 0.0:
        time.sleep(0.05)

    assert cabine.motor.duty == 0.0
    assert cabine.posicao_mm >= posicao.LIMITE_INFERIOR_MM - 100.0
