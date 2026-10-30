"""Procedimento de calibracao das Posicoes de Andar (Secao 3.3).

  1. pede ao central o andar_atual (registrador 0) e usa 3000 x andar como
     estimativa grosseira da contagem - so para os numeros ficarem legiveis;
     nenhuma posicao sai dela;
  2. desce em velocidade constante ate sair da bandeirola do andar 0 pela
     borda de baixo, entrando no poco;
  3. VARREDURA DE SUBIDA: sobe atravessando as 6 bandeirolas, registrando a
     contagem nas duas bordas de cada uma, e para depois de sair da do andar 5;
  4. VARREDURA DE DESCIDA: o mesmo descendo, ate sair da do andar 0. Se a
     cabine partiu do andar 5, a descida do passo 2 ja atravessou as 6
     bandeirolas por inteiro e e usada como esta varredura;
  5. monta o MapaDeAndares: borda media dos dois sentidos, e o andar e a media
     das duas bordas.

As bordas chegam por interrupcao do Sensor de Andar (bandeirola.py), com a
contagem capturada na borda crua. A qual andar pertence cada bandeirola e
perguntado ao central na borda de entrada: o andar_atual e o andar mais
proximo, entao qualquer instante dentro da bandeirola serve, e a resposta pode
chegar depois da saida sem prejuizo. Nada aqui consulta o registrador
`nivelado`.
"""
import time

from . import mapa as mapa_mod
from .mapa import ANDARES, ErroDeCalibracao, MapaDeAndares

TEMPO_PARADA_ANTES_DE_INVERTER_S = 0.5
PRAZO_DA_RESPOSTA_DO_ANDAR_S = 3.0
# Travamento no meio do poco: espera e tenta de novo. Medido na bancada
# (22/10/2026, sem BMP280): com o barramento no piso de 3000 mA e as tres
# cabines calibrando juntas, elas paravam em posicoes aleatorias.
ESPERA_PARA_RETOMAR_S = 2.0
RETOMADAS_MAXIMAS = 8

INICIO, AO_FUNDO, SUBIDA, DESCIDA, CONCLUIDA, FALHOU = (
    "inicio", "descendo ao poco", "varredura de subida", "varredura de descida",
    "concluida", "falhou")


class _Travessia:
    def __init__(self, entrada, andar=None):
        self.entrada = entrada
        self.saida = None
        self.andar = andar

    @property
    def completa(self):
        return self.entrada is not None and self.saida is not None


class Calibracao:
    def __init__(self, malha, encoder, pede_andar_atual, duty, eco=None,
                 relogio=time.monotonic, dentro_da_bandeirola=lambda: False):
        self._malha = malha
        self._encoder = encoder
        self._pede_andar_atual = pede_andar_atual
        self.duty = duty
        self._eco = eco or (lambda _texto: None)
        self._relogio = relogio
        self._dentro = dentro_da_bandeirola
        self.fase = None
        self._conferindo_travamento = False
        self._retomar_em = None
        self.retomadas = 0
        self.mapa = None
        self.erro = None
        self._travessias = {SUBIDA: [], DESCIDA: [], AO_FUNDO: []}
        self._aberta = None
        self._andar_inicial = None
        # Andar em que a cabine estava quando a primeira calibracao comecou; uma
        # retomada depois de perder o central nao o troca pelo meio do poco.
        self.andar_de_partida = None
        self._parado_desde = None
        self._parando = False
        self._pedido_desde = None

    @property
    def ativa(self):
        return self.fase not in (None, CONCLUIDA, FALHOU)

    def inicia(self):
        self.fase = INICIO
        self.mapa = None
        self.erro = None
        self._travessias = {SUBIDA: [], DESCIDA: [], AO_FUNDO: []}
        self._aberta = None
        self._andar_inicial = None
        self._parando = False
        self._conferindo_travamento = False
        self._retomar_em = None
        self.retomadas = 0
        self._pedido_desde = self._relogio()
        self._pede_andar_atual(self._recebe_andar_inicial)
        self._eco("CALIBRACAO: iniciada, perguntando o andar atual ao central")

    # ------------------------------------------------------- interrupcao
    def ao_cruzar(self, borda):
        """Chamado pela interrupcao do Sensor de Andar."""
        fase = self.fase
        if fase not in (AO_FUNDO, SUBIDA, DESCIDA) or self._parando:
            return
        if borda.entrou:
            travessia = _Travessia(borda.contagem)
            self._aberta = travessia
            self._travessias[fase].append(travessia)
            self._pergunta_andar(travessia)
            return
        travessia = self._aberta
        self._aberta = None
        if travessia is None:
            # Saiu de uma bandeirola em que ja estava quando a fase comecou:
            # so serve para saber que andar acabou de ficar para tras.
            travessia = _Travessia(None, andar=self._andar_inicial)
            self._travessias[fase].append(travessia)
        travessia.saida = borda.contagem
        self._eco("  bandeirola %s: %s..%d mm (%s)" % (
            "?" if travessia.andar is None else travessia.andar,
            "-" if travessia.entrada is None else "%d" % travessia.entrada,
            travessia.saida, fase))

    def _pergunta_andar(self, travessia):
        def recebe(andar):
            if andar is not None:
                travessia.andar = andar
        self._pede_andar_atual(recebe)

    def _recebe_andar_inicial(self, andar):
        if self.fase != INICIO:
            return
        if andar is None:
            self._falha("o central nao respondeu o andar atual")
            return
        self._andar_inicial = andar
        if self.andar_de_partida is None:
            self.andar_de_partida = andar
        # So deixa a contagem legivel (perto de mm do poco); as posicoes saem
        # das bordas medidas.
        self._encoder.zera(int(mapa_mod.VAO_NOMINAL_MM * andar))
        self._malha.reancorou(0)
        self._eco("CALIBRACAO: cabine perto do andar %d; descendo ao poco" % andar)
        # Se a cabine ja esta dentro de uma bandeirola, a saida dela entra
        # como travessia sem borda de entrada, com o andar inicial (ao_cruzar).
        self.fase = AO_FUNDO
        self._malha.anda(-1, self.duty)

    # ------------------------------------------------------------- ciclo
    def passo(self):
        if self.fase == INICIO:
            if self._relogio() - self._pedido_desde > 2 * PRAZO_DA_RESPOSTA_DO_ANDAR_S:
                self._falha("sem resposta do andar atual")
            return
        if self.fase not in (AO_FUNDO, SUBIDA, DESCIDA):
            return
        if self._parando:
            self._espera_parar()
            return
        if self._conferindo_travamento:
            return
        if self._retomar_em is not None:
            if self._relogio() >= self._retomar_em:
                self._retomar_em = None
                self._malha.anda(self._sentido_da_fase(), self.duty)
            return
        if self._malha.falha:
            self._eco("CALIBRACAO: %s; conferindo o andar" % self._malha.falha)
            self._malha.falha = None
            self._conferindo_travamento = True
            self._pede_andar_atual(self._confere_travamento)
            return
        alvo = ANDARES[-1] if self.fase == SUBIDA else ANDARES[0]
        completas = [t for t in self._travessias[self.fase]
                     if t.saida is not None]
        if any(t.andar == alvo for t in completas):
            self._fim_da_fase()
        elif self.fase == SUBIDA and len([t for t in completas if t.completa]) \
                >= len(ANDARES):
            self._fim_da_fase()

    def _sentido_da_fase(self):
        return 1 if self.fase == SUBIDA else -1

    def _confere_travamento(self, andar):
        """Travou: e o fim do poco, ou parou no meio do caminho?

        So e fim se a cabine esta no andar extremo do sentido e ja fora da
        bandeirola dele (o poco tem 400 mm alem do andar, mais que meia
        bandeirola). Senao a varredura e retomada no mesmo sentido."""
        self._conferindo_travamento = False
        if self.fase not in (AO_FUNDO, SUBIDA, DESCIDA):
            return
        extremo = ANDARES[-1] if self.fase == SUBIDA else ANDARES[0]
        if andar == extremo and not self._dentro():
            self._eco("CALIBRACAO: fim do poco no andar %d" % andar)
            self._fim_da_fase()
            return
        self.retomadas += 1
        if self.retomadas > RETOMADAS_MAXIMAS:
            self._falha("%d travamentos no meio do poco; o motor nao vence a carga "
                        "com o duty de calibracao (barramento no piso?)" % self.retomadas)
            return
        self._eco("CALIBRACAO: travou perto do andar %s, longe do fim do poco; "
                  "retomando em %.0f s (%d/%d)" % (andar, ESPERA_PARA_RETOMAR_S,
                                                    self.retomadas, RETOMADAS_MAXIMAS))
        self._retomar_em = self._relogio() + ESPERA_PARA_RETOMAR_S

    def _fim_da_fase(self):
        self._malha.para()
        self._parando = True
        self._parado_desde = None

    def _espera_parar(self):
        if not self._malha.parada:
            self._parado_desde = None
            return
        agora = self._relogio()
        if self._parado_desde is None:
            self._parado_desde = agora
            return
        if agora - self._parado_desde < TEMPO_PARADA_ANTES_DE_INVERTER_S:
            return
        self._parando = False
        if self.fase == AO_FUNDO:
            self.fase = SUBIDA
            self._eco("CALIBRACAO: no poco; varredura de subida")
            self._malha.anda(+1, self.duty)
        elif self.fase == SUBIDA:
            if self._descida_ao_fundo_completa():
                # A descida ate o poco ja atravessou as 6 bandeirolas: ela e a
                # varredura de descida, e uma terceira passagem seria repeticao.
                self._travessias[DESCIDA] = self._travessias[AO_FUNDO]
                self._eco("CALIBRACAO: a descida inicial ja cobriu os 6 andares")
                self._conclui()
                return
            self.fase = DESCIDA
            self._eco("CALIBRACAO: no sobrecurso; varredura de descida")
            self._malha.anda(-1, self.duty)
        else:
            self._conclui()

    def _descida_ao_fundo_completa(self):
        andares = {t.andar for t in self._travessias[AO_FUNDO] if t.completa}
        return andares >= set(ANDARES)

    # -------------------------------------------------------------- mapa
    def _conclui(self):
        try:
            self.mapa = MapaDeAndares(self._bordas())
        except ErroDeCalibracao as erro:
            self._falha(str(erro))
            return
        self.fase = CONCLUIDA
        self._eco("CALIBRACAO concluida:")
        for andar in ANDARES:
            self._eco("  andar %d: %8.1f mm   bandeirola de %5.1f mm"
                      % (andar, self.mapa.posicao[andar], self.mapa.largura(andar)))

    def _bordas(self):
        subida = self._completas(SUBIDA, ordem=ANDARES)
        descida = self._completas(DESCIDA, ordem=tuple(reversed(ANDARES)))
        bordas = {}
        for andar in ANDARES:
            if andar not in subida or andar not in descida:
                raise ErroDeCalibracao("andar %d sem travessia completa nos dois "
                                       "sentidos" % andar)
            de_subida, de_descida = subida[andar], descida[andar]
            bordas[andar] = {
                "inferior_subindo": de_subida.entrada,
                "superior_subindo": de_subida.saida,
                "superior_descendo": de_descida.entrada,
                "inferior_descendo": de_descida.saida,
            }
        return bordas

    def _completas(self, fase, ordem):
        completas = [t for t in self._travessias[fase] if t.completa]
        if any(t.andar is None for t in completas):
            # O central nao respondeu algum andar: a ordem da varredura diz qual
            # e, desde que ela tenha atravessado as 6.
            if len(completas) != len(ordem):
                raise ErroDeCalibracao("%d travessias na %s sem o andar de todas"
                                       % (len(completas), fase))
            for travessia, andar in zip(completas, ordem):
                travessia.andar = andar
        return {t.andar: t for t in completas}

    def _falha(self, motivo):
        self._malha.para()
        self.fase = FALHOU
        self.erro = motivo
        self._eco("CALIBRACAO FALHOU: %s" % motivo)
