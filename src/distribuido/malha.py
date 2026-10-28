"""Malha de posicao da cabine, um ciclo a cada 50 ms.

Quem chama o passo() e o laco da cabine, que dorme entre ciclos. A cada ciclo:

  1. le a posicao no encoder e estima a velocidade;
  2. supervisiona fim de curso e travamento (em qualquer fase);
  3. calcula o duty da fase atual;
  4. satura pela Cota (duty_maximo) e aplica a rampa de aceleracao.

Fases:

  LIVRE       freio, nada a fazer
  CONSTANTE   duty fixo num sentido, sem malha fechada: so a varredura de
              calibracao, que precisa de velocidade constante
  RASTREANDO  PID ate o destino
  ASSENTANDO  freio, esperando a cabine parar de verdade para medir o erro
  PULSO       renivelamento por pulsos curtos no duty de arranque
  CHEGOU      parada dentro da tolerancia

Por que existem ASSENTANDO e PULSO alem do PID: o motor nao arranca abaixo de
10% de duty (atrito estatico). Perto do destino o PID pede menos que isso, e
com a cabine parada a resposta seria nenhuma enquanto o integral cresce - o
windup que a Secao 7.1 avisa. Nessa situacao o integral e congelado e o erro
residual e corrigido como nos elevadores reais: parar, medir e corrigir com
pulsos de um ou poucos ciclos, cada um seguido de nova medicao.
"""
import time

from ..gpio import pinos

PERIODO_S = 0.050

TOLERANCIA_MM = 10.0            # Secao 3.2
# A malha mira mais perto que a tolerancia para que a deriva ate a proxima
# bandeirola e o arredondamento nao a levem para fora.
TOLERANCIA_DE_CHEGADA_MM = 6.0
# Freia a menos disto do alvo e devagar: o resto a cabine percorre parando.
# Com 3 mm e 40 mm/s a aproximacao exponencial do PID gastava 1,7 s a mais por
# parada, e ainda dava um pulso de renivelamento (simulador, Kd 8).
PARADA_FINA_MM = 6.0
VELOCIDADE_DE_PARADA_MM_S = 60.0
VELOCIDADE_PARADA_MM_S = 4.0

DUTY_DE_ARRANQUE = 12.0         # 10% do enunciado com folga
# Acima disto o Python nao acompanha as bordas do encoder: a 60% a contagem
# ficou 19 mm atras em 3000 mm na rasp34 (src/gpio/encoder.py), e na rasp52,
# a ~60% com o teto pela corrente medida, a deriva levou a porta fora do nivel.
# Ate 56% a placa chegou com +-3 mm em todas as viagens de 28/10/2026.
DUTY_MAXIMO_DO_ENCODER = 55.0
RAMPA_POR_S = 150.0             # pontos de duty por segundo na aceleracao
ERRO_PARA_ARRANQUE_MM = 30.0    # abaixo disto, parado, corrige por pulsos

TEMPO_DE_ASSENTAMENTO_S = 0.30
CICLOS_DE_PULSO_POR_MM = 0.25
CICLOS_DE_PULSO_MAXIMO = 8
MAXIMO_DE_PULSOS = 15

TEMPO_DE_TRAVAMENTO_S = 2.5
MOVIMENTO_DE_TRAVAMENTO_MM = 3.0

LIVRE, CONSTANTE, RASTREANDO, ASSENTANDO, PULSO, CHEGOU = (
    "livre", "constante", "rastreando", "assentando", "pulso", "chegou")


class MalhaDePosicao:
    def __init__(self, motor, encoder, pid, eco=None, ao_registrar=None,
                 relogio=time.monotonic):
        self._motor = motor
        self._encoder = encoder
        self.pid = pid
        self._eco = eco or (lambda _texto: None)
        self._ao_registrar = ao_registrar
        self._relogio = relogio

        self.fase = LIVRE
        self.alvo_mm = None
        self.duty_maximo = 0.0
        self.limites_mm = None          # (inferior, superior) depois da calibracao
        self.comando = 0.0              # duty com sinal: + sobe, - desce
        self.velocidade_mm_s = 0.0
        self.falha = None
        self.fora_de_nivel = False
        self.pulsos = 0

        self._posicao_anterior = None
        self._sentido_constante = 0
        self._duty_constante = 0.0
        self._assentou_em = None
        self._assentou_desde = None
        self._ciclos_de_pulso = 0
        self._travado_desde = None
        self._travado_em = None
        self._inicio_da_viagem = None

    # ------------------------------------------------------------- consultas
    @property
    def posicao_mm(self):
        return float(self._encoder.contagem)

    @property
    def parada(self):
        return abs(self.velocidade_mm_s) < VELOCIDADE_PARADA_MM_S

    @property
    def sentido(self):
        if self.velocidade_mm_s > VELOCIDADE_PARADA_MM_S:
            return 1
        if self.velocidade_mm_s < -VELOCIDADE_PARADA_MM_S:
            return -1
        return 0

    @property
    def ocupada(self):
        return self.fase in (CONSTANTE, RASTREANDO, ASSENTANDO, PULSO)

    # ------------------------------------------------------------- comandos
    def vai_para(self, mm):
        """Novo destino. No meio de uma viagem so troca a referencia."""
        if self.limites_mm is not None:
            inferior, superior = self.limites_mm
            if not inferior <= mm <= superior:
                raise ValueError("destino %.0f mm fora do poco (%.0f..%.0f)"
                                 % (mm, inferior, superior))
        em_viagem = self.fase == RASTREANDO
        self.alvo_mm = float(mm)
        self.falha = None
        self.fora_de_nivel = False
        self.pulsos = 0
        if not em_viagem:
            self.pid.reinicia()
            self._inicio_da_viagem = self._relogio()
            self._travado_desde = None
        self.fase = RASTREANDO

    def anda(self, sentido, duty):
        """Velocidade constante, sem malha fechada (varredura de calibracao)."""
        self.alvo_mm = None
        self.falha = None
        self._sentido_constante = 1 if sentido > 0 else -1
        self._duty_constante = float(duty)
        self._travado_desde = None
        self.fase = CONSTANTE

    def para(self):
        self.alvo_mm = None
        self.fase = LIVRE
        self._freia()

    def limita(self, duty_maximo):
        """Novo teto de duty aplicado na hora, sem esperar o ciclo: uma Cota
        reduzida vale a partir do recebimento."""
        self.duty_maximo = duty_maximo
        if abs(self.comando) > duty_maximo:
            self._aplica(self.comando, None)

    def reancorou(self, delta_mm):
        """A contagem foi corrigida por delta sem a cabine se mover."""
        self.pid.desloca_medida(delta_mm)
        if self._posicao_anterior is not None:
            self._posicao_anterior += delta_mm
        if self._assentou_em is not None:
            self._assentou_em += delta_mm
        if self._travado_em is not None:
            self._travado_em += delta_mm

    # ---------------------------------------------------------------- ciclo
    def passo(self, dt=PERIODO_S):
        posicao = self.posicao_mm
        if self._posicao_anterior is not None and dt > 0:
            instantanea = (posicao - self._posicao_anterior) / dt
            self.velocidade_mm_s = 0.5 * self.velocidade_mm_s + 0.5 * instantanea
        self._posicao_anterior = posicao

        if self._supervisiona_fim_de_curso(posicao) \
                or self._supervisiona_travamento(posicao):
            return

        if self.fase == CONSTANTE:
            self._aplica(self._sentido_constante * self._duty_constante, dt)
        elif self.fase == RASTREANDO:
            self._rastreia(posicao, dt)
        elif self.fase == ASSENTANDO:
            self._assenta(posicao)
        elif self.fase == PULSO:
            self._pulsa(posicao)
        else:
            self._freia()

    def _rastreia(self, posicao, dt):
        erro = self.alvo_mm - posicao
        if abs(erro) <= PARADA_FINA_MM and \
                abs(self.velocidade_mm_s) < VELOCIDADE_DE_PARADA_MM_S:
            self._comeca_assentamento(posicao)
            return
        parada = self.parada and abs(self.comando) < DUTY_DE_ARRANQUE
        # Parado e abaixo do arranque, o integral nao acumula: a cabine nao
        # responde e ele so cresceria (windup por atrito estatico).
        saida = self.pid.calcula(self.alvo_mm, posicao, self.duty_maximo,
                                 integra=not parada)
        if parada and abs(saida) < DUTY_DE_ARRANQUE:
            if abs(erro) <= ERRO_PARA_ARRANQUE_MM:
                self._comeca_assentamento(posicao)
                return
            saida = DUTY_DE_ARRANQUE if erro > 0 else -DUTY_DE_ARRANQUE
        self._aplica(saida, dt)
        self._registra(posicao, erro)

    def _comeca_assentamento(self, posicao):
        self._freia()
        self.fase = ASSENTANDO
        self._assentou_em = posicao
        self._assentou_desde = self._relogio()

    def _assenta(self, posicao):
        self._freia()
        agora = self._relogio()
        if abs(posicao - self._assentou_em) >= 1.0:
            self._assentou_em = posicao
            self._assentou_desde = agora
            return
        if agora - self._assentou_desde < TEMPO_DE_ASSENTAMENTO_S:
            return
        erro = self.alvo_mm - posicao
        if abs(erro) <= TOLERANCIA_DE_CHEGADA_MM or self.pulsos >= MAXIMO_DE_PULSOS:
            self.fora_de_nivel = abs(erro) > TOLERANCIA_MM
            self.fase = CHEGOU
            self._registra(posicao, erro)
            duracao = agora - (self._inicio_da_viagem or agora)
            self._eco("CHEGADA em %.0f mm (alvo %.0f, erro %+.1f mm, %d pulso(s), "
                      "%.1f s)%s" % (posicao, self.alvo_mm, -erro, self.pulsos,
                                     duracao, "  *** FORA DA TOLERANCIA ***"
                                     if self.fora_de_nivel else ""))
            return
        self.pulsos += 1
        self._ciclos_de_pulso = max(1, min(CICLOS_DE_PULSO_MAXIMO,
                                           int(abs(erro) * CICLOS_DE_PULSO_POR_MM)))
        self.fase = PULSO

    def _pulsa(self, posicao):
        if self._ciclos_de_pulso <= 0:
            self._comeca_assentamento(posicao)
            return
        erro = self.alvo_mm - posicao
        duty = min(DUTY_DE_ARRANQUE, self.duty_maximo)
        # O pulso dura poucos ciclos e precisa vencer o atrito ja no primeiro:
        # pela rampa ele nunca chegaria ao arranque.
        self._aplica(duty if erro > 0 else -duty, None)
        self._ciclos_de_pulso -= 1

    # --------------------------------------------------------- supervisao
    def _supervisiona_fim_de_curso(self, posicao):
        if self.limites_mm is None:
            return False
        inferior, superior = self.limites_mm
        if (self.comando > 0 and posicao >= superior) or \
                (self.comando < 0 and posicao <= inferior):
            self._abandona("FIM DE CURSO em %.0f mm (limites %.0f..%.0f)"
                           % (posicao, inferior, superior))
            return True
        return False

    def _supervisiona_travamento(self, posicao):
        if self.fase not in (CONSTANTE, RASTREANDO) or \
                abs(self.comando) < DUTY_DE_ARRANQUE:
            self._travado_desde = None
            return False
        agora = self._relogio()
        if self._travado_desde is None or \
                abs(posicao - self._travado_em) >= MOVIMENTO_DE_TRAVAMENTO_MM:
            self._travado_desde, self._travado_em = agora, posicao
            return False
        if agora - self._travado_desde >= TEMPO_DE_TRAVAMENTO_S:
            self._abandona("TRAVAMENTO: %.1f s a %.0f%% de duty sem sair de %.0f mm"
                           % (agora - self._travado_desde, abs(self.comando),
                              posicao))
            return True
        return False

    def _abandona(self, motivo):
        self.falha = motivo
        self.alvo_mm = None
        self.fase = LIVRE
        self._freia()
        self._eco(motivo)

    # ------------------------------------------------------------ atuacao
    def _aplica(self, saida, dt):
        """Satura pela Cota e limita a subida do duty pela rampa.

        dt None aplica sem rampa (pulso de renivelamento). Reduzir o duty
        nunca espera a rampa: frear e cumprir uma Cota menor sao imediatos.
        """
        modulo = min(abs(saida), self.duty_maximo, DUTY_MAXIMO_DO_ENCODER)
        mesmo_sentido = (saida > 0) == (self.comando > 0) and self.comando != 0
        atual = abs(self.comando) if mesmo_sentido else 0.0
        if dt is not None and modulo > atual:
            modulo = min(modulo, atual + RAMPA_POR_S * dt)
        if modulo <= 0.0:
            self._freia()
            return
        self.comando = modulo if saida > 0 else -modulo
        self._motor.define_direcao(pinos.SUBIR if saida > 0 else pinos.DESCER)
        self._motor.define_duty_imediato(modulo)

    def _freia(self):
        self.comando = 0.0
        self._motor.para()

    def _registra(self, posicao, erro):
        if self._ao_registrar is None:
            return
        p, i, d = self.pid.ultimos_termos
        self._ao_registrar(self._relogio(), self.alvo_mm, posicao, erro, p, i, d,
                           self.comando, self.duty_maximo, self.fase)
