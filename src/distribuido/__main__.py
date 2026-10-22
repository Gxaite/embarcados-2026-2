"""Ponto de entrada do Servidor Distribuido.

Uso, na Raspberry Pi, um terminal (ou janela do tmux) por cabine:
    python3 -m src.distribuido --cabine 1
    python3 -m src.distribuido --config config/cabine2.json --registra-pid dados/pid2.csv

Pode subir antes ou depois do Servidor Central: a cabine escuta na porta TCP
do seu arquivo de configuracao e espera o central conectar para calibrar.
"""
import argparse
import signal
import sys
import threading

from .. import configuracao
from .cabine import ServidorDistribuido
from .registro_pid import RegistroPID


def main(argv=None):
    parser = argparse.ArgumentParser(description="Servidor Distribuido de uma cabine")
    grupo = parser.add_mutually_exclusive_group(required=True)
    grupo.add_argument("--cabine", type=int, choices=(1, 2, 3),
                       help="usa config/cabineN.json")
    grupo.add_argument("--config", help="arquivo de configuracao da cabine")
    parser.add_argument("--registra-pid", metavar="CSV",
                        help="grava cada ciclo da malha num CSV (graficos do README)")
    args = parser.parse_args(argv)

    arquivo = args.config or configuracao.arquivo_da_cabine(args.cabine)
    try:
        config = configuracao.le_cabine(arquivo)
    except configuracao.ErroDeConfiguracao as erro:
        parser.error(str(erro))

    from ..gpio.rpi_backend import BackendRPi
    registro = RegistroPID(args.registra_pid) if args.registra_pid else None
    servidor = ServidorDistribuido(config, BackendRPi(), registro_pid=registro)

    terminou = threading.Event()
    encerrando = {"sim": False}

    def encerra(numero_do_sinal, _quadro):
        if encerrando["sim"]:
            return
        encerrando["sim"] = True
        print("\n%s recebido: PWM em zero, freio, GPIO e TCP liberados..."
              % signal.Signals(numero_do_sinal).name, flush=True)
        servidor.finaliza()
        if registro is not None:
            registro.fecha()
        print("cabine %d encerrada com seguranca." % config["cabine"], flush=True)
        terminou.set()

    # SIGHUP: a bancada e remota; uma queda de SSH nao pode deixar o motor
    # girando (ver Entrega 1).
    for sinal in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sinal, encerra)

    servidor.inicia()
    # O processo principal so espera o sinal: o trabalho e das threads.
    while not terminou.wait(3600):
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
