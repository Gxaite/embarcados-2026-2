"""Parte 2 - wrapper MODBUS sobre os comandos da Parte 1.

Requisicao: [0x01][funcao][sub-codigo][carga][6 digitos da matricula][CRC]
com funcao 0x23 para solicitar e 0x16 para enviar, e o sub-codigo igual ao
comando da Parte 1 (0xA1..0xB3).

O enunciado fixa a requisicao byte a byte, mas da resposta so diz o valor que
volta. O formato do envelope em volta dele (endereco 0x00 ou 0x01, sub-codigo
ecoado ou nao) nao esta escrito em lugar nenhum, e errar isso na bancada custa
um horario reservado. Por isso a resposta e lida ate a linha silenciar e
interpretada pelo tamanho: o CRC confere o quadro inteiro, e cada tipo tem
tamanho conhecido, entao so um dos formatos candidatos fecha a conta.
"""
from . import carga
from .crc16 import anexa_crc, crc_valido
from .erros import (CrcInvalido, ErroComunicacao, ExcecaoModbus,
                    RespostaInvalida, SemResposta)
from .porta import hexa

ENDERECO_DIDATICO = 0x01
FUNCAO_SOLICITA = 0x23
FUNCAO_ENVIA = 0x16
BIT_DE_EXCECAO = 0x80
TIMEOUT_PADRAO_S = 0.5
TENTATIVAS_PADRAO = 3
DIGITOS_DA_MATRICULA = 6


class ModbusDidatico:
    NOME = "MODBUS"

    def __init__(self, porta, matricula, eco=print, endereco=ENDERECO_DIDATICO,
                 timeout_s=TIMEOUT_PADRAO_S, tentativas=TENTATIVAS_PADRAO):
        self._porta = porta
        self._matricula = bytes(matricula)
        self._eco = eco or (lambda _texto: None)
        self.endereco = endereco
        self.timeout_s = timeout_s
        self.tentativas = tentativas

    # --------------------------------------------- um metodo por comando
    def pede_int(self):
        return self._transacao(FUNCAO_SOLICITA, carga.PEDE_INT)

    def pede_float(self):
        return self._transacao(FUNCAO_SOLICITA, carga.PEDE_FLOAT)

    def pede_string(self):
        return self._transacao(FUNCAO_SOLICITA, carga.PEDE_STRING)

    def envia_int(self, valor):
        return self._transacao(FUNCAO_ENVIA, carga.ENVIA_INT,
                               carga.codifica_int(valor))

    def envia_float(self, valor):
        return self._transacao(FUNCAO_ENVIA, carga.ENVIA_FLOAT,
                               carga.codifica_float(valor))

    def envia_string(self, texto):
        return self._transacao(FUNCAO_ENVIA, carga.ENVIA_STRING,
                               carga.codifica_string(texto))

    # --------------------------------------------------------- utilitarios
    def monta_pacote(self, funcao, sub_codigo, dados=b""):
        corpo = bytes((self.endereco, funcao, sub_codigo)) + bytes(dados) \
            + self._matricula
        return anexa_crc(corpo)

    def envia_pacote(self, pacote):
        self._eco("  TX (%d B): %s" % (len(pacote), hexa(pacote)))
        self._porta.envia(pacote)

    def le_resposta(self):
        resposta = self._porta.le_ate_silencio(self.timeout_s)
        if not resposta:
            raise SemResposta("timeout de %d ms" % round(self.timeout_s * 1000))
        self._eco("  RX (%d B): %s" % (len(resposta), hexa(resposta)))
        return resposta

    def interpreta(self, resposta, funcao, sub_codigo):
        """Valida o quadro e devolve (valor, descricao dos campos)."""
        if len(resposta) < 5:
            raise RespostaInvalida("quadro curto demais: %d bytes" % len(resposta))
        if not crc_valido(resposta):
            raise CrcInvalido("CRC recebido %s nao confere" % hexa(resposta[-2:]))
        endereco, funcao_recebida = resposta[0], resposta[1]
        if endereco not in (0x00, self.endereco):
            raise RespostaInvalida("endereco 0x%02X na resposta" % endereco)
        if funcao_recebida == funcao | BIT_DE_EXCECAO:
            raise ExcecaoModbus(endereco, funcao, resposta[2])
        if funcao_recebida != funcao:
            raise RespostaInvalida("funcao 0x%02X na resposta, esperada 0x%02X"
                                   % (funcao_recebida, funcao))

        tipo = carga.TIPO_DA_RESPOSTA[sub_codigo]
        miolo = resposta[2:-2]
        for formato, dados in self._candidatos(miolo, sub_codigo):
            try:
                valor = carga.decodifica(tipo, dados)
            except RespostaInvalida:
                continue
            campos = ("endereco=0x%02X funcao=0x%02X %s| %s = %s | CRC=%s"
                      % (endereco, funcao_recebida, formato, tipo,
                         carga.formata(valor), hexa(resposta[-2:])))
            return valor, campos
        raise RespostaInvalida("carga de %d bytes nao corresponde a um %s"
                               % (len(miolo), tipo))

    def _candidatos(self, miolo, sub_codigo):
        ecoa = bool(miolo) and miolo[0] == sub_codigo
        com_matricula = miolo[-DIGITOS_DA_MATRICULA:] == self._matricula
        if ecoa:
            yield "sub=0x%02X " % sub_codigo, miolo[1:]
            if com_matricula:
                yield "sub=0x%02X (+matricula) " % sub_codigo, \
                    miolo[1:-DIGITOS_DA_MATRICULA]
        yield "", miolo
        if com_matricula:
            yield "(+matricula) ", miolo[:-DIGITOS_DA_MATRICULA]

    def _transacao(self, funcao, sub_codigo, dados=b""):
        self._eco("[%s] %s (funcao 0x%02X, sub 0x%02X)"
                  % (self.NOME, carga.NOMES[sub_codigo], funcao, sub_codigo))
        pacote = self.monta_pacote(funcao, sub_codigo, dados)
        ultimo_erro = None
        for tentativa in range(1, self.tentativas + 1):
            try:
                with self._porta.trava:
                    self._porta.descarta_entrada()
                    self.envia_pacote(pacote)
                    resposta = self.le_resposta()
                valor, campos = self.interpreta(resposta, funcao, sub_codigo)
            except ExcecaoModbus as erro:
                self._eco("  EXCECAO: %s" % erro)
                raise
            except ErroComunicacao as erro:
                ultimo_erro = erro
                self._eco("  tentativa %d/%d falhou: %s: %s"
                          % (tentativa, self.tentativas, type(erro).__name__, erro))
                continue
            self._eco("  campos: %s" % campos)
            return valor
        raise ultimo_erro
