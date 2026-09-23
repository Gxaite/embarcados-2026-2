"""Saidas digitais: on/off e PWM."""
from . import backend

FREQUENCIA_PWM_HZ = 1000  # 1 kHz, exigido pelo enunciado


class SaidaDigital:
    """Um pino de saida liga/desliga (usado em DIR1 e DIR2)."""

    def __init__(self, backend_gpio, pino, nome=""):
        self._gpio = backend_gpio
        self._pino = pino
        self.nome = nome or "GPIO%d" % pino
        self._valor = 0
        self._gpio.configura_saida(pino, 0)

    @property
    def valor(self):
        return self._valor

    def escreve(self, valor):
        self._valor = 1 if valor else 0
        self._gpio.escreve(self._pino, self._valor)

    def liga(self):
        self.escreve(1)

    def desliga(self):
        self.escreve(0)


class SaidaPWM:
    """Saida PWM por software a 1 kHz, com duty de 0 a 100%.

    A rampa de aceleracao NAO e feita aqui: esta classe e so o driver do pino.
    Quem limita a taxa de variacao do duty e o controle/motor.py.
    """

    def __init__(self, backend_gpio, pino, frequencia_hz=FREQUENCIA_PWM_HZ):
        self._canal = backend_gpio.cria_pwm(pino, frequencia_hz)
        self.frequencia_hz = frequencia_hz
        self._duty = 0.0
        self._canal.inicia(0.0)

    @property
    def duty(self):
        return self._duty

    def ajusta(self, duty):
        """Aplica o duty cycle, saturado na faixa valida de 0 a 100%."""
        self._duty = max(0.0, min(100.0, float(duty)))
        self._canal.ajusta(self._duty)
        return self._duty

    def desliga(self):
        self.ajusta(0.0)

    def finaliza(self):
        self._canal.para()
        self._duty = 0.0
