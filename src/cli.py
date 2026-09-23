"""Interface de terminal (requisito 1 da Secao 3).

O laco de comandos bloqueia em input(), que dorme ate haver linha: nao ha
busy-wait aqui nem na malha de controle.
"""
from .controle import posicao
from .gpio import pinos

AJUDA = """
Comandos da Cabine 1:
  andar <0|1|2>            viaja ate o andar (malha fechada no encoder)
  ir <mm>                  viaja ate uma posicao em mm
  motor <direcao> <duty>   acionamento direto; direcao = livre|subir|descer|freio
  parar                    zera o PWM e aplica o freio
  estado                   imprime o estado completo da cabine
  zera [mm]                redefine a contagem do encoder (padrao: 0)
  medicoes                 lista as bandeirolas ja medidas
  ancora                   corrige a contagem pela ultima bandeirola medida
  obstruir | liberar       (so no modo simulado) aciona a cortina de luz
  ajuda                    mostra esta lista
  sair                     encerra o programa em seguranca
"""


def imprime_estado(estado):
    print("""
  contagem do encoder ... %d
  posicao ............... %.0f mm
  andar estimado ........ %s
  nivelado .............. %s
  direcao ............... %s
  duty cycle ............ %.1f %%
  cortina ............... %s
  sensor de andar ....... %s
  destino ............... %s
  transicoes invalidas .. %d""" % (
        estado["contagem"],
        estado["posicao_mm"],
        "n/d" if estado["andar_estimado"] is None else estado["andar_estimado"],
        "sim" if estado["nivelado"] else "nao",
        estado["direcao"],
        estado["duty"],
        "OBSTRUIDA" if estado["cortina_obstruida"] else "livre",
        "dentro da bandeirola" if estado["sensor_andar"] else "entre andares",
        "n/d" if estado["destino_mm"] is None else "%.0f mm" % estado["destino_mm"],
        estado["transicoes_invalidas"]), flush=True)


def executa(cabine, linha, simulador=None):
    """Executa uma linha de comando. Retorna False quando for para encerrar."""
    partes = linha.strip().split()
    if not partes:
        return True
    comando, argumentos = partes[0].lower(), partes[1:]

    try:
        if comando in ("sair", "exit", "quit"):
            return False

        elif comando in ("ajuda", "help", "?"):
            print(AJUDA, flush=True)

        elif comando == "andar":
            cabine.vai_para_andar(int(argumentos[0]))
            print("indo para o andar %s (%d mm)"
                  % (argumentos[0], posicao.mm_do_andar(int(argumentos[0]))), flush=True)

        elif comando == "ir":
            destino = float(argumentos[0])
            cabine.vai_para_mm(destino)
            print("indo para %.0f mm" % destino, flush=True)

        elif comando == "motor":
            direcao = argumentos[0].lower()
            duty = float(argumentos[1]) if len(argumentos) > 1 else 0.0
            if direcao not in pinos.DIRECOES:
                print("direcao invalida: %s (use %s)"
                      % (direcao, ", ".join(sorted(pinos.DIRECOES))), flush=True)
                return True
            cabine.aciona_direto(direcao, duty)
            print("motor: %s a %.1f%% (fora da malha fechada; o fim de curso "
                  "continua vigiando)" % (direcao, duty), flush=True)

        elif comando == "parar":
            cabine.para()
            print("motor parado e em freio", flush=True)

        elif comando == "estado":
            imprime_estado(cabine.estado())

        elif comando == "zera":
            mm = float(argumentos[0]) if argumentos else 0.0
            cabine.zera(mm)
            print("contagem redefinida para %.0f mm" % mm, flush=True)

        elif comando == "ancora":
            medicao, correcao = cabine.ancora()
            print("contagem reancorada pelo andar %d: centro medido em %.1f mm, "
                  "nominal %d mm, correcao de %+.1f mm"
                  % (medicao.andar, medicao.centro_mm,
                     posicao.mm_do_andar(medicao.andar), correcao), flush=True)
            print("posicao agora: %.0f mm" % cabine.posicao_mm, flush=True)

        elif comando == "medicoes":
            if not cabine.sensor_andar.medicoes:
                print("nenhuma bandeirola medida ainda", flush=True)
            for medicao in cabine.sensor_andar.medicoes:
                print("  %r" % (medicao,), flush=True)

        elif comando in ("obstruir", "liberar"):
            if simulador is None:
                print("so no modo simulado. Na bancada, use o botao "
                      "\"Obstruir porta\" do widget.", flush=True)
            elif comando == "obstruir":
                simulador.obstrui_porta()
            else:
                simulador.libera_porta()

        else:
            print("comando desconhecido: %s (digite 'ajuda')" % comando, flush=True)

    except (IndexError, ValueError) as erro:
        print("erro no comando: %s" % erro, flush=True)

    return True
