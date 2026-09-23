"""Ponto de entrada do controle da Cabine 1.

Uso:
    python3 -m src.main              # na Raspberry Pi, GPIO real
    python3 -m src.main --simulado   # sem placa, contra o modelo do poco
"""
import argparse
import signal
import sys

from . import cli
from .controle.cabine import Cabine


def cria_backend(simulado, posicao_inicial_mm):
    if simulado:
        from .gpio.sim_backend import BackendSimulado
        print("### modo SIMULADO: modelo do poco em software, sem GPIO real ###",
              flush=True)
        return BackendSimulado(posicao_inicial_mm), True
    from .gpio.rpi_backend import BackendRPi
    return BackendRPi(), False


def main(argv=None):
    parser = argparse.ArgumentParser(description="Controle da Cabine 1")
    parser.add_argument("--simulado", action="store_true",
                        help="usa o modelo do poco em software (sem placa)")
    parser.add_argument("--posicao-inicial", type=float, default=0.0,
                        help="posicao inicial da cabine em mm (padrao: 0)")
    args = parser.parse_args(argv)

    backend, e_simulador = cria_backend(args.simulado, args.posicao_inicial)
    cabine = Cabine(backend, posicao_inicial_mm=args.posicao_inicial)
    simulador = backend if e_simulador else None

    encerrando = {"sim": False}

    def encerra(numero_do_sinal, _quadro):
        """Zera o PWM, poe a direcao em freio e libera a GPIO."""
        if encerrando["sim"]:
            return
        encerrando["sim"] = True
        print("\n%s recebido: zerando PWM, aplicando freio e liberando a GPIO..."
              % signal.Signals(numero_do_sinal).name, flush=True)
        cabine.finaliza()
        print("encerrado com seguranca.", flush=True)
        sys.exit(0)

    # SIGINT e o requisito 6 da Secao 3. SIGTERM e SIGHUP estao aqui porque a
    # bancada e remota e compartilhada: se a conexao SSH cair no meio de uma
    # viagem, o default do SIGHUP mataria o processo com o motor girando e a
    # GPIO configurada, na placa do proximo da fila.
    for sinal in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sinal, encerra)

    print(cli.AJUDA, flush=True)
    try:
        while True:
            try:
                linha = input("cabine1> ")
            except EOFError:
                break
            if not cli.executa(cabine, linha, simulador):
                break
    finally:
        if not encerrando["sim"]:
            encerrando["sim"] = True
            cabine.finaliza()
    return 0


if __name__ == "__main__":
    sys.exit(main())
