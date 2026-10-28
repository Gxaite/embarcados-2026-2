"""Despacho por Destino (Secao 7.5).

A chamada vai para a cabine de menor custo, e o custo e uma estimativa de
tempo: quanto o passageiro novo vai esperar ate a porta abrir no andar de
origem, mais quanto a parada nova atrasa quem ja esta atribuido a cabine, mais
uma fracao da viagem dele (que as paradas da cabine no caminho alongam).

A estimativa simula o itinerario da cabine com a mesma regra que ela executa
(escolhe_parada, em src/distribuido/itinerario.py): SCAN, sem parar no
caminho para quem vai no sentido contrario, e o destino de quem embarca vira
parada. Cada trecho custa distancia / velocidade de cruzeiro, e cada parada o
ciclo da porta. Uma chamada cuja origem ja e parada da cabine nao acrescenta
parada - e o agrupamento de passageiros que o despacho por destino existe
para aproveitar.

So entram cabines conectadas, calibradas e operando. Sem nenhuma, a chamada
fica na fila do simulador, e nao e retirada: o invariante e que toda chamada
retirada da fila seja atendida.
"""
from ..distribuido.itinerario import escolhe_parada, sentido_da_viagem

# Modelo de tempo, medido nas viagens do simulador (ferramentas/experimentos.py
# pid): um trecho custa distancia / velocidade de cruzeiro mais um custo fixo
# de arranque e aproximacao; uma parada custa o ciclo da porta.
VELOCIDADE_POR_DUTY_MM_S = 10.0   # padrao, ate o central medir a da cabine
TEMPO_DE_ARRANQUE_S = 6.5
TEMPO_DE_PARADA_S = 5.5          # abrir 1,5 + aberta 1,5 + fechar 1,5 + folga
# Pesos menores (eram 0,5 e 0,25) favorecem a cabine que ja cobre a rota.
PESO_DO_ATRASO_DOS_OUTROS = 0.40
PESO_DA_VIAGEM = 0.20
VAO_MM = 3000.0
NO_ANDAR_MM = 10.0
# Invariante da Secao 7.5: ninguem espera mais de 90 s pelo embarque. A
# estimativa tem erro, entao o limite usado aqui tem folga.
ESPERA_MAXIMA_S = 90.0
FOLGA_DA_ESPERA_S = 15.0
PENALIDADE_S = 1000.0
# A ESP32 acusa sobrecarga (bit 0x0010 de `falha`) com 8 passageiros a bordo:
# na rasp52 ela ligou nas tres cabines no terreo, quando o agrupamento do
# up-peak embarcou 8 de uma vez. A lotacao e conferida no itinerario simulado,
# instante a instante; a cabine que passaria dela nao recebe a chamada.
LOTACAO = 7


def _simula(posicao_mm, sentido, chamadas, manuais, posicoes, velocidade_mm_s):
    """Percorre o itinerario na ordem em que a cabine o executa (a mesma
    escolhe_parada de src/distribuido/itinerario.py) e devolve, por chamada,
    [instante do embarque, instante do desembarque] a partir de agora.

    chamadas: lista de (origem, destino ou None, ja embarcada)."""
    pendentes = {i: [o, d, emb] for i, (o, d, emb) in enumerate(chamadas)}
    instantes = {i: [0.0 if emb else None, None] for i, (_, _, emb) in enumerate(chamadas)}
    manuais = set(manuais)
    tempo = 0.0
    for _ in range(2 * len(chamadas) + len(manuais) + 1):
        obrigatorias = manuais | {d for _, d, emb in pendentes.values() if emb}
        embarques = [(o, sentido_da_viagem(o, d)) for o, d, emb in pendentes.values()
                     if not emb]
        andar, sentido = escolhe_parada(posicao_mm, sentido, obrigatorias, embarques,
                                        posicoes)
        if andar is None:
            break
        distancia = abs(posicoes[andar] - posicao_mm)
        if distancia > NO_ANDAR_MM:
            tempo += distancia / velocidade_mm_s + TEMPO_DE_ARRANQUE_S
        posicao_mm = posicoes[andar]
        manuais.discard(andar)
        for i, chamada in list(pendentes.items()):
            origem, destino, embarcada = chamada
            if embarcada and destino == andar:
                instantes[i][1] = tempo
                del pendentes[i]
            elif not embarcada and origem == andar:
                instantes[i][0] = tempo
                if destino is None:
                    del pendentes[i]
                else:
                    chamada[2] = True
        tempo += TEMPO_DE_PARADA_S
    return instantes


def _lotacao_maxima(instantes):
    """Maior numero de passageiros a bordo ao mesmo tempo no itinerario
    simulado. No mesmo instante quem desce sai antes de quem embarca."""
    eventos = []
    for embarque, desembarque in instantes.values():
        if embarque is None:
            continue
        eventos.append((embarque, 1))
        if desembarque is not None:
            eventos.append((desembarque, -1))
    a_bordo = maior = 0
    for _, variacao in sorted(eventos):
        a_bordo += variacao
        maior = max(maior, a_bordo)
    return maior


def velocidade_de_cruzeiro(estado):
    por_duty = estado.get("velocidade_por_duty") or VELOCIDADE_POR_DUTY_MM_S
    duty = estado.get("duty_maximo") or 16.7
    return max(50.0, por_duty * duty)


def custo(estado, origem, destino):
    """Segundos estimados para atender a chamada nesta cabine, ou None se ela
    passaria da lotacao.

    estado["chamadas_do_central"] sao as chamadas ja atribuidas a ela e nao
    concluidas ({origem, destino, embarcada, idade_s}); estado["paradas"], as
    paradas dela, de onde saem os comandos manuais; estado["comprometidos"],
    quantas chamadas ela tem. estado["esperando"] ({origem: idade}, destino
    desconhecido) tambem e aceito."""
    posicoes = {int(a): v["posicao_mm"] for a, v in (estado.get("mapa") or {}).items()}
    if not posicoes:
        posicoes = {a: a * VAO_MM for a in range(6)}
    posicao = estado.get("posicao_mm") or 0.0
    sentido = {"subindo": 1, "descendo": -1}.get(estado.get("sentido"), 0)
    alvo = estado.get("alvo")
    if sentido == 0 and alvo is not None:
        sentido = 1 if posicoes[alvo] > posicao else -1
    if sentido == 0:
        # Parada num andar (porta abrindo ou aberta): ela segue a varredura do
        # itinerario, e nao para o lado da parada mais perto.
        sentido = estado.get("varredura") or 0
    chamadas, idades = [], []
    for chamada in estado.get("chamadas_do_central") or []:
        chamadas.append((chamada["origem"], chamada["destino"], chamada["embarcada"]))
        idades.append(None if chamada["embarcada"] else chamada.get("idade_s", 0.0))
    for andar, idade in (estado.get("esperando") or {}).items():
        chamadas.append((andar, None, False))
        idades.append(idade)
    manuais = set(estado.get("paradas") or []) \
        - {d if emb else o for o, d, emb in chamadas}
    velocidade = velocidade_de_cruzeiro(estado)

    antes = _simula(posicao, sentido, chamadas, manuais, posicoes, velocidade)
    depois = _simula(posicao, sentido, chamadas + [(origem, destino, False)], manuais,
                     posicoes, velocidade)
    # A porta ainda ocupada atrasa tudo meio ciclo.
    porta = TEMPO_DE_PARADA_S / 2 if estado.get("porta_ciclo") not in (None, "ociosa") \
        else 0.0
    embarque, desembarque = depois[len(chamadas)]
    if embarque is None:
        return PENALIDADE_S * 10
    if _lotacao_maxima(depois) > LOTACAO:
        return None
    espera = embarque + porta
    viagem = (desembarque if desembarque is not None else embarque) - embarque
    # O atraso imposto a cada chamada ja atribuida, no proximo evento dela:
    # o embarque de quem espera, o desembarque de quem esta a bordo.
    atraso = 0.0
    for i, (_, _, embarcada) in enumerate(chamadas):
        k = 1 if embarcada else 0
        if antes[i][k] is not None and depois[i][k] is not None:
            atraso += max(0.0, depois[i][k] - antes[i][k])
    total = espera + PESO_DO_ATRASO_DOS_OUTROS * atraso + PESO_DA_VIAGEM * viagem

    limite = ESPERA_MAXIMA_S - FOLGA_DA_ESPERA_S
    previstas = [espera] + [idade + depois[i][0] + porta for i, idade in enumerate(idades)
                            if idade is not None and depois[i][0] is not None]
    estouro = max(previstas) - limite
    if estouro > 0:
        total += PENALIDADE_S + estouro
    return total


def disponivel(estado):
    return bool(estado) and estado.get("calibrada") and estado.get("modo") == "operando"


def escolhe(estados, origem, destino):
    """Numero da cabine escolhida, ou None se nenhuma pode atender (todas fora
    de operacao ou lotadas: a chamada espera na fila do simulador).

    estados: {cabine: ultimo relatorio de estado, ou None se desconectada}.
    """
    candidatas = {}
    for numero, estado in estados.items():
        if disponivel(estado):
            valor = custo(estado, origem, destino)
            if valor is not None:
                candidatas[numero] = valor
    if not candidatas:
        return None, {}
    return min(candidatas, key=lambda n: (candidatas[n], n)), candidatas
