"""Reparticao do Barramento de Potencia em Cotas (Secao 7.2).

Invariante: a soma das Cotas que as cabines PODEM estar usando nunca passa de
barramento_max_ma. "Podem estar usando" e a parte delicada. Ao trocar 4000
mA da cabine 1 para a cabine 2, mandar as duas mensagens juntas nao basta: se
a da cabine 2 chegar primeiro, por um instante as duas valem 4000 a mais.

Por isso cada Cota tem numero de sequencia, e a cabine devolve no relatorio o
numero da ultima que recebeu. Uma Cota enviada continua contando como em uso
ate a cabine confirmar uma posterior, ou ate vencer (2 s). Reducoes saem na
hora; aumentos so cabem no que sobra depois de contar, de cada outra cabine,
a maior Cota que ela ainda pode estar usando. Na pratica o aumento chega um
ciclo (1 s) depois da reducao que o libera.

Divisao: cada cabine conectada recebe a Cota minima de 1000 mA (a velocidade
minima, a mesma do Modo Degradado) e o resto vai para as que tem viagem a
fazer, em partes iguais, ate 6000 mA cada. O que ainda sobrar fica com as
ociosas, para que a proxima chamada nao espere um ciclo para partir.

Cabine que nao recebe Cota (desconectada, ou com a Cota suspensa) nao sai da
conta: em Modo Degradado ela anda a 1000 mA, e esses 1000 mA ficam reservados.
"""
import itertools
import threading
import time

VALIDADE_S = 2.0
COTA_MINIMA_MA = 1000
COTA_DO_MODO_DEGRADADO_MA = 1000
COTA_MAXIMA_MA = 6000
# Sem leitura do barramento, o central assume o piso do watchdog: e o valor
# que o simulador impoe quando nao sabe a temperatura.
CAPACIDADE_DESCONHECIDA_MA = 3000


def divide(capacidade_ma, ativas, ociosas):
    """Cota ideal de cada cabine, ignorando o que esta em transito."""
    todas = list(ativas) + list(ociosas)
    if not todas:
        return {}
    base = min(COTA_MINIMA_MA, capacidade_ma // len(todas))
    cotas = {n: base for n in todas}
    restante = capacidade_ma - base * len(todas)
    for grupo in (list(ativas), list(ociosas)):
        while restante > 0:
            com_folga = [n for n in grupo if cotas[n] < COTA_MAXIMA_MA]
            parte = restante // len(com_folga) if com_folga else 0
            if parte == 0:
                break
            for n in com_folga:
                acrescimo = min(parte, COTA_MAXIMA_MA - cotas[n])
                cotas[n] += acrescimo
                restante -= acrescimo
    return cotas


class _EmTransito:
    __slots__ = ("sequencia", "cota_ma", "vence_em")

    def __init__(self, sequencia, cota_ma, vence_em):
        self.sequencia = sequencia
        self.cota_ma = cota_ma
        self.vence_em = vence_em


class RepartidorDeCotas:
    def __init__(self, relogio=time.monotonic):
        self._relogio = relogio
        self._trava = threading.Lock()
        self._sequencia = itertools.count(1)
        self._enviadas = {}        # cabine -> [_EmTransito], ordem de envio
        self.ultimas = {}          # cabine -> cota da ultima rodada

    def confirma(self, cabine, sequencia):
        """A cabine relatou ter recebido a Cota `sequencia`."""
        if sequencia is None:
            return
        with self._trava:
            enviadas = self._enviadas.get(cabine, [])
            self._enviadas[cabine] = [e for e in enviadas if e.sequencia >= sequencia]

    def em_uso(self, cabine):
        """Maior Cota que a cabine pode estar usando agora."""
        agora = self._relogio()
        with self._trava:
            vivas = [e for e in self._enviadas.get(cabine, []) if e.vence_em > agora]
            self._enviadas[cabine] = vivas
            return max((e.cota_ma for e in vivas), default=0)

    def soma_em_uso(self):
        with self._trava:
            cabines = list(self._enviadas)
        return sum(self.em_uso(c) for c in cabines)

    def reparte(self, capacidade_ma, ativas, ociosas, sem_cota=()):
        """Devolve {cabine: (cota_ma, sequencia)} a enviar nesta rodada.

        sem_cota: cabines que nao vao receber Cota (desconectadas, ou com a
        Cota suspensa). Sem Cota valida elas entram em Modo Degradado e andam
        a 1000 mA por conta propria, entao essa corrente fica reservada."""
        if capacidade_ma is None:
            capacidade_ma = CAPACIDADE_DESCONHECIDA_MA
        capacidade_ma = int(capacidade_ma)
        reserva = {c: COTA_DO_MODO_DEGRADADO_MA for c in sem_cota}
        livre = max(0, capacidade_ma - sum(reserva.values()))
        ideais = divide(livre, ativas, ociosas)
        em_uso = {c: self.em_uso(c) for c in set(self._enviadas) | set(ideais)}
        for cabine, corrente in reserva.items():
            em_uso[cabine] = max(em_uso.get(cabine, 0), corrente)
        concedidas = {}
        # Reducoes primeiro: so liberam potencia.
        ordem = sorted(ideais, key=lambda c: ideais[c] - em_uso.get(c, 0))
        for cabine in ordem:
            outras = sum(max(em_uso.get(c, 0), concedidas.get(c, 0))
                         for c in em_uso if c != cabine)
            cota = max(0, min(ideais[cabine], capacidade_ma - outras))
            concedidas[cabine] = cota
            em_uso[cabine] = max(em_uso.get(cabine, 0), cota)
        envio = {}
        vence_em = self._relogio() + VALIDADE_S
        with self._trava:
            for cabine, cota in concedidas.items():
                sequencia = next(self._sequencia)
                self._enviadas.setdefault(cabine, []).append(
                    _EmTransito(sequencia, cota, vence_em))
                envio[cabine] = (cota, sequencia)
            self.ultimas = {c: cota for c, (cota, _) in envio.items()}
        return envio

    def cancela(self, cabine, sequencia):
        """A mensagem nao saiu (conexao caiu): a Cota nao esta em uso."""
        with self._trava:
            self._enviadas[cabine] = [e for e in self._enviadas.get(cabine, [])
                                      if e.sequencia != sequencia]
