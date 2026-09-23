"""Ponto de entrada do controle da Cabine 1 - Entrega 1.

Uso:
    python3 -m src.main            # na Raspberry Pi, GPIO real
    python3 -m src.main --simulado # sem placa, contra o modelo em software
"""
import argparse
import signal
import sys

from . import cli
from .controle.cabine import Cabine


def cria_backend(simulado):
    if simulado:
        from .gpio.sim_backend import BackendSimulado
        print("### modo SIMULADO: modelo do poco em software, sem GPIO real ###",
              flush=True)
        return BackendSimulado(), True
    from .gpio.rpi_backend import BackendRPi
    return BackendRPi(), False


def main(argv=None):
    parser = argparse.ArgumentParser(description="Controle da Cabine 1")
    parser.add_argument("--simulado", action="store_true",
                        help="usa o modelo de poco em software (sem placa)")
    parser.add_argument("--posicao-inicial", type=float, default=0.0,
                        help="posicao inicial da cabine em mm (padrao: 0)")
    args = parser.parse_args(argv)

    backend_gpio, e_simulador = cria_backend(args.simulado)
    cabine = Cabine(backend_gpio, posicao_inicial_mm=args.posicao_inicial)
    simulador = backend_gpio if e_simulador else None

    encerrando = {"sim": False}

    def encerra(*_):
        """SIGINT: zera o PWM, poe a direcao em freio e libera a GPIO."""
        if encerrando["sim"]:
            return
        encerrando["sim"] = True
        print("\nSIGINT recebido: zerando PWM, aplicando freio e liberando "
              "a GPIO...", flush=True)
        cabine.finaliza()
        print("encerrado com seguranca.", flush=True)
        sys.exit(0)

    signal.signal(signal.SIGINT, encerra)
    signal.signal(signal.SIGTERM, encerra)

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
