"""Backend real, sobre a biblioteca RPi.GPIO.

A importacao da RPi.GPIO e tardia, dentro do __init__, de proposito: assim o
resto do projeto pode ser importado e testado em qualquer maquina, e so quem
realmente vai falar com a placa paga o preco de exigir a biblioteca.
"""
from . import backend
from .backend import Backend, CanalPWM


class _CanalPWMRPi(CanalPWM):
    def __init__(self, pwm):
        self._pwm = pwm
        self._iniciado = False

    def ajusta(self, duty_porcento):
        duty = max(0.0, min(100.0, float(duty_porcento)))
        if not self._iniciado:
            # start() so pode ser chamado uma vez; daí em diante e
            # ChangeDutyCycle. Chamar start() de novo empilha threads.
            self._pwm.start(duty)
            self._iniciado = True
        else:
            self._pwm.ChangeDutyCycle(duty)

    def finaliza(self):
        if self._iniciado:
            self._pwm.stop()
            self._iniciado = False


class BackendRPi(Backend):
    def __init__(self):
        import RPi.GPIO as GPIO
        self._GPIO = GPIO
        GPIO.setmode(GPIO.BCM)       # BCM, nunca BOARD
        GPIO.setwarnings(False)
        self._pwms = []
        self._pinos_configurados = set()

        self._pull = {
            backend.SEM_PULL: GPIO.PUD_OFF,
            backend.PULL_UP: GPIO.PUD_UP,
            backend.PULL_DOWN: GPIO.PUD_DOWN,
        }
        self._borda = {
            backend.BORDA_SUBIDA: GPIO.RISING,
            backend.BORDA_DESCIDA: GPIO.FALLING,
            backend.AMBAS: GPIO.BOTH,
        }

    def configura_saida(self, pino, valor_inicial=0):
        self._pinos_configurados.add(pino)
        self._GPIO.setup(pino, self._GPIO.OUT,
                         initial=self._GPIO.HIGH if valor_inicial else self._GPIO.LOW)

    def configura_entrada(self, pino, pull=backend.SEM_PULL):
        self._pinos_configurados.add(pino)
        self._GPIO.setup(pino, self._GPIO.IN, pull_up_down=self._pull[pull])

    def escreve(self, pino, valor):
        self._GPIO.output(pino, self._GPIO.HIGH if valor else self._GPIO.LOW)

    def le(self, pino):
        return 1 if self._GPIO.input(pino) else 0

    def cria_pwm(self, pino, frequencia_hz):
        # A RPi.GPIO exige setup(OUT) ANTES de GPIO.PWM(); sem isso ela levanta
        # "You must setup() the GPIO channel as an output first".
        self.configura_saida(pino, 0)
        canal = _CanalPWMRPi(self._GPIO.PWM(pino, frequencia_hz))
        self._pwms.append(canal)
        return canal

    def registra_interrupcao(self, pino, borda, callback):
        # A RPi.GPIO entrega so o numero do pino ao tratador; quem trata precisa
        # do nivel, entao ele e lido aqui, o mais perto possivel da borda.
        def adapta(numero_do_pino):
            callback(numero_do_pino, self.le(numero_do_pino))

        self._GPIO.add_event_detect(pino, self._borda[borda], callback=adapta)

    def remove_interrupcao(self, pino):
        self._GPIO.remove_event_detect(pino)

    def limpa(self, preserva=()):
        for canal in self._pwms:
            canal.finaliza()
        self._pwms = []
        if not preserva:
            self._GPIO.cleanup()
            return
        # cleanup() aceita lista de canais: limpamos todos menos os
        # preservados, que continuam como saida segurando o nivel atual.
        preserva = set(preserva)
        alvos = [p for p in self._pinos_configurados if p not in preserva]
        if alvos:
            self._GPIO.cleanup(alvos)
