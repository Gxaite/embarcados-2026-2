"""Acesso ao barramento I2C.

A implementacao real usa o /dev/i2c-N do kernel diretamente: um ioctl escolhe
o escravo e read/write fazem o resto. Isso dispensa a smbus2, que nao vem na
imagem da placa, e basta para o BMP280, que incrementa o registrador sozinho
numa leitura em rajada.
"""
import os
import threading
from abc import ABC, abstractmethod

BARRAMENTO_PADRAO = 1
I2C_SLAVE = 0x0703          # linux/i2c-dev.h


class BarramentoI2C(ABC):
    @abstractmethod
    def le_bloco(self, endereco, registrador, quantidade):
        """Le `quantidade` bytes a partir do registrador."""

    @abstractmethod
    def escreve_byte(self, endereco, registrador, valor):
        """Escreve um byte no registrador."""

    @abstractmethod
    def fecha(self):
        """Libera o barramento."""


class BarramentoLinux(BarramentoI2C):
    def __init__(self, numero=BARRAMENTO_PADRAO):
        import fcntl
        self._fcntl = fcntl
        self.caminho = "/dev/i2c-%d" % numero
        self._fd = os.open(self.caminho, os.O_RDWR)
        self._escravo = None
        # Escolher o escravo e falar com ele sao duas chamadas; entre elas
        # outra thread nao pode trocar o escravo.
        self._trava = threading.Lock()

    def _seleciona(self, endereco):
        if self._escravo != endereco:
            self._fcntl.ioctl(self._fd, I2C_SLAVE, endereco)
            self._escravo = endereco

    def le_bloco(self, endereco, registrador, quantidade):
        with self._trava:
            self._seleciona(endereco)
            os.write(self._fd, bytes((registrador,)))
            dados = os.read(self._fd, quantidade)
        if len(dados) != quantidade:
            raise OSError("I2C 0x%02X: lidos %d de %d bytes"
                          % (endereco, len(dados), quantidade))
        return dados

    def escreve_byte(self, endereco, registrador, valor):
        with self._trava:
            self._seleciona(endereco)
            os.write(self._fd, bytes((registrador, valor & 0xFF)))

    def fecha(self):
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
