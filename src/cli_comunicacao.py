"""Interface de terminal da Entrega 2.

Cada comando das Partes 1 e 2 comeca pelo protocolo (p1 ou p2), que e a forma
de "escolher o protocolo antes de cada comando" do requisito 4 da Parte 2. A
Parte 3 tem um comando por funcao da Secao 3.4. Todos imprimem os bytes
enviados e recebidos e os campos decodificados.
"""
import threading
import time

from .i2c.bmp280 import ErroBMP280
from .uart import elevadores as mapa
from .uart.erros import ErroComunicacao

AJUDA = """
Partes 1 e 2 - dispositivo didatico. <p> = p1 (simplificado) ou p2 (MODBUS)
  <p> pede-int | pede-float | pede-string
  <p> envia-int <n> | envia-float <x> | envia-string <texto>
  p1 cru <byte> [<byte>...]     envia bytes crus em hexa (ex.: p1 cru C7 0 1 5 1 1 2)

Parte 3 - simulador (enderecos aceitam 0x11 ou decimal)
  cabine <1|2|3>                le_estado_cabine()
  porta <1|2|3> <abrir|fechar|nenhum|codigo>     comanda_porta()
  predio                        le_estado_predio()
  fila                          le_chamada_da_fila()
  atribui <id> <cabine>         atribui_chamada()
  pop                           remove_chamada_da_fila()
  contorno [<graus C> <hPa>]    escreve_condicao_contorno(); sem argumentos, le o BMP280
  le <end> <reg> <qtd>          funcao 0x03 em qualquer faixa (teste de excecao)
  escreve <end> <reg> <v>...    funcao 0x10 em qualquer registrador (teste de excecao)
  monitora cabine <n> | predio [<s>]   leitura continua a cada 1 s; Enter
                                interrompe, ou para sozinha apos <s> segundos

I2C e Condicao de Contorno
  bmp                           le temperatura e pressao do BMP280
  auto [on|off|log]             escrita periodica da Condicao de Contorno (4 s)

  chamada <origem> <destino>    (so no modo simulado) registra uma chamada
Demonstracao automatica (pausa de 2 s entre comandos, para o widget)
  roteiro 1                     os 12 comandos das Partes 1 e 2 e o erro de sintaxe
  roteiro 3 [<cabine>]          watchdog, porta, fila e excecoes da Parte 3
  roteiro tudo [<cabine>]       os dois em sequencia (cabine padrao 1)

  <cmd> ; <cmd>                 varios comandos em sequencia na mesma linha
                                (ex.: porta 1 abrir ; monitora cabine 1)
  ajuda                         mostra esta lista
  sair                          encerra fechando UART e I2C
"""

PERIODO_DO_MONITOR_S = 1.0


class Contexto:
    """Tudo que os comandos usam, montado pelo ponto de entrada."""

    def __init__(self, simplificado, didatico, elevadores, sensor=None,
                 servico=None, esp32_simulada=None):
        self.protocolos = {"p1": simplificado, "p2": didatico}
        self.elevadores = elevadores
        self.sensor = sensor
        self.servico = servico
        self.esp32_simulada = esp32_simulada


# ----------------------------------------------------------- impressao
def imprime_cabine(cabine, estado):
    print("  Cabine %s: andar %d | %s | porta %s (comando %d) | %d mA | %d kg | "
          "%d passageiro(s) | posicao %d mm | falha 0x%04X"
          % (cabine, estado["andar_atual"],
             "nivelada" if estado["nivelado"] else "entre andares",
             mapa.ESTADOS_DA_PORTA.get(estado["porta_estado"],
                                       "?%d" % estado["porta_estado"]),
             estado["porta_comando"], estado["corrente_ma"], estado["carga_kg"],
             estado["passageiros"], estado["posicao_mm"], estado["falha"]),
          flush=True)


def imprime_predio(estado):
    temperatura = estado["ambiente_temp_c_x10"]
    temperatura = (temperatura - 0x10000 if temperatura & 0x8000
                   else temperatura) / 10.0
    print("""  Predio (0x20):
    fila ............... %d chamada(s); cabeca: id %d, %d -> %d
    ambiente ........... %.1f C, %d hPa
    barramento_max ..... %d mA
    watchdog_ambiente .. %d (%s)
    ultima atribuicao .. chamada %d -> cabine %d
    cenario ............ %s (geradas %d, atendidas %d)
    espera media ....... %.1f s | viagem media %.1f s""" % (
        estado["chamadas_na_fila"], estado["chamada_id"],
        estado["chamada_origem"], estado["chamada_destino"],
        temperatura, estado["ambiente_press_hpa"],
        estado["barramento_max_ma"], estado["watchdog_ambiente"],
        "EXPIRADO, piso ativo" if estado["watchdog_ambiente"] else "valido",
        estado["atribuicao_chamada_id"], estado["atribuicao_cabine"],
        mapa.CENARIOS.get(estado["cenario_ativo"], "?"),
        estado["cenario_geradas"], estado["cenario_atendidas"],
        estado["espera_media_s_x10"] / 10.0,
        estado["viagem_media_s_x10"] / 10.0), flush=True)


# ------------------------------------------------------------ comandos
def _protocolo(contexto, nome, argumentos):
    protocolo = contexto.protocolos[nome]
    if not argumentos:
        raise ValueError("falta o comando (pede-int, envia-float, ...)")
    acao, valores = argumentos[0].lower(), argumentos[1:]
    if acao == "pede-int":
        protocolo.pede_int()
    elif acao == "pede-float":
        protocolo.pede_float()
    elif acao == "pede-string":
        protocolo.pede_string()
    elif acao == "envia-int":
        protocolo.envia_int(int(valores[0], 0))
    elif acao == "envia-float":
        protocolo.envia_float(float(valores[0]))
    elif acao == "envia-string":
        protocolo.envia_string(" ".join(valores))
    elif acao == "cru" and nome == "p1":
        protocolo.envia_cru(bytes(int(v, 16) for v in valores))
    else:
        raise ValueError("comando desconhecido para %s: %s" % (nome, acao))


def _monitora(contexto, argumentos):
    alvo = argumentos[0].lower() if argumentos else ""
    if alvo == "cabine":
        cabine = int(argumentos[1])
        mapa.endereco_da_cabine(cabine)
        resto = argumentos[2:]

        def le():
            imprime_cabine(cabine, contexto.elevadores.le_estado_cabine(cabine))
    elif alvo == "predio":
        resto = argumentos[1:]

        def le():
            imprime_predio(contexto.elevadores.le_estado_predio())
    else:
        raise ValueError("use: monitora cabine <n> | monitora predio [<s>]")
    duracao_s = float(resto[0]) if resto else None

    parar = threading.Event()

    def laco():
        while not parar.is_set():
            try:
                le()
            except ErroComunicacao as erro:
                print("  ERRO: %s" % erro, flush=True)
            parar.wait(PERIODO_DO_MONITOR_S)

    if duracao_s is None:
        print("leitura continua a cada %.0f s - tecle Enter para parar"
              % PERIODO_DO_MONITOR_S, flush=True)
    else:
        print("leitura continua a cada %.0f s por %.0f s"
              % (PERIODO_DO_MONITOR_S, duracao_s), flush=True)
    thread = threading.Thread(target=laco, daemon=True, name="monitor")
    thread.start()
    try:
        if duracao_s is None:
            input()
        else:
            parar.wait(duracao_s)
    except EOFError:
        pass
    finally:
        parar.set()
        thread.join(timeout=2.0)
    print("leitura continua encerrada", flush=True)


def _auto(contexto, argumentos):
    servico = contexto.servico
    if servico is None:
        print("servico indisponivel: o BMP280 nao foi aberto", flush=True)
        return
    acao = argumentos[0].lower() if argumentos else "status"
    if acao == "on":
        servico.inicia()
    elif acao == "off":
        servico.para()
    elif acao == "log":
        servico.verboso = not servico.verboso
        print("log de cada escrita: %s" % ("ligado" if servico.verboso
                                           else "desligado"), flush=True)
    leitura = servico.ultima_leitura
    print("Condicao de Contorno automatica: %s | periodo %.0f s | %d escrita(s), "
          "%d falha(s)%s" % (
              "LIGADA" if servico.ativo else "desligada", servico.periodo_s,
              servico.escritas, servico.falhas,
              "" if leitura is None else " | ultima: %.2f C, %.2f hPa"
              % (leitura.temperatura_c, leitura.pressao_hpa)), flush=True)


def _contorno(contexto, argumentos):
    if argumentos:
        temperatura, pressao = float(argumentos[0]), float(argumentos[1])
    else:
        if contexto.sensor is None:
            raise ValueError("BMP280 indisponivel; informe <graus C> <hPa>")
        leitura = contexto.sensor.le()
        temperatura, pressao = leitura.temperatura_c, leitura.pressao_hpa
        print("BMP280: %.2f C, %.2f hPa" % (temperatura, pressao), flush=True)
    contexto.elevadores.escreve_condicao_contorno(temperatura, pressao)
    print("Condicao de Contorno escrita: %d (decimos de C), %d hPa"
          % (round(temperatura * 10), round(pressao)), flush=True)


# ------------------------------------------------------------ roteiro
PAUSA_DO_ROTEIRO_S = 2.0
EXPIRACAO_DO_WATCHDOG_S = 32
DURACAO_DA_PORTA_S = 10


class _Silencio:
    """Consulta do proprio roteiro, sem imprimir bytes que ninguem digitou."""

    def __init__(self, contexto):
        self._cliente = contexto.elevadores.cliente

    def __enter__(self):
        self._eco, self._cliente.eco = self._cliente.eco, None

    def __exit__(self, *_erro):
        self._cliente.eco = self._eco


def _passo(contexto, linha):
    """Executa um comando do roteiro como se tivesse sido digitado."""
    print("\nuart> %s" % linha, flush=True)
    _executa_um(contexto, linha)
    time.sleep(PAUSA_DO_ROTEIRO_S)


def _roteiro_partes_1_e_2(contexto):
    matricula = " ".join("%X" % d for d in contexto.protocolos["p1"].matricula)
    for protocolo in ("p1", "p2"):
        for comando in ("pede-int", "pede-float", "pede-string", "envia-int 42",
                        "envia-float 3.14", "envia-string teste"):
            _passo(contexto, "%s %s" % (protocolo, comando))
    print("\n# comando 0xC7 fora da faixa: a ESP32 descarta e a RPi registra o "
          "timeout", flush=True)
    _passo(contexto, "p1 cru C7 %s" % matricula)


def _roteiro_parte_3(contexto, cabine):
    elevadores = contexto.elevadores

    print("\n# 1. watchdog da Condicao de Contorno", flush=True)
    with _Silencio(contexto):
        watchdog = elevadores.le_estado_predio()["watchdog_ambiente"]
    if watchdog == 0:
        if contexto.servico is not None and contexto.servico.ativo:
            contexto.servico.para()
        print("# watchdog ainda valido; aguardando %d s sem escrita para ele "
              "expirar" % EXPIRACAO_DO_WATCHDOG_S, flush=True)
        time.sleep(EXPIRACAO_DO_WATCHDOG_S)
    _passo(contexto, "predio")
    _passo(contexto, "contorno" if contexto.sensor is not None
           else "contorno 25 1013")
    _passo(contexto, "predio")
    if contexto.servico is not None:
        _passo(contexto, "auto on")

    print("\n# 2. porta da cabine %d" % cabine, flush=True)
    with _Silencio(contexto):
        estado = elevadores.le_estado_cabine(cabine)
    if not estado["nivelado"] or estado["falha"] or estado["porta_estado"]:
        print("# AVISO: a cabine %d precisa estar nivelada, sem falha e com a "
              "porta fechada; escolha outra com 'roteiro 3 <cabine>'" % cabine,
              flush=True)
    print("\nuart> porta %d abrir ; monitora cabine %d %d"
          % (cabine, cabine, DURACAO_DA_PORTA_S), flush=True)
    _executa_um(contexto, "porta %d abrir" % cabine)
    _executa_um(contexto, "monitora cabine %d %d" % (cabine, DURACAO_DA_PORTA_S))
    _passo(contexto, "porta %d fechar" % cabine)

    print("\n# 3. fila de chamadas (registrar antes no quiosque do dashboard)",
          flush=True)
    with _Silencio(contexto):
        chamada = elevadores.le_chamada_da_fila()
    _passo(contexto, "fila")
    if chamada is None:
        print("# fila vazia: registre uma chamada no quiosque e repita "
              "'fila', 'atribui <id> %d', 'pop', 'fila'" % cabine, flush=True)
    else:
        _passo(contexto, "atribui %d %d" % (chamada["id"], cabine))
        _passo(contexto, "pop")
        _passo(contexto, "fila")

    print("\n# 4. excecoes 0x02: registrador somente leitura e faixa fora do mapa",
          flush=True)
    _passo(contexto, "escreve 0x11 0 5")
    _passo(contexto, "le 0x11 0 20")


def _roteiro(contexto, argumentos):
    parte = argumentos[0].lower() if argumentos else "tudo"
    cabine = int(argumentos[1]) if len(argumentos) > 1 else 1
    mapa.endereco_da_cabine(cabine)
    if parte == "1":
        _roteiro_partes_1_e_2(contexto)
    elif parte == "3":
        _roteiro_parte_3(contexto, cabine)
    elif parte == "tudo":
        _roteiro_partes_1_e_2(contexto)
        _roteiro_parte_3(contexto, cabine)
    else:
        raise ValueError("use: roteiro 1 | roteiro 3 [<cabine>] | "
                         "roteiro tudo [<cabine>]")
    print("\n# fim do roteiro", flush=True)


def executa(contexto, linha):
    """Executa uma linha, que pode ter varios comandos separados por ';'.

    Retorna False quando for para encerrar. Encadear existe para a porta: ela
    abre em poucos segundos, e digitar o monitora depois perde a transicao.
    """
    for comando in linha.split(";"):
        if not _executa_um(contexto, comando):
            return False
    return True


def _executa_um(contexto, linha):
    partes = linha.strip().split()
    if not partes:
        return True
    comando, argumentos = partes[0].lower(), partes[1:]
    elevadores = contexto.elevadores

    try:
        if comando in ("sair", "exit", "quit"):
            return False
        elif comando in ("ajuda", "help", "?"):
            print(AJUDA, flush=True)
        elif comando in contexto.protocolos:
            _protocolo(contexto, comando, argumentos)
        elif comando == "cabine":
            imprime_cabine(argumentos[0],
                           elevadores.le_estado_cabine(int(argumentos[0])))
        elif comando == "porta":
            acao = argumentos[1].lower()
            elevadores.comanda_porta(
                int(argumentos[0]),
                acao if acao in mapa.COMANDOS_DA_PORTA else int(acao))
            print("porta da cabine %s: comando %s enviado" % (argumentos[0], acao),
                  flush=True)
        elif comando == "predio":
            imprime_predio(elevadores.le_estado_predio())
        elif comando == "fila":
            chamada = elevadores.le_chamada_da_fila()
            if chamada is None:
                print("  fila vazia", flush=True)
            else:
                print("  %d na fila; cabeca: chamada %d, andar %d -> %d"
                      % (chamada["na_fila"], chamada["id"], chamada["origem"],
                         chamada["destino"]), flush=True)
        elif comando == "atribui":
            elevadores.atribui_chamada(int(argumentos[0]), int(argumentos[1]))
            print("chamada %s atribuida a cabine %s" % tuple(argumentos[:2]),
                  flush=True)
        elif comando == "pop":
            elevadores.remove_chamada_da_fila()
            print("chamada da cabeca removida da fila", flush=True)
        elif comando == "contorno":
            _contorno(contexto, argumentos)
        elif comando == "le":
            elevadores.cliente.le_registradores(
                int(argumentos[0], 0), int(argumentos[1], 0), int(argumentos[2], 0))
        elif comando == "escreve":
            elevadores.cliente.escreve_registradores(
                int(argumentos[0], 0), int(argumentos[1], 0),
                [int(v, 0) for v in argumentos[2:]] or [0])
        elif comando == "monitora":
            _monitora(contexto, argumentos)
        elif comando == "roteiro":
            _roteiro(contexto, argumentos)
        elif comando == "bmp":
            if contexto.sensor is None:
                print("BMP280 indisponivel", flush=True)
            else:
                leitura = contexto.sensor.le()
                print("  BMP280 (0x%02X): %.2f C, %.2f hPa"
                      % (contexto.sensor.endereco, leitura.temperatura_c,
                         leitura.pressao_hpa), flush=True)
        elif comando == "auto":
            _auto(contexto, argumentos)
        elif comando == "chamada":
            if contexto.esp32_simulada is None:
                print("so no modo simulado. Na bancada, registre a chamada no "
                      "quiosque do dashboard.", flush=True)
            else:
                contexto.esp32_simulada.registra_chamada(int(argumentos[0]),
                                                         int(argumentos[1]))
                print("chamada registrada no simulador", flush=True)
        else:
            print("comando desconhecido: %s (digite 'ajuda')" % comando, flush=True)

    except ErroComunicacao as erro:
        print("  ERRO: %s: %s" % (type(erro).__name__, erro), flush=True)
    except (OSError, ErroBMP280) as erro:
        print("  ERRO de E/S: %s" % erro, flush=True)
    except (IndexError, ValueError) as erro:
        print("erro no comando: %s" % (erro or "faltam argumentos"), flush=True)

    return True

