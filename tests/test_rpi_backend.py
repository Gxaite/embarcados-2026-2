"""Backend real (RPi.GPIO) exercitado contra uma biblioteca falsa.

Este e o unico arquivo do projeto que nao roda nem nos testes nem no modo
--simulado: ele so executa na Raspberry Pi. Um erro de API aqui - nome de
funcao trocado, argumento fora de ordem, assinatura de callback errada - nao
aparece em lugar nenhum ate a bancada.

A solucao e registrar um modulo falso chamado "RPi.GPIO" em sys.modules antes
de importar o backend. Como rpi_backend.py importa a biblioteca tardiamente
(dentro do __init__, de proposito), o import cai no falso e todas as chamadas
ficam gravadas.

Isto NAO prova que o programa funciona na placa: prova que as chamadas feitas a
biblioteca sao as corretas, o que e o que da para verificar longe da bancada.
"""
import sys
import types

import pytest

from src.gpio import backend, pinos
from src.gpio.saidas import FREQUENCIA_PWM_HZ


class PWMFalso:
    """Imita GPIO.PWM: registra start/ChangeDutyCycle/stop."""

    def __init__(self, pino, frequencia):
        self.pino = pino
        self.frequencia = frequencia
        self.duty = None
        self.iniciado = 0
        self.parado = 0
        self.mudancas = []

    def start(self, duty):
        self.iniciado += 1
        self.duty = duty

    def ChangeDutyCycle(self, duty):  # noqa: N802 - nome da RPi.GPIO
        self.duty = duty
        self.mudancas.append(duty)

    def stop(self):
        self.parado += 1


def _modulo_falso():
    """Monta um modulo com a mesma superficie de API da RPi.GPIO."""
    mod = types.ModuleType("RPi.GPIO")

    # Constantes: valores arbitrarios, so precisam ser distinguiveis entre si.
    mod.BCM, mod.BOARD = "BCM", "BOARD"
    mod.OUT, mod.IN = "OUT", "IN"
    mod.RISING, mod.FALLING, mod.BOTH = "RISING", "FALLING", "BOTH"
    mod.PUD_OFF, mod.PUD_UP, mod.PUD_DOWN = "PUD_OFF", "PUD_UP", "PUD_DOWN"
    mod.VERSION = "0.7.1-falso"

    mod.chamadas = []      # historico de (funcao, args, kwargs)
    mod.modo = None
    mod.niveis = {}        # pino -> nivel logico
    mod.configuracoes = {}  # pino -> (direcao, kwargs)
    mod.deteccoes = {}     # pino -> (borda, callback)
    mod.pwms = {}          # pino -> PWMFalso
    mod.limpou = 0

    def registra(nome, *args, **kwargs):
        mod.chamadas.append((nome, args, kwargs))

    def setmode(modo):
        registra("setmode", modo)
        mod.modo = modo

    def setwarnings(ligado):
        registra("setwarnings", ligado)

    def setup(pino, direcao, **kwargs):
        registra("setup", pino, direcao, **kwargs)
        mod.configuracoes[pino] = (direcao, kwargs)
        if direcao == mod.OUT:
            mod.niveis[pino] = kwargs.get("initial", 0)
        else:
            mod.niveis.setdefault(pino, 0)

    def output(pino, valor):
        registra("output", pino, valor)
        if mod.configuracoes.get(pino, (None,))[0] != mod.OUT:
            raise RuntimeError("escrita em pino que nao e saida: %s" % pino)
        mod.niveis[pino] = valor

    def input_(pino):
        registra("input", pino)
        return mod.niveis.get(pino, 0)

    def add_event_detect(pino, borda, callback=None, bouncetime=None):
        registra("add_event_detect", pino, borda,
                 callback=callback, bouncetime=bouncetime)
        if mod.configuracoes.get(pino, (None,))[0] != mod.IN:
            raise RuntimeError("interrupcao em pino que nao e entrada: %s" % pino)
        mod.deteccoes[pino] = (borda, callback)

    def pwm(pino, frequencia):
        registra("PWM", pino, frequencia)
        mod.pwms[pino] = PWMFalso(pino, frequencia)
        return mod.pwms[pino]

    def cleanup():
        registra("cleanup")
        mod.limpou += 1

    mod.setmode = setmode
    mod.setwarnings = setwarnings
    mod.setup = setup
    mod.output = output
    mod.input = input_
    mod.add_event_detect = add_event_detect
    mod.PWM = pwm
    mod.cleanup = cleanup

    # --- estimulo: muda um pino de entrada e dispara a interrupcao ---
    def dispara(pino, valor):
        """Imita uma borda no pino, como a RPi.GPIO faria numa thread."""
        anterior = mod.niveis.get(pino, 0)
        if anterior == valor:
            return
        mod.niveis[pino] = valor
        borda, callback = mod.deteccoes.get(pino, (None, None))
        if callback is None:
            return
        subida = valor == 1
        if borda == mod.BOTH or (borda == mod.RISING) == subida:
            # A RPi.GPIO chama o callback com UM argumento: o numero do pino.
            callback(pino)

    mod.dispara = dispara
    return mod


@pytest.fixture
def rpi(monkeypatch):
    """Instala o RPi.GPIO falso e devolve o modulo, para inspecao."""
    mod = _modulo_falso()
    pacote = types.ModuleType("RPi")
    pacote.GPIO = mod
    monkeypatch.setitem(sys.modules, "RPi", pacote)
    monkeypatch.setitem(sys.modules, "RPi.GPIO", mod)
    return mod


@pytest.fixture
def backend_rpi(rpi):
    from src.gpio.rpi_backend import BackendRPi
    return BackendRPi()


# ----------------------------------------------------------------------
# Configuracao inicial
# ----------------------------------------------------------------------
def test_usa_numeracao_bcm(backend_rpi, rpi):
    """O mapa de pinos e BCM; BOARD leria o header fisico e moveria tudo."""
    assert rpi.modo == rpi.BCM


def test_saida_configurada_com_nivel_inicial_baixo(backend_rpi, rpi):
    backend_rpi.configura_saida(pinos.DIR1, 0)
    direcao, kwargs = rpi.configuracoes[pinos.DIR1]
    assert direcao == rpi.OUT
    assert kwargs["initial"] == 0


def test_entrada_traduz_o_resistor_interno(backend_rpi, rpi):
    backend_rpi.configura_entrada(pinos.CORTINA, backend.PULL_BAIXO)
    direcao, kwargs = rpi.configuracoes[pinos.CORTINA]
    assert direcao == rpi.IN
    assert kwargs["pull_up_down"] == rpi.PUD_DOWN

    backend_rpi.configura_entrada(pinos.ENC_A, backend.PULL_NENHUM)
    assert rpi.configuracoes[pinos.ENC_A][1]["pull_up_down"] == rpi.PUD_OFF


def test_escreve_e_le(backend_rpi):
    backend_rpi.configura_saida(pinos.DIR2, 0)
    backend_rpi.escreve(pinos.DIR2, 1)
    assert backend_rpi.le(pinos.DIR2) == 1
    backend_rpi.escreve(pinos.DIR2, 0)
    assert backend_rpi.le(pinos.DIR2) == 0


def test_le_devolve_sempre_0_ou_1(backend_rpi, rpi):
    """A RPi.GPIO pode devolver True/False; o resto do codigo espera int."""
    backend_rpi.configura_entrada(pinos.SENSOR_ANDAR)
    rpi.niveis[pinos.SENSOR_ANDAR] = True
    valor = backend_rpi.le(pinos.SENSOR_ANDAR)
    assert valor == 1 and isinstance(valor, int)


# ----------------------------------------------------------------------
# Interrupcoes
# ----------------------------------------------------------------------
def test_bordas_traduzidas(backend_rpi, rpi):
    backend_rpi.configura_entrada(pinos.ENC_A)
    backend_rpi.registra_interrupcao(pinos.ENC_A, backend.AMBAS, lambda p, v: None)
    assert rpi.deteccoes[pinos.ENC_A][0] == rpi.BOTH


def test_callback_recebe_pino_e_valor(backend_rpi, rpi):
    """A RPi.GPIO chama callback(pino); o projeto espera callback(pino, valor).

    Quem faz a adaptacao e o lambda de registra_interrupcao. Se a assinatura
    estiver errada, o erro estoura numa thread de interrupcao na bancada - onde
    ele e dificil de ver.
    """
    recebidos = []
    backend_rpi.configura_entrada(pinos.CORTINA, backend.PULL_BAIXO)
    backend_rpi.registra_interrupcao(pinos.CORTINA, backend.AMBAS,
                                     lambda p, v: recebidos.append((p, v)))

    rpi.dispara(pinos.CORTINA, 1)
    rpi.dispara(pinos.CORTINA, 0)

    assert recebidos == [(pinos.CORTINA, 1), (pinos.CORTINA, 0)]


def test_interrupcao_so_depois_de_configurar_entrada(backend_rpi, rpi):
    """Registrar interrupcao num pino nao configurado e erro na RPi.GPIO real."""
    with pytest.raises(RuntimeError):
        backend_rpi.registra_interrupcao(pinos.ENC_B, backend.AMBAS,
                                         lambda p, v: None)


# ----------------------------------------------------------------------
# PWM
# ----------------------------------------------------------------------
def test_pwm_criado_a_1_khz(backend_rpi, rpi):
    """Requisito 4 do enunciado, verificado na chamada real a GPIO.PWM."""
    backend_rpi.cria_pwm(pinos.PWM, FREQUENCIA_PWM_HZ)
    assert rpi.pwms[pinos.PWM].frequencia == 1000


def test_pwm_configura_o_pino_como_saida_antes(backend_rpi, rpi):
    backend_rpi.cria_pwm(pinos.PWM, FREQUENCIA_PWM_HZ)
    nomes = [c[0] for c in rpi.chamadas]
    assert nomes.index("setup") < nomes.index("PWM")


def test_pwm_inicia_uma_vez_e_depois_so_muda_o_duty(backend_rpi, rpi):
    canal = backend_rpi.cria_pwm(pinos.PWM, FREQUENCIA_PWM_HZ)
    canal.inicia(0.0)
    canal.ajusta(30.0)
    canal.ajusta(60.0)
    falso = rpi.pwms[pinos.PWM]
    assert falso.iniciado == 1              # start() uma unica vez
    assert falso.mudancas == [30.0, 60.0]   # o resto via ChangeDutyCycle


def test_pwm_ajustado_antes_de_iniciar_faz_start(backend_rpi, rpi):
    """ChangeDutyCycle antes de start() nao tem efeito na RPi.GPIO real."""
    canal = backend_rpi.cria_pwm(pinos.PWM, FREQUENCIA_PWM_HZ)
    canal.ajusta(40.0)
    falso = rpi.pwms[pinos.PWM]
    assert falso.iniciado == 1
    assert falso.duty == 40.0


def test_pwm_satura_a_faixa_de_0_a_100(backend_rpi, rpi):
    canal = backend_rpi.cria_pwm(pinos.PWM, FREQUENCIA_PWM_HZ)
    canal.inicia(0.0)
    canal.ajusta(150.0)
    canal.ajusta(-20.0)
    assert rpi.pwms[pinos.PWM].mudancas == [100.0, 0.0]


def test_para_duas_vezes_nao_quebra(backend_rpi, rpi):
    """stop() repetido na RPi.GPIO real dispara excecao; o backend protege."""
    canal = backend_rpi.cria_pwm(pinos.PWM, FREQUENCIA_PWM_HZ)
    canal.inicia(10.0)
    canal.para()
    canal.para()
    assert rpi.pwms[pinos.PWM].parado == 1


# ----------------------------------------------------------------------
# Encerramento
# ----------------------------------------------------------------------
def test_finaliza_chama_cleanup(backend_rpi, rpi):
    backend_rpi.finaliza()
    assert rpi.limpou == 1


# ----------------------------------------------------------------------
# Integracao: a Cabine inteira sobre o backend real
# ----------------------------------------------------------------------
def test_cabine_completa_sobe_sobre_o_backend_real(rpi):
    """Monta a Cabine no backend da placa e confere a fiacao dos 7 sinais.

    E o teste que mais se aproxima do "ligar na bancada": todo o caminho
    Cabine -> Motor/Encoder/Cortina/SensorAndar -> BackendRPi -> RPi.GPIO e
    percorrido de verdade.
    """
    from src.controle.cabine import Cabine
    from src.gpio.rpi_backend import BackendRPi

    cabine = Cabine(BackendRPi())
    try:
        # Saidas declaradas como saida...
        for pino in (pinos.DIR1, pinos.DIR2, pinos.PWM):
            assert rpi.configuracoes[pino][0] == rpi.OUT, pino
        # ...e entradas como entrada, todas com interrupcao nas duas bordas.
        for pino in (pinos.ENC_A, pinos.ENC_B, pinos.CORTINA,
                     pinos.SENSOR_ANDAR):
            assert rpi.configuracoes[pino][0] == rpi.IN, pino
            assert rpi.deteccoes[pino][0] == rpi.BOTH, pino
        assert rpi.pwms[pinos.PWM].frequencia == 1000
    finally:
        cabine.finaliza()

    # Encerramento seguro: PWM parado, freio aplicado, GPIO liberada.
    assert rpi.pwms[pinos.PWM].parado == 1
    assert (rpi.niveis[pinos.DIR1], rpi.niveis[pinos.DIR2]) == (1, 1)
    assert rpi.limpou == 1


def test_movimento_comanda_os_pinos_certos(rpi):
    """Um comando de subida tem de acender DIR1 e mexer no duty, na placa."""
    from src.controle.cabine import Cabine
    from src.gpio.rpi_backend import BackendRPi

    cabine = Cabine(BackendRPi())
    try:
        cabine.vai_para_mm(3000.0)
        cabine.espera_chegada(timeout=1.0)   # nao chega: o encoder nao anda
        assert (rpi.niveis[pinos.DIR1], rpi.niveis[pinos.DIR2]) == (1, 0)
        assert rpi.pwms[pinos.PWM].duty > 0.0
    finally:
        cabine.finaliza()
