"""CRC-16 das mensagens MODBUS da bancada.

A variante e a CRC-16/ARC: polinomio 0x8005 refletido (0xA001) e valor inicial
ZERO. O MODBUS RTU padrao comeca em 0xFFFF, e e assim que bibliotecas prontas
(pymodbus, libmodbus) calculam - contra este simulador elas errariam todos os
quadros. Conferido contra os quatro exemplos da Secao 3.3 da Entrega 2.

No quadro, o CRC vai no fim com o byte menos significativo primeiro.
"""

POLINOMIO_REFLETIDO = 0xA001
VALOR_INICIAL = 0x0000


def _monta_tabela():
    tabela = []
    for byte in range(256):
        crc = byte
        for _ in range(8):
            crc = (crc >> 1) ^ POLINOMIO_REFLETIDO if crc & 1 else crc >> 1
        tabela.append(crc)
    return tuple(tabela)


_TABELA = _monta_tabela()


def calcula_crc(dados):
    """CRC-16 de uma sequencia de bytes, como inteiro de 16 bits."""
    crc = VALOR_INICIAL
    for byte in dados:
        crc = (crc >> 8) ^ _TABELA[(crc ^ byte) & 0xFF]
    return crc


def anexa_crc(dados):
    """Devolve o quadro com o CRC anexado, byte baixo primeiro."""
    crc = calcula_crc(dados)
    return bytes(dados) + bytes((crc & 0xFF, crc >> 8))


def crc_valido(quadro):
    """Confere os dois ultimos bytes do quadro contra o CRC do restante."""
    if len(quadro) < 3:
        return False
    crc = calcula_crc(quadro[:-2])
    return quadro[-2] == (crc & 0xFF) and quadro[-1] == (crc >> 8)
