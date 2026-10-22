"""Sensor de Andar lido por interrupcao, nas duas bordas.

A contagem do encoder e o sentido do movimento sao capturados na borda CRUA,
antes do debounce: lidos depois, a cabine ja teria andado durante a janela e a
borda sairia deslocada no sentido do movimento.

Cada borda e classificada pela posicao no poco, nao pelo nivel do sinal:
entrar na bandeirola subindo e cruzar a borda INFERIOR, e sair descendo
tambem. E essa classificacao que permite reancorar em cada borda isolada, sem
precisar de uma travessia completa - a cabine para no meio da bandeirola em
todo andar que atende.
"""
from ..gpio.entradas import EntradaInterrupcao

DEBOUNCE_MS = 2.0

INFERIOR = "inferior"
SUPERIOR = "superior"


class Borda:
    __slots__ = ("entrou", "contagem", "sentido")

    def __init__(self, entrou, contagem, sentido):
        self.entrou = entrou
        self.contagem = contagem
        self.sentido = sentido

    @property
    def lado(self):
        """Qual borda da bandeirola foi cruzada, ou None sem sentido conhecido."""
        if self.sentido == 0:
            return None
        subindo = self.sentido > 0
        return INFERIOR if subindo == self.entrou else SUPERIOR

    def __repr__(self):
        return "Borda(%s, %s, %d)" % ("entrou" if self.entrou else "saiu",
                                     self.lado, self.contagem)


class SensorDeAndar:
    def __init__(self, backend, pino, encoder, ao_cruzar):
        self._encoder = encoder
        self._ao_cruzar = ao_cruzar
        self.bordas = 0
        self._entrada = EntradaInterrupcao(
            backend, pino, self._trata, debounce_ms=DEBOUNCE_MS,
            instantanea=encoder.leitura)

    @property
    def dentro(self):
        return self._entrada.nivel == 1

    def _trata(self, nivel, instantanea):
        contagem, sentido = instantanea if instantanea is not None \
            else self._encoder.leitura()
        self.bordas += 1
        self._ao_cruzar(Borda(nivel == 1, contagem, sentido))

    def finaliza(self):
        self._entrada.finaliza()
