"""Debounce das entradas on/off."""
import time

from src.gpio import pinos
from src.gpio.entradas import EntradaDigital


def _espera_eventos(eventos, quantos, timeout=1.0):
    limite = time.monotonic() + timeout
    while len(eventos) < quantos and time.monotonic() < limite:
        time.sleep(0.005)
    return eventos


def test_repique_gera_um_unico_evento(gpio):
    eventos = []
    EntradaDigital(gpio, pinos.CORTINA, "CORTINA", debounce_ms=20,
                   ao_mudar=eventos.append)

    # Repique tipico: cinco bordas rapidas terminando em nivel alto.
    for nivel in (1, 0, 1, 0, 1):
        gpio.muda(pinos.CORTINA, nivel)
        time.sleep(0.002)

    _espera_eventos(eventos, 1)
    time.sleep(0.05)
    assert len(eventos) == 1, "repique contou obstrucao fantasma"
    assert eventos[0].subida


def test_pulso_que_volta_ao_estado_anterior_nao_gera_evento(gpio):
    eventos = []
    EntradaDigital(gpio, pinos.CORTINA, "CORTINA", debounce_ms=20,
                   ao_mudar=eventos.append)
    gpio.muda(pinos.CORTINA, 1)
    time.sleep(0.002)
    gpio.muda(pinos.CORTINA, 0)   # voltou antes de estabilizar
    time.sleep(0.08)
    assert eventos == []


def test_obstrucao_e_liberacao_geram_dois_eventos(gpio):
    eventos = []
    EntradaDigital(gpio, pinos.CORTINA, "CORTINA", debounce_ms=15,
                   ao_mudar=eventos.append)
    gpio.muda(pinos.CORTINA, 1)
    _espera_eventos(eventos, 1)
    gpio.muda(pinos.CORTINA, 0)
    _espera_eventos(eventos, 2)
    assert [e.nivel for e in eventos] == [1, 0]


def test_captura_e_do_instante_da_borda_crua_nao_do_fim_do_debounce(gpio):
    """A contagem registrada deve ser a de quando o pino mudou de verdade.

    Se fosse lida depois do atraso de debounce, a cabine ja teria andado e a
    medicao do centro da bandeirola sairia enviesada.
    """
    contador = {"valor": 1000}
    eventos = []
    EntradaDigital(gpio, pinos.SENSOR_ANDAR, "SENSOR", debounce_ms=30,
                   ao_mudar=eventos.append,
                   captura=lambda: contador["valor"])

    gpio.muda(pinos.SENSOR_ANDAR, 1)   # borda crua com o contador em 1000
    contador["valor"] = 1234           # a cabine continua subindo
    _espera_eventos(eventos, 1)

    assert eventos[0].captura == 1000
