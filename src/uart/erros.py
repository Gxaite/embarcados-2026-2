"""Erros de comunicacao comuns aos tres protocolos.

A distincao entre eles decide se a requisicao e repetida: timeout, CRC
invalido e resposta malformada sao repetidos; excecao MODBUS nao, porque o
dispositivo entendeu o pedido e o recusou - repetir daria a mesma recusa.
"""


class ErroComunicacao(Exception):
    """Base de todos os erros de transacao na UART."""


class SemResposta(ErroComunicacao):
    """Timeout: nenhum byte, ou menos bytes que o esperado."""


class CrcInvalido(ErroComunicacao):
    """A resposta chegou, mas o CRC nao confere. O quadro e descartado."""


class RespostaInvalida(ErroComunicacao):
    """Resposta com CRC correto mas inconsistente com a requisicao."""


class ExcecaoModbus(ErroComunicacao):
    """O dispositivo respondeu com o bit de erro na funcao."""

    SIGNIFICADOS = {
        0x01: "funcao invalida",
        0x02: "endereco invalido",
        0x03: "valor invalido",
        0x04: "falha no dispositivo",
    }

    def __init__(self, endereco, funcao, codigo):
        self.endereco = endereco
        self.funcao = funcao
        self.codigo = codigo
        super().__init__("excecao 0x%02X (%s) do dispositivo 0x%02X na funcao 0x%02X"
                         % (codigo, self.significado, endereco, funcao))

    @property
    def significado(self):
        return self.SIGNIFICADOS.get(self.codigo, "codigo desconhecido")
