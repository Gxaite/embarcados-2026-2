"""Integracao contra o poco simulado: viagens, medicao e seguranca.

Estes testes rodam em tempo real e levam alguns minutos. Eles exercitam o
mesmo codigo de controle que roda na placa - o que muda e so o backend.
"""
import time

import pytest

from src.controle import posicao
from src.controle.cabine import Cabine
from src.gpio import pinos
from src.gpio.sim_backend import BackendSimulado


@pytest.fixture
def cabine():
    backend = BackendSimulado()
    c = Cabine(backend)
    c.simulador = backend
    yield c
    c.finaliza()


def espera_chegar(cabine, limite_s=45.0):
    fim = time.monotonic() + limite_s
    while cabine.em_viagem and time.monotonic() < fim:
        time.sleep(0.02)
    time.sleep(0.3)          # deixa a frenagem assentar
    assert not cabine.em_viagem, "a viagem nao terminou em %.0f s" % limite_s


@pytest.mark.parametrize("andar", [1, 2, 0])
def test_para_dentro_da_tolerancia(cabine, andar):
    cabine.vai_para_andar(andar)
    espera_chegar(cabine)
    assert posicao.nivelado(cabine.posicao_mm, andar), \
        "parou em %.0f mm, fora dos +-%d mm do andar %d" % (
            cabine.posicao_mm, posicao.TOLERANCIA_MM, andar)


def test_viagem_completa_sem_perder_bordas(cabine):
    for andar in (2, 0, 1):
        cabine.vai_para_andar(andar)
        espera_chegar(cabine)
    assert cabine.encoder.transicoes_invalidas == 0, \
        "o Python perdeu bordas do encoder durante as viagens"


def test_mede_a_bandeirola_ao_atravessar(cabine):
    """Subir do andar 0 ao 2 atravessa a bandeirola do andar 1 por inteiro."""
    cabine.vai_para_andar(2)
    espera_chegar(cabine)
    do_andar_1 = [m for m in cabine.sensor_andar.medicoes if m.andar == 1]
    assert do_andar_1, "a travessia do andar 1 deveria ter sido medida"
    medicao = do_andar_1[0]
    assert medicao.largura_mm == pytest.approx(84.0, abs=3.0)
    assert medicao.centro_mm == pytest.approx(3000.0, abs=3.0)


def test_fim_de_curso_no_topo(cabine):
    """Acionamento manual NAO passa pela malha fechada; o fim de curso sim."""
    cabine.vai_para_andar(2)
    espera_chegar(cabine)
    cabine.aciona_direto(pinos.SUBIR, 40.0)
    time.sleep(2.0)
    assert cabine.posicao_mm <= posicao.TOPO_MM
    assert cabine.motor.direcao == pinos.FREIO


def test_fim_de_curso_no_fundo(cabine):
    cabine.aciona_direto(pinos.DESCER, 40.0)
    time.sleep(2.0)
    assert cabine.posicao_mm >= posicao.FUNDO_MM
    assert cabine.motor.direcao == pinos.FREIO


def test_cortina_filtra_o_repique(cabine):
    """O simulador repica de proposito: uma obstrucao deve virar um evento."""
    cabine.simulador.obstrui_porta()
    time.sleep(0.2)
    cabine.simulador.libera_porta()
    time.sleep(0.2)
    assert cabine.cortina.obstrucoes == 1
    assert cabine.cortina.liberacoes == 1
    assert cabine.cortina.bordas_cruas > 2, "o simulador deveria ter repicado"


def test_destino_fora_do_poco_e_recusado(cabine):
    with pytest.raises(ValueError):
        cabine.vai_para_mm(6500)
    with pytest.raises(ValueError):
        cabine.vai_para_mm(-10)


def test_encerramento_deixa_a_placa_limpa(cabine):
    cabine.aciona_direto(pinos.SUBIR, 30.0)
    time.sleep(0.5)
    cabine.finaliza()
    assert cabine.motor.duty == 0.0
    assert cabine.motor.direcao == pinos.FREIO
