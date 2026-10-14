"""Menu numerado da Entrega 2 contra a ESP32 simulada."""
import pytest

from src import cli_comunicacao as cli
from src import menu_comunicacao as menu
from src.uart import modbus
from src.uart.elevadores import Elevadores
from src.uart.esp32_simulada import Esp32Simulada, PortaSimulada
from src.uart.matricula import em_bytes
from src.uart.modbus_didatico import ModbusDidatico
from src.uart.simplificado import ProtocoloSimplificado

MATRICULA = em_bytes("654321")


@pytest.fixture
def esp32():
    return Esp32Simulada()


@pytest.fixture
def contexto(esp32):
    porta = PortaSimulada(esp32)
    eco = lambda texto: print(texto)
    return cli.Contexto(
        ProtocoloSimplificado(porta, MATRICULA, eco=eco),
        ModbusDidatico(porta, MATRICULA, eco=eco),
        Elevadores(modbus.ClienteModbus(porta, MATRICULA, eco=eco)),
        esp32_simulada=esp32)


def _digita(monkeypatch, *entradas):
    fila = list(entradas)

    def entrada(_prompt=""):
        if not fila:
            raise EOFError
        return fila.pop(0)
    monkeypatch.setattr("builtins.input", entrada)


def test_opcoes_da_parte_1_montam_os_comandos(contexto, monkeypatch, capsys):
    # Parte 1: enviar inteiro com o padrao, enviar inteiro digitado, receber
    # string e o comando invalido; volta e sai.
    _digita(monkeypatch, "1", "6", "", "6", "7", "5", "9", "0", "0")
    assert menu.navega(contexto) is True
    saida = capsys.readouterr().out
    for esperado in ("uart> p1 envia-int 42", "uart> p1 envia-int 7",
                     "uart> p1 pede-string", "uart> p1 cru C7 6 5 4 3 2 1",
                     "int = 42", "int = 7"):
        assert esperado in saida


def test_receber_e_enviar_valores_fazem_os_tres_tipos(contexto, monkeypatch, capsys):
    _digita(monkeypatch, "2", "1", "2", "", "2.5", "oi", "0", "0")
    menu.navega(contexto)
    saida = capsys.readouterr().out
    assert "uart> p2 pede-int ; p2 pede-float ; p2 pede-string" in saida
    assert ("uart> p2 envia-int 42 ; p2 envia-float 2.5 ; p2 envia-string oi"
            in saida)
    assert saida.count("TX (") == 6


def test_parte_2_nao_tem_o_comando_cru(contexto, monkeypatch, capsys):
    _digita(monkeypatch, "2", "9", "3", "0", "0")
    menu.navega(contexto)
    saida = capsys.readouterr().out
    assert "opcao invalida: '9'" in saida
    assert "uart> p2 pede-int" in saida


def test_valor_invalido_e_perguntado_de_novo(contexto, monkeypatch, capsys):
    _digita(monkeypatch, "2", "7", "abc", "2.5", "0", "0")
    menu.navega(contexto)
    saida = capsys.readouterr().out
    assert "valor invalido" in saida
    assert "uart> p2 envia-float 2.5" in saida


def test_parte_3_fila_atribui_pop_e_excecoes(contexto, esp32, monkeypatch, capsys):
    esp32.registra_chamada(0, 4)
    _digita(monkeypatch, "3", "7", "8", "1", "2", "9", "7", "10", "11", "12",
            "0", "0")
    menu.navega(contexto)
    saida = capsys.readouterr().out
    for esperado in ("uart> fila", "uart> atribui 1 2", "uart> pop",
                     "chamada 1 removida da fila", "fila vazia",
                     "uart> escreve 0x11 0 5", "uart> le 0x11 0 20",
                     "uart> escreve 0x11 3 7"):
        assert esperado in saida
    assert saida.count("EXCECAO 0x02") == 2
    assert saida.count("EXCECAO 0x03") == 1
    assert esp32.atribuicoes == [(1, 2)]


def test_cabine_fora_de_1_a_3_e_recusada(contexto, monkeypatch, capsys):
    _digita(monkeypatch, "3", "1", "4", "3", "0", "0")
    menu.navega(contexto)
    saida = capsys.readouterr().out
    assert "cabine e 1, 2 ou 3" in saida
    assert "uart> cabine 3" in saida


def test_terminal_volta_ao_menu_e_sair_encerra(contexto, monkeypatch, capsys):
    _digita(monkeypatch, "6", "p2 pede-int", "menu", "6", "sair")
    assert menu.navega(contexto) is True
    assert "int = 2026" in capsys.readouterr().out


def test_menu_aberto_do_terminal_volta_em_vez_de_sair(contexto, monkeypatch, capsys):
    _digita(monkeypatch, "0")
    assert menu.navega(contexto, raiz=False) is False
    assert "Voltar" in capsys.readouterr().out
