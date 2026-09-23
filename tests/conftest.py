"""Backend de mentira, dirigido pelo teste.

Permite provocar bordas, repique e sequencias de quadratura na mao, sem placa e
sem esperar tempo real.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.gpio import backend as bk          # noqa: E402
from src.gpio.backend import Backend, CanalPWM  # noqa: E402


class CanalPWMFalso(CanalPWM):
    def __init__(self, pino, frequencia_hz):
        self.pino = pino
        self.frequencia_hz = frequencia_hz
        self.duty = 0.0
        self.finalizado = False
        self.historico = []

    def ajusta(self, duty_porcento):
        self.duty = duty_porcento
        self.historico.append(duty_porcento)

    def finaliza(self):
        self.finalizado = True


class BackendFalso(Backend):
    def __init__(self):
        self.niveis = {}
        self.modos = {}
        self.pulls = {}
        self.interrupcoes = {}
        self.pwms = []
        self.limpou = False

    def configura_saida(self, pino, valor_inicial=0):
        self.modos[pino] = "saida"
        self.niveis[pino] = 1 if valor_inicial else 0

    def configura_entrada(self, pino, pull=bk.SEM_PULL):
        self.modos[pino] = "entrada"
        self.pulls[pino] = pull
        self.niveis.setdefault(pino, 0)

    def escreve(self, pino, valor):
        self.niveis[pino] = 1 if valor else 0

    def le(self, pino):
        return self.niveis.get(pino, 0)

    def cria_pwm(self, pino, frequencia_hz):
        canal = CanalPWMFalso(pino, frequencia_hz)
        self.pwms.append(canal)
        return canal

    def registra_interrupcao(self, pino, borda, callback):
        self.interrupcoes[pino] = (borda, callback)

    def remove_interrupcao(self, pino):
        self.interrupcoes.pop(pino, None)

    def limpa(self):
        self.limpou = True

    # ------------------------------------------------- dirigido pelo teste
    def provoca(self, pino, valor):
        """Muda o nivel do pino e dispara a interrupcao registrada."""
        valor = 1 if valor else 0
        self.niveis[pino] = valor
        registro = self.interrupcoes.get(pino)
        if registro is None:
            return
        borda, callback = registro
        if borda == bk.AMBAS \
                or (borda == bk.BORDA_SUBIDA and valor == 1) \
                or (borda == bk.BORDA_DESCIDA and valor == 0):
            callback(pino, valor)


@pytest.fixture
def backend():
    return BackendFalso()
