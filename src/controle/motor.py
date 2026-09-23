"""Motor de tracao: tabela de direcao e rampa de duty.

A rampa e feita por LIMITACAO DA TAXA DE VARIACAO do duty, nao por espera
bloqueante. Isso atende a rampa de aceleracao do enunciado sem violar o
requisito 9 (sem busy-wait): a malha de controle chama passo() uma vez por
ciclo e o duty caminha sozinho ate o alvo.
"""
from ..gpio import pinos
from ..gpio.saidas import SaidaDigital, SaidaPWM

TAXA_RAMPA_POR_S = 120.0       # pontos percentuais de duty por segundo
DUTY_MINIMO_DE_MOVIMENTO = 10.0  # abaixo disso o motor parado nao arranca


class Motor:
    def __init__(self, backend):
        self._dir1 = SaidaDigital(backend, pinos.DIR1, 0)
        self._dir2 = SaidaDigital(backend, pinos.DIR2, 0)
        self._pwm = SaidaPWM(backend, pinos.PWM)
        self._direcao = pinos.LIVRE
        self._alvo_de_duty = 0.0

    @property
    def direcao(self):
        return self._direcao

    @property
    def duty(self):
        return self._pwm.duty

    @property
    def alvo_de_duty(self):
        return self._alvo_de_duty

    def define_direcao(self, direcao):
        if direcao not in pinos.DIRECOES:
            raise ValueError("direcao invalida: %r (validas: %s)"
                             % (direcao, ", ".join(sorted(pinos.DIRECOES))))
        v1, v2 = pinos.DIRECOES[direcao]
        self._dir1.escreve(v1)
        self._dir2.escreve(v2)
        self._direcao = direcao

    def define_alvo_de_duty(self, duty):
        """Alvo da rampa. O duty efetivo caminha ate ele em passo()."""
        duty = max(0.0, min(100.0, float(duty)))
        # Duty diferente de zero nunca fica abaixo do arranque: ali o motor so
        # zumbe, esquenta e nao anda.
        if 0.0 < duty < DUTY_MINIMO_DE_MOVIMENTO:
            duty = DUTY_MINIMO_DE_MOVIMENTO
        self._alvo_de_duty = duty

    def passo(self, dt):
        """Aproxima o duty do alvo respeitando a taxa de rampa."""
        limite = TAXA_RAMPA_POR_S * dt
        atual = self._pwm.duty
        delta = self._alvo_de_duty - atual
        if abs(delta) > limite:
            delta = limite if delta > 0 else -limite
        self._pwm.ajusta(atual + delta)
        return self._pwm.duty

    def aciona_direto(self, direcao, duty):
        """Acionamento manual do requisito 1: sem rampa, valor imediato."""
        self.define_direcao(direcao)
        self._alvo_de_duty = max(0.0, min(100.0, float(duty)))
        self._pwm.ajusta(self._alvo_de_duty)

    def para(self):
        self._alvo_de_duty = 0.0
        self._pwm.ajusta(0.0)
        self.define_direcao(pinos.FREIO)

    def finaliza(self):
        self._alvo_de_duty = 0.0
        self._pwm.ajusta(0.0)
        self.define_direcao(pinos.FREIO)
        self._pwm.finaliza()
