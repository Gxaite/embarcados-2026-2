"""Matricula de 6 digitos que vai no fim de toda requisicao.

Cada digito e transmitido como o byte cru 0x00..0x09, nunca como o caractere
ASCII: o digito 6 e 0x06, nao 0x36.

O repositorio e publico, entao a matricula nao fica no codigo. Ela vem, nesta
ordem, do argumento --matricula, da variavel de ambiente FSE_MATRICULA ou do
arquivo `matricula` na raiz do repositorio (ignorado pelo git).
"""
import os

DIGITOS = 6
VARIAVEL_DE_AMBIENTE = "FSE_MATRICULA"
ARQUIVO = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "matricula")


def em_bytes(texto):
    """Converte a matricula em 6 bytes crus, usando os 6 ultimos digitos.

    Aceita a matricula completa (ex.: "12/3456789"); separadores sao ignorados.
    """
    digitos = [c for c in str(texto) if c.isdigit()]
    if len(digitos) < DIGITOS:
        raise ValueError("matricula precisa de pelo menos %d digitos: %r"
                         % (DIGITOS, texto))
    return bytes(int(c) for c in digitos[-DIGITOS:])


def como_texto(matricula_em_bytes):
    return "".join(str(b) for b in matricula_em_bytes)


def resolve(argumento=None, ambiente=None, arquivo=ARQUIVO):
    """Procura a matricula no argumento, no ambiente e no arquivo.

    Devolve os 6 bytes, ou None se nenhuma das tres fontes tiver o valor.
    """
    ambiente = os.environ if ambiente is None else ambiente
    if argumento:
        return em_bytes(argumento)
    if ambiente.get(VARIAVEL_DE_AMBIENTE):
        return em_bytes(ambiente[VARIAVEL_DE_AMBIENTE])
    if arquivo and os.path.isfile(arquivo):
        with open(arquivo) as conteudo:
            texto = conteudo.read().strip()
        if texto:
            return em_bytes(texto)
    return None
