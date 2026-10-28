"""Chamadas atribuidas a cabine e a ordem em que as paradas sao feitas.

A ordem e a do elevador coletivo (algoritmo SCAN): a cabine segue no sentido
em que esta enquanto houver parada a frente, e so entao inverte. Paradas sao
os andares de destino das chamadas que ja embarcaram, os comandos manuais do
central e as origens das que esperam, mas so das que vao no sentido da
varredura: quem quer descer nao embarca numa cabine que ainda sobe (subiria
para depois descer; na rasp52, 1 -> 0 levou 150 s no down-peak). A cabine vai
ate a origem contraria mais distante, onde inverte, e as do caminho embarcam
na volta. A mesma regra (escolhe_parada) faz a estimativa do despacho.

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
# Distancia abaixo da qual a cabine ja esta no andar, so terminando de assentar.
PERTO_DO_ANDAR_MM = 50.0


def sentido_da_viagem(origem, destino):
    """+1 sobe, -1 desce, None se o destino nao e conhecido."""
    if destino is None:
        return None
    return 1 if destino > origem else -1


def escolhe_parada(posicao_mm, sentido, obrigatorias, embarques, posicoes):
    """(andar, sentido da varredura) da proxima parada, ou (None, 0) sem nada.

    obrigatorias: andares de desembarque e comandos manuais. embarques: pares
    (origem, sentido do passageiro); sentido None embarca em qualquer
    varredura. posicoes: andar -> mm."""
    andares = set(obrigatorias) | {a for a, _ in embarques}
    if not andares:
        return None, 0

    def distancia(a):
        return abs(posicoes[a] - posicao_mm)

    if sentido == 0:
        mais_perto = min(andares, key=distancia)
        sentido = 1 if posicoes[mais_perto] > posicao_mm else -1
    for varredura in (sentido, -sentido):
        def a_frente(a):
            return (posicoes[a] - posicao_mm) * varredura > 0
        paradas = [a for a in obrigatorias if a_frente(a)] + \
            [a for a, s in embarques if s in (varredura, None) and a_frente(a)]
        if paradas:
            return min(paradas, key=distancia), varredura
        contrarias = [a for a, s in embarques if a_frente(a)]
        if contrarias:
            return max(contrarias, key=distancia), varredura
    # A unica parada e exatamente onde a cabine esta, ainda sem nivelar.
    return min(andares, key=distancia), sentido


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

    def esquece(self, identificadores):
        """Chamadas que o central descartou (a ESP32 foi reiniciada)."""
        with self._trava:
            esquecidas = [i for i in identificadores if self.chamadas.pop(i, None)]
            self._concluidas.extend(esquecidas)
            return esquecidas

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
            distancia = mapa.posicao[urgente] - posicao_mm
            # Ja chegando ao andar urgente o sentido fica: decidido pelos
            # poucos mm de sobrepasso ele inverteria a varredura, e a cabine
            # largaria as paradas a frente (espera de 95 s no down-peak).
            if abs(distancia) > PERTO_DO_ANDAR_MM:
                self.sentido = 1 if distancia > 0 else -1
            return urgente
        with self._trava:
            obrigatorias = {c.destino for c in self.chamadas.values()
                            if c.estado == EMBARCADA} | set(self.manuais)
            embarques = [(c.origem, sentido_da_viagem(c.origem, c.destino))
                         for c in self.chamadas.values() if c.estado == AGUARDANDO]
        andar, self.sentido = escolhe_parada(posicao_mm, self.sentido, obrigatorias,
                                             embarques, mapa.posicao)
        return andar

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
