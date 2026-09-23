"""Backend real: Raspberry Pi via biblioteca RPi.GPIO.

Importa RPi.GPIO apenas na construcao, para que a maquina de desenvolvimento
(que nao tem a biblioteca) consiga importar o resto do projeto.
"""
from . import backend
from .backend import BackendGPIO, CanalPWM

_BORDAS = {}   # preenchido no primeiro uso, depende do modulo GPIO importado
_PULLS = {}


class _CanalPWMRPi(CanalPWM):
    def __init__(self, pwm):
        self._pwm = pwm
        self._ligado = False

    def inicia(self, duty):
        self._pwm.start(max(0.0, min(100.0, float(duty))))
        self._ligado = True

    def ajusta(self, duty):
        duty = max(0.0, min(100.0, float(duty)))
        if not self._ligado:
            self.inicia(duty)
        else:
            self._pwm.ChangeDutyCycle(duty)

    def para(self):
        if self._ligado:
            self._pwm.stop()
            self._ligado = False


class BackendRPi(BackendGPIO):
    def __init__(self):
        import RPi.GPIO as GPIO  # noqa: N814  (import tardio, de proposito)

        self._GPIO = GPIO
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)

        _BORDAS.update({backend.SUBIDA: GPIO.RISING,
                        backend.DESCIDA: GPIO.FALLING,
                        backend.AMBAS: GPIO.BOTH})
        _PULLS.update({backend.PULL_NENHUM: GPIO.PUD_OFF,
                       backend.PULL_CIMA: GPIO.PUD_UP,
                       backend.PULL_BAIXO: GPIO.PUD_DOWN})

    def configura_saida(self, pino, valor_inicial=0):
        self._GPIO.setup(pino, self._GPIO.OUT, initial=valor_inicial)

    def configura_entrada(self, pino, pull=backend.PULL_NENHUM):
        self._GPIO.setup(pino, self._GPIO.IN, pull_up_down=_PULLS[pull])

    def escreve(self, pino, valor):
        self._GPIO.output(pino, 1 if valor else 0)

    def le(self, pino):
        return 1 if self._GPIO.input(pino) else 0

    def registra_interrupcao(self, pino, borda, callback):
        # Sem bouncetime aqui: o debounce e feito no nivel de cima
        # (gpio/entradas.py), onde ele pode registrar a contagem do encoder no
        # instante da borda crua antes de filtrar o repique.
        self._GPIO.add_event_detect(pino, _BORDAS[borda],
                                    callback=lambda p: callback(p, self.le(p)))

    def cria_pwm(self, pino, frequencia_hz):
        self.configura_saida(pino, 0)
        return _CanalPWMRPi(self._GPIO.PWM(pino, frequencia_hz))

    def finaliza(self):
        self._GPIO.cleanup()
