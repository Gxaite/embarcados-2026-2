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
        # [(rotulo, acao)]. acao: Menu, linha de comando, lista de passos
        # (aviso, linha) ou funcao do contexto que devolve um dos dois.
        self.opcoes = opcoes


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


def _cabine(texto):
    if texto not in ("1", "2", "3"):
        raise ValueError("cabine e 1, 2 ou 3")


def _pergunta_cabine():
    return _pergunta("cabine (1-3)", "1", _cabine)


# ---------------------------------------------------------------- menus
# Valores fixos dos envios: a opcao roda sem perguntar nada.
INTEIRO_ENVIADO = 42
FLOAT_ENVIADO = 3.14
TEXTO_ENVIADO = "teste"


def _recebe_valores(protocolo):
    return [
        ("# solicita o inteiro; a ESP32 devolve um valor constante",
         "%s pede-int" % protocolo),
        ("# solicita o float; a ESP32 devolve um valor constante",
         "%s pede-float" % protocolo),
        ("# solicita a string; a ESP32 devolve um texto constante",
         "%s pede-string" % protocolo),
    ]


def _envia_valores(protocolo):
    def passos(contexto):
        # A matricula e a mesma nos dois protocolos; so o p1 a expoe.
        digito = contexto.protocolos["p1"].matricula[-1]
        return [
            ("# inteiro enviado: %d; esperado %d x %d = %d (ultimo digito da "
             "matricula)" % (INTEIRO_ENVIADO, INTEIRO_ENVIADO, digito,
                             INTEIRO_ENVIADO * digito),
             "%s envia-int %d" % (protocolo, INTEIRO_ENVIADO)),
            ("# float enviado: %g; esperado %g x %d = %g"
             % (FLOAT_ENVIADO, FLOAT_ENVIADO, digito, FLOAT_ENVIADO * digito),
             "%s envia-float %g" % (protocolo, FLOAT_ENVIADO)),
            ("# string enviada: \"%s\"; esperado \"Resposta da UART: %s\""
             % (TEXTO_ENVIADO, TEXTO_ENVIADO),
             "%s envia-string %s" % (protocolo, TEXTO_ENVIADO)),
        ]
    return passos


def _comando_invalido(contexto):
    matricula = " ".join("%X" % d for d in contexto.protocolos["p1"].matricula)
    return [("# comando 0xC7, fora da faixa: a ESP32 descarta o pacote sem "
             "responder, e a Raspberry registra o timeout",
             "p1 cru C7 %s" % matricula)]


def _menu_didatico(protocolo, titulo):
    """Receber e enviar os tres tipos de uma vez: e o que a parte testa."""
    opcoes = [
        ("Receber valores: inteiro, float e string (0xA1-0xA3)",
         _recebe_valores(protocolo)),
        ("Enviar valores: %d, %g e \"%s\" (0xB1-0xB3)"
         % (INTEIRO_ENVIADO, FLOAT_ENVIADO, TEXTO_ENVIADO),
         _envia_valores(protocolo)),
    ]
    if protocolo == "p1":
        opcoes.append(("Comando invalido 0xC7 (erro de sintaxe: timeout)",
                       _comando_invalido))
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
        if callable(acao):
            acao = acao(contexto)
        if isinstance(acao, str):
            acao = [(None, acao)]
        for aviso, linha in acao or ():
            exibe()
            if aviso:
                exibe(aviso)
            exibe("uart> %s" % linha)
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
