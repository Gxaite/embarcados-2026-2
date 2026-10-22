"""Registro do Barramento de Potencia em CSV, um ponto por rodada de Cotas.

Serve aos graficos do README: capacidade do barramento, Cota concedida e
corrente medida (registrador corrente_ma) de cada cabine, e a soma das Cotas
em uso. Ligado por `python3 -m src.central --registra-potencia CSV`.
"""
import csv
import os
import threading
import time


class RegistroDePotencia:
    def __init__(self, arquivo, cabines=(1, 2, 3)):
        os.makedirs(os.path.dirname(os.path.abspath(arquivo)), exist_ok=True)
        self._cabines = tuple(cabines)
        self._saida = open(arquivo, "w", newline="")
        self._escritor = csv.writer(self._saida)
        self._escritor.writerow(
            ["t_s", "capacidade_ma", "cotas_em_uso_ma"]
            + ["cota%d_ma" % n for n in self._cabines]
            + ["corrente%d_ma" % n for n in self._cabines]
            + ["posicao%d_mm" % n for n in self._cabines])
        self._inicio = time.monotonic()
        self._trava = threading.Lock()

    def __call__(self, servidor):
        linha = ["%.2f" % (time.monotonic() - self._inicio),
                 servidor.capacidade_ma() or "", servidor.cotas.soma_em_uso()]
        linha += [servidor.cotas.ultimas.get(n, 0) for n in self._cabines]
        for campo in ("corrente_ma", "posicao_mm"):
            for numero in self._cabines:
                cabine = servidor.cabines[numero]
                if campo == "corrente_ma":
                    valor = (cabine.registradores or {}).get(campo, "")
                else:
                    valor = (cabine.estado or {}).get(campo, "")
                linha.append(valor)
        with self._trava:
            if self._saida is not None:
                self._escritor.writerow(linha)
                self._saida.flush()

    def fecha(self):
        with self._trava:
            if self._saida is not None:
                self._saida.close()
                self._saida = None
