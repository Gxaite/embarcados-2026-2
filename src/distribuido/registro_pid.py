"""Registro da malha em CSV, para os graficos de sintonia do README.

Uma linha por ciclo de controle em malha fechada. O arquivo e escrito com
buffer e descarregado a cada segundo, nao a cada linha: um flush por ciclo de
50 ms poria o disco do cartao SD no caminho da malha.
"""
import csv
import os
import threading
import time

COLUNAS = ("t_s", "alvo_mm", "posicao_mm", "erro_mm", "p", "i", "d",
           "duty", "duty_maximo", "fase")


class RegistroPID:
    def __init__(self, arquivo):
        os.makedirs(os.path.dirname(os.path.abspath(arquivo)), exist_ok=True)
        self.arquivo = arquivo
        self._saida = open(arquivo, "w", newline="")
        self._escritor = csv.writer(self._saida)
        self._escritor.writerow(COLUNAS)
        self._trava = threading.Lock()
        self._inicio = None
        self._ultimo_flush = time.monotonic()

    def __call__(self, instante, alvo, posicao, erro, p, i, d, duty, duty_maximo, fase):
        with self._trava:
            if self._saida is None:
                return
            if self._inicio is None:
                self._inicio = instante
            self._escritor.writerow((
                "%.3f" % (instante - self._inicio), "%.1f" % alvo, "%.1f" % posicao,
                "%.1f" % erro, "%.2f" % p, "%.2f" % i, "%.2f" % d, "%.1f" % duty,
                "%.1f" % duty_maximo, fase))
            if time.monotonic() - self._ultimo_flush >= 1.0:
                self._saida.flush()
                self._ultimo_flush = time.monotonic()

    def fecha(self):
        with self._trava:
            if self._saida is not None:
                self._saida.close()
                self._saida = None
