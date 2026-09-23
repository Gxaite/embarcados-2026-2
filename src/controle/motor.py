"""Motor de tracao: direcao (DIR1/DIR2) e potencia (PWM), com rampa.

A rampa e feita por limitacao da taxa de variacao do duty: a cada ciclo da
malha o duty so pode andar TAXA_RAMPA * dt em direcao ao alvo. Partida e
frenagem ficam suaves sem nenhuma espera bloqueante, e a mesma limitacao serve
para a rampa de aceleracao e para a de desaceleracao.
"""
from ..gpio import pinos
from ..gpio.saidas import SaidaDigital, SaidaPWM

# Tabela 2 do enunciado: (DIR1, DIR2)
LIVRE = "livre"
SUBIR = "subir"
DESCER = "descer"
FREIO = "freio"

DIRECOES = {
    LIVRE:  (0, 0),
    SUBIR:  (1, 0),
    DESCER: (0, 1),
    FREIO:  (1, 1),
}

# O motor parado nao vence o atrito estatico abaixo disso.
DUTY_MINIMO = 10.0
TAXA_RAMPA = 150.0  # pontos percentuais de duty por segundo


class Motor:
    def __init__(self, backend_gpio):
        self._dir1 = SaidaDigital(backend_gpio, pinos.DIR1, "DIR1")
        self._dir2 = SaidaDigital(backend_gpio, pinos.DIR2, "DIR2")
        self._pwm = SaidaPWM(backend_gpio, pinos.PWM)
        self._direcao = LIVRE
        self.livre()

    # --- direcao -------------------------------------------------------
    @property
    def direcao(self):
        return self._direcao

    def define_direcao(self, direcao):
        if direcao not in DIRECOES:
            raise ValueError("direcao invalida: %r" % (direcao,))
        d1, d2 = DIRECOES[direcao]
        self._dir1.escreve(d1)
        self._dir2.escreve(d2)
        self._direcao = direcao

    def livre(self):
        self.define_direcao(LIVRE)

    def subir(self):
        self.define_direcao(SUBIR)

    def descer(self):
        self.define_direcao(DESCER)

    def freio(self):
        self.define_direcao(FREIO)

    # --- potencia ------------------------------------------------------
    @property
    def duty(self):
        return self._pwm.duty

    def aplica_duty(self, duty):
        """Aplica o duty imediatamente, sem rampa (acionamento manual)."""
        return self._pwm.ajusta(duty)

    def rampa_para(self, duty_alvo, dt):
        """Anda um passo de rampa em direcao a duty_alvo. Devolve o duty novo.

        Se o alvo for diferente de zero mas abaixo do minimo de arranque, sobe
        para DUTY_MINIMO: pedir 4% ao motor so faz ele zumbir parado.
        """
        duty_alvo = max(0.0, min(100.0, float(duty_alvo)))
        if 0.0 < duty_alvo < DUTY_MINIMO:
            duty_alvo = DUTY_MINIMO
        passo = TAXA_RAMPA * dt
        atual = self._pwm.duty
        if duty_alvo > atual:
            novo = min(duty_alvo, atual + passo)
        else:
            novo = max(duty_alvo, atual - passo)
        return self._pwm.ajusta(novo)

    # --- encerramento --------------------------------------------------
    def para_com_freio(self):
        """Zera o PWM e trava a cabine. Usado na chegada e no SIGINT."""
        self._pwm.ajusta(0.0)
        self.freio()

    def finaliza(self):
        self.para_com_freio()
        self._pwm.finaliza()
