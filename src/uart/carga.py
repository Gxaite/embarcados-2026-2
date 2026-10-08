"""Comandos e cargas uteis comuns as Partes 1 e 2.

As duas partes trocam os mesmos tres tipos (int32, float e string) com os
mesmos codigos de comando; o que muda e o envelope. Este modulo cuida so do
miolo: codificar o valor que vai e decodificar o que volta.

Tudo em little-endian, como a Entrega 2 especifica (o `uart_modbus.md`
original mostra o inteiro em big-endian, mas o exemplo da Secao 2.3 da
Entrega 2, que e o que vale, esta em little-endian).
"""
import struct

from .erros import RespostaInvalida

PEDE_INT = 0xA1
PEDE_FLOAT = 0xA2
PEDE_STRING = 0xA3
ENVIA_INT = 0xB1
ENVIA_FLOAT = 0xB2
ENVIA_STRING = 0xB3

INT = "int"
FLOAT = "float"
STRING = "string"

TIPO_DA_RESPOSTA = {
    PEDE_INT: INT, PEDE_FLOAT: FLOAT, PEDE_STRING: STRING,
    ENVIA_INT: INT, ENVIA_FLOAT: FLOAT, ENVIA_STRING: STRING,
}

NOMES = {
    PEDE_INT: "solicita inteiro", PEDE_FLOAT: "solicita float",
    PEDE_STRING: "solicita string", ENVIA_INT: "envia inteiro",
    ENVIA_FLOAT: "envia float", ENVIA_STRING: "envia string",
}

TAMANHO_MAXIMO_DE_STRING = 255     # o tamanho viaja em um byte so
INT32_MIN, INT32_MAX = -2 ** 31, 2 ** 31 - 1


def codifica_int(valor):
    valor = int(valor)
    if not INT32_MIN <= valor <= INT32_MAX:
        raise ValueError("inteiro fora da faixa de int32: %d" % valor)
    return struct.pack("<i", valor)


def codifica_float(valor):
    return struct.pack("<f", float(valor))


def codifica_string(texto):
    dados = texto.encode("utf-8") if isinstance(texto, str) else bytes(texto)
    if len(dados) > TAMANHO_MAXIMO_DE_STRING:
        raise ValueError("string com %d bytes; o tamanho vai em um byte, maximo %d"
                         % (len(dados), TAMANHO_MAXIMO_DE_STRING))
    return bytes((len(dados),)) + dados


def tamanho_da_resposta(tipo, dados):
    """Quantos bytes a resposta deste tipo ocupa, olhando o que ja chegou.

    Para string e preciso ter recebido o byte de tamanho; antes disso devolve
    None.
    """
    if tipo in (INT, FLOAT):
        return 4
    if not dados:
        return None
    return 1 + dados[0]


def decodifica(tipo, dados):
    """Decodifica exatamente `dados` como resposta do tipo pedido.

    Sobra ou falta de bytes e erro: e isso que deixa o MODBUS didatico
    reconhecer o formato da resposta pelo tamanho.
    """
    esperado = tamanho_da_resposta(tipo, dados)
    if esperado is None or len(dados) != esperado:
        raise RespostaInvalida("%s com %d bytes, esperado %s"
                               % (tipo, len(dados), esperado))
    if tipo == INT:
        return struct.unpack("<i", dados)[0]
    if tipo == FLOAT:
        return struct.unpack("<f", dados)[0]
    return dados[1:].decode("utf-8", errors="replace")
