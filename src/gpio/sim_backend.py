"""Backend simulado: um modelo do poco do elevador em software.

Existe por um motivo pratico: a bancada e compartilhada, remota e usada em slot
cronometrado. Tempo de placa e o recurso escasso do projeto, e depurar logica de
controle la dentro e desperdicio. Este backend permite escrever e testar tudo
longe da placa, e chegar no slot so para medir.

O que ele reproduz, porque cada um destes ja causou um bug real:

- Atrito estatico: parado, o motor nao arranca abaixo de 10% de duty.
- Inercia: a velocidade persegue o alvo, nao salta para ele.
- Quadratura de verdade: cada milimetro gera uma transicao em ENC_A ou ENC_B,
  no ciclo de Gray correto, disparando interrupcao como na placa.
- Bandeirolas de LARGURAS DIFERENTES em cada andar, o que impede deduzir o
  centro a partir de uma borda so.
- Repique da cortina de luz em cada borda.

O que ele NAO reproduz, e por isso nao substitui a bancada: jitter de
escalonador, latencia real de interrupcao e o atrito de verdade do motor. Serve
para validar logica; sintonia de ganho so vale medida na placa.
"""
import threading
import time

from . import backend as bk
from . import pinos
from .backend import Backend, CanalPWM

# Ciclo de Gray da quadratura, um passo por milimetro.
_CICLO = [0b00, 0b01, 0b11, 0b10]

DUTY_DE_ARRANQUE = 10.0        # abaixo disso, parado nao sai do lugar
VELOCIDADE_MAXIMA_MM_S = 500.0  # a 100% de duty
CONSTANTE_DE_INERCIA_S = 0.25
PASSO_DA_FISICA_S = 0.002

POSICOES_DOS_ANDARES_MM = (0.0, 3000.0, 6000.0)
LARGURAS_DAS_BANDEIROLAS_MM = (120.0, 84.0, 150.0)

FUNDO_DO_POCO_MM = 0.0
TOPO_DO_POCO_MM = 6000.0


class _CanalPWMSimulado(CanalPWM):
    def __init__(self, dono, pino):
        self._dono = dono
        self._pino = pino

    def ajusta(self, duty_porcento):
        self._dono._duty = max(0.0, min(100.0, float(duty_porcento)))

    def finaliza(self):
        self._dono._duty = 0.0


class BackendSimulado(Backend):
    def __init__(self, posicao_inicial_mm=0.0):
        self._trava = threading.RLock()
        self._niveis = {}
        self._interrupcoes = {}

        self._duty = 0.0
        self.posicao_mm = float(posicao_inicial_mm)
        self.velocidade_mm_s = 0.0

        self._niveis[pinos.DIR1] = 0
        self._niveis[pinos.DIR2] = 0
        self._niveis[pinos.CORTINA] = 0
        self._atualiza_encoder(inicial=True)
        self._atualiza_sensor_de_andar()

        self._parar = threading.Event()
        self._fisica = threading.Thread(target=self._laco_da_fisica, daemon=True)
        self._fisica.start()

    # ---------------------------------------------------------------- Backend
    def configura_saida(self, pino, valor_inicial=0):
        with self._trava:
            self._niveis[pino] = 1 if valor_inicial else 0

    def configura_entrada(self, pino, pull=bk.SEM_PULL):
        with self._trava:
            self._niveis.setdefault(pino, 0)

    def escreve(self, pino, valor):
        with self._trava:
            self._niveis[pino] = 1 if valor else 0

    def le(self, pino):
        with self._trava:
            return self._niveis.get(pino, 0)

    def cria_pwm(self, pino, frequencia_hz):
        self.frequencia_pwm_hz = frequencia_hz
        return _CanalPWMSimulado(self, pino)

    def registra_interrupcao(self, pino, borda, callback):
        with self._trava:
            self._interrupcoes[pino] = (borda, callback)

    def remove_interrupcao(self, pino):
        with self._trava:
            self._interrupcoes.pop(pino, None)

    def limpa(self):
        self._parar.set()
        self._fisica.join(timeout=1.0)
        with self._trava:
            self._interrupcoes.clear()

    # ------------------------------------------------------------- estimulos
    def obstrui_porta(self, repiques=4):
        """Botao "Obstruir porta" do widget, com o repique que o simulador emite."""
        self._aciona_cortina(1, repiques)

    def libera_porta(self, repiques=4):
        self._aciona_cortina(0, repiques)

    def _aciona_cortina(self, nivel_final, repiques):
        for i in range(repiques):
            self._muda_pino(pinos.CORTINA, (i % 2) ^ nivel_final ^ 1)
            time.sleep(0.001)
        self._muda_pino(pinos.CORTINA, nivel_final)

    # ----------------------------------------------------------------- fisica
    def _laco_da_fisica(self):
        anterior = time.monotonic()
        while not self._parar.wait(PASSO_DA_FISICA_S):
            agora = time.monotonic()
            dt = agora - anterior
            anterior = agora
            self._passo(dt)

    def _passo(self, dt):
        with self._trava:
            dir1 = self._niveis.get(pinos.DIR1, 0)
            dir2 = self._niveis.get(pinos.DIR2, 0)
            duty = self._duty

        if (dir1, dir2) == (1, 0):
            sentido = +1.0
        elif (dir1, dir2) == (0, 1):
            sentido = -1.0
        else:
            sentido = 0.0      # livre ou freio: sem torque de tracao

        parado = abs(self.velocidade_mm_s) < 1.0
        if sentido == 0.0 or (parado and duty < DUTY_DE_ARRANQUE):
            alvo = 0.0
        else:
            alvo = sentido * VELOCIDADE_MAXIMA_MM_S * duty / 100.0

        # Freio para mais rapido que a inercia natural; livre desacelera solto.
        tau = CONSTANTE_DE_INERCIA_S / 3.0 if (dir1, dir2) == (1, 1) \
            else CONSTANTE_DE_INERCIA_S
        self.velocidade_mm_s += (alvo - self.velocidade_mm_s) * min(1.0, dt / tau)

        nova = self.posicao_mm + self.velocidade_mm_s * dt
        if nova <= FUNDO_DO_POCO_MM:
            nova, self.velocidade_mm_s = FUNDO_DO_POCO_MM, 0.0
        elif nova >= TOPO_DO_POCO_MM:
            nova, self.velocidade_mm_s = TOPO_DO_POCO_MM, 0.0
        self.posicao_mm = nova

        self._atualiza_encoder()
        self._atualiza_sensor_de_andar()

    def _atualiza_encoder(self, inicial=False):
        indice = int(self.posicao_mm) % 4
        estado = _CICLO[indice]
        a, b = (estado >> 1) & 1, estado & 1
        if inicial:
            self._niveis[pinos.ENC_A] = a
            self._niveis[pinos.ENC_B] = b
            return
        # Uma transicao por milimetro: so um dos canais muda por passo do ciclo.
        self._muda_pino(pinos.ENC_A, a)
        self._muda_pino(pinos.ENC_B, b)

    def _atualiza_sensor_de_andar(self):
        dentro = 0
        for centro, largura in zip(POSICOES_DOS_ANDARES_MM,
                                   LARGURAS_DAS_BANDEIROLAS_MM):
            if abs(self.posicao_mm - centro) <= largura / 2.0:
                dentro = 1
                break
        self._muda_pino(pinos.SENSOR_ANDAR, dentro)

    def _muda_pino(self, pino, valor):
        valor = 1 if valor else 0
        with self._trava:
            if self._niveis.get(pino) == valor:
                return
            self._niveis[pino] = valor
            registro = self._interrupcoes.get(pino)
        if registro is None:
            return
        borda, callback = registro
        if borda == bk.AMBAS \
                or (borda == bk.BORDA_SUBIDA and valor == 1) \
                or (borda == bk.BORDA_DESCIDA and valor == 0):
            callback(pino, valor)
