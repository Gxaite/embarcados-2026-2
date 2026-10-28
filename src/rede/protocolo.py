"""Mensagens entre o Servidor Central e as cabines.

Cada mensagem e um objeto JSON numa linha, com o campo "tipo". JSON por linha
e legivel no tcpdump e no `nc`, nao precisa de biblioteca e delimita o quadro
pelo proprio '\\n', que o JSON nunca contem fora de string.

Central -> cabine:
  cota          {"cota_ma", "validade_s", "seq"}      a cada 1 s
  chamada       {"id", "origem", "destino"}           atribuicao do Despacho
  vai_andar     {"andar"}                             comando manual
  esquece       {"ids"}                               chamadas descartadas (ESP32 reiniciada)
  registradores {"dados": {...}}                      leitura MODBUS da cabine
  resposta      {"pedido", "ok", "dados"|"erro"}      resposta a um pedido

Cabine -> central:
  ola           {"cabine"}                            primeira mensagem
  estado        {...}                                 a cada 500 ms
  pedido        {"pedido", "op", ...}                 operacao MODBUS na cabine

Os eventos de embarque e desembarque vao dentro do "estado", na lista dos
ultimos eventos. O central descarta os que ja conhece pelo par (chamada,
evento), entao um estado perdido numa queda de conexao nao perde o evento.
"""
import json

COTA = "cota"
CHAMADA = "chamada"
VAI_ANDAR = "vai_andar"
ESQUECE = "esquece"
REGISTRADORES = "registradores"
RESPOSTA = "resposta"
OLA = "ola"
ESTADO = "estado"
PEDIDO = "pedido"

OP_LE_CABINE = "le_cabine"
OP_PORTA = "porta"

TAMANHO_MAXIMO_DE_LINHA = 64 * 1024


class MensagemInvalida(ValueError):
    pass


def codifica(mensagem):
    if "tipo" not in mensagem:
        raise MensagemInvalida("mensagem sem tipo: %r" % (mensagem,))
    return (json.dumps(mensagem, separators=(",", ":"), ensure_ascii=False)
            + "\n").encode("utf-8")


def decodifica(linha):
    if len(linha) > TAMANHO_MAXIMO_DE_LINHA:
        raise MensagemInvalida("linha de %d bytes" % len(linha))
    try:
        mensagem = json.loads(linha.decode("utf-8") if isinstance(linha, bytes)
                              else linha)
    except (UnicodeDecodeError, json.JSONDecodeError) as erro:
        raise MensagemInvalida(str(erro))
    if not isinstance(mensagem, dict) or "tipo" not in mensagem:
        raise MensagemInvalida("nao e mensagem: %r" % (mensagem,))
    return mensagem
