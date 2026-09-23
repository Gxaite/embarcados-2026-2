"""Cortina de luz da porta: entrada on/off com debounce e log imediato.

O simulador emite repique de proposito em cada borda; sem debounce o programa
contaria obstrucoes fantasmas. O filtro fica na EntradaDigital - aqui so
traduzimos nivel logico em evento de porta e imprimimos na hora, como o
enunciado exige.
"""
import time

from ..gpio import pinos
from ..gpio.backend import PULL_BAIXO
from ..gpio.entradas import EntradaDigital

DEBOUNCE_MS = 25.0


class CortinaDeLuz:
    def __init__(self, backend_gpio, ao_evento=None, captura=None):
        self._ao_evento = ao_evento
        self.obstrucoes = 0
        self._entrada = EntradaDigital(
            backend_gpio, pinos.CORTINA, nome="CORTINA",
            debounce_ms=DEBOUNCE_MS, pull=PULL_BAIXO,
            ao_mudar=self._na_mudanca, captura=captura)

    @property
    def obstruida(self):
        return self._entrada.ativa()

    def _na_mudanca(self, evento):
        if evento.subida:
            self.obstrucoes += 1
            texto = "CORTINA: obstrucao detectada (porta bloqueada)"
        else:
            texto = "CORTINA: obstrucao liberada (porta livre)"
        if evento.captura is not None:
            texto += "  [encoder = %d]" % evento.captura
        print("[%s] %s" % (time.strftime("%H:%M:%S"), texto), flush=True)
        if self._ao_evento:
            self._ao_evento(evento)

    def finaliza(self):
        self._entrada.finaliza()
