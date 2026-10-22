"""Uma conexao TCP estabelecida.

A leitura roda numa thread propria, bloqueada no recv do socket: nao ha
consulta em laco. O prazo de leitura e o detector de queda: os dois lados
mandam mensagem pelo menos a cada segundo (cota de um lado, estado do outro),
entao um silencio maior que SILENCIO_MAXIMO_S e conexao morta, mesmo que o TCP
ainda nao tenha percebido (cabo puxado, processo congelado).
"""
import socket
import threading

from . import protocolo

SILENCIO_MAXIMO_S = 5.0


class Conexao:
    def __init__(self, sock, ao_receber, ao_fechar=None, nome="conexao"):
        self._sock = sock
        self._ao_receber = ao_receber
        self._ao_fechar = ao_fechar
        self.nome = nome
        self._trava_de_envio = threading.Lock()
        self._fechada = threading.Event()
        sock.settimeout(SILENCIO_MAXIMO_S)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        self._leitor = threading.Thread(target=self._le, daemon=True,
                                        name="leitor-%s" % nome)

    def inicia(self):
        self._leitor.start()
        return self

    @property
    def aberta(self):
        return not self._fechada.is_set()

    def envia(self, mensagem):
        """Devolve False se a conexao caiu; quem chama nao precisa tratar."""
        if self._fechada.is_set():
            return False
        dados = protocolo.codifica(mensagem)
        try:
            with self._trava_de_envio:
                self._sock.sendall(dados)
            return True
        except OSError:
            self.fecha()
            return False

    def espera_fechar(self, timeout=None):
        return self._fechada.wait(timeout)

    def _le(self):
        buffer = bytearray()
        try:
            while not self._fechada.is_set():
                try:
                    pedaco = self._sock.recv(4096)
                except socket.timeout:
                    break
                if not pedaco:
                    break
                buffer.extend(pedaco)
                while b"\n" in buffer:
                    linha, _, resto = bytes(buffer).partition(b"\n")
                    buffer = bytearray(resto)
                    self._entrega(linha)
                if len(buffer) > protocolo.TAMANHO_MAXIMO_DE_LINHA:
                    break
        except OSError:
            pass
        finally:
            self.fecha()

    def _entrega(self, linha):
        if not linha.strip():
            return
        try:
            mensagem = protocolo.decodifica(linha)
        except protocolo.MensagemInvalida:
            return
        try:
            self._ao_receber(self, mensagem)
        except Exception as erro:            # o leitor nao pode morrer
            print("ERRO tratando mensagem %s em %s: %r"
                  % (mensagem.get("tipo"), self.nome, erro), flush=True)

    def fecha(self):
        if self._fechada.is_set():
            return
        self._fechada.set()
        try:
            self._sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self._sock.close()
        if self._ao_fechar is not None:
            self._ao_fechar(self)
