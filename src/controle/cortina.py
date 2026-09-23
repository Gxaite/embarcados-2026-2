"""Cortina de luz da porta.

Entrada on/off por interrupcao, com debounce. O simulador emite repique de
proposito em cada borda: sem debounce, uma unica obstrucao vira varias. O
requisito 5 pede impressao IMEDIATA de cada evento, entao o log sai do proprio
tratador, assim que o nivel assenta.
"""
import time

from ..gpio import pinos
from ..gpio.entradas import EntradaInterrupcao

DEBOUNCE_MS = 20.0


class Cortina:
    def __init__(self, backend, ao_evento=None):
        self._ao_evento = ao_evento
        self.obstrucoes = 0
        self.liberacoes = 0
        self._entrada = EntradaInterrupcao(
            backend, pinos.CORTINA, self._trata, debounce_ms=DEBOUNCE_MS)

    @property
    def obstruida(self):
        return self._entrada.nivel == 1

    @property
    def bordas_cruas(self):
        """Bordas antes do debounce. Se for muito maior que obstrucoes +
        liberacoes, o repique esta sendo filtrado como deveria."""
        return self._entrada.bordas_cruas

    def _trata(self, nivel, _instantanea):
        if nivel == 1:
            self.obstrucoes += 1
            texto = "CORTINA: porta OBSTRUIDA"
        else:
            self.liberacoes += 1
            texto = "CORTINA: porta LIBERADA"
        print("[%.3f] %s" % (time.monotonic(), texto), flush=True)
        if self._ao_evento is not None:
            self._ao_evento(nivel)

    def finaliza(self):
        self._entrada.finaliza()
