"""Cota de Potencia vigente (Secoes 7.2 e 7.3).

A Cota chega do Servidor Central a cada 1 s e vale 2 s. Ela vira teto de duty
pela formula do enunciado, duty_max = cota / 6000 * 100, e e esse teto que
satura a saida do PID.

O prazo e contado no relogio desta cabine a partir do recebimento, nunca por
um horario mandado pelo central: os dois processos podem estar em maquinas
diferentes, e um relogio adiantado faria toda cota chegar ja vencida.

A formula supoe 6000 mA a 100% de duty. Na bancada (22/10/2026) a ESP32
mediu 1212 mA a 17% de duty, uns 20% acima do que ela preve. Por isso a
corrente medida (registrador corrente_ma, que o central repassa a cada 500 ms)
corrige a conversao: o fator e o pior excesso visto, com folga, e so desce
devagar. Ele nunca fica abaixo de 1: a cabine nunca usa mais duty do que a
formula do enunciado permite.

Sem Cota valida a cabine entra em Modo Degradado e usa o teto de 1000 mA, a
velocidade minima. Ela nao inventa potencia para si: 1000 mA e o que o
enunciado reserva para o pouso de emergencia.
"""
import threading
import time

CORRENTE_DE_ACELERACAO_PLENA_MA = 6000.0
COTA_DO_MODO_DEGRADADO_MA = 1000.0
VALIDADE_PADRAO_S = 2.0

# Corrente medida / corrente da formula. Comeca acima do 1,21 medido na
# bancada, para nao estourar a Cota antes da primeira medicao.
FATOR_INICIAL = 1.3
FATOR_MAXIMO = 2.0
FOLGA_DO_FATOR = 1.05
QUEDA_DO_FATOR_POR_MEDICAO = 0.002
DUTY_MINIMO_PARA_MEDIR = 12.0


def duty_maximo_de(cota_ma, fator=1.0):
    return max(0.0, min(100.0, cota_ma / (CORRENTE_DE_ACELERACAO_PLENA_MA * fator)
                        * 100.0))


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
        self.fator_de_corrente = FATOR_INICIAL

    def mede_corrente(self, corrente_ma, duty):
        """Corrente medida com o motor no duty `duty` (em %)."""
        duty = abs(duty)
        if corrente_ma is None or duty < DUTY_MINIMO_PARA_MEDIR:
            return
        prevista = CORRENTE_DE_ACELERACAO_PLENA_MA * duty / 100.0
        medido = float(corrente_ma) / prevista * FOLGA_DO_FATOR
        with self._trava:
            self.fator_de_corrente = max(
                1.0, min(FATOR_MAXIMO, max(medido, self.fator_de_corrente
                                           - QUEDA_DO_FATOR_POR_MEDICAO)))

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
        return duty_maximo_de(self.cota_ma, self.fator_de_corrente)

    def duty_maximo_durante(self, segundos):
        """Teto de duty que continua valido pelos proximos `segundos`.

        A malha aplica o duty uma vez por ciclo. Se a Cota vence antes do
        proximo ciclo, o teto de degradado tem de valer ja neste, senao a
        cabine passaria ate um ciclo inteiro acima da Cota vencida."""
        with self._trava:
            valida_ate_la = self._vence_em is not None and \
                self._relogio() + segundos < self._vence_em
            cota = self._cota_ma if valida_ate_la else COTA_DO_MODO_DEGRADADO_MA
        return duty_maximo_de(min(cota, self.cota_ma), self.fator_de_corrente)
