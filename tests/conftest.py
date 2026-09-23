"""Apoio aos testes: um backend de GPIO controlado a mao.

Permite acionar pino por pino, sem tempo real nem thread, para testar o
decodificador de quadratura e o debounce de forma deterministica.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.gpio import backend  # noqa: E402
from src.gpio.backend import BackendGPIO, CanalPWM  # noqa: E402


class CanalPWMFalso(CanalPWM):
    def __init__(self):
        self.duty = 0.0
        self.ligado = False

    def inicia(self, duty):
        self.ligado = True
        self.duty = duty

    def ajusta(self, duty):
        self.duty = duty

    def para(self):
        self.ligado = False
        self.duty = 0.0


class BackendManual(BackendGPIO):
    """Backend sem tempo real: o teste decide quando cada pino muda."""

    def __init__(self):
        self.valores = {}
        self.callbacks = {}
        self.pwm = {}
        self.finalizado = False

    def configura_saida(self, pino, valor_inicial=0):
        self.valores[pino] = valor_inicial

    def configura_entrada(self, pino, pull=backend.PULL_NENHUM):
        self.valores.setdefault(pino, 0)

    def escreve(self, pino, valor):
        self.valores[pino] = 1 if valor else 0

    def le(self, pino):
        return self.valores.get(pino, 0)

    def registra_interrupcao(self, pino, borda, callback):
        self.callbacks.setdefault(pino, []).append((borda, callback))

    def cria_pwm(self, pino, frequencia_hz):
        self.pwm[pino] = CanalPWMFalso()
        return self.pwm[pino]

    def finaliza(self):
        self.finalizado = True

    # --- estimulo de teste ---
    def muda(self, pino, valor):
        """Muda um pino e dispara as interrupcoes registradas para ele."""
        valor = 1 if valor else 0
        if self.valores.get(pino, 0) == valor:
            return
        self.valores[pino] = valor
        borda = backend.SUBIDA if valor else backend.DESCIDA
        for borda_pedida, callback in self.callbacks.get(pino, []):
            if borda_pedida in (borda, backend.AMBAS):
                callback(pino, valor)


@pytest.fixture
def gpio():
    return BackendManual()
