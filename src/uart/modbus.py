"""Parte 3 - cliente MODBUS RTU das funcoes 0x03 e 0x10.

Formato dos quadros (Secao 3.1 da Entrega 2):

  0x03 req:  [addr][0x03][reg LE][qtd LE][matricula 6][CRC]
  0x03 resp: [addr][0x03][byte_count][valor BE]...[CRC]
  0x10 req:  [addr][0x10][reg LE][qtd LE][byte_count][valor LE]...[matricula 6][CRC]
  0x10 resp: [addr][0x10][reg BE][qtd BE][CRC]
  excecao:   [addr][funcao | 0x80][codigo][CRC]

A ordem dos bytes nao e a do MODBUS padrao, e nem e a mesma nos dois
sentidos: a requisicao vai em little-endian e a resposta volta em big-endian.

Diferente da Parte 2, aqui o tamanho da resposta e deterministico, entao ela e
lida campo a campo: dois bytes dizem se e excecao ou resposta normal, e o
resto do tamanho sai dai. Nao ha espera por silencio na linha, o que importa
porque o Servidor Central faz varias destas transacoes por segundo.

Este modulo e o que a Entrega Final importa. Nao conhece cabine nem predio:
isso fica em elevadores.py.
"""
import struct

from .crc16 import anexa_crc, crc_valido
from .erros import (CrcInvalido, ErroComunicacao, ExcecaoModbus,
                    RespostaInvalida, SemResposta)
from .porta import SILENCIO_DE_FIM_DE_QUADRO_S, hexa

FUNCAO_LE = 0x03
FUNCAO_ESCREVE = 0x10
BIT_DE_EXCECAO = 0x80
# O enunciado pede timeout entre 200 e 500 ms e ate 3 tentativas.
TIMEOUT_PADRAO_S = 0.3
TENTATIVAS_PADRAO = 3
MAXIMO_DE_REGISTRADORES = 125     # limite do MODBUS para 0x03


def uint16_de(valor):
    """Valor de registrador para transmissao; negativos viram complemento de 2."""
    valor = int(valor)
    if not -0x8000 <= valor <= 0xFFFF:
        raise ValueError("valor fora de 16 bits: %d" % valor)
    return valor & 0xFFFF


def int16_de(valor):
    """Le um registrador de 16 bits como inteiro com sinal."""
    return valor - 0x10000 if valor & 0x8000 else valor


class ClienteModbus:
    def __init__(self, porta, matricula, eco=print, timeout_s=TIMEOUT_PADRAO_S,
                 tentativas=TENTATIVAS_PADRAO):
        self._porta = porta
        self._matricula = bytes(matricula)
        self.eco = eco
        self.timeout_s = timeout_s
        self.tentativas = tentativas
        self.transacoes = 0
        self.falhas = 0

    def _mostra(self, texto):
        if self.eco is not None:
            self.eco(texto)

    # ------------------------------------------------------------ funcoes
    def le_registradores(self, endereco, registrador, quantidade):
        """Funcao 0x03. Devolve a lista de valores, como uint16."""
        if not 1 <= quantidade <= MAXIMO_DE_REGISTRADORES:
            raise ValueError("quantidade invalida: %d" % quantidade)
        quadro = anexa_crc(
            bytes((endereco, FUNCAO_LE))
            + struct.pack("<HH", registrador, quantidade)
            + self._matricula)
        self._mostra("[MODBUS 0x03] le %d registrador(es) a partir de %d no "
                     "dispositivo 0x%02X" % (quantidade, registrador, endereco))
        resposta = self._transacao(quadro, endereco, FUNCAO_LE,
                                   lambda: self._le_resposta_leitura(quantidade))
        valores = list(struct.unpack(">%dH" % quantidade, resposta[3:-2]))
        self._mostra("  campos: endereco=0x%02X funcao=0x03 byte_count=%d "
                     "valores=%s CRC=%s" % (resposta[0], resposta[2], valores,
                                            hexa(resposta[-2:])))
        return valores

    def escreve_registradores(self, endereco, registrador, valores):
        """Funcao 0x10. Escreve os valores em registradores consecutivos."""
        valores = [uint16_de(v) for v in valores]
        quantidade = len(valores)
        if not 1 <= quantidade <= MAXIMO_DE_REGISTRADORES:
            raise ValueError("quantidade invalida: %d" % quantidade)
        quadro = anexa_crc(
            bytes((endereco, FUNCAO_ESCREVE))
            + struct.pack("<HHB", registrador, quantidade, 2 * quantidade)
            + struct.pack("<%dH" % quantidade, *valores)
            + self._matricula)
        self._mostra("[MODBUS 0x10] escreve %s a partir do registrador %d no "
                     "dispositivo 0x%02X" % (valores, registrador, endereco))
        resposta = self._transacao(quadro, endereco, FUNCAO_ESCREVE,
                                   self._le_resposta_escrita)
        eco_registrador, eco_quantidade = struct.unpack(">HH", resposta[2:6])
        if (eco_registrador, eco_quantidade) != (registrador, quantidade):
            # O quadro passou no CRC, entao nao e ruido: o dispositivo
            # confirmou outra escrita. Repetir nao ajuda; e erro de logica.
            raise RespostaInvalida("eco reg=%d qtd=%d, enviado reg=%d qtd=%d"
                                   % (eco_registrador, eco_quantidade,
                                      registrador, quantidade))
        self._mostra("  campos: endereco=0x%02X funcao=0x10 reg=%d qtd=%d CRC=%s"
                     % (resposta[0], eco_registrador, eco_quantidade,
                        hexa(resposta[-2:])))

    # ----------------------------------------------------------- transacao
    def _transacao(self, quadro, endereco, funcao, le_resto):
        """Envia, le e valida, repetindo em timeout ou quadro corrompido."""
        ultimo_erro = None
        for tentativa in range(1, self.tentativas + 1):
            self.transacoes += 1
            try:
                with self._porta.trava:
                    self._porta.descarta_entrada()
                    self._mostra("  TX (%d B): %s" % (len(quadro), hexa(quadro)))
                    self._porta.envia(quadro)
                    resposta = self._le_resposta(endereco, funcao, le_resto)
                return resposta
            except ExcecaoModbus as erro:
                self._mostra("  EXCECAO 0x%02X: %s (nao e repetida)"
                             % (erro.codigo, erro.significado))
                raise
            except ErroComunicacao as erro:
                self.falhas += 1
                ultimo_erro = erro
                self._mostra("  tentativa %d/%d falhou: %s: %s"
                             % (tentativa, self.tentativas,
                                type(erro).__name__, erro))
        raise ultimo_erro

    def _le_resposta(self, endereco, funcao, le_resto):
        cabecalho = self._porta.le(2, self.timeout_s)
        if len(cabecalho) < 2:
            self._mostra_rx(cabecalho)
            raise SemResposta("timeout de %d ms" % round(self.timeout_s * 1000))
        if cabecalho[1] == funcao | BIT_DE_EXCECAO:
            resposta = cabecalho + self._le_exato(3, cabecalho)
        elif cabecalho[1] == funcao:
            resposta = cabecalho + le_resto()
        else:
            # Funcao inesperada: o tamanho do resto e desconhecido. Drenar a
            # linha evita que o lixo seja lido como a proxima resposta.
            resposta = cabecalho + self._porta.le_ate_silencio(
                SILENCIO_DE_FIM_DE_QUADRO_S)
            self._mostra_rx(resposta)
            raise RespostaInvalida("funcao 0x%02X na resposta, esperada 0x%02X"
                                   % (cabecalho[1], funcao))
        self._mostra_rx(resposta)
        if not crc_valido(resposta):
            raise CrcInvalido("CRC recebido %s nao confere" % hexa(resposta[-2:]))
        if resposta[0] != endereco:
            raise RespostaInvalida("resposta do dispositivo 0x%02X, esperado 0x%02X"
                                   % (resposta[0], endereco))
        if resposta[1] & BIT_DE_EXCECAO:
            raise ExcecaoModbus(endereco, funcao, resposta[2])
        return resposta

    def _le_resposta_leitura(self, quantidade):
        byte_count = self._le_exato(1)
        if byte_count[0] != 2 * quantidade:
            # Valida antes de ler o resto: um byte_count corrompido mandaria
            # esperar uma quantidade de bytes que nunca vai chegar.
            resto = self._porta.le_ate_silencio(SILENCIO_DE_FIM_DE_QUADRO_S)
            self._mostra_rx(byte_count + resto)
            raise RespostaInvalida("byte_count %d, esperado %d"
                                   % (byte_count[0], 2 * quantidade))
        return byte_count + self._le_exato(byte_count[0] + 2, byte_count)

    def _le_resposta_escrita(self):
        return self._le_exato(6)

    def _le_exato(self, quantidade, ja_lido=b""):
        dados = self._porta.le(quantidade, self.timeout_s)
        if len(dados) < quantidade:
            self._mostra_rx(bytes(ja_lido) + dados)
            raise SemResposta("resposta incompleta: faltaram %d bytes"
                              % (quantidade - len(dados)))
        return dados

    def _mostra_rx(self, dados):
        if dados:
            self._mostra("  RX (%d B): %s" % (len(dados), hexa(dados)))
        else:
            self._mostra("  RX: (nada)")
