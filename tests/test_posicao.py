"""Conversoes, tolerancia de nivelamento e limites da bancada."""
from src.controle import posicao


def test_uma_contagem_e_um_milimetro():
    assert posicao.contagem_para_mm(3000) == 3000.0
    assert posicao.mm_para_contagem(6000.0) == 6000


def test_andares_da_bancada():
    assert posicao.POSICAO_ANDAR_MM == {0: 0.0, 1: 3000.0, 2: 6000.0}


def test_nivelamento_respeita_os_dez_milimetros():
    assert posicao.nivelado(3000.0, 1)
    assert posicao.nivelado(3010.0, 1)
    assert posicao.nivelado(2990.0, 1)
    assert not posicao.nivelado(3011.0, 1)
    assert not posicao.nivelado(2989.0, 1)


def test_andar_mais_proximo():
    assert posicao.andar_mais_proximo(100.0) == 0
    assert posicao.andar_mais_proximo(2900.0) == 1
    assert posicao.andar_mais_proximo(5000.0) == 2


def test_limites_de_fim_de_curso():
    assert posicao.dentro_dos_limites(0.0)
    assert posicao.dentro_dos_limites(6000.0)
    assert not posicao.dentro_dos_limites(-1.0)
    assert not posicao.dentro_dos_limites(6001.0)


def test_andar_invalido():
    assert not posicao.andar_valido(3)
    assert not posicao.andar_valido(-1)
