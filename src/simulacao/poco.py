"""Fisica de uma cabine no poco de 6 andares.

Reproduz o que o enunciado descreve e o que a Entrega Final precisa exercitar:

- andares fora dos multiplos de 3000 mm, diferentes em cada cabine, e
  bandeirolas de largura diferente em cada andar;
- 400 mm de poco abaixo do andar 0 e de sobrecurso acima do andar 5;
- atrito estatico (parado, nao arranca abaixo de 10% de duty) e inercia;
- quadratura de verdade, uma transicao por milimetro, e perda ocasional de
  transicoes para simular a deriva da contagem na Raspberry Pi;
- corrente de 300 mA parada mais 54 mA por ponto de duty com o motor
  acionado, como a ESP32 mediu (22/10 e 28/10/2026);
- porta com tempos de abertura e fechamento, obstruida pela cortina de luz.

Tambem conta as violacoes que a avaliacao verifica (porta aberta fora do
nivelamento, cabine andando de porta aberta, batida no fim do poco), para que
os testes possam conferir os invariantes.
"""
import math
import random
import threading

DUTY_DE_ARRANQUE = 10.0
VELOCIDADE_MAXIMA_MM_S = 1000.0     # a 100% de duty
CONSTANTE_DE_INERCIA_S = 0.30
# Medido na ESP32: 300 mA com a cabine parada, 1212 mA a 17% (22/10/2026),
# cerca de 2300 mA a 37% e 3000 mA a 56% (rasp52, 28/10/2026). Nao e
# proporcional: a 17% passa 21% da formula do enunciado, a 56% fica abaixo.
CORRENTE_EM_REPOUSO_MA = 300.0
CORRENTE_POR_PONTO_DE_DUTY_MA = 54.0
TOLERANCIA_MM = 10.0
POCO_MM = 400.0

TEMPO_DE_ABERTURA_S = 1.5
TEMPO_DE_FECHAMENTO_S = 1.5

FECHADA, ABRINDO, ABERTA, FECHANDO, OBSTRUIDA = range(5)

# Bits do registrador `falha` neste simulador.
FALHA_FIM_DE_CURSO = 0x01
FALHA_PORTA_FORA_DE_NIVEL = 0x02
FALHA_ANDOU_DE_PORTA_ABERTA = 0x04

_CICLO = (0b00, 0b01, 0b11, 0b10)


def andares_de_exemplo(numero_da_cabine):
    """Posicoes e larguras de bandeirola diferentes por cabine, deterministicas."""
    sorteio = random.Random(1000 + numero_da_cabine)
    andares = [3000.0 * a + sorteio.uniform(-60.0, 60.0) for a in range(6)]
    andares[0] = 0.0 + sorteio.uniform(-20.0, 20.0)
    larguras = [sorteio.uniform(90.0, 240.0) for _ in range(6)]
    return andares, larguras


class CabineFisica:
    def __init__(self, numero, pinagem, andares_mm, larguras_mm,
                 andar_inicial=0, perda_de_transicoes=0.0, semente=0):
        self.numero = numero
        self.pinagem = dict(pinagem)
        self.andares_mm = list(andares_mm)
        self.larguras_mm = list(larguras_mm)
        self.fundo_mm = self.andares_mm[0] - POCO_MM
        self.topo_mm = self.andares_mm[-1] + POCO_MM

        self.trava = threading.RLock()
        self.niveis = {p: 0 for p in self.pinagem.values()}
        self.interrupcoes = {}
        self.duty = 0.0

        self.posicao_mm = self.andares_mm[andar_inicial]
        self.velocidade_mm_s = 0.0
        self._passo_inteiro = math.floor(self.posicao_mm)
        self._perda = perda_de_transicoes
        self._sorteio = random.Random(semente)
        self.transicoes_perdidas = 0
        self._atualiza_saidas(inicial=True)

        self.porta_estado = FECHADA
        self.porta_comando = 0
        self._porta_desde = 0.0
        self.falha = 0
        self.sem_energia = False       # barramento em sobrecarga (predio.py)
        self.violacoes = []          # (instante, descricao)
        self.passageiros = 0

    # ----------------------------------------------------------- consultas
    @property
    def corrente_ma(self):
        dir1 = self.niveis[self.pinagem["DIR1"]]
        dir2 = self.niveis[self.pinagem["DIR2"]]
        if (dir1, dir2) in ((1, 0), (0, 1)):
            return CORRENTE_EM_REPOUSO_MA + CORRENTE_POR_PONTO_DE_DUTY_MA * self.duty
        return CORRENTE_EM_REPOUSO_MA

    def andar_mais_proximo(self):
        return min(range(len(self.andares_mm)),
                   key=lambda a: abs(self.posicao_mm - self.andares_mm[a]))

    def nivelado(self):
        andar = self.andar_mais_proximo()
        return abs(self.posicao_mm - self.andares_mm[andar]) <= TOLERANCIA_MM

    def parada(self):
        return abs(self.velocidade_mm_s) < 1.0

    # ------------------------------------------------------------ porta
    def comanda_porta(self, comando, agora):
        self.porta_comando = comando
        if comando == 1 and self.porta_estado in (FECHADA, FECHANDO, OBSTRUIDA):
            if not (self.nivelado() and self.parada()):
                self.falha |= FALHA_PORTA_FORA_DE_NIVEL
                self.violacoes.append(
                    (agora, "porta comandada a abrir fora do nivelamento "
                     "(%.1f mm do andar %d)" % (
                         self.posicao_mm - self.andares_mm[
                             self.andar_mais_proximo()],
                         self.andar_mais_proximo())))
                return
            self.porta_estado, self._porta_desde = ABRINDO, agora
        elif comando == 2 and self.porta_estado in (ABERTA, ABRINDO, OBSTRUIDA):
            if self.niveis[self.pinagem["CORTINA"]]:
                self.porta_estado, self._porta_desde = OBSTRUIDA, agora
            else:
                self.porta_estado, self._porta_desde = FECHANDO, agora

    def atualiza_porta(self, agora):
        """Devolve True quando a porta acabou de abrir."""
        decorrido = agora - self._porta_desde
        if self.porta_estado == ABRINDO and decorrido >= TEMPO_DE_ABERTURA_S:
            self.porta_estado = ABERTA
            return True
        if self.porta_estado == FECHANDO:
            if self.niveis[self.pinagem["CORTINA"]]:
                self.porta_estado = OBSTRUIDA
            elif decorrido >= TEMPO_DE_FECHAMENTO_S:
                self.porta_estado = FECHADA
        return False

    # ----------------------------------------------------------- fisica
    def passo(self, dt, agora):
        """Avanca a fisica e devolve as bordas a disparar, fora da trava."""
        with self.trava:
            dir1 = self.niveis[self.pinagem["DIR1"]]
            dir2 = self.niveis[self.pinagem["DIR2"]]
            duty = self.duty
        sentido = {(1, 0): 1.0, (0, 1): -1.0}.get((dir1, dir2), 0.0)
        if self.sem_energia:
            sentido = 0.0
        if sentido == 0.0 or (self.parada() and duty < DUTY_DE_ARRANQUE):
            alvo = 0.0
        else:
            alvo = sentido * VELOCIDADE_MAXIMA_MM_S * duty / 100.0
        tau = CONSTANTE_DE_INERCIA_S / 3.0 if (dir1, dir2) == (1, 1) \
            else CONSTANTE_DE_INERCIA_S
        self.velocidade_mm_s += (alvo - self.velocidade_mm_s) * min(1.0, dt / tau)
        if abs(self.velocidade_mm_s) < 0.5 and alvo == 0.0:
            self.velocidade_mm_s = 0.0

        nova = self.posicao_mm + self.velocidade_mm_s * dt
        if nova <= self.fundo_mm or nova >= self.topo_mm:
            nova = min(max(nova, self.fundo_mm), self.topo_mm)
            self.velocidade_mm_s = 0.0
            if not self.falha & FALHA_FIM_DE_CURSO:
                self.violacoes.append((agora, "fim de curso em %.0f mm" % nova))
            self.falha |= FALHA_FIM_DE_CURSO
        if self.velocidade_mm_s != 0.0 and self.porta_estado != FECHADA:
            if not self.falha & FALHA_ANDOU_DE_PORTA_ABERTA:
                self.violacoes.append((agora, "andou com a porta %d"
                                       % self.porta_estado))
            self.falha |= FALHA_ANDOU_DE_PORTA_ABERTA
        self.posicao_mm = nova
        return self._atualiza_saidas()

    def _atualiza_saidas(self, inicial=False):
        bordas = []
        alvo = math.floor(self.posicao_mm)
        a_pino, b_pino = self.pinagem["ENC_A"], self.pinagem["ENC_B"]
        while self._passo_inteiro != alvo:
            self._passo_inteiro += 1 if alvo > self._passo_inteiro else -1
            estado = _CICLO[self._passo_inteiro % 4]
            a, b = (estado >> 1) & 1, estado & 1
            if not inicial and self._perda and self._sorteio.random() < self._perda:
                # A transicao acontece no poco, mas a Raspberry nao a ve: o
                # nivel muda sem interrupcao, como uma borda perdida.
                self.transicoes_perdidas += 1
                with self.trava:
                    self.niveis[a_pino], self.niveis[b_pino] = a, b
                continue
            bordas += self._muda(a_pino, a, inicial) + self._muda(b_pino, b, inicial)
        dentro = any(abs(self.posicao_mm - centro) <= largura / 2.0
                     for centro, largura in zip(self.andares_mm, self.larguras_mm))
        bordas += self._muda(self.pinagem["SENSOR_ANDAR"], int(dentro), inicial)
        return bordas

    def _muda(self, pino, valor, inicial=False):
        with self.trava:
            if self.niveis.get(pino) == valor:
                return []
            self.niveis[pino] = valor
        return [] if inicial else [(pino, valor)]

    def dispara(self, bordas):
        for pino, valor in bordas:
            with self.trava:
                callback = self.interrupcoes.get(pino)
            if callback is not None:
                callback(pino, valor)

    # --------------------------------------------------------- cortina
    def aciona_cortina(self, obstruida, repiques=4):
        """Botao "Obstruir porta" do dashboard, com o repique do simulador."""
        pino = self.pinagem["CORTINA"]
        nivel = 1 if obstruida else 0
        for i in range(repiques):
            self.dispara(self._muda(pino, (i % 2) ^ nivel ^ 1))
        self.dispara(self._muda(pino, nivel))
