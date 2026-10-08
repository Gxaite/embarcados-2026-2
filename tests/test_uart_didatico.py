"""Partes 1 e 2: protocolo simplificado e MODBUS didatico."""
import struct

import pytest

from src.uart import crc16
from src.uart.erros import CrcInvalido, ExcecaoModbus, SemResposta
from src.uart.esp32_simulada import (CONSTANTE_FLOAT, CONSTANTE_INT,
                                     CONSTANTE_STRING, Esp32Simulada,
                                     PortaSimulada)
from src.uart.matricula import em_bytes, resolve
from src.uart.modbus_didatico import ModbusDidatico
from src.uart.simplificado import ProtocoloSimplificado

MATRICULA = em_bytes("654321")


@pytest.fixture
def porta():
    return PortaSimulada(Esp32Simulada())


@pytest.fixture
def simplificado(porta):
    return ProtocoloSimplificado(porta, MATRICULA, eco=None)


@pytest.fixture
def didatico(porta):
    return ModbusDidatico(porta, MATRICULA, eco=None)


# -------------------------------------------------------------- matricula
def test_matricula_vira_bytes_crus_dos_seis_ultimos_digitos():
    assert em_bytes("12/3456789") == bytes((4, 5, 6, 7, 8, 9))
    assert em_bytes("654321") == b"\x06\x05\x04\x03\x02\x01"


def test_matricula_curta_e_recusada():
    with pytest.raises(ValueError):
        em_bytes("12345")


def test_matricula_vem_do_argumento_do_ambiente_ou_do_arquivo(tmp_path):
    arquivo = tmp_path / "matricula"
    arquivo.write_text("111222\n")
    assert resolve("654321", {}, str(arquivo)) == em_bytes("654321")
    assert resolve(None, {"FSE_MATRICULA": "333444"}, str(arquivo)) \
        == em_bytes("333444")
    assert resolve(None, {}, str(arquivo)) == em_bytes("111222")
    assert resolve(None, {}, str(tmp_path / "nao_existe")) is None


# ----------------------------------------------------------------- Parte 1
def test_pacote_simplificado_igual_ao_exemplo(simplificado, porta):
    simplificado.pede_int()
    assert porta.enviados[0] == bytes.fromhex("A1 06 05 04 03 02 01")


def test_os_tres_pedidos(simplificado):
    assert simplificado.pede_int() == CONSTANTE_INT
    assert simplificado.pede_float() == pytest.approx(CONSTANTE_FLOAT, rel=1e-6)
    assert simplificado.pede_string() == CONSTANTE_STRING


def test_os_tres_envios(simplificado, porta):
    assert simplificado.envia_int(3245) == 3245 * 1
    assert porta.enviados[-1] == bytes.fromhex("B1 AD 0C 00 00 06 05 04 03 02 01")
    assert simplificado.envia_float(1.5) == pytest.approx(1.5)
    assert simplificado.envia_string("ola") == "Resposta da UART: ola"
    assert porta.enviados[-1] == b"\xB3\x03ola" + MATRICULA


def test_resposta_multiplica_pelo_ultimo_digito():
    porta = PortaSimulada(Esp32Simulada())
    protocolo = ProtocoloSimplificado(porta, em_bytes("123457"), eco=None)
    assert protocolo.envia_int(-10) == -70
    assert protocolo.envia_float(0.5) == pytest.approx(3.5)


def test_comando_desconhecido_da_timeout(simplificado):
    with pytest.raises(SemResposta):
        simplificado.envia_cru(b"\xC7" + MATRICULA)


def test_string_maior_que_255_bytes_e_recusada(simplificado, porta):
    with pytest.raises(ValueError):
        simplificado.envia_string("x" * 256)
    assert porta.enviados == []


def test_int_fora_de_32_bits_e_recusado(simplificado):
    with pytest.raises(ValueError):
        simplificado.envia_int(2 ** 31)


def test_string_incompleta_e_timeout(simplificado, porta):
    porta.perturbacoes = [lambda r: r[:5]]
    with pytest.raises(SemResposta):
        simplificado.pede_string()


# ----------------------------------------------------------------- Parte 2
def test_pacotes_modbus_iguais_aos_exemplos(didatico, porta):
    didatico.pede_int()
    didatico.envia_int(3245)
    esperado_pede = bytes.fromhex("01 23 A1 06 05 04 03 02 01")
    esperado_envia = bytes.fromhex("01 16 B1 AD 0C 00 00 06 05 04 03 02 01")
    assert porta.enviados[0] == crc16.anexa_crc(esperado_pede)
    assert porta.enviados[1] == crc16.anexa_crc(esperado_envia)
    assert len(porta.enviados[0]) == 11 and len(porta.enviados[1]) == 15


def test_os_seis_comandos_modbus(didatico):
    assert didatico.pede_int() == CONSTANTE_INT
    assert didatico.pede_float() == pytest.approx(CONSTANTE_FLOAT, rel=1e-6)
    assert didatico.pede_string() == CONSTANTE_STRING
    assert didatico.envia_int(7) == 7
    assert didatico.envia_float(2.0) == pytest.approx(2.0)
    assert didatico.envia_string("abc") == "Resposta da UART: abc"


@pytest.mark.parametrize("cabecalho, rabo", [
    (b"\x00\x23\xA1", b""),                  # endereco 0x00, sub ecoado
    (b"\x01\x23\xA1", b""),                  # endereco 0x01, sub ecoado
    (b"\x00\x23", b""),                      # sem eco do sub-codigo
    (b"\x01\x23", MATRICULA),                # com a matricula de volta
    (b"\x00\x23\xA1", MATRICULA),
])
def test_formatos_de_resposta_aceitos(didatico, porta, cabecalho, rabo):
    valor = struct.pack("<i", 42)
    porta.perturbacoes = [lambda _r: crc16.anexa_crc(cabecalho + valor + rabo)]
    assert didatico.pede_int() == 42


def test_string_sem_eco_do_sub_codigo(didatico, porta):
    porta.perturbacoes = [lambda _r: crc16.anexa_crc(b"\x00\x23\x02oi")]
    assert didatico.pede_string() == "oi"


def test_string_com_terminador_nulo_como_na_bancada(didatico, porta):
    # Bytes capturados na rasp49: o tamanho 0x06 conta o '\0' do fim.
    porta.perturbacoes = [lambda _r: crc16.anexa_crc(b"\x00\x16\xB3\x06teste\x00")]
    assert didatico.envia_string("teste") == "teste"


def test_crc_invalido_e_repetido(didatico, porta):
    def corrompe(resposta):
        return resposta[:-1] + bytes((resposta[-1] ^ 0xFF,))
    porta.perturbacoes = [corrompe]
    assert didatico.pede_int() == CONSTANTE_INT
    assert len(porta.enviados) == 2


def test_tres_crcs_invalidos_desistem(didatico, porta):
    porta.perturbacoes = [lambda r: r[:-1] + bytes((r[-1] ^ 1,))] * 3
    with pytest.raises(CrcInvalido):
        didatico.pede_int()
    assert len(porta.enviados) == 3


def test_bit_de_erro_vira_excecao_sem_repetir(didatico, porta):
    porta.perturbacoes = [lambda _r: crc16.anexa_crc(b"\x00\xA3\x01")]
    with pytest.raises(ExcecaoModbus) as erro:
        didatico.pede_int()
    assert erro.value.codigo == 0x01
    assert len(porta.enviados) == 1


# ------------------------------------------------------------------- CLI
def test_cli_encadeia_comandos_com_ponto_e_virgula(simplificado, didatico, porta,
                                                   capsys):
    from src import cli_comunicacao as cli
    contexto = cli.Contexto(simplificado, didatico, elevadores=None)
    assert cli.executa(contexto, "p1 pede-int ; p2 pede-int") is True
    assert len(porta.enviados) == 2
    assert cli.executa(contexto, "p1 pede-int ; sair ; p1 pede-int") is False
    assert len(porta.enviados) == 3
