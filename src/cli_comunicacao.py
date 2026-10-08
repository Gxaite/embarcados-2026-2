"""Interface de terminal da Entrega 2.

Cada comando das Partes 1 e 2 comeca pelo protocolo (p1 ou p2), que e a forma
de "escolher o protocolo antes de cada comando" do requisito 4 da Parte 2. A
Parte 3 tem um comando por funcao da Secao 3.4. Todos imprimem os bytes
enviados e recebidos e os campos decodificados.
"""
import threading

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
  monitora cabine <n> | predio  leitura continua a cada 1 s; Enter interrompe

I2C e Condicao de Contorno
  bmp                           le temperatura e pressao do BMP280
  auto [on|off|log]             escrita periodica da Condicao de Contorno (4 s)

  chamada <origem> <destino>    (so no modo simulado) registra uma chamada
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

        def le():
            imprime_cabine(cabine, contexto.elevadores.le_estado_cabine(cabine))
    elif alvo == "predio":
        def le():
            imprime_predio(contexto.elevadores.le_estado_predio())
    else:
        raise ValueError("use: monitora cabine <n> | monitora predio")

    parar = threading.Event()

    def laco():
        while not parar.is_set():
            try:
                le()
            except ErroComunicacao as erro:
                print("  ERRO: %s" % erro, flush=True)
            parar.wait(PERIODO_DO_MONITOR_S)

    print("leitura continua a cada %.0f s - tecle Enter para parar"
          % PERIODO_DO_MONITOR_S, flush=True)
    thread = threading.Thread(target=laco, daemon=True, name="monitor")
    thread.start()
    try:
        input()
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


def executa(contexto, linha):
    """Executa uma linha de comando. Retorna False quando for para encerrar."""
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

