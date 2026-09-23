"""Sensor de Andar: medicao da bandeirola pelas duas bordas.

A bandeirola e uma regiao do poco centrada no andar, em que o sinal fica alto.
Duas propriedades dela tornam este exercicio necessario:

- e MUITO mais larga que os +-10 mm de tolerancia, entao parar assim que o
  sensor sobe nao deixa a cabine nivelada;
- tem largura DIFERENTE em cada andar, entao nao da para deduzir o centro a
  partir de uma borda so.

Dai o centro ser a media das contagens nas duas bordas.

Travessia incompleta e descartada: se a cabine entra na bandeirola, para e
inverte o sentido, ela sai pelo mesmo lado por onde entrou. A largura medida
fica minuscula e a media cairia numa extremidade, nao no centro.
"""
from ..gpio import pinos
from ..gpio.entradas import EntradaInterrupcao
from . import posicao

DEBOUNCE_MS = 2.0

# Largura minima para aceitar uma travessia como completa.
#
# O valor vem da bancada, nao de chute: as bandeirolas reais medidas na rasp42
# tem cerca de 190 mm (andar 0), 241 mm (andar 1) e 142 mm (andar 2). Uma
# "travessia" bem menor que a menor delas nao e bandeirola - e a cabine que
# entrou e saiu pelo mesmo lado, ou uma borda espuria por ruido eletrico.
#
# Com o limite antigo de 20 mm, a bancada produziu uma medicao de 34 mm com
# centro em 2898 mm, ou seja 102 mm fora do nominal do andar 1. Aceitar isso
# contamina a medicao do centro, que e justamente o que o requisito 7 cobra.
LARGURA_MINIMA_MM = 60.0


class Medicao:
    def __init__(self, andar, borda_de_entrada, borda_de_saida):
        self.andar = andar
        self.borda_de_entrada = borda_de_entrada
        self.borda_de_saida = borda_de_saida

    @property
    def largura_mm(self):
        return abs(self.borda_de_saida - self.borda_de_entrada)

    @property
    def centro_mm(self):
        return (self.borda_de_entrada + self.borda_de_saida) / 2.0

    @property
    def erro_mm(self):
        """Centro medido menos a posicao nominal do andar."""
        if self.andar is None:
            return None
        return self.centro_mm - posicao.mm_do_andar(self.andar)

    def __repr__(self):
        return ("Medicao(andar=%s, largura=%.1f mm, centro=%.1f mm, erro=%s)"
                % (self.andar, self.largura_mm, self.centro_mm,
                   "n/d" if self.erro_mm is None else "%+.1f mm" % self.erro_mm))


class SensorAndar:
    def __init__(self, backend, encoder, ao_medir=None):
        self._encoder = encoder
        self._ao_medir = ao_medir
        self.medicoes = []
        self._contagem_de_entrada = None
        self._entrada = EntradaInterrupcao(
            backend, pinos.SENSOR_ANDAR, self._trata, debounce_ms=DEBOUNCE_MS,
            # A contagem e capturada na BORDA CRUA. Lida depois do debounce, a
            # cabine ja teria andado e o centro sairia enviesado.
            instantanea=lambda: self._encoder.contagem)

    @property
    def dentro_da_bandeirola(self):
        return self._entrada.nivel == 1

    def _trata(self, nivel, contagem_da_borda):
        if contagem_da_borda is None:
            contagem_da_borda = self._encoder.contagem
        mm = posicao.mm_de_contagem(contagem_da_borda)

        if nivel == 1:
            self._contagem_de_entrada = mm
            print("SENSOR_ANDAR: entrou na bandeirola em %d mm" % mm, flush=True)
            return

        print("SENSOR_ANDAR: saiu da bandeirola em %d mm" % mm, flush=True)
        entrada = self._contagem_de_entrada
        self._contagem_de_entrada = None
        if entrada is None:
            return

        medicao = Medicao(None, entrada, mm)
        if medicao.largura_mm < LARGURA_MINIMA_MM:
            print("  travessia incompleta (%.1f mm): medicao descartada"
                  % medicao.largura_mm, flush=True)
            return

        medicao.andar = posicao.andar_estimado(medicao.centro_mm)
        self.medicoes.append(medicao)
        print("  bandeirola: largura %.1f mm | centro %.1f mm | erro %s"
              % (medicao.largura_mm, medicao.centro_mm,
                 "n/d" if medicao.erro_mm is None else "%+.1f mm" % medicao.erro_mm),
              flush=True)
        if self._ao_medir is not None:
            self._ao_medir(medicao)

    def finaliza(self):
        self._entrada.finaliza()
