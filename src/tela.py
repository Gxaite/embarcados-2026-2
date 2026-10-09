"""Cores do terminal da Entrega 2.

Os modulos de protocolo imprimem texto puro, com prefixos fixos ("  TX",
"  RX", "  campos:", "  EXCECAO"...). A cor e aplicada aqui, pelo prefixo da
linha, para que o terminal da demonstracao destaque envio, resposta e erro
sem que a biblioteca da Parte 3 (importada pela Entrega Final) dependa disso.

Sem terminal (saida redirecionada), com NO_COLOR ou com --sem-cor, tudo sai
sem codigos de escape.
"""
import os
import sys

_RESET = "\033[0m"
NEGRITO = "1"
FRACO = "2"
VERMELHO = "31"
VERDE = "32"
AMARELO = "33"
AZUL = "34"
MAGENTA = "35"
CIANO = "36"

_ativa = sys.stdout.isatty() and "NO_COLOR" not in os.environ

# (prefixo, ate onde vai a cor do prefixo, cor do prefixo, cor do resto).
# O "ate" e o caractere que encerra o rotulo (":" em "  RX (9 B):"), ou None
# para pintar so o prefixo. A primeira regra que casar vale.
_REGRAS = (
    ("  TX", ":", CIANO + ";" + NEGRITO, CIANO),
    ("  RX: (nada)", None, AMARELO + ";" + NEGRITO, AMARELO),
    ("  RX: timeout", None, AMARELO + ";" + NEGRITO, AMARELO),
    ("  RX", ":", VERDE + ";" + NEGRITO, VERDE),
    ("  campos:", ":", FRACO, ""),
    ("  =>", None, VERDE + ";" + NEGRITO, NEGRITO),
    ("  EXCECAO", ":", VERMELHO + ";" + NEGRITO, VERMELHO),
    ("  ERRO", ":", VERMELHO + ";" + NEGRITO, VERMELHO),
    ("  tentativa", None, AMARELO, AMARELO),
    ("[CONTORNO]", None, MAGENTA, ""),
    ("[", "]", NEGRITO, NEGRITO),
    ("uart>", None, CIANO + ";" + NEGRITO, NEGRITO),
    ("#", None, AZUL + ";" + NEGRITO, AZUL + ";" + NEGRITO),
    ("AVISO", None, AMARELO + ";" + NEGRITO, AMARELO),
)


def desliga():
    global _ativa
    _ativa = False


def cor(texto, codigo):
    if not _ativa or not codigo:
        return texto
    return "\033[%sm%s%s" % (codigo, texto, _RESET)


def colore(linha):
    """Aplica a cor da primeira regra cujo prefixo casa com a linha."""
    if not _ativa:
        return linha
    for prefixo, ate, cor_do_prefixo, cor_do_resto in _REGRAS:
        if linha.startswith(prefixo):
            corte = len(prefixo)
            if ate is not None and ate in linha:
                corte = linha.index(ate) + 1
            return cor(linha[:corte], cor_do_prefixo) + cor(linha[corte:],
                                                            cor_do_resto)
    return linha


def exibe(texto=""):
    print("\n".join(colore(linha) for linha in str(texto).split("\n")),
          flush=True)


def prompt(texto):
    """Prompt colorido que o readline mede certo (\\001 e \\002 marcam o que
    nao ocupa coluna)."""
    if not _ativa:
        return texto
    return "\001\033[%s;%sm\002%s\001%s\002" % (NEGRITO, CIANO, texto, _RESET)
