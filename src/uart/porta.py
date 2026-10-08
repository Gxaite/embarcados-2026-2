"""Acesso a porta serial.

A implementacao real fala direto com o termios do Linux, sem pyserial: a placa
do laboratorio e compartilhada, nao da para garantir pip install nela, e o que
o projeto precisa da porta cabe em poucas chamadas. A espera por bytes e feita
com select(), que dorme no kernel ate chegar dado ou estourar o prazo - nao ha
laco girando em CPU.

A trava de transacao existe porque o Servidor Central e o unico processo que
abre a porta, mas dentro dele ha mais de uma thread falando com a ESP32 (a CLI
e o servico da Condicao de Contorno). Uma requisicao e a sua resposta tem de
ocupar a linha juntas, senao a resposta de um vai parar no outro.
"""
import os
import select
import threading
import time
from abc import ABC, abstractmethod

PORTA_PADRAO = "/dev/serial0"
BAUDRATE = 115200
# Bytes que caberiam numa pausa de MODBUS RTU (3,5 caracteres) somam 0,3 ms a
# 115200 bps, mas o escalonador do Linux e o buffer da UART entregam rajadas
# bem mais espacadas. 20 ms de silencio e folgado para fim de quadro sem pesar
# no tempo de cada transacao.
SILENCIO_DE_FIM_DE_QUADRO_S = 0.020
TAMANHO_MAXIMO_DE_QUADRO = 512


def hexa(dados):
    """Bytes em hexadecimal separado por espaco: 11 03 00 00 ..."""
    return " ".join("%02X" % b for b in dados)


class Porta(ABC):
    """Porta de comunicacao byte a byte com prazo de leitura."""

    def __init__(self):
        self.trava = threading.RLock()

    @abstractmethod
    def envia(self, dados):
        """Transmite todos os bytes."""

    @abstractmethod
    def le(self, quantidade, timeout_s):
        """Le ate `quantidade` bytes, esperando no maximo `timeout_s` no total.

        Devolve menos bytes que o pedido se o prazo acabar antes.
        """

    def le_ate_silencio(self, timeout_s, silencio_s=SILENCIO_DE_FIM_DE_QUADRO_S):
        """Le um quadro de tamanho desconhecido.

        Espera ate `timeout_s` pelo primeiro byte e depois continua lendo ate a
        linha ficar `silencio_s` sem trafego.
        """
        quadro = bytearray(self.le(1, timeout_s))
        while quadro and len(quadro) < TAMANHO_MAXIMO_DE_QUADRO:
            mais = self.le(TAMANHO_MAXIMO_DE_QUADRO - len(quadro), silencio_s)
            if not mais:
                break
            quadro.extend(mais)
        return bytes(quadro)

    @abstractmethod
    def descarta_entrada(self):
        """Joga fora o que estiver no buffer de recepcao.

        Chamado antes de cada requisicao: a resposta atrasada de uma tentativa
        anterior nao pode ser lida como resposta da atual.
        """

    @abstractmethod
    def fecha(self):
        """Libera a porta."""


class PortaSerial(Porta):
    """UART real, 115200 bps, 8N1, sem controle de fluxo."""

    def __init__(self, caminho=PORTA_PADRAO, baudrate=BAUDRATE):
        super().__init__()
        import termios
        self._termios = termios
        self.caminho = caminho
        velocidade = getattr(termios, "B%d" % baudrate)
        self._fd = os.open(caminho, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        try:
            atributos = termios.tcgetattr(self._fd)
            # Modo cru: nada de eco, de conversao de CR/LF, de XON/XOFF nem de
            # sinal por caractere. Com isso 0x03 e 0x11 passam como dado, e nao
            # como Ctrl+C e XON - e os dois aparecem nos quadros desta bancada.
            atributos[0] = 0                                    # iflag
            atributos[1] = 0                                    # oflag
            atributos[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
            atributos[3] = 0                                    # lflag
            atributos[4] = velocidade                           # ispeed
            atributos[5] = velocidade                           # ospeed
            atributos[6][termios.VMIN] = 0
            atributos[6][termios.VTIME] = 0
            termios.tcsetattr(self._fd, termios.TCSANOW, atributos)
            termios.tcflush(self._fd, termios.TCIOFLUSH)
        except Exception:
            os.close(self._fd)
            raise

    def envia(self, dados):
        restante = memoryview(bytes(dados))
        while restante:
            try:
                escritos = os.write(self._fd, restante)
            except BlockingIOError:
                select.select([], [self._fd], [], 0.1)
                continue
            restante = restante[escritos:]
        self._termios.tcdrain(self._fd)

    def le(self, quantidade, timeout_s):
        recebido = bytearray()
        prazo = time.monotonic() + timeout_s
        while len(recebido) < quantidade:
            restante = prazo - time.monotonic()
            if restante <= 0:
                break
            prontos, _, _ = select.select([self._fd], [], [], restante)
            if not prontos:
                break
            try:
                pedaco = os.read(self._fd, quantidade - len(recebido))
            except BlockingIOError:
                continue
            if not pedaco:
                # Pronto para leitura mas sem dado: o dispositivo sumiu. Sem
                # este break o select devolveria na hora, em laco, ate o prazo.
                break
            recebido.extend(pedaco)
        return bytes(recebido)

    def descarta_entrada(self):
        self._termios.tcflush(self._fd, self._termios.TCIFLUSH)

    def fecha(self):
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
