"""PortaSerial contra um pseudo-terminal.

O pty faz o papel da ESP32: o lado mestre e o "dispositivo", o escravo e a
UART aberta pela PortaSerial. Isso exercita o termios, o select e os prazos de
verdade - so nao ha cabo nem baudrate fisico.
"""
import os
import time

import pytest

from src.uart.porta import PortaSerial

termios = pytest.importorskip("termios")


@pytest.fixture
def par():
    mestre, escravo = os.openpty()
    porta = PortaSerial(os.ttyname(escravo))
    yield mestre, porta
    porta.fecha()
    os.close(escravo)
    os.close(mestre)


def test_bytes_de_controle_passam_crus(par):
    # 0x03 e 0x11 sao Ctrl+C e XON num terminal; aparecem em todo quadro.
    mestre, porta = par
    quadro = bytes.fromhex("11 03 00 00 09 00 06 05 04 03 02 01 0E E4 0D 0A")
    porta.envia(quadro)
    assert os.read(mestre, 64) == quadro
    os.write(mestre, quadro)
    assert porta.le(len(quadro), 0.5) == quadro


def test_leitura_respeita_o_prazo(par):
    _, porta = par
    inicio = time.monotonic()
    assert porta.le(4, 0.2) == b""
    decorrido = time.monotonic() - inicio
    assert 0.18 <= decorrido < 0.5


def test_leitura_ate_silencio_junta_o_quadro(par):
    mestre, porta = par
    os.write(mestre, b"\x20\x10\x00\x05\x00\x02\x57\x63")
    assert porta.le_ate_silencio(0.3) == b"\x20\x10\x00\x05\x00\x02\x57\x63"


def test_descarta_entrada_joga_fora_resposta_atrasada(par):
    mestre, porta = par
    os.write(mestre, b"lixo")
    time.sleep(0.05)
    porta.descarta_entrada()
    assert porta.le(4, 0.05) == b""
