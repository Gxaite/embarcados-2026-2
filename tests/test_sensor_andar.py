"""Medicao da bandeirola pelas duas bordas (requisito 7)."""
import time

from src.controle.sensor_andar import SensorAndar
from src.gpio import pinos


class EncoderFalso:
    def __init__(self):
        self.contagem = 0


def atravessa(backend, encoder, entrada_mm, saida_mm, espera=0.03):
    encoder.contagem = entrada_mm
    backend.provoca(pinos.SENSOR_ANDAR, 1)
    time.sleep(espera)
    encoder.contagem = saida_mm
    backend.provoca(pinos.SENSOR_ANDAR, 0)
    time.sleep(espera)


def test_centro_e_a_media_das_duas_bordas(backend):
    encoder = EncoderFalso()
    sensor = SensorAndar(backend, encoder)
    atravessa(backend, encoder, 2940, 3060)     # bandeirola de 120 mm
    assert len(sensor.medicoes) == 1
    medicao = sensor.medicoes[0]
    assert medicao.largura_mm == 120
    assert medicao.centro_mm == 3000
    assert medicao.erro_mm == 0
    assert medicao.andar == 1


def test_erro_em_relacao_ao_nominal(backend):
    encoder = EncoderFalso()
    sensor = SensorAndar(backend, encoder)
    atravessa(backend, encoder, 2950, 3090)     # centro em 3020
    assert sensor.medicoes[0].centro_mm == 3020
    assert sensor.medicoes[0].erro_mm == 20


def test_larguras_diferentes_por_andar(backend):
    """Nao da para deduzir o centro de uma borda so: cada andar tem sua largura."""
    encoder = EncoderFalso()
    sensor = SensorAndar(backend, encoder)
    atravessa(backend, encoder, -60, 60)        # andar 0, 120 mm
    atravessa(backend, encoder, 2958, 3042)     # andar 1, 84 mm
    atravessa(backend, encoder, 5925, 6075)     # andar 2, 150 mm
    assert [m.largura_mm for m in sensor.medicoes] == [120, 84, 150]
    assert [m.andar for m in sensor.medicoes] == [0, 1, 2]
    assert all(m.erro_mm == 0 for m in sensor.medicoes)


def test_travessia_incompleta_e_descartada(backend):
    """Entrou e saiu pelo mesmo lado: a media cairia numa extremidade."""
    encoder = EncoderFalso()
    sensor = SensorAndar(backend, encoder)
    atravessa(backend, encoder, 2940, 2945)
    assert sensor.medicoes == []


def test_saida_sem_entrada_nao_gera_medicao(backend):
    """Comecar ja dentro da bandeirola nao produz medicao valida."""
    encoder = EncoderFalso()
    sensor = SensorAndar(backend, encoder)
    encoder.contagem = 60
    backend.provoca(pinos.SENSOR_ANDAR, 0)
    time.sleep(0.03)
    assert sensor.medicoes == []


def test_travessia_curta_demais_da_bancada_e_descartada(backend):
    """Caso real da rasp42: 34 mm de largura, 102 mm fora do nominal.

    As bandeirolas reais tem 142 a 242 mm. Uma travessia de 34 mm e a cabine
    entrando e saindo pelo mesmo lado, ou ruido - nunca uma bandeirola.
    """
    encoder = EncoderFalso()
    sensor = SensorAndar(backend, encoder)
    atravessa(backend, encoder, 2881, 2915)
    assert sensor.medicoes == []


def test_bandeirolas_reais_da_bancada_sao_aceitas(backend):
    """Larguras medidas na rasp42 em 23/09/2026."""
    encoder = EncoderFalso()
    sensor = SensorAndar(backend, encoder)
    atravessa(backend, encoder, 2879, 3121)     # andar 1: 242 mm
    atravessa(backend, encoder, 5929, 6071)     # andar 2: 142 mm
    assert [m.largura_mm for m in sensor.medicoes] == [242, 142]
    assert [m.andar for m in sensor.medicoes] == [1, 2]
    assert all(m.erro_mm == 0 for m in sensor.medicoes)
