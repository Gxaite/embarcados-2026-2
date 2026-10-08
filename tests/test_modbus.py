"""Parte 3: CRC, formato dos quadros, validacao, retentativas e excecoes.

Os quadros esperados sao os exemplos byte a byte da Secao 3.3 da Entrega 2,
com a matricula 654321 que o enunciado usa.
"""
import pytest

from src.uart import crc16
from src.uart.elevadores import Elevadores
from src.uart.erros import CrcInvalido, ExcecaoModbus, RespostaInvalida, SemResposta
from src.uart.esp32_simulada import Esp32Simulada, PortaSimulada
from src.uart.matricula import em_bytes
from src.uart.modbus import ClienteModbus, int16_de, uint16_de

MATRICULA = em_bytes("654321")

EXEMPLO_LEITURA = bytes.fromhex("11 03 00 00 09 00 06 05 04 03 02 01 0E E4")
EXEMPLO_ESCRITA = bytes.fromhex(
    "20 10 05 00 02 00 04 FD 00 F5 03 06 05 04 03 02 01 56 C3")
EXEMPLO_RESPOSTA_ESCRITA = bytes.fromhex("20 10 00 05 00 02 57 63")
EXEMPLO_EXCECAO = bytes.fromhex("11 83 02 B0 F4")


@pytest.fixture
def esp32():
    return Esp32Simulada()


@pytest.fixture
def porta(esp32):
    return PortaSimulada(esp32)


@pytest.fixture
def cliente(porta):
    return ClienteModbus(porta, MATRICULA, eco=None)


# ------------------------------------------------------------------- CRC
@pytest.mark.parametrize("quadro", [EXEMPLO_LEITURA, EXEMPLO_ESCRITA,
                                    EXEMPLO_RESPOSTA_ESCRITA, EXEMPLO_EXCECAO])
def test_crc_confere_com_os_exemplos_do_enunciado(quadro):
    assert crc16.anexa_crc(quadro[:-2]) == quadro
    assert crc16.crc_valido(quadro)


def test_crc_nao_e_o_modbus_padrao():
    # O MODBUS padrao comeca em 0xFFFF; o desta bancada, em zero.
    assert crc16.calcula_crc(EXEMPLO_LEITURA[:-2]) == 0xE40E
    assert crc16.VALOR_INICIAL == 0


def test_crc_detecta_um_bit_trocado():
    corrompido = bytearray(EXEMPLO_LEITURA)
    corrompido[3] ^= 0x01
    assert not crc16.crc_valido(bytes(corrompido))


# --------------------------------------------------------------- quadros
def test_requisicao_de_leitura_igual_ao_exemplo(cliente, porta):
    cliente.le_registradores(0x11, 0, 9)
    assert porta.enviados[0] == EXEMPLO_LEITURA


def test_requisicao_de_escrita_igual_ao_exemplo(porta):
    Elevadores(ClienteModbus(porta, MATRICULA, eco=None)) \
        .escreve_condicao_contorno(25.3, 1013)
    assert porta.enviados[0] == EXEMPLO_ESCRITA


def test_resposta_de_leitura_e_big_endian(cliente, esp32):
    esp32.cabines[0x11].posicao_mm = 0x1234
    valores = cliente.le_registradores(0x11, 7, 1)
    assert valores == [0x1234]


def test_posicao_negativa_vem_com_sinal(cliente, esp32):
    esp32.cabines[0x11].posicao_mm = -350
    estado = Elevadores(cliente).le_estado_cabine(1)
    assert estado["posicao_mm"] == -350


def test_conversoes_de_16_bits():
    assert uint16_de(-1) == 0xFFFF
    assert int16_de(0xFFFF) == -1
    assert int16_de(0x7FFF) == 0x7FFF
    with pytest.raises(ValueError):
        uint16_de(0x10000)


# ------------------------------------------------------------ retentativa
def _corrompe(resposta):
    quadro = bytearray(resposta)
    quadro[-1] ^= 0xFF
    return bytes(quadro)


def test_crc_invalido_e_repetido_ate_dar_certo(cliente, porta):
    porta.perturbacoes = [_corrompe, _corrompe]
    assert cliente.le_registradores(0x11, 0, 9)[1] == 1
    assert len(porta.enviados) == 3


def test_timeout_e_repetido_tres_vezes_e_desiste(cliente, porta):
    porta.perturbacoes = [lambda _r: None] * 3
    with pytest.raises(SemResposta):
        cliente.le_registradores(0x11, 0, 9)
    assert len(porta.enviados) == 3


def test_tres_crcs_invalidos_desistem_com_crc_invalido(cliente, porta):
    porta.perturbacoes = [_corrompe] * 3
    with pytest.raises(CrcInvalido):
        cliente.le_registradores(0x11, 0, 9)


def test_resposta_truncada_conta_como_timeout(cliente, porta):
    porta.perturbacoes = [lambda r: r[:-3]]
    assert cliente.le_registradores(0x11, 0, 9)
    assert len(porta.enviados) == 2


def test_resposta_de_outro_dispositivo_e_rejeitada(cliente, porta):
    def troca_endereco(resposta):
        return crc16.anexa_crc(bytes((0x12,)) + resposta[1:-2])
    porta.perturbacoes = [troca_endereco] * 3
    with pytest.raises(RespostaInvalida):
        cliente.le_registradores(0x11, 0, 9)


def test_byte_count_errado_e_rejeitado(cliente, porta):
    def muda_byte_count(resposta):
        return crc16.anexa_crc(resposta[:2] + bytes((resposta[2] - 2,))
                               + resposta[3:-4])
    porta.perturbacoes = [muda_byte_count] * 3
    with pytest.raises(RespostaInvalida):
        cliente.le_registradores(0x11, 0, 9)


def test_bit_trocado_no_byte_count_e_repetido_como_na_bancada(porta):
    # rasp49: chegou 11 03 13 ... no lugar de 11 03 12 ...; a segunda tentativa
    # leu certo. A linha impressa precisa mostrar o quadro inteiro.
    linhas = []
    cliente = ClienteModbus(porta, MATRICULA, eco=linhas.append)
    porta.perturbacoes = [lambda r: r[:2] + bytes((r[2] ^ 1,)) + r[3:]]
    assert len(cliente.le_registradores(0x11, 0, 9)) == 9
    assert len(porta.enviados) == 2
    rx_ruim = next(l for l in linhas if l.startswith("  RX"))
    assert rx_ruim.startswith("  RX (23 B): 11 03 13")


def test_bit_trocado_na_funcao_da_excecao_e_crc_invalido(cliente, porta):
    # rasp50: chegou 11 92 02 BD C4, com o CRC de 11 90 02.
    porta.perturbacoes = [lambda r: r[:1] + bytes((r[1] ^ 2,)) + r[2:]]
    with pytest.raises(ExcecaoModbus):
        cliente.escreve_registradores(0x11, 0, [5])
    assert len(porta.enviados) == 2


def test_eco_da_escrita_divergente_e_rejeitado(cliente, porta):
    def muda_eco(_resposta):
        return crc16.anexa_crc(bytes.fromhex("11 10 00 04 00 01"))
    porta.perturbacoes = [muda_eco]
    with pytest.raises(RespostaInvalida):
        cliente.escreve_registradores(0x11, 3, [1])


# --------------------------------------------------------------- excecoes
def test_faixa_fora_do_mapa_da_excecao_2_sem_repetir(cliente, porta):
    with pytest.raises(ExcecaoModbus) as erro:
        cliente.le_registradores(0x11, 0, 20)
    assert erro.value.codigo == 0x02
    assert len(porta.enviados) == 1
    assert porta.enviados and porta.dispositivo.processa(porta.enviados[0]) \
        == EXEMPLO_EXCECAO


def test_escrita_em_somente_leitura_da_excecao_2(cliente):
    with pytest.raises(ExcecaoModbus) as erro:
        cliente.escreve_registradores(0x11, 0, [5])
    assert erro.value.codigo == 0x02
    assert erro.value.significado == "endereco invalido"


def test_valor_invalido_da_excecao_3(cliente):
    with pytest.raises(ExcecaoModbus) as erro:
        Elevadores(cliente).comanda_porta(1, 7)
    assert erro.value.codigo == 0x03


# ---------------------------------------------------- funcoes da Parte 3
def test_watchdog_e_derating(cliente, esp32):
    elevadores = Elevadores(cliente)
    estado = elevadores.le_estado_predio()
    assert estado["watchdog_ambiente"] == 1
    assert estado["barramento_max_ma"] == 3000
    elevadores.escreve_condicao_contorno(35.0, 1013)
    estado = elevadores.le_estado_predio()
    assert estado["watchdog_ambiente"] == 0
    assert estado["barramento_max_ma"] == 10000


def test_porta_abre_e_fecha(cliente, esp32):
    agora = [100.0]
    esp32._relogio = lambda: agora[0]
    elevadores = Elevadores(cliente)
    elevadores.comanda_porta(1, "abrir")
    assert elevadores.le_estado_cabine(1)["porta_estado"] == 1
    agora[0] += 2
    assert elevadores.le_estado_cabine(1)["porta_estado"] == 2
    elevadores.comanda_porta(1, "fechar")
    assert elevadores.le_estado_cabine(1)["porta_estado"] == 3
    agora[0] += 2
    assert elevadores.le_estado_cabine(1)["porta_estado"] == 0


def test_fluxo_de_uma_chamada(cliente, esp32):
    esp32.registra_chamada(0, 4)
    elevadores = Elevadores(cliente)
    chamada = elevadores.le_chamada_da_fila()
    assert chamada == {"na_fila": 1, "origem": 0, "destino": 4, "id": 1}
    elevadores.atribui_chamada(chamada["id"], 2)
    elevadores.remove_chamada_da_fila()
    assert elevadores.le_chamada_da_fila() is None
    assert esp32.atribuicoes == [(1, 2)]


def test_atribuicao_a_cabine_inexistente_nem_sai_da_raspberry(cliente, porta):
    with pytest.raises(ValueError):
        Elevadores(cliente).atribui_chamada(1, 4)
    assert porta.enviados == []
