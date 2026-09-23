"""Sensor de Andar: mede a bandeirola pelas suas DUAS bordas.

A bandeirola e uma regiao do poco centrada na posicao do andar, dezenas de
milimetros mais larga que a tolerancia de +-10 mm - e a largura e diferente em
cada andar. Por isso:

  - parar assim que o sensor sobe NAO deixa a cabine nivelada;
  - uma borda so nao permite deduzir o centro, ja que a largura e desconhecida.

O centro estimado e a MEDIA das contagens do encoder nas duas bordas. Cada
contagem e capturada no instante da borda crua (ver gpio/entradas.py).

Nesta entrega o sensor nao comanda a parada - quem fecha a malha e o encoder.
Ele serve para medir a bandeirola e conferir o contador contra uma referencia
absoluta. Na Entrega Final este mesmo procedimento vira a calibracao dos
6 andares.
"""
import time

from . import posicao
from ..gpio import pinos
from ..gpio.backend import PULL_BAIXO
from ..gpio.entradas import EntradaDigital

DEBOUNCE_MS = 5.0  # curto: a bandeirola nao repica como a cortina

# Largura minima para aceitar uma travessia como valida.
#
# Se a cabine para DENTRO da bandeirola e depois inverte o sentido, ela sai
# pelo mesmo lado por onde entrou: a contagem da borda de saida fica colada na
# da entrada e a media cairia numa extremidade, nao no centro. Uma travessia
# completa sempre atravessa a bandeirola inteira, que por enunciado e "dezenas
# de milimetros" - bem mais larga que a tolerancia de +-10 mm. Entao uma
# largura pequena denuncia meia-travessia, e a medicao e descartada.
LARGURA_MINIMA_MM = 20.0


class MedicaoBandeirola:
    """Resultado de uma travessia completa de bandeirola."""

    __slots__ = ("contagem_entrada", "contagem_saida", "andar", "instante")

    def __init__(self, contagem_entrada, contagem_saida, andar, instante):
        self.contagem_entrada = contagem_entrada
        self.contagem_saida = contagem_saida
        self.andar = andar
        self.instante = instante

    @property
    def centro(self):
        """Centro estimado do andar: media das duas bordas."""
        return (self.contagem_entrada + self.contagem_saida) / 2.0

    @property
    def largura(self):
        return abs(self.contagem_saida - self.contagem_entrada)

    @property
    def erro(self):
        """Erro do centro medido em relacao a posicao nominal do andar."""
        return self.centro - posicao.posicao_do_andar(self.andar)


class SensorAndar:
    def __init__(self, backend_gpio, encoder, ao_medir=None):
        self._encoder = encoder
        self._ao_medir = ao_medir
        self._contagem_entrada = None
        self.medicoes = []
        self._entrada = EntradaDigital(
            backend_gpio, pinos.SENSOR_ANDAR, nome="SENSOR_ANDAR",
            debounce_ms=DEBOUNCE_MS, pull=PULL_BAIXO,
            ao_mudar=self._na_borda, captura=lambda: encoder.contagem)

    @property
    def dentro_da_bandeirola(self):
        return self._entrada.ativa()

    def _na_borda(self, evento):
        agora = time.strftime("%H:%M:%S")
        contagem = evento.captura

        if evento.subida:
            self._contagem_entrada = contagem
            print("[%s] BANDEIROLA: borda de ENTRADA  encoder = %d (%.0f mm)"
                  % (agora, contagem, posicao.contagem_para_mm(contagem)),
                  flush=True)
            return

        print("[%s] BANDEIROLA: borda de SAIDA    encoder = %d (%.0f mm)"
              % (agora, contagem, posicao.contagem_para_mm(contagem)),
              flush=True)

        if self._contagem_entrada is None:
            print("           (sem borda de entrada correspondente - a cabine "
                  "provavelmente comecou dentro da bandeirola; medicao "
                  "descartada)", flush=True)
            return

        largura = abs(contagem - self._contagem_entrada)
        if largura < LARGURA_MINIMA_MM:
            print("           (travessia incompleta: largura de %.0f mm, a "
                  "cabine entrou e saiu pelo mesmo lado; medicao descartada)"
                  % largura, flush=True)
            self._contagem_entrada = None
            return

        medicao = MedicaoBandeirola(
            self._contagem_entrada, contagem,
            posicao.andar_mais_proximo(
                posicao.contagem_para_mm((self._contagem_entrada + contagem) / 2.0)),
            time.monotonic())
        self._contagem_entrada = None
        self.medicoes.append(medicao)

        print("           -> andar %d | largura = %.0f mm | centro estimado = "
              "%.1f mm | nominal = %.0f mm | ERRO = %+.1f mm"
              % (medicao.andar, medicao.largura, medicao.centro,
                 posicao.posicao_do_andar(medicao.andar), medicao.erro),
              flush=True)

        if self._ao_medir:
            self._ao_medir(medicao)

    def finaliza(self):
        self._entrada.finaliza()
