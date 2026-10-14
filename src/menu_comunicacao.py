"""Menu numerado da Entrega 2.

Navegacao por numeros sobre os mesmos comandos do terminal: cada opcao monta a
linha de comando, mostra-a como se tivesse sido digitada e a executa por
cli.executa. O menu nao duplica logica nenhuma, e quem assiste ve qual
comando corresponde a cada opcao, com os mesmos bytes TX e RX.
"""
from . import cli_comunicacao as cli
from . import tela
from .tela import exibe


class Sair(Exception):
    """'Sair' escolhido, ou entrada encerrada, em qualquer nivel do menu."""


class Menu:
    def __init__(self, titulo, opcoes):
        self.titulo = titulo
        self.opcoes = opcoes      # [(rotulo, acao)]; acao: str, funcao ou Menu


# ------------------------------------------------------------- perguntas
def _le(texto):
    try:
        return input(texto)
    except EOFError:
        raise Sair()


def _pergunta(rotulo, padrao, valida):
    """Pede um valor; Enter aceita o padrao. Devolve o texto ja validado."""
    while True:
        texto = _le("  %s [%s]: " % (rotulo, padrao)).strip() or padrao
        try:
            valida(texto)
            return texto
        except ValueError as erro:
            exibe("  valor invalido: %s" % erro)


def _inteiro(texto):
    int(texto, 0)


def _real(texto):
    float(texto)


def _texto(texto):
    # O ';' separa comandos na linha que o menu executa.
    if ";" in texto:
        raise ValueError("o texto nao pode ter ';'")


def _cabine(texto):
    if texto not in ("1", "2", "3"):
        raise ValueError("cabine e 1, 2 ou 3")


def _pergunta_cabine():
    return _pergunta("cabine (1-3)", "1", _cabine)


# ---------------------------------------------------------------- menus
def _menu_didatico(protocolo, titulo):
    """Receber e enviar os tres tipos de uma vez: e o que a parte testa."""
    def envia_valores(_c):
        return " ; ".join((
            "%s envia-int %s" % (protocolo, _pergunta("inteiro", "42", _inteiro)),
            "%s envia-float %s" % (protocolo, _pergunta("float", "3.14", _real)),
            "%s envia-string %s" % (protocolo, _pergunta("texto", "teste", _texto))))

    opcoes = [
        ("Receber valores: inteiro, float e string (0xA1-0xA3)",
         " ; ".join("%s %s" % (protocolo, acao)
                    for acao in ("pede-int", "pede-float", "pede-string"))),
        ("Enviar valores: inteiro, float e string (0xB1-0xB3)", envia_valores),
    ]
    if protocolo == "p1":
        opcoes.append(("Comando invalido 0xC7 (erro de sintaxe: timeout)",
                       lambda c: "p1 cru C7 " + " ".join(
                           "%X" % d for d in c.protocolos["p1"].matricula)))
    return Menu(titulo, opcoes)


def _terminal(contexto):
    """Digitacao livre, como no modo --comandos. 'menu' volta."""
    exibe("# terminal de comandos: 'ajuda' lista os comandos, 'menu' volta")
    while True:
        linha = _le(tela.prompt("uart> "))
        if linha.strip().lower() in ("menu", "voltar"):
            return None
        if not cli.executa(contexto, linha):
            raise Sair()
        if linha.strip():
            print(flush=True)


def menu_principal(_contexto):
    return Menu("Menu principal", [
        ("Parte 1 - protocolo simplificado (sem CRC)",
         _menu_didatico("p1", "Parte 1 - protocolo simplificado (sem CRC)")),
        ("Parte 2 - MODBUS didatico (com CRC)",
         _menu_didatico("p2", "Parte 2 - MODBUS didatico (com CRC)")),
        ("Parte 3 - demonstracao: watchdog, porta, chamada e excecoes",
         lambda _c: "roteiro 3 %s" % _pergunta_cabine()),
        ("Terminal UART (digitar comandos)", _terminal),
    ])


# ------------------------------------------------------------- navegacao
def _mostra(menu, caminho):
    exibe()
    print(tela.cor("== %s ==" % " > ".join(caminho + [menu.titulo]),
                   tela.NEGRITO), flush=True)
    for numero, (rotulo, acao) in enumerate(menu.opcoes, 1):
        seta = " >" if isinstance(acao, Menu) else ""
        print("  %s  %s%s" % (tela.cor("%2d" % numero, tela.CIANO), rotulo,
                              tela.cor(seta, tela.FRACO)), flush=True)
    print("  %s  %s" % (tela.cor("%2d" % 0, tela.CIANO),
                        "Sair" if not caminho else "Voltar"), flush=True)


def _navega(contexto, menu, caminho):
    while True:
        _mostra(menu, caminho)
        escolha = _le(tela.prompt("opcao> ")).strip()
        if escolha == "0":
            if not caminho:
                raise Sair()
            return
        if not escolha.isdigit() or not 1 <= int(escolha) <= len(menu.opcoes):
            exibe("  opcao invalida: %r" % escolha)
            continue
        _, acao = menu.opcoes[int(escolha) - 1]
        if isinstance(acao, Menu):
            _navega(contexto, acao, caminho + [menu.titulo])
            continue
        linha = acao if isinstance(acao, str) else acao(contexto)
        if linha:
            exibe("\nuart> %s" % linha)
            if not cli.executa(contexto, linha):
                raise Sair()


def navega(contexto, raiz=True):
    """Abre o menu principal. Com raiz=False, o 0 do menu principal volta em
    vez de sair (menu aberto do terminal). Devolve True se for para encerrar."""
    try:
        _navega(contexto, menu_principal(contexto), [] if raiz else ["Terminal"])
    except Sair:
        return True
    return False
