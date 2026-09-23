"""Malha de posicao da Cabine 1.

A malha roda a 50 ms dormindo em Event.wait() - nao ha laco girando em CPU
(requisito 9). Cada ciclo faz, nesta ordem:

  1. supervisiona o fim de curso (SEMPRE, inclusive em acionamento manual);
  2. calcula o alvo de duty, se houver viagem em andamento;
  3. anda um passo da rampa do motor.

A supervisao de fim de curso vir primeiro e vir em todo ciclo e deliberado: o
comando de acionamento direto NAO passa pela malha fechada, e sem isso ele
levaria a cabine para fora dos 0..6000 mm. E o requisito 5 da Secao 3.
"""
import threading
import time

from ..gpio import pinos
from ..gpio.encoder import EncoderQuadratura
from ..gpio.entradas import EntradaPolling
from . import posicao
from .cortina import Cortina
from . import motor as motor_mod
from .motor import Motor
from .sensor_andar import SensorAndar

PERIODO_DA_MALHA_S = 0.050
GANHO_P = 0.06                 # duty por mm de erro
DUTY_MAXIMO = 60.0
DUTY_DE_APROXIMACAO = 15.0     # teto nos ultimos milimetros
DISTANCIA_DE_APROXIMACAO_MM = 300.0
# Margem do fim de curso no acionamento MANUAL.
#
# Medido na rasp42: comandando "motor subir" ate o limite, a cabine parou em
# 6010 mm com margem de 5 mm - a inercia levou 15 mm alem do ponto de corte.
# No acionamento direto nao ha rampa de aproximacao freando antes, entao a
# margem precisa absorver a frenagem inteira sozinha.
MARGEM_DE_FIM_DE_CURSO_MM = 25.0

# Travamento: motor comandado, cabine sem sair do lugar.
#
# Acontece quando o destino e inalcancavel - tipicamente porque a contagem
# derivou e aponta para fora do poco fisico. A cabine encosta no batente, o
# encoder para de contar, e sem isto a malha comandaria motor indefinidamente
# contra o fim de curso mecanico. Numa bancada compartilhada isso e o tipo de
# coisa que estraga o equipamento de outra pessoa.
TEMPO_DE_TRAVAMENTO_S = 6.0
MOVIMENTO_MINIMO_MM = 3.0

# A tolerancia exigida e +-10 mm; a malha mira mais perto de proposito, para
# que a folga absorva a inercia da frenagem em vez de ser gasta antes dela.
PARADA_FINA_MM = 3.0

# Renivelamento.
#
# O motor nao arranca abaixo de ~10% de duty, entao existe uma velocidade
# minima e, com ela, uma distancia minima de frenagem. Medido na rasp42: o
# `andar 2` freou no ponto certo e a inercia levou ate 6016 mm - 16 mm alem do
# nominal, fora dos +-10 mm exigidos.
#
# Quando a distancia de frenagem e maior que a tolerancia, NAO existe ganho que
# acerte em uma tacada so. A saida e a mesma dos elevadores de verdade: parar,
# deixar assentar, medir de novo e corrigir com pulsos curtos. Cada pulso dura
# um ciclo da malha, o que limita o quanto a cabine anda antes da proxima
# medicao e faz a correcao convergir em vez de oscilar.
TEMPO_DE_ASSENTAMENTO_S = 0.4
# Duracao do pulso, em ciclos da malha, por milimetro que falta. Um pulso fixo
# nao serve: curto demais nao sai de erros grandes, longo demais passa do ponto
# nos pequenos. Como cada pulso e seguido de nova medicao, errar a duracao so
# custa mais uma iteracao - o processo converge como uma bisseccao.
CICLOS_DE_PULSO_POR_MM = 0.25
CICLOS_DE_PULSO_MAXIMO = 10
MOVIMENTO_DE_ASSENTAMENTO_MM = 1.0
MAXIMO_DE_RENIVELAMENTOS = 12


class Cabine:
    def __init__(self, backend, posicao_inicial_mm=0.0):
        self._backend = backend
        self.encoder = EncoderQuadratura(backend)
        self.encoder.zera(posicao.contagem_de_mm(posicao_inicial_mm))

        self.motor = Motor(backend)
        self.cortina = Cortina(backend)
        self.sensor_andar = SensorAndar(backend, self.encoder)

        # O mesmo sinal lido pelos DOIS caminhos, e cada um serve a uma coisa:
        # a interrupcao acima enxerga as bordas (para medir a bandeirola), e o
        # polling abaixo da o nivel atual a cada ciclo da malha, que e o que o
        # comando "estado" e o relatorio de chegada precisam.
        self.sensor_andar_polling = EntradaPolling(backend, pinos.SENSOR_ANDAR)

        self._destino_mm = None
        self._parado_desde = None
        self._posicao_de_referencia = None
        self._assentando = False
        self._assentou_em = None
        self._assentou_desde = None
        self._renivelamentos = 0
        self._ciclos_de_pulso = None
        self._encerrar = threading.Event()
        self._acordar = threading.Event()
        self._malha = threading.Thread(target=self._laco, daemon=True)
        self._malha.start()

    # ------------------------------------------------------------- consultas
    @property
    def posicao_mm(self):
        return posicao.mm_de_contagem(self.encoder.contagem)

    @property
    def em_viagem(self):
        return self._destino_mm is not None

    def estado(self):
        mm = self.posicao_mm
        andar = posicao.andar_estimado(mm)
        return {
            "contagem": self.encoder.contagem,
            "posicao_mm": mm,
            "andar_estimado": andar,
            "nivelado": andar is not None and posicao.nivelado(mm, andar),
            "direcao": self.motor.direcao,
            "duty": self.motor.duty,
            "cortina_obstruida": self.cortina.obstruida,
            "cortina_eventos": self.cortina.obstrucoes + self.cortina.liberacoes,
            "cortina_bordas_cruas": self.cortina.bordas_cruas,
            "sensor_andar": self.sensor_andar_polling.le(),
            "destino_mm": self._destino_mm,
            "transicoes_invalidas": self.encoder.transicoes_invalidas,
        }

    # ------------------------------------------------------------- comandos
    def vai_para_andar(self, andar):
        self.vai_para_mm(posicao.mm_do_andar(andar))

    def vai_para_mm(self, mm):
        if not posicao.dentro_do_poco(mm):
            raise ValueError("destino fora do poco: %.1f mm (faixa: %d..%d)"
                             % (mm, posicao.FUNDO_MM, posicao.TOPO_MM))
        self._destino_mm = float(mm)
        self._parado_desde = None
        self._posicao_de_referencia = None
        self._assentando = False
        self._renivelamentos = 0
        self._ciclos_de_pulso = None
        self._acordar.set()

    def aciona_direto(self, direcao, duty):
        self._destino_mm = None       # sai da malha fechada
        self.motor.aciona_direto(direcao, duty)

    def para(self):
        self._destino_mm = None
        self.motor.para()

    def zera(self, mm=0.0):
        self.encoder.zera(posicao.contagem_de_mm(mm))

    def ancora(self):
        """Corrige a contagem usando a ultima bandeirola medida.

        A contagem do encoder e RELATIVA: ela conta deslocamento desde onde foi
        zerada, e nao sabe onde a cabine esta de fato. Ela deriva por duas
        razoes - bordas perdidas por ruido, e o "Resetar bancada" do widget,
        que muda o zero do simulador sem avisar a Raspberry.

        As bandeirolas, ao contrario, estao em posicoes ABSOLUTAS conhecidas
        (0, 3000 e 6000 mm). Uma travessia completa mede o centro de uma delas,
        e a diferenca entre esse centro e o nominal do andar e exatamente o
        quanto a contagem derivou.

        Nesta entrega isso e uma correcao explicita, pedida pelo operador: o
        enunciado diz que quem fecha a malha e o encoder, e o Sensor de Andar
        serve para CONFERIR o contador contra uma referencia absoluta. Na
        Entrega Final a reancoragem passa a ser automatica a cada passagem.
        """
        if not self.sensor_andar.medicoes:
            raise ValueError("nenhuma bandeirola medida ainda - faca uma "
                             "travessia completa antes")
        medicao = self.sensor_andar.medicoes[-1]
        if medicao.andar is None:
            raise ValueError("a ultima medicao nao corresponde a nenhum andar")
        correcao = posicao.mm_do_andar(medicao.andar) - medicao.centro_mm
        self.encoder.zera(posicao.contagem_de_mm(self.posicao_mm + correcao))
        return medicao, correcao

    # ----------------------------------------------------------------- malha
    def _laco(self):
        while not self._encerrar.wait(PERIODO_DA_MALHA_S):
            try:
                self._ciclo(PERIODO_DA_MALHA_S)
            except Exception as erro:            # a malha nao pode morrer
                print("ERRO na malha de controle: %r" % (erro,), flush=True)

    def _ciclo(self, dt):
        self._supervisiona_fim_de_curso()
        if self._destino_mm is not None:
            self._supervisiona_travamento()
        if self._destino_mm is not None:
            self._passo_de_controle()
        self.motor.passo(dt)

    def _supervisiona_travamento(self):
        """Aborta se o motor esta comandado e a cabine nao anda.

        Nao vale durante assentamento e renivelamento: ali a cabine fica parada
        ou anda pouquissimo DE PROPOSITO, e o pulso zera o duty a cada ciclo.
        """
        if self._assentando or self._renivelamentos:
            self._parado_desde = None
            self._posicao_de_referencia = None
            return
        if self.motor.duty <= 0.0:
            # Os dois andam juntos: manter a referencia sem o instante faria a
            # conta do tempo cair sobre um None no ciclo seguinte.
            self._parado_desde = None
            self._posicao_de_referencia = None
            return
        agora = time.monotonic()
        mm = self.posicao_mm
        if self._posicao_de_referencia is None \
                or abs(mm - self._posicao_de_referencia) >= MOVIMENTO_MINIMO_MM:
            self._posicao_de_referencia = mm
            self._parado_desde = agora
            return
        if agora - self._parado_desde >= TEMPO_DE_TRAVAMENTO_S:
            self._aborta("TRAVAMENTO: %.1f s de motor a %.0f%% sem a cabine "
                         "sair de %.0f mm. Destino provavelmente inalcancavel "
                         "- a contagem pode ter derivado (use 'ancora')"
                         % (agora - self._parado_desde, self.motor.duty, mm))

    def _supervisiona_fim_de_curso(self):
        """Roda em TODO ciclo, inclusive sem viagem em andamento.

        A margem so vale no acionamento manual. Em malha fechada o destino ja
        foi validado dentro do poco e o controle proporcional freia sozinho na
        aproximacao - aplicar a margem ali cortaria a viagem antes de chegar
        aos andares extremos, que estao exatamente em 0 e 6000 mm.
        """
        mm = self.posicao_mm
        margem = 0.0 if self._destino_mm is not None else MARGEM_DE_FIM_DE_CURSO_MM
        subindo = self.motor.direcao == pinos.SUBIR
        descendo = self.motor.direcao == pinos.DESCER
        if subindo and mm >= posicao.TOPO_MM - margem:
            self._aborta("FIM DE CURSO: movimento interrompido no topo do poco "
                         "(%d mm)" % posicao.TOPO_MM)
        elif descendo and mm <= posicao.FUNDO_MM + margem:
            self._aborta("FIM DE CURSO: movimento interrompido no fundo do poco "
                         "(%d mm)" % posicao.FUNDO_MM)

    def _aborta(self, motivo):
        self._destino_mm = None
        self._parado_desde = None
        self._posicao_de_referencia = None
        self.motor.para()
        print(motivo, flush=True)

    def _passo_de_controle(self):
        mm = self.posicao_mm

        if self._assentando:
            self._passo_de_assentamento(mm)
            return

        erro = self._destino_mm - mm

        if abs(erro) <= PARADA_FINA_MM:
            # Freia e para de decidir: a inercia ainda vai levar a cabine mais
            # um tanto, e so depois que ela assentar e que da para saber se o
            # nivelamento ficou dentro da tolerancia.
            self.motor.para()
            self._assentando = True
            self._assentou_em = mm
            self._assentou_desde = time.monotonic()
            return

        self.motor.define_direcao(pinos.SUBIR if erro > 0 else pinos.DESCER)

        if self._renivelamentos:
            # Renivelando por pulsos: um ciclo de motor no duty minimo, freio, e
            # volta a assentar para medir de novo. Manter o motor ligado traria
            # de volta o problema que estamos corrigindo - a inercia passaria do
            # ponto outra vez. O pulso limita o quanto a cabine anda entre duas
            # medicoes, e por isso a correcao converge em vez de oscilar.
            if self._ciclos_de_pulso is None:
                self._ciclos_de_pulso = max(1, min(
                    CICLOS_DE_PULSO_MAXIMO,
                    int(abs(erro) * CICLOS_DE_PULSO_POR_MM)))
            if self._ciclos_de_pulso > 0:
                self.motor.define_duty_imediato(
                    motor_mod.DUTY_MINIMO_DE_MOVIMENTO)
                self._ciclos_de_pulso -= 1
                return
            self.motor.para()
            self._ciclos_de_pulso = None
            self._assentando = True
            self._assentou_em = mm
            self._assentou_desde = time.monotonic()
            return

        teto = DUTY_MAXIMO
        if abs(erro) < DISTANCIA_DE_APROXIMACAO_MM:
            teto = DUTY_DE_APROXIMACAO
        self.motor.define_alvo_de_duty(min(teto, GANHO_P * abs(erro)))

    def _passo_de_assentamento(self, mm):
        """Espera a cabine parar de verdade, mede, e renivela se precisar."""
        agora = time.monotonic()
        if abs(mm - self._assentou_em) >= MOVIMENTO_DE_ASSENTAMENTO_MM:
            self._assentou_em = mm
            self._assentou_desde = agora
            return
        if agora - self._assentou_desde < TEMPO_DE_ASSENTAMENTO_S:
            return

        destino = self._destino_mm
        erro = destino - mm
        dentro = abs(erro) <= posicao.TOLERANCIA_MM

        if dentro or self._renivelamentos >= MAXIMO_DE_RENIVELAMENTOS:
            self._destino_mm = None
            self._assentando = False
            self._ciclos_de_pulso = None
            andar = posicao.andar_estimado(mm)
            aviso = "" if dentro else "  *** FORA DA TOLERANCIA DE +-%d mm ***" \
                % posicao.TOLERANCIA_MM
            print("CHEGADA: %.0f mm (destino %.0f mm, erro %+.0f mm, andar %s, "
                  "%d renivelamento(s))%s"
                  % (mm, destino, mm - destino,
                     "n/d" if andar is None else andar,
                     self._renivelamentos, aviso), flush=True)
            self._renivelamentos = 0
            return

        self._renivelamentos += 1
        self._assentando = False
        self._ciclos_de_pulso = None
        print("RENIVELANDO (%d/%d): parou em %.0f mm, faltam %+.0f mm"
              % (self._renivelamentos, MAXIMO_DE_RENIVELAMENTOS, mm, erro),
              flush=True)

    # ------------------------------------------------------------ encerramento
    def finaliza(self):
        """Encerramento seguro: PWM em zero, direcao em freio, GPIO liberada."""
        self._destino_mm = None
        self._encerrar.set()
        self._malha.join(timeout=1.0)
        self.motor.finaliza()
        self.cortina.finaliza()
        self.sensor_andar.finaliza()
        self.encoder.finaliza()
        # DIR1/DIR2 ficam de fora da limpeza, segurando o freio: liberados,
        # eles flutuam e a bancada le a combinacao solta como DESCER.
        self._backend.limpa(preserva=(pinos.DIR1, pinos.DIR2))
