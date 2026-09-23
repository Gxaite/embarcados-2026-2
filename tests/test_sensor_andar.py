"""Medicao da bandeirola pelas duas bordas."""
import time

from src.controle.sensor_andar import MedicaoBandeirola, SensorAndar
from src.gpio import pinos


class EncoderFalso:
    def __init__(self, contagem=0):
        self.contagem = contagem


def test_centro_e_a_media_das_duas_bordas():
    # Bandeirola do andar 1 (nominal 3000 mm), 84 mm de largura,
    # atravessada de 2958 a 3042: o centro e exatamente 3000.
    m = MedicaoBandeirola(2958, 3042, andar=1, instante=0.0)
    assert m.centro == 3000.0
    assert m.largura == 84
    assert m.erro == 0.0


def test_erro_aparece_quando_a_travessia_e_assimetrica():
    # Contador atrasado em 20 mm: as duas bordas vem deslocadas junto.
    m = MedicaoBandeirola(2938, 3022, andar=1, instante=0.0)
    assert m.centro == 2980.0
    assert m.erro == -20.0


def test_parar_na_primeira_borda_nao_nivela():
    """A razao de ser da media: a bandeirola e mais larga que a tolerancia."""
    entrada, saida = 2958, 3042
    erro_se_parasse_na_primeira_borda = abs(entrada - 3000)
    assert erro_se_parasse_na_primeira_borda > 10   # fora dos +-10 mm
    assert abs((entrada + saida) / 2 - 3000) <= 10  # a media nivela


def test_travessia_completa_registra_uma_medicao(gpio):
    encoder = EncoderFalso(2958)
    sensor = SensorAndar(gpio, encoder)

    gpio.muda(pinos.SENSOR_ANDAR, 1)     # entra na bandeirola
    time.sleep(0.02)
    encoder.contagem = 3042
    gpio.muda(pinos.SENSOR_ANDAR, 0)     # sai da bandeirola
    time.sleep(0.05)

    assert len(sensor.medicoes) == 1
    assert sensor.medicoes[0].centro == 3000.0
    assert sensor.medicoes[0].andar == 1


def test_saida_sem_entrada_correspondente_e_descartada(gpio):
    encoder = EncoderFalso(50)
    sensor = SensorAndar(gpio, encoder)
    gpio.valores[pinos.SENSOR_ANDAR] = 1   # comeca dentro, sem borda de subida
    gpio.muda(pinos.SENSOR_ANDAR, 0)
    time.sleep(0.05)
    assert sensor.medicoes == []


def test_travessia_incompleta_e_descartada(gpio):
    """Cabine para dentro da bandeirola e inverte: sai pelo lado da entrada."""
    encoder = EncoderFalso(2958)
    sensor = SensorAndar(gpio, encoder)

    gpio.muda(pinos.SENSOR_ANDAR, 1)     # entra na bandeirola subindo
    time.sleep(0.02)
    encoder.contagem = 2957              # parou dentro e voltou
    gpio.muda(pinos.SENSOR_ANDAR, 0)     # saiu pelo mesmo lado
    time.sleep(0.05)

    assert sensor.medicoes == [], "meia-travessia nao pode virar medicao"
