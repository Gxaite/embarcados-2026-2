"""Ativacao da placa por etapas, da mais segura para a menos.

A ordem nao e arbitraria: entradas antes de saidas, saidas antes de movimento.
Cada etapa isola uma classe de falha, e as duas ultimas so rodam com
confirmacao explicita porque movem o motor de verdade.

    python3 -m ferramentas.bringup mapa       # nao toca na GPIO
    python3 -m ferramentas.bringup entradas   # so le
    python3 -m ferramentas.bringup encoder    # conta bordas
    python3 -m ferramentas.bringup direcao    # MOVE o motor
    python3 -m ferramentas.bringup pwm        # MOVE o motor
    python3 -m ferramentas.bringup limpa      # libera a GPIO e sai

Acrescente --simulado para ensaiar o roteiro sem a placa.
"""
import argparse
import time

from src.gpio import pinos
from src.gpio.encoder import EncoderQuadratura
from src.gpio.entradas import EntradaPolling
from src.gpio.saidas import SaidaDigital, SaidaPWM


def barra(titulo):
    print("\n" + "=" * 62 + "\n  %s\n" % titulo + "=" * 62, flush=True)


def confirma(pergunta):
    try:
        return input("%s [s/N] " % pergunta).strip().lower() in ("s", "sim")
    except EOFError:
        return False


def etapa_mapa(_backend=None):
    barra("ETAPA 1 - PINAGEM DA CABINE 1")
    print("  O numero BCM NAO e a posicao no conector. Confira fio a fio.\n")
    print("  %-14s %-8s %-14s %s" % ("SINAL", "BCM", "PINO FISICO", "FUNCAO"))
    print("  " + "-" * 58)
    funcoes = {
        pinos.PWM: "saida (PWM 1 kHz)",
        pinos.DIR1: "saida on/off",
        pinos.DIR2: "saida on/off",
        pinos.ENC_A: "entrada (interrupcao)",
        pinos.ENC_B: "entrada (interrupcao)",
        pinos.CORTINA: "entrada on/off",
        pinos.SENSOR_ANDAR: "entrada on/off",
    }
    for pino in (pinos.PWM, pinos.DIR1, pinos.DIR2, pinos.ENC_A,
                 pinos.ENC_B, pinos.CORTINA, pinos.SENSOR_ANDAR):
        print("  %-14s %-8d %-14d %s"
              % (pinos.NOME[pino], pino, pinos.PINO_FISICO[pino], funcoes[pino]))
    print("""
  Os dois que se confundem:
    DIR1         = GPIO 17 -> pino fisico 11
    SENSOR_ANDAR = GPIO 11 -> pino fisico 23
""", flush=True)


def etapa_entradas(backend, segundos=30.0):
    barra("ETAPA 2 - ENTRADAS ON/OFF (nao move nada)")
    print("""  Estimule pelo widget do ThingsBoard:
    CORTINA      -> botao "Obstruir porta"
    SENSOR_ANDAR -> mova a cabine ate dentro de uma bandeirola

  Pino preso em 0 ou em 1 e fiacao ou periferico tomando o pino, nao e o
  codigo. Confira a secao de conflitos do README.   (Ctrl+C encerra)
""", flush=True)
    cortina = EntradaPolling(backend, pinos.CORTINA)
    sensor = EntradaPolling(backend, pinos.SENSOR_ANDAR)
    mudancas = {"cortina": 0, "sensor": 0}
    anterior = (cortina.le(), sensor.le())
    fim = time.monotonic() + segundos
    try:
        while time.monotonic() < fim:
            atual = (cortina.le(), sensor.le())
            if atual[0] != anterior[0]:
                mudancas["cortina"] += 1
            if atual[1] != anterior[1]:
                mudancas["sensor"] += 1
            anterior = atual
            print("\r  CORTINA=%d (%d mudancas)   SENSOR_ANDAR=%d (%d mudancas)   "
                  % (atual[0], mudancas["cortina"], atual[1], mudancas["sensor"]),
                  end="", flush=True)
            time.sleep(0.05)
    except KeyboardInterrupt:
        pass
    print("\n", flush=True)
    for nome, chave in (("CORTINA", "cortina"), ("SENSOR_ANDAR", "sensor")):
        if mudancas[chave] == 0:
            print("  AVISO: %s nao mudou em %.0f s. Ou ninguem estimulou pelo "
                  "widget, ou o sinal nao chega." % (nome, segundos), flush=True)


def etapa_encoder(backend, segundos=30.0):
    barra("ETAPA 3 - ENCODER (nao move nada)")
    print("""  Mova a cabine pelo widget e observe:
    - a contagem deve SUBIR ao subir e DESCER ao descer;
      invertido significa ENC_A e ENC_B trocados;
    - 1 contagem = 1 mm; um andar = 3000 contagens;
    - transicoes invalidas deve ficar em ZERO.

  Transicao invalida e salto impossivel na quadratura: so acontece quando uma
  borda de interrupcao se perde. Se esse numero cresce, a posicao esta
  derivando e o nivelamento vai falhar de forma intermitente.   (Ctrl+C encerra)
""", flush=True)
    encoder = EncoderQuadratura(backend)
    fim = time.monotonic() + segundos
    try:
        while time.monotonic() < fim:
            print("\r  contagem=%-10d  invalidas=%-6d"
                  % (encoder.contagem, encoder.transicoes_invalidas),
                  end="", flush=True)
            time.sleep(0.05)
    except KeyboardInterrupt:
        pass
    print("\n", flush=True)
    if encoder.transicoes_invalidas:
        print("  ATENCAO: %d transicoes invalidas. O Python esta perdendo bordas."
              % encoder.transicoes_invalidas, flush=True)
    encoder.finaliza()


def etapa_direcao(backend):
    barra("ETAPA 4 - DIRECAO (O MOTOR SE MOVE)")
    print("""  Percorre as quatro linhas da tabela de direcao. Mantenha a mao no
  Ctrl+C. Se "subir" descer, DIR1 e DIR2 estao trocados.
""", flush=True)
    if not confirma("  Liberar o motor para se mover?"):
        print("  cancelado.", flush=True)
        return

    dir1 = SaidaDigital(backend, pinos.DIR1)
    dir2 = SaidaDigital(backend, pinos.DIR2)
    pwm = SaidaPWM(backend, pinos.PWM)
    encoder = EncoderQuadratura(backend)
    try:
        for acao in (pinos.LIVRE, pinos.SUBIR, pinos.DESCER, pinos.FREIO):
            v1, v2 = pinos.DIRECOES[acao]
            if not confirma("\n  Aplicar %s (DIR1=%d DIR2=%d)?" % (acao.upper(), v1, v2)):
                continue
            antes = encoder.contagem
            dir1.escreve(v1)
            dir2.escreve(v2)
            pwm.ajusta(20.0 if acao in (pinos.SUBIR, pinos.DESCER) else 0.0)
            time.sleep(1.5)
            pwm.ajusta(0.0)
            delta = encoder.contagem - antes
            esperado = {pinos.LIVRE: "parada", pinos.FREIO: "parada",
                        pinos.SUBIR: "subiu", pinos.DESCER: "desceu"}[acao]
            print("    %s: a cabine andou %+d mm  (esperado: %s)"
                  % (acao.upper(), delta, esperado), flush=True)
    finally:
        pwm.ajusta(0.0)
        dir1.escreve(1)
        dir2.escreve(1)
        pwm.finaliza()
        encoder.finaliza()
        print("\n  motor deixado em FREIO com PWM zerado.", flush=True)


def etapa_pwm(backend):
    barra("ETAPA 5 - PWM (O MOTOR SE MOVE)")
    print("""  Rampa de 0 a 30%%. A cabine nao deve sair do lugar abaixo de ~10%%:
  e o atrito estatico do enunciado, nao defeito. Anote o duty em que ela
  comeca a andar - esse numero entra no README.
""", flush=True)
    if not confirma("  Liberar o motor para se mover?"):
        print("  cancelado.", flush=True)
        return

    dir1 = SaidaDigital(backend, pinos.DIR1)
    dir2 = SaidaDigital(backend, pinos.DIR2)
    pwm = SaidaPWM(backend, pinos.PWM)
    encoder = EncoderQuadratura(backend)
    arranque = None
    try:
        dir1.escreve(1)
        dir2.escreve(0)          # subir
        for duty in range(0, 31, 2):
            antes = encoder.contagem
            pwm.ajusta(float(duty))
            time.sleep(1.0)
            delta = encoder.contagem - antes
            print("    duty %2d%% -> %+d mm" % (duty, delta), flush=True)
            if arranque is None and abs(delta) > 2:
                arranque = duty
    finally:
        pwm.ajusta(0.0)
        dir1.escreve(1)
        dir2.escreve(1)
        pwm.finaliza()
        encoder.finaliza()
        if arranque is not None:
            print("\n  duty minimo de arranque medido: %d%%" % arranque, flush=True)
        print("  motor deixado em FREIO com PWM zerado.", flush=True)


def etapa_limpa(backend):
    barra("LIMPEZA DA GPIO")
    for pino in (pinos.DIR1, pinos.DIR2):
        SaidaDigital(backend, pino, 1)       # freio
    backend.limpa()
    print("  GPIO liberada. Pode dar exit no SSH.", flush=True)


ETAPAS = {
    "mapa": etapa_mapa,
    "entradas": etapa_entradas,
    "encoder": etapa_encoder,
    "direcao": etapa_direcao,
    "pwm": etapa_pwm,
    "limpa": etapa_limpa,
}
COM_DURACAO = ("entradas", "encoder")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Bring-up da Cabine 1, etapa por etapa")
    parser.add_argument("etapa", choices=sorted(ETAPAS), nargs="?", default="mapa")
    parser.add_argument("--simulado", action="store_true",
                        help="ensaia o roteiro sem a placa")
    parser.add_argument("--segundos", type=float, default=30.0,
                        help="duracao das etapas de leitura (padrao: 30)")
    args = parser.parse_args(argv)

    if args.etapa == "mapa":
        etapa_mapa()
        return 0

    if args.simulado:
        from src.gpio.sim_backend import BackendSimulado
        backend = BackendSimulado()
        print("### modo SIMULADO ###", flush=True)
    else:
        from src.gpio.rpi_backend import BackendRPi
        backend = BackendRPi()

    try:
        if args.etapa in COM_DURACAO:
            ETAPAS[args.etapa](backend, args.segundos)
        else:
            ETAPAS[args.etapa](backend)
    finally:
        if args.etapa != "limpa":
            backend.limpa()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
