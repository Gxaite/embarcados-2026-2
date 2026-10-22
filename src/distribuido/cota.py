"""Cota de Potencia vigente (Secoes 7.2 e 7.3).

A Cota chega do Servidor Central a cada 1 s e vale 2 s. Ela vira teto de duty
pela formula do enunciado, duty_max = cota / 6000 * 100, e e esse teto que
satura a saida do PID.

O prazo e contado no relogio desta cabine a partir do recebimento, nunca por
um horario mandado pelo central: os dois processos podem estar em maquinas
diferentes, e um relogio adiantado faria toda cota chegar ja vencida.

Sem Cota valida a cabine entra em Modo Degradado e usa o teto de 1000 mA, a
velocidade minima. Ela nao inventa potencia para si: 1000 mA e o que o
enunciado reserva para o pouso de emergencia.
"""
import threading
import time

CORRENTE_DE_ACELERACAO_PLENA_MA = 6000.0
COTA_DO_MODO_DEGRADADO_MA = 1000.0
VALIDADE_PADRAO_S = 2.0


def duty_maximo_de(cota_ma):
    return max(0.0, min(100.0, cota_ma / CORRENTE_DE_ACELERACAO_PLENA_MA * 100.0))


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
        return duty_maximo_de(self.cota_ma)

    def duty_maximo_durante(self, segundos):
        """Teto de duty que continua valido pelos proximos `segundos`.

        A malha aplica o duty uma vez por ciclo. Se a Cota vence antes do
        proximo ciclo, o teto de degradado tem de valer ja neste, senao a
        cabine passaria ate um ciclo inteiro acima da Cota vencida."""
        with self._trava:
            valida_ate_la = self._vence_em is not None and \
                self._relogio() + segundos < self._vence_em
            cota = self._cota_ma if valida_ate_la else COTA_DO_MODO_DEGRADADO_MA
        return duty_maximo_de(min(cota, self.cota_ma))
