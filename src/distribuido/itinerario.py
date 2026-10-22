"""Chamadas atribuidas a cabine e a ordem em que as paradas sao feitas.

A ordem e a do elevador coletivo (algoritmo SCAN): a cabine segue no sentido
em que esta enquanto houver parada a frente, e so entao inverte. Paradas sao
os andares de origem das chamadas que ainda esperam e os de destino das que
ja embarcaram, mais os comandos manuais do central.

Embarque e desembarque acontecem quando a porta abre no andar: e o instante
que o enunciado usa para medir espera e viagem. Cada um vira um evento com
id da chamada e horario, que vai para o central no relatorio de estado.
"""
import threading
import time
from collections import OrderedDict, deque

AGUARDANDO = "aguardando"
EMBARCADA = "embarcada"
EMBARQUE = "embarque"
DESEMBARQUE = "desembarque"

EVENTOS_GUARDADOS = 200
# Uma origem que espera ha mais que isto passa na frente da ordem do SCAN: e o
# que segura o limite de 90 s quando chamadas novas vao entrando no caminho.
ESPERA_URGENTE_S = 50.0


class Chamada:
    __slots__ = ("id", "origem", "destino", "estado", "registro")

    def __init__(self, identificador, origem, destino, estado=AGUARDANDO, registro=0.0):
        self.id = identificador
        self.origem = origem
        self.destino = destino
        self.estado = estado
        self.registro = registro

    @property
    def parada(self):
        return self.origem if self.estado == AGUARDANDO else self.destino

    def como_dicionario(self):
        return {"id": self.id, "origem": self.origem, "destino": self.destino,
                "estado": self.estado}


class Itinerario:
    def __init__(self, relogio=time.time):
        self._relogio = relogio
        self._trava = threading.Lock()
        self.chamadas = OrderedDict()
        self.manuais = []
        self.eventos = deque(maxlen=EVENTOS_GUARDADOS)
        self._concluidas = deque(maxlen=EVENTOS_GUARDADOS)
        self.sentido = 0

    # ---------------------------------------------------------- entradas
    def atribui(self, identificador, origem, destino, estado=AGUARDANDO, espera_s=0.0):
        """Devolve True se a chamada e nova. Repeticoes sao ignoradas: o
        central reenvia as pendentes a cada reconexao.

        espera_s e ha quanto tempo a chamada foi registrada, segundo o central:
        a contagem do limite de espera comeca no quiosque, nao aqui."""
        with self._trava:
            if identificador in self.chamadas or identificador in self._concluidas:
                return False
            self.chamadas[identificador] = Chamada(
                identificador, int(origem), int(destino), estado,
                registro=self._relogio() - float(espera_s))
            return True

    def manual(self, andar):
        with self._trava:
            if andar not in self.manuais:
                self.manuais.append(int(andar))

    # ---------------------------------------------------------- consultas
    def paradas(self):
        with self._trava:
            return {c.parada for c in self.chamadas.values()} | set(self.manuais)

    def lista(self):
        with self._trava:
            return [c.como_dicionario() for c in self.chamadas.values()]

    def ultimos_eventos(self, quantidade=40):
        with self._trava:
            return list(self.eventos)[-quantidade:]

    def proxima_parada(self, posicao_mm, mapa, andar_aqui):
        """Andar da proxima parada, ou None sem nada a fazer.

        andar_aqui e o andar em que a cabine esta nivelada (ou None)."""
        paradas = self.paradas()
        if not paradas:
            self.sentido = 0
            return None
        if andar_aqui in paradas:
            return andar_aqui
        urgente = self._origem_urgente()
        if urgente is not None:
            self.sentido = 1 if mapa.posicao[urgente] > posicao_mm else -1
            return urgente
        acima = [a for a in paradas if mapa.posicao[a] > posicao_mm]
        abaixo = [a for a in paradas if mapa.posicao[a] < posicao_mm]
        if not acima and not abaixo:
            # A unica parada e exatamente onde a cabine esta, ainda sem nivelar.
            return min(paradas, key=lambda a: abs(mapa.posicao[a] - posicao_mm))
        if self.sentido == 0:
            mais_perto = min(paradas, key=lambda a: abs(mapa.posicao[a] - posicao_mm))
            self.sentido = 1 if mapa.posicao[mais_perto] > posicao_mm else -1
        if self.sentido > 0 and not acima:
            self.sentido = -1
        elif self.sentido < 0 and not abaixo:
            self.sentido = 1
        return min(acima) if self.sentido > 0 else max(abaixo)

    def _origem_urgente(self):
        agora = self._relogio()
        with self._trava:
            atrasadas = [c for c in self.chamadas.values()
                         if c.estado == AGUARDANDO and agora - c.registro > ESPERA_URGENTE_S]
        if not atrasadas:
            return None
        return min(atrasadas, key=lambda c: c.registro).origem

    # ----------------------------------------------------------- porta
    def porta_abriu(self, andar):
        """Embarca quem espera no andar e desembarca quem ia para ele."""
        agora = self._relogio()
        novos = []
        with self._trava:
            for chamada in list(self.chamadas.values()):
                if chamada.estado == EMBARCADA and chamada.destino == andar:
                    del self.chamadas[chamada.id]
                    self._concluidas.append(chamada.id)
                    novos.append({"id": chamada.id, "evento": DESEMBARQUE,
                                  "t": agora, "andar": andar})
                elif chamada.estado == AGUARDANDO and chamada.origem == andar:
                    chamada.estado = EMBARCADA
                    novos.append({"id": chamada.id, "evento": EMBARQUE,
                                  "t": agora, "andar": andar})
            if andar in self.manuais:
                self.manuais.remove(andar)
            self.eventos.extend(novos)
        return novos
