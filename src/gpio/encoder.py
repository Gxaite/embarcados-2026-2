"""Encoder em quadratura, lido por interrupcao nos dois canais (requisito 6).

Os canais A e B estao defasados de 90 graus, entao o par (A, B) percorre um
ciclo de Gray cuja ORDEM diz o sentido:

    subindo:  00 -> 01 -> 11 -> 10 -> 00
    descendo: o mesmo ciclo ao contrario

Tratando as quatro transicoes obtemos contagem em quadratura 4x. Com os 1000
pulsos por metro do enunciado, isso da 1 contagem = 1 mm, e 3000 contagens por
andar.

Um salto de dois estados (00 -> 11, por exemplo) e impossivel na quadratura: so
acontece quando uma borda se perde. Nesse caso NAO se chuta a contagem - o
evento vai para transicoes_invalidas, que e o indicador mais honesto de que o
Python nao esta acompanhando o encoder.
"""
import threading

from . import backend as bk
from . import pinos

_LIMITE_32 = 2 ** 31

# (estado_anterior, estado_novo) -> incremento. Estado = (A << 1) | B.
_TRANSICOES = {
    (0b00, 0b01): +1, (0b01, 0b11): +1, (0b11, 0b10): +1, (0b10, 0b00): +1,
    (0b00, 0b10): -1, (0b10, 0b11): -1, (0b11, 0b01): -1, (0b01, 0b00): -1,
}


class EncoderQuadratura:
    def __init__(self, backend, pino_a=pinos.ENC_A, pino_b=pinos.ENC_B):
        self._backend = backend
        self.pino_a = pino_a
        self.pino_b = pino_b

        self._trava = threading.Lock()
        self._contagem = 0
        self.transicoes_invalidas = 0

        backend.configura_entrada(pino_a)
        backend.configura_entrada(pino_b)
        self._estado = (backend.le(pino_a) << 1) | backend.le(pino_b)

        # Interrupcao em AMBAS as bordas dos DOIS canais: e o que da a
        # quadratura 4x e o que o enunciado exige explicitamente.
        backend.registra_interrupcao(pino_a, bk.AMBAS, self._na_borda)
        backend.registra_interrupcao(pino_b, bk.AMBAS, self._na_borda)

    @property
    def contagem(self):
        with self._trava:
            return self._contagem

    def zera(self, valor=0):
        with self._trava:
            self._contagem = int(valor)

    def _na_borda(self, pino, valor):
        with self._trava:
            a = valor if pino == self.pino_a else self._backend.le(self.pino_a)
            b = valor if pino == self.pino_b else self._backend.le(self.pino_b)
            novo = (a << 1) | b
            if novo == self._estado:
                return          # borda que nao mudou o par: nada a contar
            passo = _TRANSICOES.get((self._estado, novo))
            self._estado = novo
            if passo is None:
                self.transicoes_invalidas += 1
                return
            self._contagem = self._satura(self._contagem + passo)

    @staticmethod
    def _satura(valor):
        """Contador de 32 bits com sinal, conforme o enunciado."""
        if valor >= _LIMITE_32:
            return _LIMITE_32 - 1
        if valor < -_LIMITE_32:
            return -_LIMITE_32
        return valor

    def finaliza(self):
        self._backend.remove_interrupcao(self.pino_a)
        self._backend.remove_interrupcao(self.pino_b)
