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
from .tela import exibe
from .uart.erros import ErroComunicacao, ExcecaoModbus

AJUDA = """
## Partes 1 e 2 - dispositivo didatico 0x01   (<p> = p1 simplificado | p2 MODBUS)
  <p> pede-int | pede-float | pede-string
  <p> envia-int <n> | envia-float <x> | envia-string <texto>
  p1 cru <byte>...              bytes crus em hexa (ex.: p1 cru C7 0 1 5 1 1 2)

## Parte 3 - cabines 0x11-0x13 e predio 0x20
  cabine <1|2|3>                le_estado_cabine()
  porta <1|2|3> abrir|fechar    comanda_porta()
  predio                        le_estado_predio()
  fila                          le_chamada_da_fila()
  atribui <id> <cabine>         atribui_chamada()
  pop [<id>]                    remove_chamada_da_fila()
  contorno [<graus C> <hPa>]    escreve_condicao_contorno() (sem argumento: BMP280)
  le <end> <reg> <qtd>          funcao 0x03 crua (teste de excecao)
  escreve <end> <reg> <v>...    funcao 0x10 crua (teste de excecao)
  monitora cabine <n> [<s>]     leitura continua a cada 1 s (Enter para,
  monitora predio [<s>]         ou para sozinha apos <s> segundos)

## I2C e Condicao de Contorno
  bmp                           le temperatura e pressao do BMP280
  auto [on|off|log]             escrita periodica da Condicao de Contorno (4 s)

## Demonstracao (3 s entre comandos, para o widget acompanhar)
  roteiro 1                     os 6 comandos da Parte 1 e o erro de sintaxe
  roteiro 2                     os 6 comandos da Parte 2
  roteiro 3 [<cabine>]          watchdog e BMP280, porta, fila e excecoes
                                (espera a chamada do quiosque)
  roteiro tudo [<cabine>]       as tres em sequencia

## Terminal
  menu                          menu numerado
  <cmd> ; <cmd>                 varios comandos na mesma linha
  chamada <origem> <destino>    registra chamada (so no modo --simulado)
  ajuda | sair
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
    exibe("  => Cabine %s | andar %d %s | porta %-9s (cmd %d) | %4d mA | %3d kg, "
          "%d pass. | %5d mm | falha 0x%04X"
          % (cabine, estado["andar_atual"],
             "nivelada" if estado["nivelado"] else "em transito",
             mapa.ESTADOS_DA_PORTA.get(estado["porta_estado"],
                                       "?%d" % estado["porta_estado"]),
             estado["porta_comando"], estado["corrente_ma"], estado["carga_kg"],
             estado["passageiros"], estado["posicao_mm"], estado["falha"]))


def imprime_predio(estado):
    temperatura = estado["ambiente_temp_c_x10"]
    temperatura = (temperatura - 0x10000 if temperatura & 0x8000
                   else temperatura) / 10.0
    exibe("""  => Predio (0x20):
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
        estado["viagem_media_s_x10"] / 10.0))


def imprime_fila(chamada):
    if chamada is None:
        exibe("  => fila vazia")
    else:
        exibe("  => %d na fila; cabeca: chamada %d, andar %d -> %d"
              % (chamada["na_fila"], chamada["id"], chamada["origem"],
                 chamada["destino"]))


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
                exibe("  ERRO: %s" % erro)
            parar.wait(PERIODO_DO_MONITOR_S)

    if duracao_s is None:
        exibe("leitura continua a cada %.0f s - tecle Enter para parar"
              % PERIODO_DO_MONITOR_S)
    else:
        exibe("leitura continua a cada %.0f s por %.0f s"
              % (PERIODO_DO_MONITOR_S, duracao_s))
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
    exibe("leitura continua encerrada")


def _auto(contexto, argumentos):
    servico = contexto.servico
    if servico is None:
        exibe("servico indisponivel: o BMP280 nao foi aberto")
        return
    acao = argumentos[0].lower() if argumentos else "status"
    if acao == "on":
        servico.inicia()
    elif acao == "off":
        servico.para()
    elif acao == "log":
        servico.verboso = not servico.verboso
        exibe("log de cada escrita: %s" % ("ligado" if servico.verboso
                                           else "desligado"))
    leitura = servico.ultima_leitura
    exibe("  => Condicao de Contorno automatica: %s | periodo %.0f s | %d escrita(s), "
          "%d falha(s)%s" % (
              "LIGADA" if servico.ativo else "desligada", servico.periodo_s,
              servico.escritas, servico.falhas,
              "" if leitura is None else " | ultima: %.2f C, %.2f hPa"
              % (leitura.temperatura_c, leitura.pressao_hpa)))


def _contorno(contexto, argumentos):
    if argumentos:
        temperatura, pressao = float(argumentos[0]), float(argumentos[1])
    else:
        if contexto.sensor is None:
            raise ValueError("BMP280 indisponivel; informe <graus C> <hPa>")
        leitura = contexto.sensor.le()
        temperatura, pressao = leitura.temperatura_c, leitura.pressao_hpa
        exibe("[I2C] BMP280 0x%02X: %.2f C, %.2f hPa"
              % (contexto.sensor.endereco, temperatura, pressao))
    contexto.elevadores.escreve_condicao_contorno(temperatura, pressao)
    exibe("  => Condicao de Contorno escrita: %d (decimos de C), %d hPa"
          % (round(temperatura * 10), round(pressao)))


# ------------------------------------------------------------ roteiro
# O widget do dashboard deixou de receber eventos na rasp50 apos uns 30 em
# 40 s, entao o roteiro evita trafego que ninguem ve: toda consulta dele e um
# comando impresso, e a escrita automatica (2 eventos a cada 4 s) so liga no
# final.
PAUSA_DO_ROTEIRO_S = 3.0
EXPIRACAO_DO_WATCHDOG_S = 32
# A porta do simulador leva ~2 s abrindo, fica ~3 s aberta e fecha sozinha.
# O fechar vai enquanto ela esta aberta, para o comando aparecer fazendo efeito.
DURACAO_DA_ABERTURA_S = 3
DURACAO_DO_FECHAMENTO_S = 5
# Espera pela chamada do quiosque: uma leitura da fila a cada 3 s, cada uma
# um evento no widget, por no maximo 3 min.
INTERVALO_DA_ESPERA_S = 3.0
ESPERA_DA_CHAMADA_S = 180


def _passo(contexto, linha, aviso=None):
    """Executa um comando do roteiro como se tivesse sido digitado, depois de
    explicar o que ele envia e o que se espera."""
    exibe()
    if aviso:
        exibe(aviso)
    exibe("uart> %s" % linha)
    _executa_um(contexto, linha)
    time.sleep(PAUSA_DO_ROTEIRO_S)


def _consulta(linha, le, imprime, aviso=None):
    """Passo do roteiro cujo resultado decide o proximo. Impresso igual ao
    comando digitado; devolve None se a leitura falhar."""
    exibe()
    if aviso:
        exibe(aviso)
    exibe("uart> %s" % linha)
    try:
        estado = le()
    except ErroComunicacao as erro:
        if not isinstance(erro, ExcecaoModbus):
            exibe("  ERRO: %s: %s" % (type(erro).__name__, erro))
        estado = None
    else:
        imprime(estado)
    time.sleep(PAUSA_DO_ROTEIRO_S)
    return estado


def _passo_contorno(contexto, aviso):
    """Escrita da Condicao de Contorno; sem BMP280, com valores fixos."""
    _passo(contexto, "contorno" if contexto.sensor is not None
           else "contorno 25 1013", aviso)


def _espera_chamada(elevadores):
    """Le a fila a cada 3 s ate aparecer uma chamada, uma linha por leitura.

    Os bytes dessas leituras nao sao impressos: seriam cinco linhas a cada
    3 s so para dizer que a fila continua vazia. A leitura que vale aparece
    depois, como o comando 'fila'.
    """
    cliente = elevadores.cliente
    eco, cliente.eco = cliente.eco, None
    inicio = time.monotonic()
    try:
        while True:
            try:
                chamada = elevadores.le_chamada_da_fila()
            except ErroComunicacao as erro:
                exibe("  leitura da fila falhou (%s); tentando de novo" % erro)
                chamada = None
            decorrido = time.monotonic() - inicio
            if chamada is not None:
                exibe("  chamada %d encontrada apos %.0f s: andar %d -> %d"
                      % (chamada["id"], decorrido, chamada["origem"],
                         chamada["destino"]))
                return chamada
            if decorrido >= ESPERA_DA_CHAMADA_S:
                return None
            exibe("  fila vazia, aguardando a chamada... (%.0f s)" % decorrido)
            time.sleep(INTERVALO_DA_ESPERA_S)
    finally:
        cliente.eco = eco


def _roteiro_seis_comandos(contexto, protocolo):
    for comando in ("pede-int", "pede-float", "pede-string", "envia-int 42",
                    "envia-float 3.14", "envia-string teste"):
        _passo(contexto, "%s %s" % (protocolo, comando))


def _roteiro_parte_1(contexto):
    _roteiro_seis_comandos(contexto, "p1")
    matricula = " ".join("%X" % d for d in contexto.protocolos["p1"].matricula)
    exibe("\n# comando 0xC7 fora da faixa: a ESP32 descarta e a RPi registra o "
          "timeout")
    _passo(contexto, "p1 cru C7 %s" % matricula)


def _roteiro_parte_2(contexto):
    _roteiro_seis_comandos(contexto, "p2")


def _roteiro_parte_3(contexto, cabine):
    elevadores = contexto.elevadores
    servico = contexto.servico

    exibe("\n# 1. watchdog da Condicao de Contorno")
    if servico is not None and servico.ativo:
        servico.para()
    predio = _consulta("predio", elevadores.le_estado_predio, imprime_predio,
                       "# le os 16 registradores do predio (0x20); sem escrita "
                       "ha mais de 30 s, esperado watchdog = 1 e barramento "
                       "3000 mA")
    if predio is not None and predio["watchdog_ambiente"] == 0:
        exibe("# watchdog ainda valido; aguardando %d s sem escrita para ele "
              "expirar" % EXPIRACAO_DO_WATCHDOG_S)
        time.sleep(EXPIRACAO_DO_WATCHDOG_S)
        _passo(contexto, "predio", "# le o predio de novo: agora o watchdog "
               "deve estar expirado")
    if contexto.sensor is not None:
        _passo(contexto, "bmp", "# le temperatura e pressao do BMP280 pelo I2C")
    _passo_contorno(contexto, "# escreve temperatura (decimos de C) e pressao "
                    "(hPa) nos registradores 5 e 6 do predio")
    _passo(contexto, "predio", "# esperado watchdog = 0 e barramento = 12000 - "
           "200 x (T - 25) mA")

    exibe("\n# 2. porta da cabine %d" % cabine)
    estado = _consulta("cabine %d" % cabine,
                       lambda: elevadores.le_estado_cabine(cabine),
                       lambda e: imprime_cabine(cabine, e),
                       "# le os 9 registradores da cabine %d: ela precisa "
                       "estar nivelada e com a porta fechada" % cabine)
    if estado is not None and (not estado["nivelado"] or estado["falha"]
                               or estado["porta_estado"]):
        exibe("# AVISO: a cabine %d precisa estar nivelada, sem falha e com a "
              "porta fechada; escolha outra com 'roteiro 3 <cabine>'" % cabine)
    for acao, codigo, duracao_s, esperado in (
            ("abrir", 1, DURACAO_DA_ABERTURA_S, "fechada -> abrindo -> aberta"),
            ("fechar", 2, DURACAO_DO_FECHAMENTO_S, "fechando -> fechada")):
        linha = "porta %d %s ; monitora cabine %d %s" % (cabine, acao, cabine,
                                                         duracao_s)
        exibe("\n# escreve %d (%s) no registrador 3 da cabine e le a cada 1 s "
              "por %d s; esperado %s" % (codigo, acao, duracao_s, esperado))
        exibe("uart> %s" % linha)
        executa(contexto, linha)
    time.sleep(PAUSA_DO_ROTEIRO_S)

    exibe("\n# 3. fila de chamadas")
    exibe("# registre uma chamada no quiosque do dashboard (qualquer origem e "
          "destino); a fila e lida a cada %.0f s e o roteiro segue sozinho"
          % INTERVALO_DA_ESPERA_S)
    if _espera_chamada(elevadores) is None:
        exibe("# nenhuma chamada em %d s: a fila fica para o terminal "
              "('fila', 'atribui <id> %d', 'pop', 'fila')"
              % (ESPERA_DA_CHAMADA_S, cabine))
    else:
        _passo_contorno(contexto, "# renova a Condicao de Contorno: a porta e "
                        "a espera ja passaram dos 30 s do watchdog")
        chamada = _consulta("fila", elevadores.le_chamada_da_fila, imprime_fila,
                            "# le os registradores 0 a 3 do predio: tamanho "
                            "da fila e a chamada da cabeca")
        if chamada is not None:
            _passo(contexto, "atribui %d %d" % (chamada["id"], cabine),
                   "# escreve id %d e cabine %d nos registradores 9 e 10"
                   % (chamada["id"], cabine))
            _passo(contexto, "pop %d" % chamada["id"],
                   "# escreve 1 no registrador 4: remove a chamada da cabeca")
            _passo(contexto, "fila", "# le a fila de novo: a chamada %d nao "
                   "deve mais estar na cabeca" % chamada["id"])

    exibe("\n# 4. excecoes")
    _passo(contexto, "escreve 0x11 0 5", "# escreve no registrador 0 da "
           "cabine 1, que e somente leitura: esperado excecao 0x02")
    _passo(contexto, "le 0x11 0 20", "# le 20 registradores da cabine 1, que "
           "so tem 9: esperado excecao 0x02")

    if servico is not None:
        exibe("\n# 5. Condicao de Contorno automatica")
        _passo(contexto, "auto on", "# liga a escrita da temperatura a cada "
               "4 s, para o watchdog nao expirar de novo")
        _passo(contexto, "predio", "# esperado watchdog = 0")


def _roteiro(contexto, argumentos):
    parte = argumentos[0].lower() if argumentos else "tudo"
    cabine = int(argumentos[1]) if len(argumentos) > 1 else 1
    mapa.endereco_da_cabine(cabine)
    if parte == "1":
        _roteiro_parte_1(contexto)
    elif parte == "2":
        _roteiro_parte_2(contexto)
    elif parte == "3":
        _roteiro_parte_3(contexto, cabine)
    elif parte == "tudo":
        _roteiro_parte_1(contexto)
        _roteiro_parte_2(contexto)
        _roteiro_parte_3(contexto, cabine)
    else:
        raise ValueError("use: roteiro 1 | roteiro 2 | roteiro 3 [<cabine>] | "
                         "roteiro tudo [<cabine>]")
    exibe("\n# fim do roteiro")


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
            exibe(AJUDA)
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
            exibe("  => porta da cabine %s: comando %s enviado" % (argumentos[0], acao))
        elif comando == "predio":
            imprime_predio(elevadores.le_estado_predio())
        elif comando == "fila":
            imprime_fila(elevadores.le_chamada_da_fila())
        elif comando == "atribui":
            elevadores.atribui_chamada(int(argumentos[0]), int(argumentos[1]))
            exibe("  => chamada %s atribuida a cabine %s" % tuple(argumentos[:2]))
        elif comando == "pop":
            removida = elevadores.remove_chamada_da_fila(
                int(argumentos[0]) if argumentos else None)
            if removida is None:
                exibe("  => fila vazia: nada a remover")
            else:
                exibe("  => chamada %d removida da fila" % removida)
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
                exibe("BMP280 indisponivel")
            else:
                leitura = contexto.sensor.le()
                exibe("[I2C] BMP280 0x%02X: %.2f C, %.2f hPa"
                      % (contexto.sensor.endereco, leitura.temperatura_c,
                         leitura.pressao_hpa))
        elif comando == "auto":
            _auto(contexto, argumentos)
        elif comando == "chamada":
            if contexto.esp32_simulada is None:
                exibe("so no modo simulado. Na bancada, registre a chamada no "
                      "quiosque do dashboard.")
            else:
                contexto.esp32_simulada.registra_chamada(int(argumentos[0]),
                                                         int(argumentos[1]))
                exibe("chamada registrada no simulador")
        else:
            exibe("comando desconhecido: %s (digite 'ajuda')" % comando)

    except ExcecaoModbus:
        pass  # o protocolo ja imprimiu o codigo e o significado
    except ErroComunicacao as erro:
        exibe("  ERRO: %s: %s" % (type(erro).__name__, erro))
    except (OSError, ErroBMP280) as erro:
        exibe("  ERRO de E/S: %s" % erro)
    except (IndexError, ValueError) as erro:
        exibe("erro no comando: %s" % (erro or "faltam argumentos"))

    return True

