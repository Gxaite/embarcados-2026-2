"""Cota de Potencia vigente (Secoes 7.2 e 7.3).

A Cota chega do Servidor Central a cada 1 s e vale 2 s. Ela vira teto de duty
pela formula do enunciado, duty_max = cota / 6000 * 100, e e esse teto que
satura a saida do PID.

O prazo e contado no relogio desta cabine a partir do recebimento, nunca por
um horario mandado pelo central: os dois processos podem estar em maquinas
diferentes, e um relogio adiantado faria toda cota chegar ja vencida.

A formula supoe 6000 mA a 100% de duty, proporcional. A ESP32 nao e assim:
marca 300 mA com a cabine parada mais ~54 mA por ponto de duty (1212 mA a 17%
na bancada em 22/10/2026; 2300 a 37% e 3000 a 56% na rasp52 em 28/10/2026).
A cabine mede os dois numeros na corrente que o central repassa a cada
500 ms e usa como teto o maior duty cuja corrente prevista cabe na Cota, com
folga. A inclinacao e a pior vista e so desce devagar, e o teto nunca passa
da formula do enunciado. Um fator unico sobre a formula, como antes, era
medido em duty baixo, onde os 300 mA pesam, e travava o cruzeiro em ~48% com
Cota de 4000 mA: o barramento ficava 40% ocioso.

Sem Cota valida a cabine entra em Modo Degradado e usa o teto de 1000 mA, a
velocidade minima. Ela nao inventa potencia para si: 1000 mA e o que o
enunciado reserva para o pouso de emergencia.
"""
import threading
import time
from collections import deque

CORRENTE_DE_ACELERACAO_PLENA_MA = 6000.0
COTA_DO_MODO_DEGRADADO_MA = 1000.0
VALIDADE_PADRAO_S = 2.0

CORRENTE_PARADA_INICIAL_MA = 300.0
# mA por ponto de duty: o percentil 90 das ultimas medidas com o duty estavel.
# Na rasp52 a inclinacao em cruzeiro foi de 56 mA por ponto (p90 58), igual
# subindo e descendo; o pior valor visto (70 a 81, em picos raros), guardado e
# esquecido devagar, travava o cruzeiro em 42-49% de duty. Os picos ficam com
# a folga da Cota e a reserva do barramento. Ate juntar medidas, 10% acima dos
# 60 da formula.
CORRENTE_POR_DUTY_INICIAL_MA = 66.0
CORRENTE_POR_DUTY_MINIMA_MA = 30.0
CORRENTE_POR_DUTY_MAXIMA_MA = 150.0
MEDIDAS_GUARDADAS = 40
MEDIDAS_PARA_CONFIAR = 10
PERCENTIL_DA_INCLINACAO = 0.9
# Margem para o pico da partida sobre a corrente de cruzeiro (1,13 vez na
# rasp52); com 5% os picos somados estouraram o barramento.
FOLGA_DA_COTA = 1.10
DUTY_MINIMO_PARA_MEDIR = 12.0


def duty_maximo_de(cota_ma, corrente_parada_ma=None, corrente_por_duty_ma=None):
    """Teto de duty da Cota: a formula do enunciado, cota / 6000 x 100, e, com
    o modelo medido, o duty cuja corrente prevista cabe na Cota com folga."""
    teto = cota_ma / CORRENTE_DE_ACELERACAO_PLENA_MA * 100.0
    if corrente_por_duty_ma:
        teto = min(teto, (cota_ma / FOLGA_DA_COTA - (corrente_parada_ma or 0.0))
                   / corrente_por_duty_ma)
    return max(0.0, min(100.0, teto))


class CotaDePotencia:
    def __init__(self, relogio=time.monotonic):
        self._relogio = relogio
        self._trava = threading.Lock()
        self._cota_ma = 0.0
        self._vence_em = None
        self.recebidas = 0
        # Numero da ultima Cota recebida. Volta ao central no relatorio de
        # estado: e assim que ele sabe que uma reducao ja chegou e que a
        # potencia liberada pode ser concedida a outra cabine.
        self.sequencia = None
        self.corrente_parada_ma = CORRENTE_PARADA_INICIAL_MA
        self.corrente_por_duty_ma = CORRENTE_POR_DUTY_INICIAL_MA
        self._inclinacoes = deque(maxlen=MEDIDAS_GUARDADAS)

    def mede_corrente(self, corrente_ma, duty):
        """Corrente medida (registrador corrente_ma) com o motor no duty `duty`,
        em %, estavel desde antes da leitura. Parado, ela e a corrente de
        repouso; acima de 12%, da a inclinacao."""
        if corrente_ma is None:
            return
        duty = abs(duty)
        with self._trava:
            if duty == 0.0:
                self.corrente_parada_ma = float(corrente_ma)
                return
            if duty < DUTY_MINIMO_PARA_MEDIR:
                return
            medida = (float(corrente_ma) - self.corrente_parada_ma) / duty
            self._inclinacoes.append(min(CORRENTE_POR_DUTY_MAXIMA_MA, medida))
            ordenadas = sorted(self._inclinacoes)
            inclinacao = ordenadas[int(PERCENTIL_DA_INCLINACAO * (len(ordenadas) - 1))]
            if len(ordenadas) < MEDIDAS_PARA_CONFIAR:
                inclinacao = max(inclinacao, CORRENTE_POR_DUTY_INICIAL_MA)
            self.corrente_por_duty_ma = max(CORRENTE_POR_DUTY_MINIMA_MA, inclinacao)

    def recebe(self, cota_ma, validade_s=VALIDADE_PADRAO_S, sequencia=None):
        with self._trava:
            self._cota_ma = max(0.0, float(cota_ma))
            self._vence_em = self._relogio() + float(validade_s)
            self.recebidas += 1
            self.sequencia = sequencia

    def invalida(self):
        with self._trava:
            self._vence_em = None

    @property
    def valida(self):
        with self._trava:
            return self._vence_em is not None and self._relogio() < self._vence_em

    @property
    def cota_ma(self):
        """Cota que esta limitando a cabine agora (a de degradado, se vencida)."""
        return self._cota_ma if self.valida else COTA_DO_MODO_DEGRADADO_MA

    @property
    def duty_maximo(self):
        return duty_maximo_de(self.cota_ma, self.corrente_parada_ma,
                              self.corrente_por_duty_ma)

    def duty_maximo_durante(self, segundos):
        """Teto de duty que continua valido pelos proximos `segundos`.

        A malha aplica o duty uma vez por ciclo. Se a Cota vence antes do
        proximo ciclo, o teto de degradado tem de valer ja neste, senao a
        cabine passaria ate um ciclo inteiro acima da Cota vencida."""
        with self._trava:
            valida_ate_la = self._vence_em is not None and \
                self._relogio() + segundos < self._vence_em
            cota = self._cota_ma if valida_ate_la else COTA_DO_MODO_DEGRADADO_MA
        return duty_maximo_de(min(cota, self.cota_ma), self.corrente_parada_ma,
                              self.corrente_por_duty_ma)
