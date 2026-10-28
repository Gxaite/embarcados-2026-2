"""Despacho por Destino (Secao 7.5).

A chamada vai para a cabine de menor custo, e o custo e uma estimativa de
tempo: quanto o passageiro novo vai esperar ate a porta abrir no andar de
origem, mais quanto a parada nova atrasa quem ja esta atribuido a cabine, mais
uma fracao da viagem dele (que as paradas da cabine no caminho alongam).

A estimativa percorre o itinerario da cabine na mesma ordem em que ela o
executa (SCAN, ver src/distribuido/itinerario.py): segue no sentido atual ate
a ultima parada, inverte e volta. Cada trecho custa distancia / velocidade de
cruzeiro, e cada parada o ciclo da porta. Uma chamada cuja origem ja e parada
da cabine nao acrescenta parada - e o agrupamento de passageiros que o
despacho por destino existe para aproveitar.

So entram cabines conectadas, calibradas e operando. Sem nenhuma, a chamada
fica na fila do simulador, e nao e retirada: o invariante e que toda chamada
retirada da fila seja atendida.
"""
# Modelo de tempo, medido nas viagens do simulador (ferramentas/experimentos.py
# pid): um trecho custa distancia / velocidade de cruzeiro mais um custo fixo
# de arranque e aproximacao; uma parada custa o ciclo da porta.
VELOCIDADE_POR_DUTY_MM_S = 10.0   # padrao, ate o central medir a da cabine
TEMPO_DE_ARRANQUE_S = 6.5
TEMPO_DE_PARADA_S = 6.0          # abrir 1,5 + aberta 2 + fechar 1,5 + folga
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
# up-peak embarcou 8 de uma vez. As chamadas atribuidas e nao concluidas de uma
# cabine sao o pior caso de lotacao: no up-peak todos embarcam no terreo, no
# down-peak ninguem desce antes dele.
LOTACAO = 7


def _ordem_scan(posicao_mm, sentido, paradas, posicoes):
    # Parada no andar em que a cabine ja esta vem primeiro, como no itinerario:
    # contada como "abaixo", ela puxava a estimativa para a descida.
    aqui = [a for a in paradas if abs(posicoes[a] - posicao_mm) <= NO_ANDAR_MM]
    acima = sorted(a for a in paradas if posicoes[a] - posicao_mm > NO_ANDAR_MM)
    abaixo = sorted((a for a in paradas if posicao_mm - posicoes[a] > NO_ANDAR_MM),
                    reverse=True)
    if sentido < 0 or (sentido == 0 and abaixo and (
            not acima or posicao_mm - posicoes[abaixo[0]]
            < posicoes[acima[0]] - posicao_mm)):
        return aqui + abaixo + acima
    return aqui + acima + abaixo


def _percorre(posicao_mm, ordem, posicoes, velocidade_mm_s):
    """Instante de chegada a cada parada, na ordem."""
    instantes = {}
    tempo = 0.0
    for andar in ordem:
        distancia = abs(posicoes[andar] - posicao_mm)
        if distancia > 10.0:
            tempo += distancia / velocidade_mm_s + TEMPO_DE_ARRANQUE_S
        instantes.setdefault(andar, tempo)
        tempo += TEMPO_DE_PARADA_S
        posicao_mm = posicoes[andar]
    return instantes


def velocidade_de_cruzeiro(estado):
    por_duty = estado.get("velocidade_por_duty") or VELOCIDADE_POR_DUTY_MM_S
    duty = estado.get("duty_maximo") or 16.7
    return max(50.0, por_duty * duty)


def custo(estado, origem, destino):
    """Segundos estimados para atender a chamada nesta cabine.

    estado["esperando"] e {andar de origem: ha quanto tempo a chamada mais
    antiga ali espera}, das chamadas ja atribuidas a esta cabine, e
    estado["comprometidos"] quantas delas ainda nao desembarcaram."""
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
    paradas = set(estado.get("paradas") or [])
    velocidade = velocidade_de_cruzeiro(estado)

    antes = _percorre(posicao, _ordem_scan(posicao, sentido, paradas, posicoes),
                      posicoes, velocidade)
    depois = _percorre(posicao, _ordem_scan(posicao, sentido, paradas | {origem},
                                            posicoes), posicoes, velocidade)
    # A porta ainda ocupada atrasa tudo meio ciclo.
    porta = TEMPO_DE_PARADA_S / 2 if estado.get("porta_ciclo") not in (None, "ociosa") \
        else 0.0
    espera = depois[origem] + porta
    atraso = sum(max(0.0, depois[a] - antes[a]) for a in antes)
    # Dentro da cabine, cada parada dela entre a origem e o destino alonga a
    # viagem do passageiro novo.
    entre = [a for a in paradas if min(origem, destino) < a < max(origem, destino)]
    viagem = abs(posicoes[destino] - posicoes[origem]) / velocidade \
        + len(entre) * TEMPO_DE_PARADA_S
    total = espera + PESO_DO_ATRASO_DOS_OUTROS * atraso + PESO_DA_VIAGEM * viagem

    limite = ESPERA_MAXIMA_S - FOLGA_DA_ESPERA_S
    previstas = [espera] + [idade + depois[a] + porta
                            for a, idade in (estado.get("esperando") or {}).items()
                            if a in depois]
    estouro = max(previstas) - limite
    if estouro > 0:
        total += PENALIDADE_S + estouro
    if (estado.get("comprometidos") or 0) >= LOTACAO:
        total += PENALIDADE_S
    return total


def disponivel(estado):
    return bool(estado) and estado.get("calibrada") and estado.get("modo") == "operando"


def escolhe(estados, origem, destino):
    """Numero da cabine escolhida, ou None se nenhuma pode atender.

    estados: {cabine: ultimo relatorio de estado, ou None se desconectada}.
    """
    candidatas = {n: custo(e, origem, destino)
                  for n, e in estados.items() if disponivel(e)}
    if not candidatas:
        return None, {}
    return min(candidatas, key=lambda n: (candidatas[n], n)), candidatas
