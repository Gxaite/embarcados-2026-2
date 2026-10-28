"""Testes rapidos dos modulos da Entrega Final, sem tempo real."""
import pytest

from src.central import cotas, despacho
from src.central.registro import RegistroDeChamadas
from src.distribuido import cota as cota_mod
from src.distribuido.bandeirola import INFERIOR, SUPERIOR, Borda
from src.distribuido.itinerario import DESEMBARQUE, EMBARQUE, Itinerario
from src.distribuido.mapa import ErroDeCalibracao, MapaDeAndares
from src.distribuido.pid import PID
from src.distribuido.porta import (ABERTA, FECHADA, FECHANDO, OBSTRUIDA,
                                   CicloDaPorta)
from src.rede import protocolo


class Relogio:
    def __init__(self, agora=0.0):
        self.agora = agora

    def __call__(self):
        return self.agora


def mapa_regular(deslocamento=0.0, largura=100.0):
    bordas = {}
    for andar in range(6):
        centro = 3000.0 * andar + deslocamento
        bordas[andar] = {
            "inferior_subindo": centro - largura / 2 + 2,
            "superior_subindo": centro + largura / 2 + 2,
            "superior_descendo": centro + largura / 2 - 2,
            "inferior_descendo": centro - largura / 2 - 2,
        }
    return MapaDeAndares(bordas)


# ---------------------------------------------------------- tempo real
def test_laco_periodico_em_tempo_absoluto_pula_ciclos_perdidos():
    import threading
    import time as tempo
    from src.tempo_real import LacoPeriodico
    encerrar = threading.Event()
    laco = LacoPeriodico(0.02, encerrar)
    instantes = []

    def ciclo():
        instantes.append(tempo.monotonic())
        if len(instantes) == 3:
            tempo.sleep(0.07)          # ciclo lento: perde 3 periodos
        if len(instantes) == 10:
            encerrar.set()

    laco.roda(ciclo)
    assert laco.ciclos_perdidos >= 3
    # Depois do atraso nao ha rajada: o intervalo seguinte nao e quase zero.
    intervalos = [b - a for a, b in zip(instantes, instantes[1:])]
    assert min(intervalos[3:]) > 0.01
    # Tempo absoluto: os ciclos caem na grade de 20 ms, sem deriva.
    inicio = instantes[0]
    for instante in instantes[4:]:
        fase = ((instante - inicio) / 0.02) % 1.0
        assert min(fase, 1 - fase) < 0.25


# ---------------------------------------------------------------- PID
def test_pid_satura_na_cota():
    pid = PID(0.5, 0.05, 5.0)
    assert pid.calcula(3000, 0, limite_saida=30.0) == 30.0
    assert pid.calcula(-3000, 0, limite_saida=30.0) == -30.0


def test_pid_nao_acumula_integral_saturado():
    pid = PID(0.5, 0.05, 0.0)
    for _ in range(100):
        pid.calcula(3000, 0, limite_saida=50.0)
    assert pid.integral == 0.0


def test_pid_so_integra_perto_do_destino():
    pid = PID(0.0, 0.05, 0.0)
    pid.calcula(500, 0, limite_saida=100)
    assert pid.integral == 0.0
    pid.calcula(20, 0, limite_saida=100)
    assert pid.integral == pytest.approx(1.0)


def test_pid_derivada_na_medida_ignora_troca_de_destino():
    pid = PID(0.0, 0.0, 10.0)
    pid.calcula(1000, 500, limite_saida=100)
    # Destino salta, cabine parada: a derivada da medida e zero.
    assert pid.calcula(4000, 500, limite_saida=100) == 0.0


def test_pid_desloca_medida_na_reancoragem():
    pid = PID(0.0, 0.0, 10.0)
    pid.calcula(1000, 500, limite_saida=100)
    pid.desloca_medida(20)
    assert pid.calcula(1000, 520, limite_saida=100) == 0.0


# --------------------------------------------------------------- Cota
def test_cota_vira_duty_pela_formula():
    assert cota_mod.duty_maximo_de(6000) == 100.0
    assert cota_mod.duty_maximo_de(3000) == 50.0
    assert cota_mod.duty_maximo_de(1000) == pytest.approx(16.67, abs=0.01)


def test_cota_vencida_cai_para_o_degradado():
    relogio = Relogio()
    cota = cota_mod.CotaDePotencia(relogio=relogio)
    assert not cota.valida
    cota.recebe(4000, 2.0, sequencia=7)
    assert cota.valida and cota.cota_ma == 4000 and cota.sequencia == 7
    relogio.agora = 1.97
    # Vence antes do proximo ciclo: o teto de degradado ja vale.
    assert cota.duty_maximo_durante(0.05) == pytest.approx(cota_mod.duty_maximo_de(
        1000, cota.corrente_parada_ma, cota.corrente_por_duty_ma))
    relogio.agora = 2.1
    assert not cota.valida and cota.cota_ma == 1000


def corrente_da_esp32(duty):
    """Medida na ESP32: 300 mA parada mais ~54 mA por ponto de duty."""
    return 300 + 54.0 * duty if duty else 300


def test_teto_pela_corrente_medida_cabe_na_cota():
    cota = cota_mod.CotaDePotencia(relogio=Relogio())
    cota.recebe(1000, 2.0)
    cota.mede_corrente(300, 0)
    cota.mede_corrente(1212, 16.67)       # medido na bancada em 22/10
    assert corrente_da_esp32(cota.duty_maximo) <= 1000
    cota.mede_corrente(None, 50)
    cota.mede_corrente(5000, 5)           # duty baixo demais para medir
    assert cota.corrente_por_duty_ma >= (1212 - 300) / 16.67


def test_teto_de_cruzeiro_usa_o_barramento():
    # rasp52: com Cota de 4000 mA as cabines cruzavam a 37% (2300 mA).
    cota = cota_mod.CotaDePotencia(relogio=Relogio())
    cota.recebe(4000, 2.0)
    cota.mede_corrente(300, 0)
    for _ in range(1000):
        cota.mede_corrente(corrente_da_esp32(37), 37)
    assert cota.duty_maximo > 60
    assert corrente_da_esp32(cota.duty_maximo) <= 4000 / cota_mod.FOLGA_DA_COTA


def test_teto_nunca_passa_da_formula():
    cota = cota_mod.CotaDePotencia(relogio=Relogio())
    cota.recebe(3000, 2.0)
    cota.mede_corrente(0, 0)
    for _ in range(2000):
        cota.mede_corrente(1000, 50)      # corrente bem abaixo da formula
    assert cota.duty_maximo == 50.0


def test_divisao_respeita_capacidade_e_teto():
    for capacidade in (3000, 10000, 11600, 12000, 18000):
        for ativas, ociosas in (([1, 2, 3], []), ([1], [2, 3]), ([], [1, 2, 3])):
            divisao = cotas.divide(capacidade, ativas, ociosas)
            assert sum(divisao.values()) <= capacidade
            assert all(v <= cotas.COTA_MAXIMA_MA for v in divisao.values())
            assert all(v >= min(1000, capacidade // 3) for v in divisao.values())


def test_divisao_privilegia_quem_tem_viagem():
    divisao = cotas.divide(12000, [1], [2, 3])
    assert divisao[1] == 6000 and divisao[2] == divisao[3] == 3000


def test_aumento_espera_a_reducao_ser_confirmada():
    relogio = Relogio()
    repartidor = cotas.RepartidorDeCotas(relogio=relogio)
    primeira = repartidor.reparte(12000, [1], [2, 3])
    for cabine, (_cota, seq) in primeira.items():
        repartidor.confirma(cabine, seq)
    relogio.agora = 1.0
    # Agora a cabine 2 precisa de potencia e a 1 ficou ociosa.
    segunda = repartidor.reparte(12000, [2], [1, 3])
    assert segunda[1][0] < primeira[1][0]
    # A 1 ainda pode estar usando os 6000 antigos: a 2 nao pode subir.
    assert segunda[2][0] + 6000 + primeira[3][0] <= 12000
    assert repartidor.soma_em_uso() <= 12000
    for cabine, (_cota, seq) in segunda.items():
        repartidor.confirma(cabine, seq)
    relogio.agora = 2.0
    terceira = repartidor.reparte(12000, [2], [1, 3])
    assert terceira[2][0] == 6000
    assert repartidor.soma_em_uso() <= 12000


def test_cota_nao_confirmada_vence_em_dois_segundos():
    relogio = Relogio()
    repartidor = cotas.RepartidorDeCotas(relogio=relogio)
    repartidor.reparte(12000, [1, 2, 3], [])
    assert repartidor.em_uso(1) == 4000
    relogio.agora = 2.5
    assert repartidor.em_uso(1) == 0


def test_cabine_sem_cota_tem_a_corrente_do_degradado_reservada():
    relogio = Relogio()
    repartidor = cotas.RepartidorDeCotas(relogio=relogio)
    envio = repartidor.reparte(11600, [1, 2], [], sem_cota=[3])
    assert 3 not in envio
    assert sum(c for c, _ in envio.values()) + 1000 <= 11600
    assert repartidor.soma_em_uso() <= 11600 - 1000


def test_sem_leitura_do_barramento_usa_o_piso():
    repartidor = cotas.RepartidorDeCotas(relogio=Relogio())
    envio = repartidor.reparte(None, [1, 2, 3], [])
    assert sum(c for c, _ in envio.values()) <= cotas.CAPACIDADE_DESCONHECIDA_MA


# --------------------------------------------------------------- mapa
def test_mapa_media_das_bordas_e_dos_sentidos():
    mapa = mapa_regular(deslocamento=37.0, largura=120.0)
    assert mapa.posicao[2] == pytest.approx(6037.0)
    assert mapa.largura(2) == pytest.approx(120.0)
    assert mapa.inferior[2] == pytest.approx(6037.0 - 60.0)


def test_mapa_recusa_vao_impossivel():
    bordas = {a: {"inferior_subindo": 3000 * a - 50, "superior_subindo": 3000 * a + 50,
                  "superior_descendo": 3000 * a + 50, "inferior_descendo": 3000 * a - 50}
              for a in range(6)}
    bordas[3] = {k: v - 1500 for k, v in bordas[3].items()}
    with pytest.raises(ErroDeCalibracao):
        MapaDeAndares(bordas)


def test_borda_cruzada_e_proximo_andar():
    mapa = mapa_regular()
    assert mapa.borda_cruzada(2955.0, INFERIOR, 80) == (1, pytest.approx(2950.0))
    assert mapa.borda_cruzada(2700.0, INFERIOR, 80) is None
    assert mapa.proximo_andar_no_sentido(4000.0, +1, 60) == 2
    assert mapa.proximo_andar_no_sentido(4000.0, -1, 60) == 1
    assert mapa.proximo_andar_no_sentido(5980.0, +1, 60) == 3


def test_lado_da_borda_pelo_sentido():
    assert Borda(True, 0, +1).lado == INFERIOR
    assert Borda(False, 0, +1).lado == SUPERIOR
    assert Borda(True, 0, -1).lado == SUPERIOR
    assert Borda(False, 0, -1).lado == INFERIOR
    assert Borda(True, 0, 0).lado is None


# ---------------------------------------------------------- itinerario
def test_scan_segue_o_sentido_antes_de_inverter():
    mapa = mapa_regular()
    itinerario = Itinerario()
    itinerario.atribui(1, 4, 0)
    itinerario.atribui(2, 1, 5)
    itinerario.sentido = 1
    # Cabine no andar 2 subindo: atende o 4 antes de descer para o 1.
    assert itinerario.proxima_parada(6000.0, mapa, None) == 4
    itinerario.sentido = -1
    assert itinerario.proxima_parada(6000.0, mapa, None) == 1


def test_embarque_e_desembarque_quando_a_porta_abre():
    itinerario = Itinerario(relogio=lambda: 100.0)
    assert itinerario.atribui(7, 2, 4)
    assert not itinerario.atribui(7, 2, 4), "repeticao deveria ser ignorada"
    eventos = itinerario.porta_abriu(2)
    assert [(e["id"], e["evento"]) for e in eventos] == [(7, EMBARQUE)]
    assert itinerario.paradas() == {4}
    eventos = itinerario.porta_abriu(4)
    assert [(e["id"], e["evento"]) for e in eventos] == [(7, DESEMBARQUE)]
    assert itinerario.paradas() == set()
    assert not itinerario.atribui(7, 2, 4), "concluida nao volta"


# ----------------------------------------------------------- despacho
def estado_de_cabine(posicao, paradas=(), modo="operando"):
    return {"calibrada": True, "modo": modo, "posicao_mm": posicao,
            "sentido": "parado", "paradas": list(paradas), "alvo": None,
            "porta_ciclo": "ociosa", "mapa": None}


def test_despacho_escolhe_a_mais_proxima_ociosa():
    estados = {1: estado_de_cabine(0.0), 2: estado_de_cabine(9000.0),
               3: estado_de_cabine(15000.0)}
    escolhida, _ = despacho.escolhe(estados, origem=3, destino=0)
    assert escolhida == 2


def test_despacho_ignora_cabine_indisponivel():
    estados = {1: None, 2: estado_de_cabine(9000.0, modo="degradado"),
               3: estado_de_cabine(15000.0, modo="calibrando")}
    assert despacho.escolhe(estados, 3, 0) == (None, {})
    estados[3] = estado_de_cabine(15000.0)
    assert despacho.escolhe(estados, 3, 0)[0] == 3


def test_despacho_evita_sobrecarregar_uma_cabine():
    livre = estado_de_cabine(3000.0)
    cheia = estado_de_cabine(3000.0, paradas=(0, 2, 4, 5))
    escolhida, _ = despacho.escolhe({1: cheia, 2: livre}, origem=1, destino=3)
    assert escolhida == 2


def test_despacho_nao_empurra_espera_alem_de_90_s():
    perto = estado_de_cabine(6000.0, paradas=(1, 0))
    perto["sentido"] = "descendo"
    perto["esperando"] = {1: 80.0}
    longe = estado_de_cabine(15000.0)
    # A cabine "perto" atenderia a origem 3 antes, mas atrasaria quem espera ha
    # 80 s no andar 1.
    escolhida, custos = despacho.escolhe({1: perto, 2: longe}, origem=3, destino=5)
    assert escolhida == 2 and custos[1] > despacho.PENALIDADE_S


def test_despacho_respeita_a_lotacao():
    # Down-peak na rasp52: a mesma cabine recebia o andar inteiro e chegou ao
    # terreo com 11 passageiros (sobrecarga na ESP32).
    cheia = estado_de_cabine(6000.0, paradas=(2, 0))
    cheia["comprometidos"] = despacho.LOTACAO
    livre = estado_de_cabine(15000.0)
    escolhida, custos = despacho.escolhe({1: cheia, 2: livre}, origem=2, destino=0)
    assert escolhida == 2 and custos[1] > despacho.PENALIDADE_S


def test_despacho_segue_a_varredura_da_cabine_parada_no_andar():
    # Up-peak no simulador: parada no andar 1 com passageiros para 2, 3 e 4, a
    # cabine sobe antes de voltar ao terreo. Estimada como descendo, recebeu a
    # chamada do terreo, que esperou 92 s.
    subindo = estado_de_cabine(3000.0, paradas=(1, 2, 3, 4))
    subindo["porta_ciclo"] = "abrindo"
    subindo["varredura"] = 1
    longe = estado_de_cabine(9000.0)
    escolhida, custos = despacho.escolhe({1: subindo, 2: longe}, origem=0, destino=1)
    assert escolhida == 2 and custos[1] > despacho.PENALIDADE_S


def test_origem_urgente_passa_na_frente_do_scan():
    relogio = Relogio(1000.0)
    mapa = mapa_regular()
    itinerario = Itinerario(relogio=relogio)
    itinerario.atribui(1, 5, 2, espera_s=0.0)
    itinerario.atribui(2, 0, 3, espera_s=55.0)
    itinerario.sentido = 1
    assert itinerario.proxima_parada(6000.0, mapa, None) == 0


def test_sobrepasso_no_andar_urgente_nao_inverte_a_varredura():
    # Down-peak no simulador: subindo para a origem urgente no 4, a cabine
    # passou 3 mm do andar; depois do embarque descia para o 0 e largava o 5.
    relogio = Relogio(1000.0)
    mapa = mapa_regular()
    itinerario = Itinerario(relogio=relogio)
    itinerario.atribui(1, 4, 0, espera_s=55.0)
    itinerario.atribui(2, 5, 4, espera_s=30.0)
    itinerario.sentido = 1
    assert itinerario.proxima_parada(mapa.posicao[4] + 3.0, mapa, None) == 4
    itinerario.porta_abriu(4)
    assert itinerario.proxima_parada(mapa.posicao[4] + 3.0, mapa, 4) == 5


# -------------------------------------------------------------- porta
class PortaFalsa:
    def __init__(self):
        self.comandos = []
        self.obstruida = False


def ciclo_de_porta(relogio, falsa):
    return CicloDaPorta(falsa.comandos.append, lambda: None, lambda: falsa.obstruida,
                        tempo_aberta_s=3.0, relogio=relogio)


def test_ciclo_completo_da_porta():
    relogio, falsa = Relogio(), PortaFalsa()
    porta = ciclo_de_porta(relogio, falsa)
    porta.abre()
    assert falsa.comandos == ["abrir"]
    relogio.agora = 1.5
    porta.registradores(ABERTA, relogio.agora)
    porta.passo()
    assert porta.abriu
    relogio.agora = 4.6
    porta.passo()
    assert falsa.comandos == ["abrir", "fechar"]
    relogio.agora = 6.0
    porta.registradores(FECHADA, relogio.agora)
    porta.passo()
    assert porta.fechada


def test_cortina_inibe_e_reinicia_o_fechamento():
    relogio, falsa = Relogio(), PortaFalsa()
    porta = ciclo_de_porta(relogio, falsa)
    porta.abre()
    relogio.agora = 1.5
    porta.registradores(ABERTA, relogio.agora)
    porta.passo()
    relogio.agora = 4.6
    porta.passo()
    assert falsa.comandos[-1] == "fechar"
    relogio.agora = 5.0
    falsa.obstruida = True
    porta.ao_mudar_cortina(True)
    porta.registradores(OBSTRUIDA, relogio.agora)
    for instante in (5.5, 6.0, 9.0):
        relogio.agora = instante
        porta.passo()
    assert falsa.comandos.count("fechar") == 1, "fechou com a cortina ativa"
    relogio.agora = 9.5
    falsa.obstruida = False
    porta.ao_mudar_cortina(False)
    relogio.agora = 10.1
    porta.passo()
    assert falsa.comandos.count("fechar") == 2
    relogio.agora = 11.0
    porta.registradores(FECHANDO, relogio.agora)
    porta.passo()
    relogio.agora = 12.5
    porta.registradores(FECHADA, relogio.agora)
    porta.passo()
    assert porta.fechada


def test_porta_aberta_no_degradado_nao_fecha_sozinha():
    relogio, falsa = Relogio(), PortaFalsa()
    porta = ciclo_de_porta(relogio, falsa)
    porta.abre(manter=True)
    relogio.agora = 1.5
    porta.registradores(ABERTA, relogio.agora)
    porta.passo()
    relogio.agora = 60.0
    porta.passo()
    assert "fechar" not in falsa.comandos


# ----------------------------------------------------------- registro
def test_registro_persiste_e_gera_log(tmp_path):
    estado, viagens = str(tmp_path / "estado.json"), str(tmp_path / "viagens.csv")
    relogio = Relogio(1000.0)
    registro = RegistroDeChamadas(estado, viagens, relogio=relogio)
    registro.nova(5, 0, 3, cabine=2)
    registro.nova(6, 4, 1, cabine=1)
    assert registro.aplica_evento(2, {"id": 5, "evento": "embarque", "t": 1010.0})
    assert registro.aplica_evento(2, {"id": 5, "evento": "embarque", "t": 1010.0}) is None
    assert registro.aplica_evento(1, {"id": 5, "evento": "desembarque", "t": 1020.0}) is None

    restaurado = RegistroDeChamadas(estado, viagens, relogio=relogio)
    assert restaurado.carrega() == 2
    assert restaurado.pendentes[5].embarque == 1010.0
    assert restaurado.aplica_evento(2, {"id": 5, "evento": "desembarque", "t": 1030.0})
    metricas = restaurado.metricas()
    assert metricas["concluidas"] == 1
    assert metricas["espera_media_s"] == pytest.approx(10.0)
    assert metricas["viagem_media_s"] == pytest.approx(20.0)
    linhas = open(viagens).read().splitlines()
    assert linhas[0].startswith("id,origem,destino,cabine,registro,embarque,desembarque")
    assert linhas[1].startswith("5,0,3,2,")


# ---------------------------------------------------------- protocolo
def test_protocolo_ida_e_volta():
    mensagem = {"tipo": "cota", "cota_ma": 4000, "validade_s": 2.0, "seq": 3}
    linha = protocolo.codifica(mensagem)
    assert linha.endswith(b"\n") and linha.count(b"\n") == 1
    assert protocolo.decodifica(linha.strip()) == mensagem
    with pytest.raises(protocolo.MensagemInvalida):
        protocolo.decodifica(b'{"sem": "tipo"}')
    with pytest.raises(protocolo.MensagemInvalida):
        protocolo.decodifica(b"lixo")
