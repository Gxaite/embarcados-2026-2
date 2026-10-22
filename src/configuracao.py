"""Arquivos de configuracao da Entrega Final (pasta config/).

Cada Servidor Distribuido le o seu (cabine1.json, cabine2.json, cabine3.json)
e com ele se configura: pinos, endereco MODBUS, porta TCP e ganhos do PID. O
Servidor Central le o central.json, que diz onde encontrar cada cabine.

Caminhos relativos nos arquivos sao relativos a raiz do repositorio, para que
o programa funcione de qualquer diretorio.
"""
import json
import os

from .gpio import pinos

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PASTA = os.path.join(RAIZ, "config")


class ErroDeConfiguracao(ValueError):
    pass


def caminho(relativo):
    return relativo if os.path.isabs(relativo) else os.path.join(RAIZ, relativo)


def _le(arquivo):
    try:
        with open(caminho(arquivo)) as conteudo:
            return json.load(conteudo)
    except (OSError, json.JSONDecodeError) as erro:
        raise ErroDeConfiguracao("%s: %s" % (arquivo, erro))


def _endereco(valor):
    return int(valor, 0) if isinstance(valor, str) else int(valor)


def arquivo_da_cabine(numero):
    return os.path.join(PASTA, "cabine%d.json" % int(numero))


def le_cabine(arquivo):
    dados = _le(arquivo)
    try:
        numero = int(dados["cabine"])
        if numero not in (1, 2, 3):
            raise ErroDeConfiguracao("cabine %d: use 1, 2 ou 3" % numero)
        configuracao = {
            "cabine": numero,
            "endereco_modbus": _endereco(dados["endereco_modbus"]),
            "tcp_endereco": dados["tcp"].get("endereco", "0.0.0.0"),
            "tcp_porta": int(dados["tcp"]["porta"]),
            "pinos": pinos.valida(dados["pinos"]),
            "kp": float(dados["pid"]["kp"]),
            "ki": float(dados["pid"]["ki"]),
            "kd": float(dados["pid"]["kd"]),
            "duty_de_calibracao": float(dados["calibracao"]["duty_porcento"]),
            "arquivo_de_calibracao": caminho(dados["calibracao"]["arquivo"]),
            "tempo_de_porta_aberta_s": float(dados["porta"]["tempo_aberta_s"]),
        }
    except (KeyError, TypeError, ValueError) as erro:
        if isinstance(erro, ErroDeConfiguracao):
            raise
        raise ErroDeConfiguracao("%s: campo ausente ou invalido: %s" % (arquivo, erro))
    referencia = pinos.PINAGENS_DAS_CABINES[numero]
    if configuracao["pinos"] != referencia:
        # Nao e erro: a bancada ja teve a Tabela 1 trocada uma vez. Mas tem de
        # ser visto por quem sobe o processo.
        print("AVISO: pinos de %s diferem da Tabela 1 do enunciado para a "
              "Cabine %d" % (arquivo, numero), flush=True)
    return configuracao


def le_central(arquivo=None):
    dados = _le(arquivo or os.path.join(PASTA, "central.json"))
    try:
        return {
            "uart": dados["uart"]["porta"],
            "timeout_s": float(dados["uart"].get("timeout_s", 0.3)),
            "i2c": int(dados["i2c"]["barramento"]),
            "cabines": {
                int(c["cabine"]): {
                    "host": c["host"], "porta": int(c["porta"]),
                    "endereco_modbus": _endereco(c["endereco_modbus"]),
                } for c in dados["cabines"]},
            "arquivo_de_estado": caminho(dados["dados"]["estado"]),
            "arquivo_de_viagens": caminho(dados["dados"]["viagens"]),
            "arquivo_de_eventos": caminho(dados["dados"]["eventos"]),
        }
    except (KeyError, TypeError, ValueError) as erro:
        raise ErroDeConfiguracao("central.json: campo ausente ou invalido: %s" % erro)
