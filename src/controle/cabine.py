"""Logica de alto nivel da Cabine 1: malha de posicao e estado.

Controle desta entrega: proporcional com saturacao, rampa na partida e na
aproximacao (o PID completo e objeto da Entrega Final). A malha roda a 50 ms
numa thread propria, dormindo entre ciclos - nao ha busy-wait.

O feedback de posicao e o ENCODER. O Sensor de Andar apenas mede a bandeirola
e reporta, conforme a Secao 2.4 do enunciado.
"""
import threading
import time

from . import posicao
from .cortina import CortinaDeLuz
from .motor import DESCER, DUTY_MINIMO, Motor, SUBIR
from .sensor_andar import SensorAndar
from ..gpio import pinos
from ..gpio.encoder import EncoderQuadratura

PERIODO_MALHA_S = 0.050   # 50 ms, como o README geral sugere
GANHO_P = 0.08            # % de duty por mm de erro
DUTY_MAXIMO = 85.0
DUTY_APROXIMACAO = 25.0   # teto de duty perto do alvo
DISTANCIA_APROXIMACAO = 250.0  # mm a partir dos quais a velocidade cai
# Margem antes de acusar fim de curso. Vale a propria tolerancia de
# nivelamento: parar exatamente no andar 2 significa ficar a +-10 mm de
# 6000 mm, e isso nao pode ser confundido com estouro de curso.
MARGEM_FIM_DE_CURSO = posicao.TOLERANCIA_MM


class Cabine:
    """Reune o motor, o encoder, a cortina e o sensor de andar."""

    def __init__(self, backend_gpio, posicao_inicial_mm=0.0):
        self._gpio = backend_gpio
        self.motor = Motor(backend_gpio)
        self.encoder = EncoderQuadratura(
            backend_gpio, pinos.ENC_A, pinos.ENC_B,
            contagem_inicial=posicao.mm_para_contagem(posicao_inicial_mm))
        self.sensor_andar = SensorAndar(backend_gpio, self.encoder)
        self.cortina = CortinaDeLuz(backend_gpio,
                                    captura=lambda: self.encoder.contagem)

        self._alvo_mm = None
        self._andar_alvo = None
        self._lock = threading.Lock()
        self._parar = threading.Event()
        self._chegou = threading.Event()
        self._chegou.set()
        self._manual = False

        self._thread = threading.Thread(target=self._laco_de_controle,
                                        daemon=True, name="malha-cabine")
        self._thread.start()

    # ------------------------------------------------------------------
    # Leitura de estado
    # ------------------------------------------------------------------
    @property
    def contagem(self):
        return self.encoder.contagem

    @property
    def posicao_mm(self):
        return posicao.contagem_para_mm(self.encoder.contagem)

    @property
    def andar_estimado(self):
        return posicao.andar_mais_proximo(self.posicao_mm)

    @property
    def nivelado(self):
        return posicao.nivelado(self.posicao_mm)

    @property
    def em_movimento(self):
        return not self._chegou.is_set()

    def estado(self):
        """Dicionario com tudo que o comando `estado` da CLI imprime."""
        mm = self.posicao_mm
        andar = self.andar_estimado
        return {
            "contagem": self.contagem,
            "posicao_mm": mm,
            "andar_estimado": andar,
            "erro_mm": posicao.erro_para_andar(mm, andar),
            "nivelado": posicao.nivelado(mm, andar),
            "direcao": self.motor.direcao,
            "duty": self.motor.duty,
            "cortina": "OBSTRUIDA" if self.cortina.obstruida else "livre",
            "obstrucoes": self.cortina.obstrucoes,
            "sensor_andar": ("DENTRO da bandeirola"
                             if self.sensor_andar.dentro_da_bandeirola
                             else "entre andares"),
            "bandeirolas_medidas": len(self.sensor_andar.medicoes),
            "transicoes_invalidas": self.encoder.transicoes_invalidas,
        }

    # ------------------------------------------------------------------
    # Comandos
    # ------------------------------------------------------------------
    def vai_para_andar(self, andar):
        if not posicao.andar_valido(andar):
            raise ValueError("andar fora da bancada: %r (validos: %s)"
                             % (andar, posicao.ANDARES))
        self.vai_para_mm(posicao.posicao_do_andar(andar), andar)

    def vai_para_mm(self, alvo_mm, andar=None):
        """Protecao de fim de curso: satura o alvo na faixa util da bancada."""
        alvo_mm = max(posicao.LIMITE_INFERIOR_MM,
                      min(posicao.LIMITE_SUPERIOR_MM, float(alvo_mm)))
        with self._lock:
            self._manual = False
            self._alvo_mm = alvo_mm
            self._andar_alvo = andar
            self._chegou.clear()
        print("MOVIMENTO: destino %s (%.0f mm), posicao atual %.0f mm"
              % ("andar %d" % andar if andar is not None else "%.0f mm" % alvo_mm,
                 alvo_mm, self.posicao_mm), flush=True)

    def aciona_manual(self, direcao, duty):
        """Acionamento direto do motor, sem malha fechada."""
        with self._lock:
            self._manual = True
            self._alvo_mm = None
            self._chegou.set()
        self.motor.define_direcao(direcao)
        aplicado = self.motor.aplica_duty(duty)
        return aplicado

    def espera_chegada(self, timeout=None):
        return self._chegou.wait(timeout)

    def parada_de_emergencia(self):
        with self._lock:
            self._manual = False
            self._alvo_mm = None
            self._chegou.set()
        self.motor.para_com_freio()

    # ------------------------------------------------------------------
    # Malha de controle
    # ------------------------------------------------------------------
    def _laco_de_controle(self):
        anterior = time.monotonic()
        while not self._parar.is_set():
            # Dorme entre ciclos: sem busy-wait.
            self._parar.wait(PERIODO_MALHA_S)
            agora = time.monotonic()
            dt = agora - anterior
            anterior = agora

            # Protecao de fim de curso: roda sempre, inclusive no
            # acionamento manual, que nao passa pela malha fechada.
            if self._supervisiona_fim_de_curso():
                continue

            with self._lock:
                alvo = self._alvo_mm
                andar = self._andar_alvo
                manual = self._manual
            if manual or alvo is None:
                continue

            self._passo_de_controle(alvo, andar, dt)

    def _supervisiona_fim_de_curso(self):
        """Corta o movimento se a cabine sair da faixa util da bancada.

        O comando `motor` aciona o motor sem malha fechada; sem esta
        supervisao ele levaria a cabine para fora dos 0..6000 mm. Devolve True
        quando teve de intervir.
        """
        if self.motor.duty <= 0.0:
            return False

        mm = self.posicao_mm
        direcao = self.motor.direcao
        estourou_em_cima = (direcao == SUBIR and
                            mm >= posicao.LIMITE_SUPERIOR_MM + MARGEM_FIM_DE_CURSO)
        estourou_embaixo = (direcao == DESCER and
                            mm <= posicao.LIMITE_INFERIOR_MM - MARGEM_FIM_DE_CURSO)
        if not (estourou_em_cima or estourou_embaixo):
            return False

        print("FIM DE CURSO: movimento abortado em %.1f mm (limite %s da "
              "bancada); PWM zerado e freio aplicado"
              % (mm, "superior" if estourou_em_cima else "inferior"),
              flush=True)
        self.parada_de_emergencia()
        return True

    def _passo_de_controle(self, alvo_mm, andar, dt):
        atual = self.posicao_mm
        erro = alvo_mm - atual

        if abs(erro) <= posicao.TOLERANCIA_MM:
            self._conclui(alvo_mm, andar, atual)
            return

        self.motor.define_direcao(SUBIR if erro > 0 else DESCER)

        # Proporcional com teto reduzido na aproximacao: a rampa de
        # desaceleracao sai da propria queda do erro, limitada pela rampa do
        # motor.
        duty_alvo = min(DUTY_MAXIMO, GANHO_P * abs(erro))
        if abs(erro) < DISTANCIA_APROXIMACAO:
            duty_alvo = min(duty_alvo, DUTY_APROXIMACAO)
        duty_alvo = max(duty_alvo, DUTY_MINIMO)
        self.motor.rampa_para(duty_alvo, dt)

    def _conclui(self, alvo_mm, andar, atual):
        self.motor.para_com_freio()
        with self._lock:
            self._alvo_mm = None
            self._andar_alvo = None
            self._chegou.set()
        if andar is not None:
            print("CHEGADA: andar %d | posicao %.1f mm | erro %+.1f mm | %s"
                  % (andar, atual, atual - alvo_mm,
                     "NIVELADO" if posicao.nivelado(atual, andar)
                     else "FORA DE NIVEL"), flush=True)
        else:
            print("CHEGADA: %.1f mm (erro %+.1f mm)"
                  % (atual, atual - alvo_mm), flush=True)

    # ------------------------------------------------------------------
    def finaliza(self):
        """Encerramento seguro: PWM em zero, direcao em freio, GPIO liberada."""
        self._parar.set()
        self._thread.join(timeout=1.0)
        self.motor.finaliza()
        self.cortina.finaliza()
        self.sensor_andar.finaliza()
        self._gpio.finaliza()
