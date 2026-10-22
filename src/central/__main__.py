"""Ponto de entrada do Servidor Central.

Uso, na Raspberry Pi:
    python3 -m src.central                     # painel em tela cheia
    python3 -m src.central --sem-tela          # eventos em texto e comandos por linha

A matricula vem de --matricula, de $FSE_MATRICULA ou do arquivo `matricula`
(como na Entrega 2). O central pode subir antes ou depois das cabines: ele
tenta conectar em cada uma a cada segundo.
"""
import argparse
import signal
import sys

from .. import configuracao
from ..comunicacao import abre_sensor, obtem_matricula
from ..uart import modbus
from ..uart.elevadores import Elevadores
from .comandos import Comandos
from .condicao_contorno import PERIODO_PADRAO_S, ServicoCondicaoContorno
from .interface import InterfaceDeTela
from .registro_potencia import RegistroDePotencia
from .servidor_central import ServidorCentral


def roda_interface(servidor, comandos, sem_tela):
    if not sem_tela and sys.stdout.isatty():
        InterfaceDeTela(servidor, comandos.executa).roda()
        return
    print(comandos.ajuda, flush=True)
    while True:
        try:
            linha = input("central> ")
        except EOFError:
            return
        resposta = comandos.executa(linha)
        if resposta is None:
            return
        print(resposta, flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Servidor Central")
    parser.add_argument("--config", help="arquivo de configuracao (padrao: config/central.json)")
    parser.add_argument("--matricula", help="matricula; usa os 6 ultimos digitos")
    parser.add_argument("--sem-tela", action="store_true",
                        help="sem painel curses: eventos em texto e comandos por linha")
    parser.add_argument("--registra-potencia", metavar="CSV",
                        help="grava capacidade, Cotas e correntes a cada 1 s")
    args = parser.parse_args(argv)
    try:
        config = configuracao.le_central(args.config)
    except configuracao.ErroDeConfiguracao as erro:
        parser.error(str(erro))

    matricula = obtem_matricula(args.matricula)
    from ..uart.porta import PortaSerial
    porta = PortaSerial(config["uart"])
    elevadores = Elevadores(modbus.ClienteModbus(porta, matricula, eco=None,
                                                 timeout_s=config["timeout_s"]))
    sensor, barramento = abre_sensor(False, config["i2c"])

    eco = print if args.sem_tela or not sys.stdout.isatty() else None
    potencia = RegistroDePotencia(args.registra_potencia) if args.registra_potencia else None
    servidor = ServidorCentral(config, elevadores, eco=eco, registro_de_potencia=potencia)
    if sensor is not None:
        servidor.contorno = ServicoCondicaoContorno(
            sensor, elevadores, periodo_s=PERIODO_PADRAO_S, eco=servidor.log)
    else:
        servidor.log("AVISO: sem BMP280 o watchdog expira e o barramento cai a 3000 mA")

    encerrando = {"sim": False}

    def finaliza():
        if encerrando["sim"]:
            return
        encerrando["sim"] = True
        servidor.finaliza()
        if potencia is not None:
            potencia.fecha()
        porta.fecha()
        if barramento is not None:
            barramento.fecha()

    def encerra(numero_do_sinal, _quadro):
        finaliza()
        print("\n%s recebido: estado salvo, UART e I2C fechados, TCP encerrado."
              % signal.Signals(numero_do_sinal).name, flush=True)
        sys.exit(0)

    for sinal in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sinal, encerra)

    servidor.inicia()
    try:
        roda_interface(servidor, Comandos(servidor), args.sem_tela)
    finally:
        finaliza()
    print("Servidor Central encerrado.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
