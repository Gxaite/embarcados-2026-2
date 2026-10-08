"""BMP280 e servico da Condicao de Contorno."""
import pytest

from src.central.condicao_contorno import ServicoCondicaoContorno
from src.i2c import bmp280
from src.i2c.bmp280_simulado import (ADC_P_DO_DATASHEET, ADC_T_DO_DATASHEET,
                                     CALIBRACAO_DO_DATASHEET,
                                     BarramentoBMP280Simulado)
from src.uart.elevadores import Elevadores
from src.uart.esp32_simulada import Esp32Simulada, PortaSimulada
from src.uart.matricula import em_bytes
from src.uart.modbus import ClienteModbus


def test_compensacao_bate_com_o_exemplo_do_datasheet():
    temperatura, t_fine = bmp280.compensa_temperatura(
        ADC_T_DO_DATASHEET, CALIBRACAO_DO_DATASHEET)
    pressao = bmp280.compensa_pressao(ADC_P_DO_DATASHEET, t_fine,
                                      CALIBRACAO_DO_DATASHEET)
    assert temperatura == pytest.approx(25.08, abs=0.01)
    assert pressao == pytest.approx(100653.27, abs=0.5)


def test_driver_le_pelo_barramento():
    sensor = bmp280.BMP280(BarramentoBMP280Simulado(temperatura_c=31.2,
                                                    pressao_hpa=887.0))
    leitura = sensor.le()
    assert leitura.temperatura_c == pytest.approx(31.2, abs=0.01)
    assert leitura.pressao_hpa == pytest.approx(887.0, abs=0.05)


def test_driver_configura_o_sensor():
    barramento = BarramentoBMP280Simulado()
    bmp280.BMP280(barramento)
    assert barramento.registradores[bmp280.REG_CTRL_MEAS] == bmp280.CTRL_MEAS
    assert barramento.registradores[bmp280.REG_CONFIG] == bmp280.CONFIG


def test_chip_errado_e_recusado():
    class OutroChip(BarramentoBMP280Simulado):
        def le_bloco(self, endereco, registrador, quantidade):
            if registrador == bmp280.REG_ID:
                return b"\x60"           # BME280
            return super().le_bloco(endereco, registrador, quantidade)
    with pytest.raises(bmp280.ErroBMP280):
        bmp280.BMP280(OutroChip())


def test_separacao_das_leituras_cruas():
    assert bmp280.cruas_de(bytes((0x65, 0x5A, 0xC0, 0x7E, 0xED, 0x00))) \
        == (519888, 415148)


# ------------------------------------------------------------------ servico
@pytest.fixture
def cadeia():
    esp32 = Esp32Simulada()
    cliente = ClienteModbus(PortaSimulada(esp32), em_bytes("654321"), eco=None)
    sensor = bmp280.BMP280(BarramentoBMP280Simulado(temperatura_c=35.0,
                                                    pressao_hpa=1013.0))
    mensagens = []
    servico = ServicoCondicaoContorno(sensor, Elevadores(cliente),
                                      eco=mensagens.append)
    return esp32, servico, mensagens


def test_um_ciclo_satisfaz_o_watchdog_e_aplica_derating(cadeia):
    esp32, servico, _ = cadeia
    assert esp32.barramento_max_ma() == 3000
    servico.executa_uma_vez()
    assert esp32.temperatura_x10 == 350
    assert esp32.pressao_hpa == 1013
    assert not esp32.watchdog_expirado()
    assert esp32.barramento_max_ma() == 10000


def test_thread_escreve_na_partida_e_para(cadeia):
    esp32, servico, _ = cadeia
    servico.inicia()
    try:
        for _ in range(100):
            if servico.escritas:
                break
            servico._parar.wait(0.01)
    finally:
        servico.para()
    assert servico.escritas >= 1
    assert not servico.ativo
    assert not esp32.watchdog_expirado()


def test_falha_e_registrada_uma_vez_e_a_thread_sobrevive(cadeia):
    _, servico, mensagens = cadeia
    servico._elevadores.cliente._porta.perturbacoes = [lambda _r: None] * 6
    servico._ciclo()
    servico._ciclo()
    assert servico.falhas == 2
    assert len([m for m in mensagens if "falha" in m]) == 1
    servico._ciclo()
    assert servico.escritas == 1
    assert any("recuperado" in m for m in mensagens)


def test_periodo_acima_de_5_s_e_recusado(cadeia):
    _, servico, _ = cadeia
    with pytest.raises(ValueError):
        ServicoCondicaoContorno(servico._sensor, servico._elevadores, periodo_s=6)
