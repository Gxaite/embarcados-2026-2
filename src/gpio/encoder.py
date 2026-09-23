"""Encoder em quadratura lido por interrupcao nos DOIS canais.

O enunciado nao aceita polling neste item: a contagem tem de sair de
interrupcao em ambas as bordas de A e de B.

Como o sentido e resolvido: os canais A e B estao defasados de 90 graus, entao o
par (A, B) percorre um ciclo de Gray cuja ORDEM diz o sentido.

    subindo:   00 -> 01 -> 11 -> 10 -> 00
    descendo:  00 -> 10 -> 11 -> 01 -> 00

Olhar so uma borda de um canal perderia passos e nao distinguiria o sentido.
Tratando as quatro transicoes por ciclo temos a contagem em quadratura (4x) que
o enunciado especifica: 1000 contagens por metro, ou seja 1 contagem = 1 mm.
"""
import threading

from . import backend

# (estado_anterior, estado_novo) -> incremento, com estado = (A << 1) | B
TRANSICOES = {
    (0b00, 0b01): +1, (0b01, 0b11): +1, (0b11, 0b10): +1, (0b10, 0b00): +1,
    (0b00, 0b10): -1, (0b10, 0b11): -1, (0b11, 0b01): -1, (0b01, 0b00): -1,
}

LIMITE_INT32 = 1 << 31


def _como_int32(valor):
    """Reduz o valor a um inteiro de 32 bits com sinal, dando a volta.

    E o comportamento de um contador int32 de verdade: depois de 2**31 - 1 o
    proximo valor e -2**31. O enunciado exige contador de 32 bits com sinal.
    """
    return ((valor + LIMITE_INT32) % (1 << 32)) - LIMITE_INT32


class EncoderQuadratura:
    def __init__(self, backend_gpio, pino_a, pino_b, contagem_inicial=0):
        self._gpio = backend_gpio
        self._pino_a = pino_a
        self._pino_b = pino_b
        self._lock = threading.Lock()
        self._contagem = int(contagem_inicial)
        self._transicoes_invalidas = 0

        self._gpio.configura_entrada(pino_a, backend.PULL_NENHUM)
        self._gpio.configura_entrada(pino_b, backend.PULL_NENHUM)
        self._estado = self._le_estado()

        # Interrupcao nas DUAS bordas dos DOIS canais.
        self._gpio.registra_interrupcao(pino_a, backend.AMBAS, self._na_borda)
        self._gpio.registra_interrupcao(pino_b, backend.AMBAS, self._na_borda)

    def _le_estado(self):
        return (self._gpio.le(self._pino_a) << 1) | self._gpio.le(self._pino_b)

    @property
    def contagem(self):
        """Posicao acumulada em contagens de quadratura (1 contagem = 1 mm)."""
        with self._lock:
            return self._contagem

    @property
    def transicoes_invalidas(self):
        """Saltos de estado impossiveis - indicam bordas perdidas."""
        with self._lock:
            return self._transicoes_invalidas

    def zera(self, valor=0):
        with self._lock:
            self._contagem = _como_int32(int(valor))

    def _na_borda(self, pino, valor):
        """Rotina de interrupcao. Curta de proposito: so atualiza o contador."""
        novo = self._le_estado()
        with self._lock:
            if novo == self._estado:
                return
            passo = TRANSICOES.get((self._estado, novo))
            if passo is None:
                # Salto de dois estados: alguma borda foi perdida. Nao da para
                # saber o sentido, entao registramos o problema em vez de
                # chutar uma contagem errada.
                self._transicoes_invalidas += 1
            else:
                self._contagem = _como_int32(self._contagem + passo)
            self._estado = novo
