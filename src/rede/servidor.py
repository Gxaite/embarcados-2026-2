"""Lado da cabine: escuta a conexao do Servidor Central.

So existe um Servidor Central, entao so uma conexao vale: quando o central
reinicia e conecta de novo, a conexao antiga (que pode ainda nao ter sido
percebida como morta) e fechada em favor da nova.
"""
import socket
import threading

from .conexao import Conexao


class ServidorTCP:
    def __init__(self, porta, ao_conectar, ao_receber, ao_desconectar,
                 endereco="0.0.0.0", nome="cabine"):
        self._ao_conectar = ao_conectar
        self._ao_receber = ao_receber
        self._ao_desconectar = ao_desconectar
        self.nome = nome
        self._trava = threading.Lock()
        self.conexao = None
        self._encerrar = threading.Event()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # Sem SO_REUSEADDR, reiniciar a cabine logo depois de um Ctrl+C
        # falharia com "Address already in use" por causa do TIME_WAIT.
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((endereco, porta))
        self._sock.listen(2)
        self.porta = self._sock.getsockname()[1]
        self._thread = threading.Thread(target=self._aceita, daemon=True,
                                        name="tcp-%s" % nome)

    def inicia(self):
        self._thread.start()
        return self

    def envia(self, mensagem):
        conexao = self.conexao
        return conexao is not None and conexao.envia(mensagem)

    @property
    def conectado(self):
        conexao = self.conexao
        return conexao is not None and conexao.aberta

    def _aceita(self):
        while not self._encerrar.is_set():
            try:
                sock, origem = self._sock.accept()
            except OSError:
                return
            conexao = Conexao(sock, self._ao_receber, self._fechou,
                              nome="%s<-%s:%d" % (self.nome, *origem))
            with self._trava:
                antiga, self.conexao = self.conexao, conexao
            if antiga is not None:
                antiga.fecha()
            conexao.inicia()
            self._ao_conectar(conexao)

    def _fechou(self, conexao):
        with self._trava:
            if self.conexao is conexao:
                self.conexao = None
            else:
                return
        self._ao_desconectar(conexao)

    def encerra(self):
        self._encerrar.set()
        # So close() nao acorda a thread presa no accept(), e o socket continua
        # escutando, segurando a porta. O shutdown() a acorda.
        try:
            self._sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self._sock.close()
        if self._thread.is_alive() and self._thread is not threading.current_thread():
            self._thread.join(timeout=2.0)
        conexao = self.conexao
        if conexao is not None:
            conexao.fecha()
