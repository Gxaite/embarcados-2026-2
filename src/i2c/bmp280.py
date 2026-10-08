"""Driver do BMP280 (Bosch), endereco 0x76.

O sensor entrega leituras cruas de 20 bits; temperatura e pressao de verdade
saem das formulas de compensacao do datasheet (Secao 8.1, versao em ponto
flutuante), alimentadas pelos 12 coeficientes de calibracao gravados em
fabrica em cada chip. Sem a compensacao o numero lido nao e grau nem pascal.

A temperatura tem de ser calculada antes da pressao: a compensacao da pressao
usa o t_fine que sai da temperatura.
"""
import struct
import threading
import time
from collections import namedtuple

ENDERECO_PADRAO = 0x76

REG_CALIBRACAO = 0x88       # 24 bytes, dig_T1..dig_P9
REG_ID = 0xD0
REG_RESET = 0xE0
REG_STATUS = 0xF3
REG_CTRL_MEAS = 0xF4
REG_CONFIG = 0xF5
REG_DADOS = 0xF7            # press_msb..temp_xlsb, 6 bytes

ID_DO_BMP280 = 0x58

# ctrl_meas: osrs_t x2 (010), osrs_p x16 (101), modo normal (11). E o perfil
# "indoor navigation" do datasheet; com ele o sensor mede sozinho e a leitura
# nao precisa esperar conversao.
CTRL_MEAS = 0b010_101_11
# config: t_sb 125 ms (010), filtro IIR coeficiente 4 (010), SPI 3 fios off.
CONFIG = 0b010_010_00
ESPERA_DA_PRIMEIRA_CONVERSAO_S = 0.1

Calibracao = namedtuple("Calibracao", "T1 T2 T3 P1 P2 P3 P4 P5 P6 P7 P8 P9")
Leitura = namedtuple("Leitura", "temperatura_c pressao_hpa")


class ErroBMP280(Exception):
    pass


def le_calibracao(bloco):
    return Calibracao(*struct.unpack("<HhhHhhhhhhhh", bytes(bloco)))


def cruas_de(bloco):
    """Separa os 6 bytes de dados em (adc_T, adc_P), 20 bits cada."""
    p = (bloco[0] << 12) | (bloco[1] << 4) | (bloco[2] >> 4)
    t = (bloco[3] << 12) | (bloco[4] << 4) | (bloco[5] >> 4)
    return t, p


def compensa_temperatura(adc_t, cal):
    """Devolve (temperatura em graus C, t_fine)."""
    var1 = (adc_t / 16384.0 - cal.T1 / 1024.0) * cal.T2
    var2 = ((adc_t / 131072.0 - cal.T1 / 8192.0) ** 2) * cal.T3
    t_fine = var1 + var2
    return t_fine / 5120.0, t_fine


def compensa_pressao(adc_p, t_fine, cal):
    """Devolve a pressao em Pa."""
    var1 = t_fine / 2.0 - 64000.0
    var2 = var1 * var1 * cal.P6 / 32768.0
    var2 = var2 + var1 * cal.P5 * 2.0
    var2 = var2 / 4.0 + cal.P4 * 65536.0
    var1 = (cal.P3 * var1 * var1 / 524288.0 + cal.P2 * var1) / 524288.0
    var1 = (1.0 + var1 / 32768.0) * cal.P1
    if var1 == 0:
        # Divisao por zero no datasheet: coeficientes zerados, sensor ausente
        # ou barramento devolvendo lixo.
        raise ErroBMP280("calibracao invalida (P1 = 0)")
    p = 1048576.0 - adc_p
    p = (p - var2 / 4096.0) * 6250.0 / var1
    var1 = cal.P9 * p * p / 2147483648.0
    var2 = p * cal.P8 / 32768.0
    return p + (var1 + var2 + cal.P7) / 16.0


class BMP280:
    def __init__(self, barramento, endereco=ENDERECO_PADRAO):
        self._barramento = barramento
        self.endereco = endereco
        self._trava = threading.Lock()
        identificador = self._barramento.le_bloco(endereco, REG_ID, 1)[0]
        if identificador != ID_DO_BMP280:
            raise ErroBMP280("chip id 0x%02X no endereco 0x%02X; esperado 0x%02X"
                             % (identificador, endereco, ID_DO_BMP280))
        self.calibracao = le_calibracao(
            self._barramento.le_bloco(endereco, REG_CALIBRACAO, 24))
        # No modo normal o datasheet avisa que a escrita em config pode ser
        # ignorada. O sensor pode ter ficado em normal desde a execucao
        # anterior, entao ele passa por sleep antes de configurar.
        self._barramento.escreve_byte(endereco, REG_CTRL_MEAS, 0x00)
        self._barramento.escreve_byte(endereco, REG_CONFIG, CONFIG)
        self._barramento.escreve_byte(endereco, REG_CTRL_MEAS, CTRL_MEAS)
        # A primeira conversao com estas sobreamostragens leva uns 44 ms; antes
        # dela os registradores de dados guardam o valor de reset.
        time.sleep(ESPERA_DA_PRIMEIRA_CONVERSAO_S)

    def le(self):
        """Le temperatura (graus C) e pressao (hPa)."""
        with self._trava:
            # Leitura em rajada dos 6 bytes: o sensor trava o registrador de
            # sombra durante ela, entao temperatura e pressao saem da mesma
            # conversao.
            bloco = self._barramento.le_bloco(self.endereco, REG_DADOS, 6)
        adc_t, adc_p = cruas_de(bloco)
        if adc_t == 0x80000 or adc_p == 0x80000:
            # 0x80000 e o valor de reset: a conversao ainda nao rodou.
            raise ErroBMP280("sensor sem medicao ainda (valor de reset)")
        temperatura, t_fine = compensa_temperatura(adc_t, self.calibracao)
        pressao_pa = compensa_pressao(adc_p, t_fine, self.calibracao)
        return Leitura(temperatura, pressao_pa / 100.0)
