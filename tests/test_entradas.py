"""Entradas nos dois modos: polling e interrupcao com debounce (requisito 5)."""
import time

from src.gpio import pinos
from src.gpio.entradas import EntradaInterrupcao, EntradaPolling


def test_polling_le_o_nivel_atual(backend):
    entrada = EntradaPolling(backend, pinos.CORTINA)
    assert backend.modos[pinos.CORTINA] == "entrada"
    assert entrada.le() == 0 and entrada.ativa is False
    backend.niveis[pinos.CORTINA] = 1
    assert entrada.le() == 1 and entrada.ativa is True


def test_polling_nao_registra_interrupcao(backend):
    """O caminho de polling nao deve custar uma thread de interrupcao."""
    EntradaPolling(backend, pinos.CORTINA)
    assert pinos.CORTINA not in backend.interrupcoes


def test_repique_gera_um_unico_evento(backend):
    eventos = []
    EntradaInterrupcao(backend, pinos.CORTINA, lambda n, _: eventos.append(n),
                       debounce_ms=15.0)
    for valor in (1, 0, 1, 0, 1):        # repique da borda de subida
        backend.provoca(pinos.CORTINA, valor)
    time.sleep(0.05)
    assert eventos == [1], "repique deveria virar um unico evento"


def test_repique_que_volta_ao_mesmo_nivel_nao_e_evento(backend):
    eventos = []
    EntradaInterrupcao(backend, pinos.CORTINA, lambda n, _: eventos.append(n),
                       debounce_ms=15.0)
    backend.provoca(pinos.CORTINA, 1)
    backend.provoca(pinos.CORTINA, 0)    # assentou de volta em 0
    time.sleep(0.05)
    assert eventos == []


def test_conta_bordas_cruas(backend):
    entrada = EntradaInterrupcao(backend, pinos.CORTINA, lambda n, i: None,
                                 debounce_ms=15.0)
    for valor in (1, 0, 1, 0, 1):
        backend.provoca(pinos.CORTINA, valor)
    time.sleep(0.05)
    assert entrada.bordas_cruas == 5


def test_instantanea_e_capturada_na_borda_crua(backend):
    """O valor precisa ser o do instante da borda, nao o do fim do debounce.

    Se fosse lido depois, a cabine ja teria andado durante a janela e a medicao
    do centro da bandeirola sairia enviesada.
    """
    contador = {"valor": 100}
    recebidos = []
    EntradaInterrupcao(backend, pinos.SENSOR_ANDAR,
                       lambda n, i: recebidos.append(i),
                       debounce_ms=15.0,
                       instantanea=lambda: contador["valor"])
    backend.provoca(pinos.SENSOR_ANDAR, 1)
    contador["valor"] = 999           # a cabine andou durante o debounce
    time.sleep(0.05)
    assert recebidos == [100]
