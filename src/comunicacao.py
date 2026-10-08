"""Ponto de entrada da Entrega 2: UART (Partes 1, 2 e 3) e I2C.

Uso:
    python3 -m src.comunicacao                # na Raspberry Pi
    python3 -m src.comunicacao --simulado     # sem placa, contra a ESP32 simulada

E um executavel irmao do src.main (controle da cabine por GPIO): os dois nao
dividem recurso nenhum. Na Entrega Final, a UART e o I2C ficam com o Servidor
Central e a GPIO com os Servidores Distribuidos, que importam os mesmos
modulos.
"""
import argparse
import signal
import sys

from . import cli_comunicacao as cli
from .central.condicao_contorno import PERIODO_PADRAO_S, ServicoCondicaoContorno
from .i2c import bmp280
from .uart import matricula as mat
from .uart import modbus
from .uart.elevadores import Elevadores
from .uart.modbus_didatico import ModbusDidatico
from .uart.porta import PORTA_PADRAO
from .uart.simplificado import ProtocoloSimplificado


def _imprime(texto):
    print(texto, flush=True)


def obtem_matricula(argumento):
    bytes_da_matricula = mat.resolve(argumento)
    while bytes_da_matricula is None:
        print("Matricula nao configurada (--matricula, $%s ou arquivo %s)."
              % (mat.VARIAVEL_DE_AMBIENTE, mat.ARQUIVO), flush=True)
        try:
            bytes_da_matricula = mat.em_bytes(input("matricula: "))
        except ValueError as erro:
            print(erro, flush=True)
    return bytes_da_matricula


def abre_porta(simulado, caminho):
    if simulado:
        from .uart.esp32_simulada import Esp32Simulada, PortaSimulada
        esp32 = Esp32Simulada()
        esp32.registra_chamada(0, 4)
        esp32.registra_chamada(3, 0)
        return PortaSimulada(esp32), esp32
    from .uart.porta import PortaSerial
    return PortaSerial(caminho), None


def abre_sensor(simulado, numero_do_barramento):
    """Abre o BMP280. Sem ele a UART continua utilizavel, entao a falha so
    desliga o que depende do sensor."""
    try:
        if simulado:
            from .i2c.bmp280_simulado import BarramentoBMP280Simulado
            barramento = BarramentoBMP280Simulado(temperatura_c=27.5,
                                                  pressao_hpa=887.0)
        else:
            from .i2c.barramento import BarramentoLinux
            barramento = BarramentoLinux(numero_do_barramento)
    except OSError as erro:
        print("AVISO: barramento I2C indisponivel (%s)" % erro, flush=True)
        return None, None
    try:
        return bmp280.BMP280(barramento), barramento
    except (OSError, bmp280.ErroBMP280) as erro:
        print("AVISO: BMP280 nao respondeu em 0x%02X (%s)"
              % (bmp280.ENDERECO_PADRAO, erro), flush=True)
        barramento.fecha()
        return None, None


def main(argv=None):
    parser = argparse.ArgumentParser(description="Entrega 2: UART-MODBUS e I2C")
    parser.add_argument("--simulado", action="store_true",
                        help="usa a ESP32 e o BMP280 simulados (sem placa)")
    parser.add_argument("--porta", default=PORTA_PADRAO,
                        help="dispositivo da UART (padrao: %s)" % PORTA_PADRAO)
    parser.add_argument("--i2c", type=int, default=1,
                        help="numero do barramento I2C (padrao: 1)")
    parser.add_argument("--matricula",
                        help="matricula; usa os 6 ultimos digitos")
    parser.add_argument("--timeout", type=float, default=modbus.TIMEOUT_PADRAO_S,
                        help="timeout de cada tentativa, em s (0,2 a 0,5)")
    parser.add_argument("--contorno-auto", action="store_true",
                        help="liga a escrita periodica da Condicao de Contorno")
    args = parser.parse_args(argv)
    if not 0.2 <= args.timeout <= 0.5:
        parser.error("o enunciado pede timeout entre 0,2 e 0,5 s")

    matricula = obtem_matricula(args.matricula)
    porta, esp32 = abre_porta(args.simulado, args.porta)
    if args.simulado:
        print("### modo SIMULADO: ESP32 e BMP280 em software ###", flush=True)
    sensor, barramento = abre_sensor(args.simulado, args.i2c)

    elevadores = Elevadores(modbus.ClienteModbus(
        porta, matricula, eco=_imprime, timeout_s=args.timeout))
    servico = None
    if sensor is not None:
        # Cliente proprio, mudo: a escrita a cada 4 s nao pode encher o
        # terminal de bytes. Ele divide a porta (e a trava) com o da CLI.
        servico = ServicoCondicaoContorno(
            sensor,
            Elevadores(modbus.ClienteModbus(porta, matricula, eco=None,
                                            timeout_s=args.timeout)),
            periodo_s=PERIODO_PADRAO_S, eco=_imprime)
    contexto = cli.Contexto(
        ProtocoloSimplificado(porta, matricula, eco=_imprime, timeout_s=args.timeout),
        ModbusDidatico(porta, matricula, eco=_imprime, timeout_s=args.timeout),
        elevadores, sensor=sensor, servico=servico, esp32_simulada=esp32)

    encerrando = {"sim": False}

    def finaliza():
        if encerrando["sim"]:
            return
        encerrando["sim"] = True
        if servico is not None:
            servico.para()
        porta.fecha()
        if barramento is not None:
            barramento.fecha()

    def encerra(numero_do_sinal, _quadro):
        print("\n%s recebido: parando a Condicao de Contorno e fechando UART e "
              "I2C..." % signal.Signals(numero_do_sinal).name, flush=True)
        finaliza()
        print("encerrado com seguranca.", flush=True)
        sys.exit(0)

    for sinal in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sinal, encerra)

    print("matricula em uso: %s | UART %s | timeout %d ms | BMP280 %s"
          % (mat.como_texto(matricula), "simulada" if args.simulado else args.porta,
             round(args.timeout * 1000), "ok" if sensor else "indisponivel"),
          flush=True)
    if args.contorno_auto and servico is not None:
        servico.inicia()
    print(cli.AJUDA, flush=True)
    try:
        while True:
            try:
                linha = input("uart> ")
            except EOFError:
                break
            if not cli.executa(contexto, linha):
                break
    finally:
        finaliza()
    return 0


if __name__ == "__main__":
    sys.exit(main())
