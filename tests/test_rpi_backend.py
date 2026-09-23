"""Backend da Raspberry Pi contra uma RPi.GPIO de mentira.

Este e o unico arquivo do projeto que nao roda nem nos testes nem no modo
--simulado: ele so executa na placa. Um erro de API ali (nome trocado,
argumento fora de ordem, assinatura de callback errada) so apareceria na
bancada, dentro de uma thread de interrupcao, onde e caro de achar e onde o
tempo e cronometrado.

Estes testes registram um RPi.GPIO falso em sys.modules antes de importar o
backend - que importa a biblioteca tardiamente, de proposito - e conferem as
chamadas de verdade.

Isto NAO prova que o programa funciona na bancada: nao ha motor, latencia de
interrupcao nem jitter de escalonador aqui. Prova que as chamadas a biblioteca
estao corretas, que e o que da para verificar longe da placa.
"""
import sys
import types

import pytest

from src.gpio import backend as bk
from src.gpio import pinos


class PWMFalso:
    def __init__(self, pino, frequencia):
        self.pino = pino
        self.frequencia = frequencia
        self.chamadas = []

    def start(self, duty):
        self.chamadas.append(("start", duty))

    def ChangeDutyCycle(self, duty):
        self.chamadas.append(("duty", duty))

    def stop(self):
        self.chamadas.append(("stop", None))


class GPIOFalso(types.ModuleType):
    BCM, BOARD = "BCM", "BOARD"
    IN, OUT = "IN", "OUT"
    HIGH, LOW = 1, 0
    PUD_OFF, PUD_UP, PUD_DOWN = "off", "up", "down"
    RISING, FALLING, BOTH = "rising", "falling", "both"

    def __init__(self):
        super().__init__("RPi.GPIO")
        self.modo = None
        self.setups = []
        self.saidas = {}
        self.entradas = {}
        self.eventos = {}
        self.pwms = []
        self.limpou = False

    def setmode(self, modo):
        self.modo = modo

    def setwarnings(self, _):
        pass

    def setup(self, pino, direcao, pull_up_down=None, initial=None):
        self.setups.append((pino, direcao, pull_up_down, initial))
        if direcao == self.OUT:
            self.saidas[pino] = initial

    def output(self, pino, valor):
        self.saidas[pino] = valor

    def input(self, pino):
        return self.entradas.get(pino, 0)

    def PWM(self, pino, frequencia):
        # A biblioteca de verdade recusa PWM em pino que nao foi configurado
        # como saida. O falso precisa recusar tambem, senao o teste nao vale.
        if pino not in self.saidas:
            raise RuntimeError(
                "You must setup() the GPIO channel as an output first")
        pwm = PWMFalso(pino, frequencia)
        self.pwms.append(pwm)
        return pwm

    def add_event_detect(self, pino, borda, callback=None):
        self.eventos[pino] = (borda, callback)

    def remove_event_detect(self, pino):
        self.eventos.pop(pino, None)

    def cleanup(self, canais=None):
        self.limpou = True
        self.limpos = list(canais) if canais is not None else "todos"


@pytest.fixture
def gpio_falso(monkeypatch):
    falso = GPIOFalso()
    pacote = types.ModuleType("RPi")
    pacote.GPIO = falso
    monkeypatch.setitem(sys.modules, "RPi", pacote)
    monkeypatch.setitem(sys.modules, "RPi.GPIO", falso)
    return falso


@pytest.fixture
def backend_rpi(gpio_falso):
    from src.gpio.rpi_backend import BackendRPi
    return BackendRPi()


def test_usa_numeracao_bcm_e_nao_board(backend_rpi, gpio_falso):
    """Todo o projeto fala em BCM; BOARD trocaria a pinagem inteira."""
    assert gpio_falso.modo == gpio_falso.BCM


def test_traduz_os_resistores_internos(backend_rpi, gpio_falso):
    backend_rpi.configura_entrada(pinos.CORTINA, bk.PULL_DOWN)
    assert gpio_falso.setups[-1][:3] == (pinos.CORTINA, "IN", "down")


def test_traduz_as_bordas(backend_rpi, gpio_falso):
    backend_rpi.registra_interrupcao(pinos.ENC_A, bk.AMBAS, lambda p, v: None)
    assert gpio_falso.eventos[pinos.ENC_A][0] == gpio_falso.BOTH


def test_pwm_exige_setup_de_saida_antes(backend_rpi, gpio_falso):
    """cria_pwm() precisa configurar o pino como saida por conta propria."""
    backend_rpi.cria_pwm(pinos.PWM, 1000)
    assert pinos.PWM in gpio_falso.saidas


def test_pwm_criado_a_1_khz_com_um_unico_start(backend_rpi, gpio_falso):
    canal = backend_rpi.cria_pwm(pinos.PWM, 1000)
    canal.ajusta(20.0)
    canal.ajusta(35.0)
    canal.ajusta(0.0)
    pwm = gpio_falso.pwms[0]
    assert pwm.frequencia == 1000
    assert [c[0] for c in pwm.chamadas] == ["start", "duty", "duty"], \
        "start() so pode ser chamado uma vez; depois e ChangeDutyCycle"


def test_callback_recebe_pino_e_valor(backend_rpi, gpio_falso):
    """A RPi.GPIO entrega so o pino; o projeto precisa do nivel junto."""
    recebidos = []
    backend_rpi.registra_interrupcao(pinos.ENC_A, bk.AMBAS,
                                     lambda p, v: recebidos.append((p, v)))
    gpio_falso.entradas[pinos.ENC_A] = 1
    _, adaptador = gpio_falso.eventos[pinos.ENC_A]
    adaptador(pinos.ENC_A)                 # como a biblioteca chamaria
    assert recebidos == [(pinos.ENC_A, 1)]


def test_limpa_libera_a_gpio(backend_rpi, gpio_falso):
    """Obrigatorio: as placas do laboratorio sao compartilhadas."""
    canal = backend_rpi.cria_pwm(pinos.PWM, 1000)
    canal.ajusta(10.0)
    backend_rpi.limpa()
    assert gpio_falso.limpou is True
    assert gpio_falso.limpos == "todos"
    assert ("stop", None) in gpio_falso.pwms[0].chamadas


def test_limpa_preserva_os_pinos_pedidos(backend_rpi, gpio_falso):
    """Pino liberado vira entrada e flutua; o freio tem que continuar de pe."""
    backend_rpi.configura_saida(pinos.DIR1, 1)
    backend_rpi.configura_saida(pinos.DIR2, 1)
    backend_rpi.configura_entrada(pinos.CORTINA)
    backend_rpi.limpa(preserva=(pinos.DIR1, pinos.DIR2))
    assert pinos.CORTINA in gpio_falso.limpos
    assert pinos.DIR1 not in gpio_falso.limpos
    assert pinos.DIR2 not in gpio_falso.limpos


def test_cabine_inteira_sobre_o_backend_da_placa(gpio_falso):
    """Monta a Cabine real e confere a fiacao dos sete sinais da Tabela 1."""
    from src.controle.cabine import Cabine
    from src.gpio.rpi_backend import BackendRPi

    cabine = Cabine(BackendRPi())
    dir1, dir2 = pinos.DIR1, pinos.DIR2
    try:
        assert set(gpio_falso.eventos) == {pinos.ENC_A, pinos.ENC_B,
                                           pinos.CORTINA, pinos.SENSOR_ANDAR}
        configurados = {s[0] for s in gpio_falso.setups}
        assert {pinos.DIR1, pinos.DIR2, pinos.CORTINA,
                pinos.SENSOR_ANDAR, pinos.ENC_A, pinos.ENC_B} <= configurados
        assert gpio_falso.pwms[0].pino == pinos.PWM
        assert gpio_falso.pwms[0].frequencia == 1000
    finally:
        cabine.finaliza()
    assert gpio_falso.limpou is True
    # DIR1/DIR2 ficam fora da limpeza segurando o freio: liberados, flutuam e a
    # bancada le a combinacao solta como DESCER (medido na rasp42).
    assert dir1 not in gpio_falso.limpos and dir2 not in gpio_falso.limpos
    assert gpio_falso.saidas[dir1] == 1 and gpio_falso.saidas[dir2] == 1
    assert pinos.PWM in gpio_falso.limpos
