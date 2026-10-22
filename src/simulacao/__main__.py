"""Sistema completo contra o edificio simulado, sem placa.

    python3 -m src.simulacao
    python3 -m src.simulacao --sem-tela --registra-pid

Sobe, num processo so, o predio simulado, os tres Servidores Distribuidos e o
Servidor Central, cada um com o mesmo codigo que roda na Raspberry Pi. O que
muda e a ponta: GPIO e UART vao para a fisica simulada em vez do hardware. O
TCP entre central e cabines e de verdade, em localhost, nas portas dos
arquivos de configuracao.

Comandos a mais no painel (o quiosque e os botoes do dashboard):

  chamada <origem> <destino>     registra uma chamada no quiosque
  cenario <up-peak|down-peak|interfloor>
  obstrui <cabine> [s]           aciona a cortina de luz por s segundos
  derruba <cabine> [s]           derruba o TCP da cabine por s segundos
                                 (sem Cota: Modo Degradado)
  calor <graus>                  muda a temperatura do BMP280 simulado
  violacoes                      invariantes quebrados ate agora
"""
import argparse
import os
import signal
import sys
import threading

from .. import configuracao
from ..central.comandos import Comandos
from ..central.condicao_contorno import ServicoCondicaoContorno
from ..central.servidor_central import ServidorCentral
from ..distribuido.cabine import ServidorDistribuido
from ..distribuido.registro_pid import RegistroPID
from ..i2c import bmp280
from ..i2c.bmp280_simulado import BarramentoBMP280Simulado
from ..uart import modbus
from ..uart.elevadores import Elevadores
from ..uart.esp32_simulada import PortaSimulada
from .backend import BackendDoPoco
from .predio import CENARIOS, Esp32Predio

MATRICULA_DE_TESTE = bytes((0, 0, 0, 0, 0, 0))
PASTA_DE_DADOS = os.path.join(configuracao.RAIZ, "dados", "simulacao")


def monta(eco=None, perda_de_transicoes=0.0, andares_iniciais=(0, 0, 0),
          registra_pid=False, pasta=PASTA_DE_DADOS, temperatura_c=27.0,
          deslocamento_de_portas=0):
    """Cria predio, cabines e central. Devolve um dicionario com tudo.

    deslocamento_de_portas soma as portas TCP dos arquivos de configuracao,
    para rodar duas simulacoes (ou os testes) ao mesmo tempo."""
    predio = Esp32Predio(andar_inicial=andares_iniciais,
                         perda_de_transicoes=perda_de_transicoes)
    porta = PortaSimulada(predio)
    elevadores = Elevadores(modbus.ClienteModbus(porta, MATRICULA_DE_TESTE, eco=None))

    central_cfg = configuracao.le_central()
    central_cfg.update(
        arquivo_de_estado=os.path.join(pasta, "central_estado.json"),
        arquivo_de_viagens=os.path.join(pasta, "viagens.csv"),
        arquivo_de_eventos=os.path.join(pasta, "central.log"))
    for cabine in central_cfg["cabines"].values():
        cabine["porta"] += deslocamento_de_portas
    servidor = ServidorCentral(central_cfg, elevadores, eco=eco)
    barramento_i2c = BarramentoBMP280Simulado(temperatura_c=temperatura_c, pressao_hpa=887.0)
    servidor.contorno = ServicoCondicaoContorno(bmp280.BMP280(barramento_i2c), elevadores,
                                                eco=servidor.log)
    cabines, registros = {}, []
    for numero in (1, 2, 3):
        cfg = configuracao.le_cabine(configuracao.arquivo_da_cabine(numero))
        cfg["arquivo_de_calibracao"] = os.path.join(pasta, "calibracao_cabine%d.json"
                                                    % numero)
        cfg["tcp_porta"] += deslocamento_de_portas
        registro = None
        if registra_pid:
            registro = RegistroPID(os.path.join(pasta, "pid_cabine%d.csv" % numero))
            registros.append(registro)
        cabines[numero] = ServidorDistribuido(
            cfg, BackendDoPoco(predio.fisicas[numero]), eco=servidor.log,
            registro_pid=registro)
    return {"predio": predio, "central": servidor, "cabines": cabines,
            "i2c": barramento_i2c, "registros": registros}


def inicia(sistema):
    for cabine in sistema["cabines"].values():
        cabine.inicia()
    sistema["central"].inicia()


def finaliza(sistema):
    sistema["central"].finaliza()
    for cabine in sistema["cabines"].values():
        cabine.finaliza()
    for registro in sistema["registros"]:
        registro.fecha()
    sistema["predio"].encerra()


def comandos_do_simulador(sistema):
    predio, central = sistema["predio"], sistema["central"]

    def chamada(argumentos):
        origem, destino = int(argumentos[0]), int(argumentos[1])
        if not (0 <= origem <= 5 and 0 <= destino <= 5) or origem == destino:
            raise ValueError("andares de 0 a 5, origem diferente do destino")
        return "chamada %d registrada no quiosque: %d -> %d" % (
            predio.registra_chamada(origem, destino), origem, destino)

    def cenario(argumentos):
        if not argumentos or argumentos[0] not in CENARIOS:
            raise ValueError("cenarios: %s" % ", ".join(CENARIOS))
        predio.inicia_cenario(argumentos[0])
        return "cenario %s iniciado (5 min, semente fixa)" % argumentos[0]

    def obstrui(argumentos):
        numero = int(argumentos[0])
        segundos = float(argumentos[1]) if len(argumentos) > 1 else 3.0
        fisica = predio.fisicas[numero]
        fisica.aciona_cortina(True)
        threading.Timer(segundos, fisica.aciona_cortina, args=(False,)).start()
        return "cortina da cabine %d obstruida por %.0f s" % (numero, segundos)

    def derruba(argumentos):
        numero = int(argumentos[0])
        segundos = float(argumentos[1]) if len(argumentos) > 1 else 10.0
        central.cabines[numero].cliente.suspende(segundos)
        return "TCP da cabine %d derrubado por %.0f s" % (numero, segundos)

    def calor(argumentos):
        sistema["i2c"].ajusta(float(argumentos[0]), 887.0)
        return "BMP280 simulado em %.1f C" % float(argumentos[0])

    def violacoes(_argumentos):
        todas = predio.violacoes()
        texto = "; ".join("C%d: %s" % (n, ", ".join(d for _, d in v) or "nenhuma")
                          for n, v in todas.items())
        return texto + " | metricas: %s" % predio.metricas()

    return {
        "chamada": ("chamada <o> <d>", chamada),
        "cenario": ("cenario <nome>", cenario),
        "obstrui": ("obstrui <c> [s]", obstrui),
        "derruba": ("derruba <c> [s]", derruba),
        "calor": ("calor <C>", calor),
        "violacoes": ("violacoes", violacoes),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Sistema completo contra o predio simulado")
    parser.add_argument("--sem-tela", action="store_true")
    parser.add_argument("--registra-pid", action="store_true",
                        help="grava dados/simulacao/pid_cabineN.csv")
    parser.add_argument("--perda", type=float, default=0.0002,
                        help="fracao de transicoes do encoder perdidas (deriva)")
    args = parser.parse_args(argv)

    from ..central.__main__ import roda_interface
    eco = print if args.sem_tela or not sys.stdout.isatty() else None
    sistema = monta(eco=eco, perda_de_transicoes=args.perda,
                    registra_pid=args.registra_pid)

    def encerra(numero_do_sinal, _quadro):
        finaliza(sistema)
        print("\n%s recebido: simulacao encerrada." % signal.Signals(numero_do_sinal).name)
        sys.exit(0)

    for sinal in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sinal, encerra)
    inicia(sistema)
    try:
        roda_interface(sistema["central"],
                       Comandos(sistema["central"], comandos_do_simulador(sistema)),
                       args.sem_tela)
    finally:
        finaliza(sistema)
    return 0


if __name__ == "__main__":
    sys.exit(main())
