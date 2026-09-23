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


def test_ancora_corrige_a_deriva_da_contagem(cabine):
    """Perde a referencia e reancora pela bandeirola.

    A viagem tem de ATRAVESSAR a bandeirola por inteiro: parar dentro dela nao
    produz borda de saida, e sem as duas bordas nao ha centro para medir.
    """
    cabine.vai_para_andar(2)          # do 0 ao 2, atravessando o andar 1
    espera_chegar(cabine)
    assert cabine.sensor_andar.medicoes, "a travessia do andar 1 deveria medir"

    # A contagem passa a mentir em 150 mm, como quando o widget e resetado no
    # meio da sessao ou quando bordas se perdem por ruido eletrico.
    # Atrasa a contagem em 150 mm: a cabine passa a se julgar mais baixa do que
    # esta. Adiantar em vez de atrasar poria o destino ABAIXO do fundo do poco,
    # que e o caso de travamento coberto por test_travamento_aborta_a_viagem.
    verdadeira = cabine.posicao_mm
    cabine.zera(verdadeira - 150)

    cabine.vai_para_andar(0)          # atravessa o andar 1 de novo, ja torto
    espera_chegar(cabine)

    # A bandeirola do andar 1 esta em 3000 mm de verdade; com a contagem 150 mm
    # adiantada, o centro dela e medido em ~3150. Esse erro E a deriva.
    medicao = cabine.sensor_andar.medicoes[-1]
    assert medicao.erro_mm == pytest.approx(-150, abs=15)

    antes = cabine.posicao_mm
    _, correcao = cabine.ancora()
    assert correcao == pytest.approx(150, abs=15), \
        "a correcao deveria desfazer a deriva de 150 mm"
    assert cabine.posicao_mm == pytest.approx(antes + correcao, abs=2)


def test_travamento_aborta_a_viagem(cabine):
    """Destino inalcancavel: a cabine encosta no batente e a malha desiste.

    Sem isto o motor ficaria comandado indefinidamente contra o fim de curso
    mecanico - numa bancada compartilhada, estragando o equipamento alheio.
    """
    cabine.zera(2000)                 # a contagem mente: a cabine esta em 0
    cabine.vai_para_mm(0)             # exige descer 2000 mm que nao existem
    tempo_limite = time.monotonic() + 30
    while cabine.em_viagem and time.monotonic() < tempo_limite:
        time.sleep(0.05)
    assert not cabine.em_viagem, "a malha deveria ter abortado por travamento"
    assert cabine.motor.duty == 0.0
    assert cabine.motor.direcao == pinos.FREIO


def test_andar_extremo_nao_e_cortado_pelo_fim_de_curso(cabine):
    """O andar 2 fica em 6000 mm, que e o proprio limite do poco.

    A margem do fim de curso vale so no acionamento manual: aplicada em malha
    fechada, ela abortaria a viagem antes da chegada.
    """
    cabine.vai_para_andar(2)
    espera_chegar(cabine)
    assert posicao.nivelado(cabine.posicao_mm, 2), \
        "parou em %.0f mm" % cabine.posicao_mm

    cabine.vai_para_andar(0)
    espera_chegar(cabine)
    assert posicao.nivelado(cabine.posicao_mm, 0), \
        "parou em %.0f mm" % cabine.posicao_mm


def test_manual_para_antes_do_limite(cabine):
    """Acionamento manual nao tem rampa: a margem absorve a frenagem."""
    cabine.aciona_direto(pinos.SUBIR, 60.0)
    tempo_limite = time.monotonic() + 40
    while cabine.motor.direcao != pinos.FREIO and time.monotonic() < tempo_limite:
        time.sleep(0.05)
    time.sleep(0.5)
    assert cabine.posicao_mm <= posicao.TOPO_MM, \
        "passou do topo: %.0f mm" % cabine.posicao_mm


def test_renivelamento_quando_a_inercia_passa_do_ponto(monkeypatch):
    """Frenagem mais longa que a tolerancia: uma tacada so nao acerta.

    E o caso da bancada real, onde o `andar 2` parou em 6016 mm. Com o motor
    incapaz de andar abaixo de 10% de duty, existe uma distancia minima de
    frenagem; quando ela supera os +-10 mm, so corrigindo depois de assentar.
    """
    from src.gpio import sim_backend
    monkeypatch.setattr(sim_backend, "CONSTANTE_DE_INERCIA_S", 0.7)
    monkeypatch.setattr(sim_backend, "VELOCIDADE_MAXIMA_MM_S", 700.0)

    backend = sim_backend.BackendSimulado()
    c = Cabine(backend)
    try:
        # Andares 1 e 0, nao o 2: a 700 mm/s o simulador gera 700 interrupcoes
        # por segundo e o Python perde bordas, entao a contagem fica atras da
        # posicao real e o andar 2 (que fica no proprio topo do poco) vira
        # inalcancavel. Isso e perda de borda, nao falha de renivelamento - e a
        # bancada real registrou ZERO transicoes invalidas a 40% de duty.
        for andar in (1, 0):
            c.vai_para_andar(andar)
            espera_chegar(c, limite_s=90)
            assert posicao.nivelado(c.posicao_mm, andar), \
                "andar %d: parou em %.0f mm, fora dos +-%d mm" % (
                    andar, c.posicao_mm, posicao.TOLERANCIA_MM)
    finally:
        c.finaliza()
