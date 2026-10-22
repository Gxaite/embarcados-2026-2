"""Comandos digitados na interface do Servidor Central."""
from .interface import AJUDA, painel_em_texto


class Comandos:
    """executa(linha) devolve o texto de resposta, ou None para sair.

    `extras` acrescenta comandos: {nome: (ajuda, funcao(argumentos) -> texto)}.
    O simulador usa isso para o quiosque e os cenarios.
    """

    def __init__(self, servidor, extras=None):
        self._servidor = servidor
        self._extras = dict(extras or {})

    @property
    def ajuda(self):
        if not self._extras:
            return AJUDA
        return AJUDA + "  |  " + "  |  ".join(a for a, _ in self._extras.values())

    def executa(self, linha):
        partes = linha.split()
        if not partes:
            return self.ajuda
        nome, argumentos = partes[0].lower(), partes[1:]
        try:
            if nome in ("sair", "exit", "quit"):
                return None
            if nome in ("ajuda", "help", "?"):
                return self.ajuda
            if nome == "status":
                return painel_em_texto(self._servidor)
            if nome == "vai":
                if len(argumentos) != 2:
                    return "uso: vai <cabine 1-3> <andar 0-5>"
                cabine, andar = int(argumentos[0]), int(argumentos[1])
                self._servidor.envia_cabine_ao_andar(cabine, andar)
                return "cabine %d enviada ao andar %d" % (cabine, andar)
            if nome == "corta-cota":
                if len(argumentos) not in (1, 2):
                    return "uso: corta-cota <cabine> [segundos]"
                cabine = int(argumentos[0])
                segundos = float(argumentos[1]) if len(argumentos) == 2 else 15.0
                self._servidor.corta_cota(cabine, segundos)
                return "Cota da cabine %d suspensa por %.0f s (Modo Degradado)" % (
                    cabine, segundos)
            if nome in self._extras:
                return self._extras[nome][1](argumentos)
        except ValueError as erro:
            return "erro: %s" % erro
        return "comando desconhecido: %s   (%s)" % (nome, self.ajuda)
