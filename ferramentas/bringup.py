"""Bring-up da placa: ativa a Cabine 1 por etapas, da mais segura para a menos.

Cada etapa isola uma classe de falha. A ordem importa - entradas antes de
saidas, saidas antes de movimento - para que um erro de fiacao apareca antes de
comandar o motor.

    python3 -m ferramentas.bringup mapa       confere a pinagem (nao toca na GPIO)
    python3 -m ferramentas.bringup entradas   so le CORTINA e SENSOR_ANDAR
    python3 -m ferramentas.bringup encoder    conta bordas do encoder
    python3 -m ferramentas.bringup direcao    MOVE o motor: Tabela 2 passo a passo
    python3 -m ferramentas.bringup pwm        MOVE o motor: rampa de 0 a 30%

Acrescente --simulado para ensaiar o roteiro sem a placa e --segundos N para
encurtar as etapas de leitura.
Ver docs/BANCADA.md para o procedimento completo.
"""
import argparse
import signal
import sys
import time

from src.gpio import pinos
from src.gpio.backend import AMBAS, PULL_BAIXO
from src.gpio.encoder import EncoderQuadratura
from src.gpio.saidas import SaidaDigital, SaidaPWM

DUTY_MAXIMO_ENSAIO = 30.0   # teto do ensaio de PWM: so para ver a cabine sair
PASSO_RAMPA = 2.0


def barra(titulo):
    print("\n" + "=" * 62)
    print("  " + titulo)
    print("=" * 62, flush=True)


def confirma(pergunta):
    """Pede confirmacao explicita antes de qualquer etapa que move o motor."""
    try:
        return input("%s [s/N] " % pergunta).strip().lower() in ("s", "sim")
    except EOFError:
        return False


# ----------------------------------------------------------------------
# Etapa 1 - pinagem (nao toca na GPIO)
# ----------------------------------------------------------------------
def etapa_mapa(_backend=None):
    barra("ETAPA 1 - PINAGEM DA CABINE 1")
    print("\n  O numero BCM NAO e a posicao no conector. Confira fio a fio.\n")
    print("  %-14s %-8s %-14s %s" % ("SINAL", "BCM", "PINO FISICO", "FUNCAO"))
    print("  " + "-" * 58)
    for nome, bcm, funcao in pinos.SINAIS_CABINE_1:
        print("  %-14s %-8d %-14d %s"
              % (nome, bcm, pinos.PINO_FISICO[bcm], funcao))
    print("""
  Atencao aos dois que se confundem:
    DIR1         = GPIO 17 -> pino 11
    SENSOR_ANDAR = GPIO 11 -> pino 23

  GND mais proximos: pino 9 (DIR1/DIR2), 25 (SENSOR_ANDAR), 30 ou 34
  (encoder e PWM). Terra longo em sinal de encoder gera contagem fantasma.
""", flush=True)


# ----------------------------------------------------------------------
# Etapa 2 - entradas on/off (nao move nada)
# ----------------------------------------------------------------------
def etapa_entradas(backend, segundos=30.0):
    barra("ETAPA 2 - ENTRADAS ON/OFF (nao move nada)")
    print("""
  Estimule as entradas e veja o nivel mudar:
    CORTINA      -> botao "Obstruir porta" do widget
    SENSOR_ANDAR -> mova a cabine ate dentro de uma bandeirola

  Pino preso em 0 ou em 1 e fiacao ou periferico tomando o pino,
  nao e o codigo. Ver Secao 2 do docs/BANCADA.md.   (Ctrl+C encerra)
""", flush=True)

    monitorados = [("CORTINA", pinos.CORTINA), ("SENSOR_ANDAR", pinos.SENSOR_ANDAR)]
    bordas = {nome: 0 for nome, _ in monitorados}
    for nome, pino in monitorados:
        backend.configura_entrada(pino, PULL_BAIXO)
        backend.registra_interrupcao(
            pino, AMBAS, lambda p, v, n=nome: bordas.__setitem__(n, bordas[n] + 1))

    fim = time.monotonic() + segundos
    while time.monotonic() < fim:
        estados = "   ".join(
            "%s=%d (%d bordas)" % (nome, backend.le(pino), bordas[nome])
            for nome, pino in monitorados)
        print("\r  " + estados + " " * 10, end="", flush=True)
        time.sleep(0.1)
    print("\n", flush=True)

    for nome, _ in monitorados:
        if bordas[nome] == 0:
            print("  AVISO: %s nao mudou nenhuma vez. Confira a fiacao." % nome,
                  flush=True)


# ----------------------------------------------------------------------
# Etapa 3 - encoder
# ----------------------------------------------------------------------
def etapa_encoder(backend, segundos=30.0):
    barra("ETAPA 3 - ENCODER EM QUADRATURA")
    print("""
  Mova a cabine pelo widget e observe:
    - a contagem SOBE ao subir e DESCE ao descer;
      se estiver invertida, ENC_A e ENC_B estao trocados;
    - 1 contagem = 1 mm, um andar = 3000 contagens;
    - transicoes invalidas devem ficar em ZERO.   (Ctrl+C encerra)
""", flush=True)

    enc = EncoderQuadratura(backend, pinos.ENC_A, pinos.ENC_B)
    inicio = enc.contagem
    fim = time.monotonic() + segundos
    while time.monotonic() < fim:
        contagem = enc.contagem
        print("\r  contagem = %8d   (%+8.1f mm desde o inicio)   "
              "invalidas = %d      "
              % (contagem, contagem - inicio, enc.transicoes_invalidas),
              end="", flush=True)
        time.sleep(0.1)
    print("\n", flush=True)

    if enc.contagem == inicio:
        print("  AVISO: a contagem nao mudou. Encoder nao esta chegando na "
              "placa.", flush=True)
    if enc.transicoes_invalidas:
        print("  AVISO: %d transicoes invalidas - bordas estao se perdendo. "
              "Ver Secao 6 do docs/BANCADA.md." % enc.transicoes_invalidas,
              flush=True)


# ----------------------------------------------------------------------
# Etapa 4 - direcao (move o motor)
# ----------------------------------------------------------------------
def etapa_direcao(backend):
    barra("ETAPA 4 - DIRECAO (O MOTOR SE MOVE)")
    print("""
  Percorre as quatro linhas da Tabela 2. Mantenha a mao no Ctrl+C.
  Se "subir" descer, DIR1 e DIR2 estao trocados.
""", flush=True)
    if not confirma("  Liberar o motor para se mover?"):
        print("  cancelado.", flush=True)
        return

    dir1 = SaidaDigital(backend, pinos.DIR1, "DIR1")
    dir2 = SaidaDigital(backend, pinos.DIR2, "DIR2")
    pwm = SaidaPWM(backend, pinos.PWM)
    enc = EncoderQuadratura(backend, pinos.ENC_A, pinos.ENC_B)

    try:
        for acao, (v1, v2) in [("LIVRE", (0, 0)), ("SUBIR", (1, 0)),
                               ("DESCER", (0, 1)), ("FREIO", (1, 1))]:
            if not confirma("\n  Aplicar %s (DIR1=%d DIR2=%d)?" % (acao, v1, v2)):
                continue
            antes = enc.contagem
            dir1.escreve(v1)
            dir2.escreve(v2)
            pwm.ajusta(20.0 if acao in ("SUBIR", "DESCER") else 0.0)
            time.sleep(1.5)
            pwm.ajusta(0.0)
            delta = enc.contagem - antes
            print("    %s: a cabine andou %+d mm  %s"
                  % (acao, delta,
                     "(esperado: parada)" if acao in ("LIVRE", "FREIO")
                     else "(esperado: %s)" % ("subiu" if acao == "SUBIR"
                                              else "desceu")), flush=True)
    finally:
        pwm.ajusta(0.0)
        dir1.escreve(1)
        dir2.escreve(1)   # freio
        pwm.finaliza()
        print("\n  motor deixado em FREIO com PWM zerado.", flush=True)


# ----------------------------------------------------------------------
# Etapa 5 - PWM (move o motor)
# ----------------------------------------------------------------------
def etapa_pwm(backend):
    barra("ETAPA 5 - PWM E ATRITO ESTATICO (O MOTOR SE MOVE)")
    print("""
  Rampa de 0 a %.0f%% subindo. A cabine nao deve sair do lugar abaixo de
  ~10%%: e o atrito estatico descrito no enunciado, nao defeito.
""" % DUTY_MAXIMO_ENSAIO, flush=True)
    if not confirma("  Liberar o motor para se mover?"):
        print("  cancelado.", flush=True)
        return

    dir1 = SaidaDigital(backend, pinos.DIR1, "DIR1")
    dir2 = SaidaDigital(backend, pinos.DIR2, "DIR2")
    pwm = SaidaPWM(backend, pinos.PWM)
    enc = EncoderQuadratura(backend, pinos.ENC_A, pinos.ENC_B)

    duty_de_arranque = None
    try:
        dir1.escreve(1)
        dir2.escreve(0)          # subir
        duty = 0.0
        while duty <= DUTY_MAXIMO_ENSAIO:
            antes = enc.contagem
            pwm.ajusta(duty)
            time.sleep(0.6)
            andou = enc.contagem - antes
            if andou and duty_de_arranque is None:
                duty_de_arranque = duty
            print("    duty = %5.1f %%   andou %+4d mm   %s"
                  % (duty, andou, "<-- ARRANCOU" if andou and
                     duty_de_arranque == duty else ""), flush=True)
            duty += PASSO_RAMPA
    finally:
        pwm.ajusta(0.0)
        dir1.escreve(1)
        dir2.escreve(1)   # freio
        pwm.finaliza()
        print("\n  motor deixado em FREIO com PWM zerado.", flush=True)

    if duty_de_arranque is None:
        print("  AVISO: a cabine nao se moveu ate %.0f%%. Confira DIR1/DIR2 e "
              "o pino de PWM." % DUTY_MAXIMO_ENSAIO, flush=True)
    else:
        print("  Duty minimo de arranque medido: %.1f %%  "
              "(anote no docs/BANCADA.md, Secao 8)" % duty_de_arranque,
              flush=True)


ETAPAS = {
    "mapa": etapa_mapa,
    "entradas": etapa_entradas,
    "encoder": etapa_encoder,
    "direcao": etapa_direcao,
    "pwm": etapa_pwm,
}


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Bring-up da Cabine 1 - ver docs/BANCADA.md")
    parser.add_argument("etapa", choices=sorted(ETAPAS), nargs="?",
                        default="mapa")
    parser.add_argument("--simulado", action="store_true",
                        help="ensaia o roteiro sem a placa")
    parser.add_argument("--segundos", type=float, default=30.0,
                        help="duracao das etapas de leitura (padrao: 30)")
    args = parser.parse_args(argv)

    if args.etapa == "mapa":          # nao precisa de GPIO nenhuma
        etapa_mapa()
        return 0

    if args.simulado:
        from src.gpio.sim_backend import BackendSimulado
        backend = BackendSimulado()
        print("### modo SIMULADO ###", flush=True)
    else:
        from src.gpio.rpi_backend import BackendRPi
        backend = BackendRPi()

    def encerra(*_):
        print("\n  interrompido: liberando a GPIO...", flush=True)
        backend.finaliza()
        sys.exit(0)

    signal.signal(signal.SIGINT, encerra)
    try:
        if args.etapa in ("entradas", "encoder"):
            ETAPAS[args.etapa](backend, args.segundos)
        else:
            ETAPAS[args.etapa](backend)
    finally:
        backend.finaliza()
    return 0


if __name__ == "__main__":
    sys.exit(main())
