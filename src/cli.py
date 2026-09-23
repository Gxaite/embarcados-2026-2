"""Interface de terminal da Cabine 1.

Le comandos com input(), que bloqueia na leitura - nao consome CPU. Toda a
movimentacao acontece na thread da malha de controle, entao os eventos de
cortina e de bandeirola aparecem no terminal enquanto voce digita.
"""
from .controle import posicao
from .controle.motor import DIRECOES

AJUDA = """
Comandos:
  andar <0|1|2>            move a cabine ate o andar (malha fechada no encoder)
  ir <mm>                  move ate uma posicao em mm
  motor <direcao> <duty>   acionamento direto; direcao = livre|subir|descer|freio
  parar                    zera o PWM e aplica o freio
  estado                   imprime o estado completo da cabine
  zera [mm]                redefine a contagem do encoder (padrao: 0)
  obstruir / liberar       (so no modo simulado) aciona a cortina de luz
  ajuda                    mostra esta lista
  sair                     encerra o programa em seguranca
"""


def imprime_estado(cabine):
    e = cabine.estado()
    print("""
--- Cabine 1 ---------------------------------------------
  Posicao ............ %d contagens  (%.1f mm)
  Andar estimado ..... %d  (erro %+.1f mm)
  Nivelamento ........ %s
  Direcao / duty ..... %s / %.1f %%
  Cortina ............ %s  (%d obstrucoes)
  Sensor de Andar .... %s
  Bandeirolas medidas. %d
  Transicoes invalidas %d
----------------------------------------------------------""" % (
        e["contagem"], e["posicao_mm"], e["andar_estimado"], e["erro_mm"],
        "NIVELADO (+-%.0f mm)" % posicao.TOLERANCIA_MM if e["nivelado"]
        else "fora de nivel",
        e["direcao"], e["duty"], e["cortina"], e["obstrucoes"],
        e["sensor_andar"], e["bandeirolas_medidas"], e["transicoes_invalidas"]),
        flush=True)


def executa(cabine, linha, simulador=None):
    """Executa um comando. Devolve False quando o usuario pede para sair."""
    partes = linha.split()
    if not partes:
        return True
    comando, args = partes[0].lower(), partes[1:]

    if comando in ("sair", "exit", "quit"):
        return False

    if comando in ("ajuda", "help", "?"):
        print(AJUDA, flush=True)

    elif comando == "estado":
        imprime_estado(cabine)

    elif comando == "andar":
        if len(args) != 1:
            print("uso: andar <0|1|2>", flush=True)
        else:
            try:
                cabine.vai_para_andar(int(args[0]))
            except ValueError as erro:
                print("erro: %s" % erro, flush=True)

    elif comando == "ir":
        if len(args) != 1:
            print("uso: ir <mm>", flush=True)
        else:
            cabine.vai_para_mm(float(args[0]))

    elif comando == "motor":
        if len(args) != 2 or args[0] not in DIRECOES:
            print("uso: motor <%s> <duty 0-100>" % "|".join(DIRECOES),
                  flush=True)
        else:
            duty = cabine.aciona_manual(args[0], float(args[1]))
            print("motor: direcao=%s duty=%.1f%%" % (args[0], duty), flush=True)

    elif comando == "parar":
        cabine.parada_de_emergencia()
        print("motor parado, freio aplicado", flush=True)

    elif comando == "zera":
        valor = posicao.mm_para_contagem(float(args[0])) if args else 0
        cabine.encoder.zera(valor)
        print("encoder zerado em %d contagens" % valor, flush=True)

    elif comando in ("obstruir", "liberar"):
        if simulador is None:
            print("comando disponivel apenas no modo --simulado "
                  "(na bancada, use o botao 'Obstruir porta' do widget)",
                  flush=True)
        elif comando == "obstruir":
            simulador.obstruir_porta()
        else:
            simulador.liberar_porta()

    else:
        print("comando desconhecido: %s  (tente 'ajuda')" % comando, flush=True)

    return True
