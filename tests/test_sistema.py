"""Sistema completo contra o predio simulado: calibracao, despacho, cotas.

Roda em tempo real (uns 3 minutos): as tres cabines calibram de verdade,
pelas interrupcoes do Sensor de Andar, e atendem chamadas com o TCP de
verdade em localhost. Pular com: pytest -m "not lento".
"""
import threading
import time

import pytest

from src.simulacao import poco
from src.simulacao.__main__ import finaliza, inicia, monta

pytestmark = pytest.mark.lento


def espera(condicao, limite_s):
    fim = time.monotonic() + limite_s
    while time.monotonic() < fim:
        if condicao():
            return True
        time.sleep(0.2)
    return False


@pytest.fixture(scope="module")
def sistema(tmp_path_factory):
    pasta = str(tmp_path_factory.mktemp("simulacao"))
    sistema = monta(perda_de_transicoes=0.0005, andares_iniciais=(0, 3, 5), pasta=pasta,
                    deslocamento_de_portas=2000)
    sistema["amostras"] = {"soma_acima": 0, "cota_acima": 0}
    parar = threading.Event()

    def vigia():
        predio, central = sistema["predio"], sistema["central"]
        while not parar.wait(0.02):
            capacidade = central.capacidade_ma()
            if capacidade is None:
                continue
            if sum(f.corrente_ma for f in predio.fisicas.values()) > capacidade + 1:
                sistema["amostras"]["soma_acima"] += 1
            for numero, cabine in sistema["cabines"].items():
                if predio.fisicas[numero].corrente_ma > cabine.cota.cota_ma + 1:
                    sistema["amostras"]["cota_acima"] += 1

    threading.Thread(target=vigia, daemon=True).start()
    inicia(sistema)
    yield sistema
    parar.set()
    finaliza(sistema)


def test_calibracao_encontra_os_andares_reais(sistema):
    cabines, predio = sistema["cabines"], sistema["predio"]
    assert espera(lambda: all(c.mapa is not None for c in cabines.values()), 200), \
        "calibracao nao terminou"
    for numero, cabine in cabines.items():
        reais = predio.fisicas[numero].andares_mm
        # A contagem e relativa: o que tem de bater e cada andar contra o 0.
        for andar in range(1, 6):
            medido = cabine.mapa.posicao[andar] - cabine.mapa.posicao[0]
            real = reais[andar] - reais[0]
            assert medido == pytest.approx(real, abs=6.0), \
                "cabine %d andar %d: %.1f medido, %.1f real" % (numero, andar, medido, real)


def test_atende_chamadas_sem_violar_invariantes(sistema):
    predio, central = sistema["predio"], sistema["central"]
    assert espera(lambda: all(c.modo == "operando" for c in sistema["cabines"].values()), 30)
    for origem, destino in ((0, 4), (3, 1), (5, 0), (2, 5), (0, 3), (4, 2)):
        predio.registra_chamada(origem, destino)
    assert espera(lambda: predio.metricas(so_do_cenario=False)["atendidas"] == 6, 150), \
        "nem todas as chamadas foram atendidas: %s" % predio.metricas(so_do_cenario=False)
    metricas = predio.metricas(so_do_cenario=False)
    assert metricas["espera_maxima_s"] < 90.0
    assert predio.violacoes() == {1: [], 2: [], 3: []}
    assert sistema["amostras"] == {"soma_acima": 0, "cota_acima": 0}
    # O desembarque chega ao central no relatorio seguinte da cabine, ate ~1 s
    # depois de o simulador registra-lo.
    assert espera(lambda: central.registro.metricas()["concluidas"] == 6, 5)
    # As cabines que andaram atribuiram chamadas a mais de uma cabine.
    assert len({c.cabine for c in predio.chamadas.values()}) >= 2


def test_reancoragem_segura_a_deriva(sistema):
    for numero, cabine in sistema["cabines"].items():
        fisica = sistema["predio"].fisicas[numero]
        referencia = fisica.andares_mm[0] - cabine.mapa.posicao[0]
        erro = fisica.posicao_mm - (cabine.encoder.contagem + referencia)
        assert abs(erro) < 8.0, "cabine %d com %.1f mm de deriva" % (numero, erro)


def test_modo_degradado_pousa_e_abre_a_porta(sistema):
    predio, central = sistema["predio"], sistema["central"]
    cabine, fisica = sistema["cabines"][1], predio.fisicas[1]
    central.envia_cabine_ao_andar(1, 5 if fisica.posicao_mm < 7000 else 0)
    assert espera(lambda: abs(fisica.velocidade_mm_s) > 300, 20)
    central.corta_cota(1, 25)
    assert espera(lambda: cabine.modo == "degradado", 5)
    assert espera(lambda: fisica.porta_estado == 2 and fisica.parada(), 40), \
        "a cabine nao pousou com a porta aberta"
    assert fisica.nivelado()
    assert fisica.corrente_ma <= poco.CORRENTE_EM_REPOUSO_MA, "motor ainda acionado"
    time.sleep(3)
    assert fisica.porta_estado == 2, "a porta tem de ficar aberta sem Cota"
    assert espera(lambda: cabine.modo == "operando", 30)
    assert espera(lambda: fisica.porta_estado == 0, 15), "nao fechou ao voltar a Cota"
    assert predio.violacoes()[1] == []
