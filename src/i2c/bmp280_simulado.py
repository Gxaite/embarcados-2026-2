"""Barramento I2C com um BMP280 de mentira.

Usa os coeficientes de calibracao do exemplo do datasheet (Secao 8.2). Para
devolver uma temperatura escolhida, a leitura crua e achada por bisseccao na
propria formula de compensacao, que e monotonica - assim o simulado passa pelo
mesmo caminho de calculo que o sensor real.
"""
import struct

from . import bmp280
from .barramento import BarramentoI2C

CALIBRACAO_DO_DATASHEET = bmp280.Calibracao(
    27504, 26435, -1000, 36477, -10685, 3024, 2855, 140, -7, 15500, -14600, 6000)
# Leituras cruas do mesmo exemplo: 25,08 graus C e 100653,27 Pa.
ADC_T_DO_DATASHEET = 519888
ADC_P_DO_DATASHEET = 415148


def _bissecciona(alvo, funcao, baixo=0, alto=(1 << 20) - 1, crescente=True):
    while alto - baixo > 1:
        meio = (baixo + alto) // 2
        if (funcao(meio) < alvo) == crescente:
            baixo = meio
        else:
            alto = meio
    return baixo


class BarramentoBMP280Simulado(BarramentoI2C):
    def __init__(self, temperatura_c=None, pressao_hpa=None):
        self.calibracao = CALIBRACAO_DO_DATASHEET
        self.registradores = {}
        self.adc_t = ADC_T_DO_DATASHEET
        self.adc_p = ADC_P_DO_DATASHEET
        if temperatura_c is not None:
            self.ajusta(temperatura_c, pressao_hpa)

    def ajusta(self, temperatura_c, pressao_hpa=None):
        cal = self.calibracao
        self.adc_t = _bissecciona(
            temperatura_c, lambda adc: bmp280.compensa_temperatura(adc, cal)[0])
        if pressao_hpa is not None:
            t_fine = bmp280.compensa_temperatura(self.adc_t, cal)[1]
            # A pressao compensada cai quando a leitura crua sobe.
            self.adc_p = _bissecciona(
                pressao_hpa * 100.0,
                lambda adc: bmp280.compensa_pressao(adc, t_fine, cal),
                crescente=False)

    def le_bloco(self, endereco, registrador, quantidade):
        if endereco != bmp280.ENDERECO_PADRAO:
            raise OSError("[Errno 121] Remote I/O error (sem escravo em 0x%02X)"
                          % endereco)
        if registrador == bmp280.REG_ID:
            return bytes((bmp280.ID_DO_BMP280,))[:quantidade]
        if registrador == bmp280.REG_CALIBRACAO:
            return struct.pack("<HhhHhhhhhhhh", *self.calibracao)[:quantidade]
        if registrador == bmp280.REG_DADOS:
            p, t = self.adc_p << 4, self.adc_t << 4
            return bytes(((p >> 16) & 0xFF, (p >> 8) & 0xFF, p & 0xFF,
                          (t >> 16) & 0xFF, (t >> 8) & 0xFF, t & 0xFF))[:quantidade]
        return bytes(self.registradores.get(registrador + i, 0)
                     for i in range(quantidade))

    def escreve_byte(self, endereco, registrador, valor):
        self.registradores[registrador] = valor

    def fecha(self):
        pass
