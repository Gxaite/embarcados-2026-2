"""Lado do central: conexao com uma cabine, refeita sozinha quando cai.

A thread tenta conectar, fica dormindo enquanto a conexao estiver de pe e,
quando ela cai, espera INTERVALO_DE_RECONEXAO_S e tenta de novo. Nao ha
consulta em laco: a espera e no Event da conexao.
"""
import socket
import threading
import time

from .conexao import Conexao

INTERVALO_DE_RECONEXAO_S = 1.0
PRAZO_DE_CONEXAO_S = 2.0


class ClienteReconectavel:
    def __init__(self, host, porta, ao_conectar, ao_receber, ao_desconectar,
                 nome="cliente"):
        self.host = host
        self.porta = porta
        self.nome = nome
        self._ao_conectar = ao_conectar
        self._ao_receber = ao_receber
        self._ao_desconectar = ao_desconectar
        self.conexao = None
        self.reconexoes = 0
        self._suspenso_ate = 0.0
        self._encerrar = threading.Event()
        self._thread = threading.Thread(target=self._laco, daemon=True,
                                        name="tcp-%s" % nome)

    def inicia(self):
        self._thread.start()
        return self

    @property
    def conectado(self):
        conexao = self.conexao
        return conexao is not None and conexao.aberta

    def envia(self, mensagem):
        conexao = self.conexao
        return conexao is not None and conexao.envia(mensagem)

    def suspende(self, segundos):
        """Derruba a conexao e so tenta de novo depois de `segundos`.

        Simula a queda de rede nos ensaios de reconexao e de Modo Degradado."""
        self._suspenso_ate = time.monotonic() + segundos
        conexao = self.conexao
        if conexao is not None:
            conexao.fecha()

    def _laco(self):
        while not self._encerrar.is_set():
            espera = self._suspenso_ate - time.monotonic()
            if espera > 0:
                self._encerrar.wait(espera)
                continue
            try:
                sock = socket.create_connection((self.host, self.porta),
                                                timeout=PRAZO_DE_CONEXAO_S)
            except OSError:
                self._encerrar.wait(INTERVALO_DE_RECONEXAO_S)
                continue
            conexao = Conexao(sock, self._ao_receber, nome=self.nome)
            self.conexao = conexao
            conexao.inicia()
            self._ao_conectar(conexao)
            conexao.espera_fechar()
            self.conexao = None
            self.reconexoes += 1
            self._ao_desconectar(conexao)
            self._encerrar.wait(INTERVALO_DE_RECONEXAO_S)

    def encerra(self):
        self._encerrar.set()
        conexao = self.conexao
        if conexao is not None:
            conexao.fecha()
        self._thread.join(timeout=3.0)
