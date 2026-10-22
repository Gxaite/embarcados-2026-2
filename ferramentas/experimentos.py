"""Experimentos do README, contra o predio simulado.

    python3 -m ferramentas.experimentos pid        # sintonia: Kd 40, 15 e 5
    python3 -m ferramentas.experimentos cota       # saturacao pela Cota e degradado
    python3 -m ferramentas.experimentos cenarios   # os tres Cenarios de Trafego

Os CSVs vao para docs/experimentos/ e os graficos saem com
`python3 -m ferramentas.graficos`. Na placa, os mesmos CSVs sao gravados por
`--registra-pid` (cabine) e `--registra-potencia` (central).
"""
import argparse
import json
import os
import shutil
import sys
import time

from src.controle.motor import Motor
from src.distribuido.cota import duty_maximo_de
from src.distribuido.malha import CHEGOU, MalhaDePosicao
from src.distribuido.pid import PID
from src.distribuido.registro_pid import RegistroPID
from src.gpio.encoder import EncoderQuadratura
from src.simulacao.backend import BackendDoPoco
from src.simulacao.predio import Esp32Predio

PASTA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "docs", "experimentos")


def _cabine_sozinha():
    predio = Esp32Predio()
    fisica = predio.fisicas[1]
    backend = BackendDoPoco(fisica)
    pinagem = fisica.pinagem
    encoder = EncoderQuadratura(backend, pinagem["ENC_A"], pinagem["ENC_B"])
    encoder.zera(int(fisica.posicao_mm))
    motor = Motor(backend, pinagem)
    return predio, fisica, encoder, motor


def _viaja(malha, destino, limite_s=60.0, durante=None):
    malha.vai_para(destino)
    inicio = time.monotonic()
    while malha.fase != CHEGOU and time.monotonic() - inicio < limite_s:
        time.sleep(0.05)
        if durante is not None:
            durante(time.monotonic() - inicio)
        malha.passo(0.05)
    for _ in range(10):              # registra o repouso depois da chegada
        time.sleep(0.05)
        malha.passo(0.05)
    return time.monotonic() - inicio


def pid(_args):
    resultados = {}
    for kp, ki, kd in ((0.5, 0.05, 40.0), (0.5, 0.05, 15.0), (0.5, 0.05, 5.0)):
        nome = "pid_kd%g.csv" % kd
        registro = RegistroPID(os.path.join(PASTA, nome))
        predio, fisica, encoder, motor = _cabine_sozinha()
        malha = MalhaDePosicao(motor, encoder, PID(kp, ki, kd), ao_registrar=registro)
        malha.duty_maximo = duty_maximo_de(4000)
        tempos = [_viaja(malha, fisica.andares_mm[a]) for a in (1, 4)]
        erro = fisica.posicao_mm - fisica.andares_mm[4]
        resultados[nome] = {"kp": kp, "ki": ki, "kd": kd, "tempos_s": tempos,
                            "erro_final_mm": erro, "pulsos": malha.pulsos}
        print("Kd %-4g  1 andar %.1f s   3 andares %.1f s   erro final %+.1f mm"
              % (kd, tempos[0], tempos[1], erro), flush=True)
        registro.fecha()
        predio.encerra()
    with open(os.path.join(PASTA, "pid.json"), "w") as saida:
        json.dump(resultados, saida, indent=2)


def cota(_args):
    """Viagem do andar 0 ao 5 com a Cota caindo no meio, e depois vencendo."""
    registro = RegistroPID(os.path.join(PASTA, "cota.csv"))
    predio, fisica, encoder, motor = _cabine_sozinha()
    malha = MalhaDePosicao(motor, encoder, PID(0.5, 0.05, 15.0), ao_registrar=registro)
    etapas = ((0.0, 6000), (6.0, 3000), (12.0, 1000))

    def ajusta_cota(decorrido):
        for inicio, cota_ma in etapas:
            if decorrido >= inicio:
                malha.limita(duty_maximo_de(cota_ma))

    malha.duty_maximo = duty_maximo_de(6000)
    _viaja(malha, fisica.andares_mm[5], limite_s=90.0, durante=ajusta_cota)
    registro.fecha()
    predio.encerra()
    print("cota.csv gravado", flush=True)


def cenarios(args):
    from src.central.registro_potencia import RegistroDePotencia
    from src.simulacao.__main__ import finaliza, inicia, monta
    pasta = os.path.join(PASTA, "simulacao")
    shutil.rmtree(pasta, ignore_errors=True)
    sistema = monta(perda_de_transicoes=0.0002, pasta=pasta,
                    eco=(lambda t: print(t, flush=True)) if args.verboso else None)
    potencia = RegistroDePotencia(os.path.join(PASTA, "potencia.csv"))
    sistema["central"].registro_de_potencia = potencia
    inicia(sistema)
    predio = sistema["predio"]
    inicio = time.monotonic()
    while not all(c.mapa is not None for c in sistema["cabines"].values()):
        time.sleep(1)
    print("calibradas em %.0f s" % (time.monotonic() - inicio), flush=True)
    resultados = {}
    for nome in args.cenarios:
        antes = set(predio.chamadas)
        predio.inicia_cenario(nome, duracao_s=args.duracao)
        time.sleep(1)
        while predio.cenario_ativo or any(
                c.desembarque is None for i, c in predio.chamadas.items() if i not in antes):
            time.sleep(1)
        chamadas = [c for i, c in predio.chamadas.items() if i not in antes]
        esperas = [c.embarque - c.registro for c in chamadas]
        viagens = [c.desembarque - c.embarque for c in chamadas]
        resultados[nome] = {
            "chamadas": len(chamadas),
            "espera_media_s": sum(esperas) / len(esperas),
            "espera_maxima_s": max(esperas),
            "viagem_media_s": sum(viagens) / len(viagens),
            "por_cabine": {n: sum(1 for c in chamadas if c.cabine == n) for n in (1, 2, 3)},
        }
        print(nome, json.dumps(resultados[nome]), flush=True)
    resultados["violacoes"] = {n: [d for _, d in v] for n, v in predio.violacoes().items()}
    resultados["reancoragens"] = {n: c.reancoragens for n, c in sistema["cabines"].items()}
    resultados["transicoes_perdidas"] = {n: f.transicoes_perdidas
                                         for n, f in predio.fisicas.items()}
    with open(os.path.join(PASTA, "cenarios.json"), "w") as saida:
        json.dump(resultados, saida, indent=2)
    finaliza(sistema)
    potencia.fecha()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="experimento", required=True)
    sub.add_parser("pid")
    sub.add_parser("cota")
    cen = sub.add_parser("cenarios")
    cen.add_argument("--duracao", type=float, default=300.0)
    cen.add_argument("--cenarios", nargs="+",
                     default=["up-peak", "down-peak", "interfloor"])
    cen.add_argument("--verboso", action="store_true")
    args = parser.parse_args(argv)
    os.makedirs(PASTA, exist_ok=True)
    {"pid": pid, "cota": cota, "cenarios": cenarios}[args.experimento](args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
