"""Backend simulado: um modelo do poco da Cabine 1 rodando em software.

Serve para desenvolver e testar a Entrega 1 sem a bancada. O modelo reproduz os
comportamentos que o enunciado exige tratar:

  - motor com atrito estatico (nao arranca com duty abaixo de 10%) e inercia;
  - encoder em quadratura gerando as quatro transicoes por milimetro, com a
    ordem das bordas indicando o sentido;
  - bandeirolas de andar com LARGURAS DIFERENTES entre si e muito maiores que a
    tolerancia de +-10 mm - por isso parar na primeira borda nao nivela;
  - cortina de luz que emite repique (bounce) em cada borda, como o simulador
    da bancada faz de proposito.

NAO substitui a bancada: aqui nao ha jitter de escalonador nem latencia real de
interrupcao. Serve para validar logica, nao para sintonizar ganhos.
"""
import math
import threading
import time

from . import backend, pinos
from .backend import BackendGPIO, CanalPWM

# Sequencia de Gray dos canais (A, B) percorrida a cada milimetro.
# Subindo:  00 -> 01 -> 11 -> 10 -> 00 ; descendo, o caminho inverso.
QUADRATURA = [(0, 0), (0, 1), (1, 1), (1, 0)]

# Larguras propositalmente diferentes, e todas muito maiores que os +-10 mm de
# tolerancia de nivelamento.
LARGURA_BANDEIROLA = {0: 120.0, 1: 84.0, 2: 150.0}
POSICAO_ANDAR = {0: 0.0, 1: 3000.0, 2: 6000.0}

VELOCIDADE_MAXIMA = 1200.0  # mm/s com duty 100%
DUTY_ARRANQUE = 10.0        # abaixo disso o motor parado nao vence o atrito
TAU_MOTOR = 0.20            # constante de tempo da resposta de velocidade (s)
LIMITE_INFERIOR = -400.0    # poco abaixo do andar 0
LIMITE_SUPERIOR = 6400.0    # sobrecurso acima do andar 2

# Repique injetado em cada borda da cortina: (atraso_s, nivel)
BOUNCE = [(0.000, 1), (0.004, 0), (0.008, 1), (0.013, 0), (0.019, 1)]


class _CanalPWMSimulado(CanalPWM):
    def __init__(self, sim, pino):
        self._sim = sim
        self._pino = pino

    def inicia(self, duty):
        self.ajusta(duty)

    def ajusta(self, duty):
        self._sim._duty = max(0.0, min(100.0, float(duty)))

    def para(self):
        self._sim._duty = 0.0


class BackendSimulado(BackendGPIO):
    """Implementa a interface de GPIO sobre o modelo fisico do poco."""

    PASSO = 0.002  # periodo nominal da thread de simulacao (s)

    def __init__(self, posicao_inicial_mm=0.0):
        self._valores = {}                 # pino -> nivel logico
        self._callbacks = {}               # pino -> lista de (borda, funcao)
        self._duty = 0.0
        self._posicao = float(posicao_inicial_mm)
        self._velocidade = 0.0
        self._contagem_emitida = int(math.floor(self._posicao))
        self._eventos_cortina = []         # [(instante, nivel)] pendentes
        self._lock = threading.Lock()
        self._parar = threading.Event()

        for pino in (pinos.DIR1, pinos.DIR2, pinos.PWM):
            self._valores[pino] = 0
        self._valores[pinos.CORTINA] = 0
        self._valores[pinos.SENSOR_ANDAR] = self._dentro_de_bandeirola()
        a, b = QUADRATURA[self._contagem_emitida % 4]
        self._valores[pinos.ENC_A] = a
        self._valores[pinos.ENC_B] = b

        self._thread = threading.Thread(target=self._laco, daemon=True,
                                        name="simulador-poco")
        self._thread.start()

    # ------------------------------------------------------------------
    # Interface BackendGPIO
    # ------------------------------------------------------------------
    def configura_saida(self, pino, valor_inicial=0):
        self._valores[pino] = 1 if valor_inicial else 0

    def configura_entrada(self, pino, pull=backend.PULL_NENHUM):
        self._valores.setdefault(pino, 0)

    def escreve(self, pino, valor):
        self._valores[pino] = 1 if valor else 0

    def le(self, pino):
        return self._valores.get(pino, 0)

    def registra_interrupcao(self, pino, borda, callback):
        self._callbacks.setdefault(pino, []).append((borda, callback))

    def cria_pwm(self, pino, frequencia_hz):
        return _CanalPWMSimulado(self, pino)

    def finaliza(self):
        self._parar.set()
        self._thread.join(timeout=1.0)

    # ------------------------------------------------------------------
    # Estimulos de teste (equivalentes aos botoes do widget da bancada)
    # ------------------------------------------------------------------
    def obstruir_porta(self):
        """Equivale ao botao "Obstruir porta": sobe a cortina, com repique."""
        self._agenda_cortina(1)

    def liberar_porta(self):
        """Solta a cortina, tambem com repique na borda."""
        self._agenda_cortina(0)

    def posicao_real_mm(self):
        """Posicao verdadeira no poco - so o simulador sabe disso."""
        return self._posicao

    def _agenda_cortina(self, nivel_final):
        agora = time.monotonic()
        with self._lock:
            self._eventos_cortina = [
                (agora + atraso, nivel if nivel_final else 1 - nivel)
                for atraso, nivel in BOUNCE
            ]
            self._eventos_cortina.append((agora + 0.030, nivel_final))

    # ------------------------------------------------------------------
    # Modelo
    # ------------------------------------------------------------------
    def _sentido(self):
        """Traduz DIR1/DIR2 na Tabela 2 do enunciado."""
        d1 = self._valores.get(pinos.DIR1, 0)
        d2 = self._valores.get(pinos.DIR2, 0)
        if d1 and not d2:
            return +1      # subir
        if d2 and not d1:
            return -1      # descer
        if d1 and d2:
            return "freio"
        return "livre"

    def _dentro_de_bandeirola(self):
        for andar, centro in POSICAO_ANDAR.items():
            if abs(self._posicao - centro) <= LARGURA_BANDEIROLA[andar] / 2.0:
                return 1
        return 0

    def _laco(self):
        anterior = time.monotonic()
        while not self._parar.is_set():
            time.sleep(self.PASSO)
            agora = time.monotonic()
            dt = agora - anterior
            anterior = agora
            self._passo(dt, agora)

    def _passo(self, dt, agora):
        sentido = self._sentido()

        if sentido == "freio":
            alvo = 0.0
            tau = TAU_MOTOR / 4.0            # freio para bem mais rapido
        elif sentido == "livre":
            alvo = 0.0
            tau = TAU_MOTOR * 6.0            # roda livre: desacelera devagar
        else:
            parado = abs(self._velocidade) < 1.0
            if parado and self._duty < DUTY_ARRANQUE:
                alvo = 0.0                   # atrito estatico: nao arranca
            else:
                alvo = sentido * (self._duty / 100.0) * VELOCIDADE_MAXIMA
            tau = TAU_MOTOR

        self._velocidade += (alvo - self._velocidade) * min(1.0, dt / tau)
        self._posicao += self._velocidade * dt

        if self._posicao <= LIMITE_INFERIOR:   # batente do poco
            self._posicao, self._velocidade = LIMITE_INFERIOR, 0.0
        elif self._posicao >= LIMITE_SUPERIOR:
            self._posicao, self._velocidade = LIMITE_SUPERIOR, 0.0

        self._emite_quadratura()
        self._atualiza_entrada(pinos.SENSOR_ANDAR, self._dentro_de_bandeirola())
        self._despacha_cortina(agora)

    def _emite_quadratura(self):
        """Gera uma transicao de (A, B) por milimetro percorrido."""
        destino = int(math.floor(self._posicao))
        while self._contagem_emitida != destino:
            self._contagem_emitida += 1 if destino > self._contagem_emitida else -1
            a, b = QUADRATURA[self._contagem_emitida % 4]
            self._atualiza_entrada(pinos.ENC_A, a)
            self._atualiza_entrada(pinos.ENC_B, b)

    def _despacha_cortina(self, agora):
        with self._lock:
            vencidos = [e for e in self._eventos_cortina if e[0] <= agora]
            self._eventos_cortina = [e for e in self._eventos_cortina
                                     if e[0] > agora]
        for _, nivel in vencidos:
            self._atualiza_entrada(pinos.CORTINA, nivel)

    def _atualiza_entrada(self, pino, valor):
        """Troca o nivel de uma entrada e dispara as interrupcoes registradas."""
        antigo = self._valores.get(pino, 0)
        if antigo == valor:
            return
        self._valores[pino] = valor
        borda = backend.SUBIDA if valor else backend.DESCIDA
        for borda_pedida, callback in self._callbacks.get(pino, []):
            if borda_pedida in (borda, backend.AMBAS):
                callback(pino, valor)
