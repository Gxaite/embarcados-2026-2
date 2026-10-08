"""ESP32 de mentira, para o modo --simulado e para os testes.

Responde aos tres protocolos na mesma "linha", como a placa de verdade, e
reproduz o comportamento que a Entrega 2 manda demonstrar: watchdog da
Condicao de Contorno, derating termico do barramento, transicoes da porta,
fila de chamadas e as excecoes 0x01, 0x02 e 0x03.

NAO prova que o programa conversa com a ESP32 real. Prova que os quadros
seguem o enunciado - os exemplos byte a byte da Secao 3.3 estao nos testes - e
deixa ensaiar a CLI inteira antes de gastar um horario de bancada.
"""
import struct
import time
from collections import deque

from . import carga
from .crc16 import anexa_crc, crc_valido
from .porta import Porta

CONSTANTE_INT = 2026
CONSTANTE_FLOAT = 3.14159
CONSTANTE_STRING = "FSE 2026/2 - ESP32 simulada"

TEMPO_DA_PORTA_S = 1.0
WATCHDOG_S = 30.0
BARRAMENTO_NOMINAL_MA = 12000
BARRAMENTO_PISO_MA = 3000
DIGITOS_DA_MATRICULA = 6

ESCRITOS_NA_CABINE = {3}
ESCRITOS_NO_PREDIO = {4, 5, 6, 9, 10}
REGISTRADORES_DA_CABINE = 9
REGISTRADORES_DO_PREDIO = 16


class _Cabine:
    def __init__(self, andar):
        self.andar = andar
        self.porta_estado = 0
        self.porta_comando = 0
        self.porta_desde = 0.0
        self.posicao_mm = 3000 * andar


class Esp32Simulada:
    def __init__(self, relogio=time.monotonic):
        self._relogio = relogio
        self.cabines = {0x11: _Cabine(0), 0x12: _Cabine(2), 0x13: _Cabine(5)}
        self.fila = deque()
        self._proximo_id = 1
        self.temperatura_x10 = 0
        self.pressao_hpa = 0
        self.ultima_condicao = None
        self.atribuicoes = []
        self.recebidos = []        # (protocolo, quadro), para os testes

    # -------------------------------------------------- estimulos externos
    def registra_chamada(self, origem, destino):
        """Equivale a registrar uma chamada no quiosque do dashboard."""
        self.fila.append((origem, destino, self._proximo_id))
        self._proximo_id += 1

    # ---------------------------------------------------------- recepcao
    def processa(self, quadro):
        """Recebe um quadro e devolve a resposta, ou None (sem resposta)."""
        quadro = bytes(quadro)
        if not quadro:
            return None
        primeiro = quadro[0]
        if primeiro in carga.TIPO_DA_RESPOSTA:
            self.recebidos.append(("simplificado", quadro))
            return self._simplificado(quadro)
        if not crc_valido(quadro):
            self.recebidos.append(("crc_invalido", quadro))
            return None
        if primeiro == 0x01:
            self.recebidos.append(("modbus_didatico", quadro))
            return self._didatico(quadro)
        if primeiro in self.cabines or primeiro == 0x20:
            self.recebidos.append(("modbus", quadro))
            return self._modbus(quadro)
        return None

    # ----------------------------------------------------- Partes 1 e 2
    def _responde_comando(self, comando, dados, matricula):
        ultimo_digito = matricula[-1]
        if comando == carga.PEDE_INT:
            return carga.codifica_int(CONSTANTE_INT)
        if comando == carga.PEDE_FLOAT:
            return carga.codifica_float(CONSTANTE_FLOAT)
        if comando == carga.PEDE_STRING:
            return carga.codifica_string(CONSTANTE_STRING)
        if comando == carga.ENVIA_INT:
            valor = struct.unpack("<i", dados[:4])[0] * ultimo_digito
            valor = (valor + 2 ** 31) % 2 ** 32 - 2 ** 31
            return carga.codifica_int(valor)
        if comando == carga.ENVIA_FLOAT:
            return carga.codifica_float(struct.unpack("<f", dados[:4])[0]
                                        * ultimo_digito)
        texto = dados[1:1 + dados[0]].decode("utf-8", errors="replace")
        return carga.codifica_string(("Resposta da UART: " + texto)[:255])

    def _separa(self, comando, resto):
        """Divide [carga][matricula] conforme o comando."""
        if comando in (carga.ENVIA_INT, carga.ENVIA_FLOAT):
            tamanho = 4
        elif comando == carga.ENVIA_STRING:
            tamanho = 1 + resto[0] if resto else 0
        else:
            tamanho = 0
        dados, matricula = resto[:tamanho], resto[tamanho:]
        if len(matricula) != DIGITOS_DA_MATRICULA:
            return None
        return dados, matricula

    def _simplificado(self, quadro):
        separado = self._separa(quadro[0], quadro[1:])
        if separado is None:
            return None
        return self._responde_comando(quadro[0], *separado)

    def _didatico(self, quadro):
        funcao, sub_codigo = quadro[1], quadro[2]
        esperado = 0x23 if sub_codigo in (0xA1, 0xA2, 0xA3) else 0x16
        if sub_codigo not in carga.TIPO_DA_RESPOSTA or funcao != esperado:
            return anexa_crc(bytes((0x00, funcao | 0x80, 0x01)))
        separado = self._separa(sub_codigo, quadro[3:-2])
        if separado is None:
            return None
        valor = self._responde_comando(sub_codigo, *separado)
        return anexa_crc(bytes((0x00, funcao, sub_codigo)) + valor)

    # -------------------------------------------------------------- Parte 3
    def _excecao(self, endereco, funcao, codigo):
        return anexa_crc(bytes((endereco, funcao | 0x80, codigo)))

    def _modbus(self, quadro):
        endereco, funcao = quadro[0], quadro[1]
        if funcao not in (0x03, 0x10):
            return self._excecao(endereco, funcao, 0x01)
        if len(quadro) < 6:
            return None
        registrador, quantidade = struct.unpack("<HH", quadro[2:6])
        total = REGISTRADORES_DO_PREDIO if endereco == 0x20 \
            else REGISTRADORES_DA_CABINE
        if quantidade == 0 or registrador + quantidade > total:
            return self._excecao(endereco, funcao, 0x02)

        # Tamanhos pelos exemplos da Secao 3.3 (14 e 15 + 2*qtd bytes). O texto
        # da Secao 3.1 diz 12 e 13 + 2*qtd, conta feita com a matricula antiga
        # de 4 digitos; os exemplos byte a byte e que estao certos.
        if funcao == 0x03:
            if len(quadro) != 14:
                return None
            valores = self._registradores(endereco)[registrador:
                                                    registrador + quantidade]
            return anexa_crc(bytes((endereco, 0x03, 2 * quantidade))
                             + struct.pack(">%dH" % quantidade,
                                           *[v & 0xFFFF for v in valores]))

        if len(quadro) != 15 + 2 * quantidade or quadro[6] != 2 * quantidade:
            return None
        valores = struct.unpack("<%dH" % quantidade,
                                quadro[7:7 + 2 * quantidade])
        escritos = ESCRITOS_NO_PREDIO if endereco == 0x20 else ESCRITOS_NA_CABINE
        alvos = range(registrador, registrador + quantidade)
        if any(r not in escritos for r in alvos):
            return self._excecao(endereco, funcao, 0x02)
        codigo = self._escreve(endereco, registrador, valores)
        if codigo:
            return self._excecao(endereco, funcao, codigo)
        return anexa_crc(bytes((endereco, 0x10))
                         + struct.pack(">HH", registrador, quantidade))

    def _registradores(self, endereco):
        if endereco == 0x20:
            return self._registradores_do_predio()
        cabine = self.cabines[endereco]
        self._atualiza_porta(cabine)
        return [cabine.andar, 1, cabine.porta_estado, cabine.porta_comando,
                0, 0, 0, cabine.posicao_mm, 0]

    def _atualiza_porta(self, cabine):
        if self._relogio() - cabine.porta_desde < TEMPO_DA_PORTA_S:
            return
        if cabine.porta_estado == 1:
            cabine.porta_estado = 2
        elif cabine.porta_estado == 3:
            cabine.porta_estado = 0

    def watchdog_expirado(self):
        return (self.ultima_condicao is None
                or self._relogio() - self.ultima_condicao > WATCHDOG_S)

    def barramento_max_ma(self):
        if self.watchdog_expirado():
            return BARRAMENTO_PISO_MA
        temperatura = (self.temperatura_x10 - 0x10000
                       if self.temperatura_x10 & 0x8000
                       else self.temperatura_x10) / 10.0
        return int(BARRAMENTO_NOMINAL_MA - 200 * max(0.0, temperatura - 25.0))

    def _registradores_do_predio(self):
        origem, destino, chamada_id = self.fila[0] if self.fila else (0, 0, 0)
        ultimo_id, ultima_cabine = self.atribuicoes[-1] if self.atribuicoes \
            else (0, 0)
        return [len(self.fila), origem, destino, chamada_id, 0,
                self.temperatura_x10, self.pressao_hpa, self.barramento_max_ma(),
                1 if self.watchdog_expirado() else 0, ultimo_id, ultima_cabine,
                0, 0, 0, 0, 0]

    def _escreve(self, endereco, registrador, valores):
        """Aplica a escrita. Devolve codigo de excecao ou None."""
        novos = dict(zip(range(registrador, registrador + len(valores)), valores))
        if endereco != 0x20:
            comando = novos[3]
            if comando > 2:
                return 0x03
            cabine = self.cabines[endereco]
            self._atualiza_porta(cabine)
            cabine.porta_comando = comando
            if comando == 1 and cabine.porta_estado in (0, 3):
                cabine.porta_estado, cabine.porta_desde = 1, self._relogio()
            elif comando == 2 and cabine.porta_estado in (1, 2):
                cabine.porta_estado, cabine.porta_desde = 3, self._relogio()
            return None
        if 10 in novos and not 1 <= novos[10] <= 3:
            return 0x03
        if novos.get(4) == 1 and self.fila:
            self.fila.popleft()
        if 5 in novos:
            self.temperatura_x10 = novos[5]
        if 6 in novos:
            self.pressao_hpa = novos[6]
        if 5 in novos or 6 in novos:
            self.ultima_condicao = self._relogio()
        if 9 in novos or 10 in novos:
            self.atribuicoes.append((novos.get(9, 0), novos.get(10, 0)))
        return None


class PortaSimulada(Porta):
    """Porta ligada direto na ESP32 simulada, sem atraso nenhum.

    `perturbacoes` e uma fila de funcoes aplicadas as proximas respostas, uma
    por resposta. Os testes a usam para corromper CRC, engolir respostas e
    conferir as retentativas.
    """

    def __init__(self, dispositivo):
        super().__init__()
        self.dispositivo = dispositivo
        self.perturbacoes = []
        self.enviados = []
        self._entrada = bytearray()

    def envia(self, dados):
        self.enviados.append(bytes(dados))
        resposta = self.dispositivo.processa(dados)
        if self.perturbacoes:
            resposta = self.perturbacoes.pop(0)(resposta)
        if resposta:
            self._entrada.extend(resposta)

    def le(self, quantidade, timeout_s):
        pedaco = bytes(self._entrada[:quantidade])
        del self._entrada[:quantidade]
        return pedaco

    def descarta_entrada(self):
        self._entrada.clear()

    def fecha(self):
        pass
