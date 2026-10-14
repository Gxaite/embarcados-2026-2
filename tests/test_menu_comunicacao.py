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


def test_parte_1_recebe_envia_e_provoca_o_erro(contexto, monkeypatch, capsys):
    # Receber valores, enviar valores com os padroes, comando invalido.
    _digita(monkeypatch, "1", "1", "2", "", "", "", "3", "0", "0")
    assert menu.navega(contexto) is True
    saida = capsys.readouterr().out
    for esperado in ("uart> p1 pede-int ; p1 pede-float ; p1 pede-string",
                     "uart> p1 envia-int 42 ; p1 envia-float 3.14 ; "
                     "p1 envia-string teste",
                     "uart> p1 cru C7 6 5 4 3 2 1", "int = 42"):
        assert esperado in saida
    assert saida.count("TX (") == 7


def test_parte_2_valida_os_valores_e_nao_tem_o_comando_cru(contexto, monkeypatch,
                                                           capsys):
    _digita(monkeypatch, "2", "3", "2", "abc", "7", "2.5", "oi", "0", "0")
    menu.navega(contexto)
    saida = capsys.readouterr().out
    assert "opcao invalida: '3'" in saida
    assert "valor invalido" in saida
    assert ("uart> p2 envia-int 7 ; p2 envia-float 2.5 ; p2 envia-string oi"
            in saida)


def test_parte_3_executa_a_demonstracao(contexto, esp32, monkeypatch, capsys):
    monkeypatch.setattr(cli, "PAUSA_DO_ROTEIRO_S", 0)
    monkeypatch.setattr(cli, "EXPIRACAO_DO_WATCHDOG_S", 0)
    monkeypatch.setattr(cli, "DURACAO_DA_ABERTURA_S", 0.05)
    monkeypatch.setattr(cli, "DURACAO_DO_FECHAMENTO_S", 0.05)
    esp32.registra_chamada(0, 4)
    # Cabine 4 e recusada; a 2; Enter na pausa do quiosque; sai.
    _digita(monkeypatch, "3", "4", "2", "", "0")
    menu.navega(contexto)
    saida = capsys.readouterr().out
    assert "cabine e 1, 2 ou 3" in saida
    for esperado in ("uart> roteiro 3 2", "uart> atribui 1 2", "uart> pop 1",
                     "fim do roteiro"):
        assert esperado in saida
    assert saida.count("EXCECAO 0x02") == 2


def test_terminal_volta_ao_menu_e_sair_encerra(contexto, monkeypatch, capsys):
    _digita(monkeypatch, "4", "p2 pede-int", "menu", "4", "sair")
    assert menu.navega(contexto) is True
    assert "int = 2026" in capsys.readouterr().out


def test_menu_aberto_do_terminal_volta_em_vez_de_sair(contexto, monkeypatch, capsys):
    _digita(monkeypatch, "0")
    assert menu.navega(contexto, raiz=False) is False
    assert "Voltar" in capsys.readouterr().out
