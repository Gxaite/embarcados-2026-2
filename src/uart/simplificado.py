"""Parte 1 - protocolo simplificado.

Pacote: [comando][carga][6 digitos da matricula], sem endereco e sem CRC.
O dispositivo responde com os bytes crus do valor (4 bytes para int e float,
1 byte de tamanho mais a string para string).

Sem CRC nao ha como distinguir resposta corrompida de resposta certa, entao
nao ha retentativa: um timeout e registrado e devolvido como erro. E assim que
um comando desconhecido aparece para a Raspberry - o dispositivo descarta o
pacote e nao responde nada (Secao 1.3).
"""
from . import carga
from .erros import RespostaInvalida, SemResposta
from .porta import hexa

TIMEOUT_PADRAO_S = 0.5


class ProtocoloSimplificado:
    NOME = "SIMPLIFICADO"

    def __init__(self, porta, matricula, eco=print, timeout_s=TIMEOUT_PADRAO_S):
        self._porta = porta
        self._matricula = bytes(matricula)
        self._eco = eco or (lambda _texto: None)
        self.timeout_s = timeout_s

    # --------------------------------------------- um metodo por comando
    def pede_int(self):
        return self._transacao(carga.PEDE_INT)

    def pede_float(self):
        return self._transacao(carga.PEDE_FLOAT)

    def pede_string(self):
        return self._transacao(carga.PEDE_STRING)

    def envia_int(self, valor):
        return self._transacao(carga.ENVIA_INT, carga.codifica_int(valor))

    def envia_float(self, valor):
        return self._transacao(carga.ENVIA_FLOAT, carga.codifica_float(valor))

    def envia_string(self, texto):
        return self._transacao(carga.ENVIA_STRING, carga.codifica_string(texto))

    def envia_cru(self, dados, espera_s=None):
        """Envia bytes arbitrarios e mostra o que vier de volta.

        Serve para provocar o erro de sintaxe da Secao 1.3 (comando fora da
        faixa) e conferir que a Raspberry detecta o timeout.
        """
        with self._porta.trava:
            self._porta.descarta_entrada()
            self.envia_pacote(bytes(dados))
            resposta = self._porta.le_ate_silencio(
                self.timeout_s if espera_s is None else espera_s)
        if not resposta:
            self._eco("  RX: (nada) - timeout de %d ms"
                      % round(self.timeout_s * 1000))
            raise SemResposta("sem resposta ao pacote cru")
        self._eco("  RX (%d B): %s" % (len(resposta), hexa(resposta)))
        return resposta

    # --------------------------------------------------------- utilitarios
    def monta_pacote(self, comando, dados=b""):
        return bytes((comando,)) + bytes(dados) + self._matricula

    def envia_pacote(self, pacote):
        self._eco("  TX (%d B): %s" % (len(pacote), hexa(pacote)))
        self._porta.envia(pacote)

    def le_resposta(self, tipo):
        """Le exatamente a resposta do tipo, ou levanta SemResposta."""
        recebido = bytearray()
        if tipo == carga.STRING:
            recebido.extend(self._porta.le(1, self.timeout_s))
        esperado = carga.tamanho_da_resposta(tipo, recebido)
        if esperado is not None:
            recebido.extend(self._porta.le(esperado - len(recebido), self.timeout_s))
        if recebido:
            self._eco("  RX (%d B): %s" % (len(recebido), hexa(recebido)))
        if esperado is None or len(recebido) < esperado:
            self._eco("  RX: timeout de %d ms com %d de %s bytes"
                      % (round(self.timeout_s * 1000), len(recebido),
                         "?" if esperado is None else esperado))
            raise SemResposta("resposta incompleta: %d bytes" % len(recebido))
        return bytes(recebido)

    def _transacao(self, comando, dados=b""):
        self._eco("[%s] %s (0x%02X)" % (self.NOME, carga.NOMES[comando], comando))
        pacote = self.monta_pacote(comando, dados)
        tipo = carga.TIPO_DA_RESPOSTA[comando]
        with self._porta.trava:
            self._porta.descarta_entrada()
            self.envia_pacote(pacote)
            resposta = self.le_resposta(tipo)
        try:
            valor = carga.decodifica(tipo, resposta)
        except RespostaInvalida as erro:
            self._eco("  ERRO: %s" % erro)
            raise
        self._eco("  campos: comando=0x%02X matricula=%s | %s = %r"
                  % (comando, hexa(self._matricula), tipo, valor))
        return valor
