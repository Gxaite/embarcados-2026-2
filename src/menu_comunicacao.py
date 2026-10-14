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
    def envia_int(_c):
        return "%s envia-int %s" % (protocolo, _pergunta("inteiro", "42", _inteiro))

    def envia_float(_c):
        return "%s envia-float %s" % (protocolo, _pergunta("float", "3.14", _real))

    def envia_string(_c):
        return "%s envia-string %s" % (protocolo, _pergunta("texto", "teste", _texto))

    def envia_valores(c):
        return " ; ".join((envia_int(c), envia_float(c), envia_string(c)))

    recebe = ["%s %s" % (protocolo, acao)
              for acao in ("pede-int", "pede-float", "pede-string")]
    opcoes = [
        ("Receber valores: inteiro, float e string (0xA1-0xA3)",
         " ; ".join(recebe)),
        ("Enviar valores: inteiro, float e string (0xB1-0xB3)", envia_valores),
        ("Receber inteiro (0xA1)", recebe[0]),
        ("Receber float (0xA2)", recebe[1]),
        ("Receber string (0xA3)", recebe[2]),
        ("Enviar inteiro (0xB1)", envia_int),
        ("Enviar float (0xB2)", envia_float),
        ("Enviar string (0xB3)", envia_string),
    ]
    if protocolo == "p1":
        opcoes.append(("Comando invalido 0xC7 (erro de sintaxe: timeout)",
                       lambda c: "p1 cru C7 " + " ".join(
                           "%X" % d for d in c.protocolos["p1"].matricula)))
    return Menu(titulo, opcoes)


def _abre_porta(_contexto):
    cabine = _pergunta_cabine()
    return "porta %s abrir ; monitora cabine %s %d" % (
        cabine, cabine, cli.DURACAO_DA_ABERTURA_S)


def _fecha_porta(_contexto):
    cabine = _pergunta_cabine()
    return "porta %s fechar ; monitora cabine %s %d" % (
        cabine, cabine, cli.DURACAO_DO_FECHAMENTO_S)


def _atribui(_contexto):
    chamada = _pergunta("id da chamada (opcao 'Ler a fila' mostra)", "1",
                        _inteiro)
    return "atribui %s %s" % (chamada, _pergunta_cabine())


def _menu_parte_3(contexto):
    opcoes = [
        ("Estado da cabine", lambda _c: "cabine %s" % _pergunta_cabine()),
        ("Abrir a porta e acompanhar", _abre_porta),
        ("Fechar a porta e acompanhar", _fecha_porta),
        ("Leitura continua da cabine (Enter para)",
         lambda _c: "monitora cabine %s" % _pergunta_cabine()),
        ("Estado do predio", "predio"),
        ("Leitura continua do predio (Enter para)", "monitora predio"),
        ("Ler a fila de chamadas", "fila"),
        ("Atribuir chamada a uma cabine", _atribui),
        ("Remover a chamada da cabeca da fila (pop)", "pop"),
        ("Excecao 0x02: escrita em registrador somente leitura",
         "escreve 0x11 0 5"),
        ("Excecao 0x02: leitura fora do mapa", "le 0x11 0 20"),
        ("Excecao 0x03: comando de porta invalido", "escreve 0x11 3 7"),
    ]
    if contexto.esp32_simulada is not None:
        opcoes.append(("Registrar chamada (modo simulado)",
                       lambda _c: "chamada %s %s" % (
                           _pergunta("origem", "0", _inteiro),
                           _pergunta("destino", "5", _inteiro))))
    return Menu("Parte 3 - cabines e predio (0x03 / 0x10)", opcoes)


def _menu_i2c():
    return Menu("I2C - BMP280 e Condicao de Contorno", [
        ("Ler o BMP280", "bmp"),
        ("Escrever a Condicao de Contorno com o BMP280", "contorno"),
        ("Escrever a Condicao de Contorno com valores manuais",
         lambda _c: "contorno %s %s" % (_pergunta("temperatura (C)", "25", _real),
                                        _pergunta("pressao (hPa)", "1013", _real))),
        ("Ligar a escrita automatica (a cada 4 s)", "auto on"),
        ("Desligar a escrita automatica", "auto off"),
        ("Situacao da escrita automatica", "auto"),
    ])


def _menu_roteiros():
    return Menu("Roteiros de demonstracao (3 s entre comandos)", [
        ("Parte 1: os 6 comandos e o erro de sintaxe", "roteiro 1"),
        ("Parte 2: os 6 comandos com CRC", "roteiro 2"),
        ("Parte 3: watchdog, porta, fila e excecoes",
         lambda _c: "roteiro 3 %s" % _pergunta_cabine()),
        ("Tudo em sequencia",
         lambda _c: "roteiro tudo %s" % _pergunta_cabine()),
    ])


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


def menu_principal(contexto):
    return Menu("Menu principal", [
        ("Parte 1 - protocolo simplificado (sem CRC)",
         _menu_didatico("p1", "Parte 1 - protocolo simplificado (sem CRC)")),
        ("Parte 2 - MODBUS didatico (com CRC)",
         _menu_didatico("p2", "Parte 2 - MODBUS didatico (com CRC)")),
        ("Parte 3 - cabines e predio", _menu_parte_3(contexto)),
        ("I2C e Condicao de Contorno", _menu_i2c()),
        ("Roteiros de demonstracao", _menu_roteiros()),
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
