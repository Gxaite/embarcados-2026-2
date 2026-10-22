"""Ciclo da porta: abrir, esperar o embarque, fechar (requisito 6.1.8).

A porta e um registrador MODBUS da cabine (porta_comando, porta_estado), e so
o Servidor Central fala MODBUS. Entao o comando sai daqui como pedido TCP e o
estado volta nas leituras de registradores que o central encaminha.

A cortina de luz, ao contrario, e GPIO da cabine e chega por interrupcao
(src/controle/cortina.py, com debounce). Enquanto ela estiver ativa o comando
de fechar nao e enviado; se ela ativar durante o fechamento, o fechamento e
dado como interrompido, e quando a obstrucao cessa o comando de fechar e
reenviado (Secao 3.4).
"""
import time

# porta_estado do MODBUS (Secao 5.2)
FECHADA, ABRINDO, ABERTA, FECHANDO, OBSTRUIDA = range(5)
NOMES = {FECHADA: "fechada", ABRINDO: "abrindo", ABERTA: "aberta",
         FECHANDO: "fechando", OBSTRUIDA: "obstruida"}

ESPERA_PARA_REPETIR_S = 3.0
# Uma leitura feita antes do comando pode chegar depois dele: o "obstruida"
# do MODBUS so vale passado este tempo do envio do fechar.
CARENCIA_DO_ESTADO_S = 1.0
ESPERA_APOS_LIBERAR_S = 0.5
INTERVALO_DE_LEITURA_S = 0.25

# Estados do ciclo, do ponto de vista da cabine.
OCIOSA, PEDINDO_ABRIR, ABERTA_ESPERANDO, PEDINDO_FECHAR, INIBIDA = (
    "ociosa", "abrindo", "aberta", "fechando", "fechamento inibido")


class CicloDaPorta:
    def __init__(self, pede_comando, pede_leitura, cortina_obstruida,
                 tempo_aberta_s=3.0, eco=None, relogio=time.monotonic):
        self._pede_comando = pede_comando
        self._pede_leitura = pede_leitura
        self._obstruida = cortina_obstruida
        self.tempo_aberta_s = tempo_aberta_s
        self._eco = eco or (lambda _texto: None)
        self._relogio = relogio

        self.fase = OCIOSA
        self.manter_aberta = False
        self.estado_modbus = None
        self._estado_desde = 0.0
        self._comando_em = 0.0
        self._aberta_em = 0.0
        self._liberada_em = 0.0
        self._ultima_leitura = 0.0
        self.abriu = False          # evento consumido por quem chama

    @property
    def fechada(self):
        """Fechada e confirmada pelo MODBUS: so assim a cabine pode andar."""
        return self.fase == OCIOSA and self.estado_modbus == FECHADA

    @property
    def ocupada(self):
        return self.fase != OCIOSA

    # ---------------------------------------------------------- entradas
    def registradores(self, porta_estado, instante):
        """Leitura do porta_estado vinda do central, com o instante local."""
        self.estado_modbus = porta_estado
        self._estado_desde = instante

    def ao_mudar_cortina(self, obstruida):
        """Interrupcao da cortina, ja com debounce."""
        agora = self._relogio()
        if obstruida:
            if self.fase == PEDINDO_FECHAR:
                self.fase = INIBIDA
                self._eco("PORTA: obstrucao durante o fechamento; fechamento inibido")
        else:
            self._liberada_em = agora

    # ---------------------------------------------------------- comandos
    def abre(self, manter=False):
        self.manter_aberta = manter
        if self.fase in (PEDINDO_ABRIR, ABERTA_ESPERANDO):
            return
        self.abriu = False
        self.fase = PEDINDO_ABRIR
        self._envia("abrir")

    def fecha(self):
        self.manter_aberta = False
        if self.fase == OCIOSA and self.estado_modbus == FECHADA:
            return
        if self._obstruida():
            self.fase = INIBIDA
            return
        self.fase = PEDINDO_FECHAR
        self._envia("fechar")

    def _envia(self, comando):
        self._comando_em = self._relogio()
        self._pede_comando(comando)
        self._pede_leitura()

    # ------------------------------------------------------------- ciclo
    def passo(self):
        agora = self._relogio()
        if self.fase != OCIOSA and agora - self._ultima_leitura >= INTERVALO_DE_LEITURA_S:
            self._ultima_leitura = agora
            self._pede_leitura()
        recente = self._estado_desde > self._comando_em
        if self.fase == PEDINDO_ABRIR:
            if recente and self.estado_modbus == ABERTA:
                self.fase = ABERTA_ESPERANDO
                self._aberta_em = agora
                self.abriu = True
            elif agora - self._comando_em > ESPERA_PARA_REPETIR_S:
                self._envia("abrir")
        elif self.fase == ABERTA_ESPERANDO:
            if not self.manter_aberta and agora - self._aberta_em >= self.tempo_aberta_s:
                self.fecha()
        elif self.fase == PEDINDO_FECHAR:
            obstruida_no_modbus = recente and self.estado_modbus == OBSTRUIDA and \
                agora - self._comando_em > CARENCIA_DO_ESTADO_S
            if self._obstruida() or obstruida_no_modbus:
                self.fase = INIBIDA
                self._eco("PORTA: obstruida; fechamento inibido ate liberar")
            elif recente and self.estado_modbus == FECHADA:
                self.fase = OCIOSA
            elif agora - self._comando_em > ESPERA_PARA_REPETIR_S:
                self._envia("fechar")
        elif self.fase == INIBIDA:
            if not self._obstruida() and \
                    agora - self._liberada_em >= ESPERA_APOS_LIBERAR_S:
                self._eco("PORTA: obstrucao cessou; fechamento reiniciado")
                self.fase = PEDINDO_FECHAR
                self._envia("fechar")
