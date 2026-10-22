"""TCP de verdade em localhost: entrega, ordem e reconexao automatica."""
import threading
import time

from src.rede.cliente import ClienteReconectavel
from src.rede.servidor import ServidorTCP


def espera(condicao, limite_s=5.0):
    fim = time.monotonic() + limite_s
    while time.monotonic() < fim:
        if condicao():
            return True
        time.sleep(0.02)
    return False


class Lado:
    def __init__(self):
        self.recebidas = []
        self.conexoes = 0
        self.quedas = 0
        self.evento = threading.Event()

    def conectou(self, *_):
        self.conexoes += 1

    def recebeu(self, *argumentos):
        self.recebidas.append(argumentos[-1])
        self.evento.set()

    def caiu(self, *_):
        self.quedas += 1


def test_mensagens_nos_dois_sentidos_e_em_ordem():
    cabine, central = Lado(), Lado()
    servidor = ServidorTCP(0, cabine.conectou, cabine.recebeu, cabine.caiu,
                           endereco="127.0.0.1").inicia()
    cliente = ClienteReconectavel("127.0.0.1", servidor.porta, central.conectou,
                                  central.recebeu, central.caiu).inicia()
    try:
        assert espera(lambda: cliente.conectado and servidor.conectado)
        for i in range(50):
            cliente.envia({"tipo": "cota", "seq": i})
        servidor.envia({"tipo": "estado", "cabine": 1})
        assert espera(lambda: len(cabine.recebidas) == 50 and central.recebidas)
        assert [m["seq"] for m in cabine.recebidas] == list(range(50))
        assert central.recebidas[0] == {"tipo": "estado", "cabine": 1}
    finally:
        cliente.encerra()
        servidor.encerra()


def test_central_reconecta_quando_a_cabine_reinicia():
    cabine, central = Lado(), Lado()
    servidor = ServidorTCP(0, cabine.conectou, cabine.recebeu, cabine.caiu,
                           endereco="127.0.0.1").inicia()
    porta = servidor.porta
    cliente = ClienteReconectavel("127.0.0.1", porta, central.conectou,
                                  central.recebeu, central.caiu).inicia()
    try:
        assert espera(lambda: cliente.conectado)
        servidor.encerra()
        assert espera(lambda: not cliente.conectado)
        # A cabine volta na mesma porta: o central reconecta sozinho.
        novo = ServidorTCP(porta, cabine.conectou, cabine.recebeu, cabine.caiu,
                           endereco="127.0.0.1").inicia()
        try:
            assert espera(lambda: cliente.conectado and novo.conectado, 6.0)
            cliente.envia({"tipo": "cota", "seq": 99})
            assert espera(lambda: cabine.recebidas and cabine.recebidas[-1]["seq"] == 99)
            assert central.conexoes == 2 and central.quedas == 1
        finally:
            novo.encerra()
    finally:
        cliente.encerra()


def test_cabine_espera_o_central_subir_depois():
    cabine, central = Lado(), Lado()
    servidor = ServidorTCP(0, cabine.conectou, cabine.recebeu, cabine.caiu,
                           endereco="127.0.0.1").inicia()
    try:
        time.sleep(0.3)
        assert not servidor.conectado
        cliente = ClienteReconectavel("127.0.0.1", servidor.porta, central.conectou,
                                      central.recebeu, central.caiu).inicia()
        assert espera(lambda: servidor.conectado)
        cliente.encerra()
        assert espera(lambda: not servidor.conectado)
    finally:
        servidor.encerra()
