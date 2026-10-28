"""Chamadas de Destino: estado persistente e log das viagens.

Dois arquivos, com papeis diferentes:

- estado (JSON): as chamadas ainda nao concluidas e os contadores. E reescrito
  inteiro a cada mudanca, num arquivo temporario seguido de os.replace(), que
  e atomico: um Ctrl+C ou queda de energia no meio da escrita deixa o arquivo
  antigo inteiro, nunca um pela metade. Na partida o central o le e reenvia
  cada pendente a sua cabine quando ela conectar (requisito 6.2.7).
- viagens (CSV): uma linha por chamada concluida, so acrescentada. E o log
  persistente do requisito 6.2.5.

Os ids da ESP32 sao sequenciais e recomecam em 1 a cada "Resetar simulacao"
do dashboard. Cada reinicio abre uma epoca, e a chave de uma chamada (o id que
vai as cabines e volta nos eventos) e epoca x 100000 + id da ESP32: sem isso a
cabine ignorava uma chamada nova com o numero de uma ja concluida, que nunca
era atendida, e um evento antigo concluia uma chamada nova na hora.

Os instantes sao horario do relogio de parede (time.time()), para o log ser
legivel. O instante de registro e o momento em que o central leu a chamada na
fila do simulador: o registrador nao informa quando o passageiro a fez.
"""
import csv
import json
import os
import threading
import time

AGUARDANDO = "aguardando"
EMBARCADA = "embarcada"
CONCLUIDA = "concluida"

COLUNAS = ("id", "origem", "destino", "cabine", "registro", "embarque",
           "desembarque", "espera_s", "viagem_s")


def _horario(instante):
    if instante is None:
        return ""
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(instante)) + \
        ".%01d" % int((instante % 1) * 10)


CHAVES_POR_EPOCA = 100000


class Chamada:
    def __init__(self, identificador, origem, destino, cabine, registro,
                 embarque=None, desembarque=None, id_esp32=None):
        self.id = identificador
        self.id_esp32 = identificador if id_esp32 is None else id_esp32
        self.origem = origem
        self.destino = destino
        self.cabine = cabine
        self.registro = registro
        self.embarque = embarque
        self.desembarque = desembarque

    @property
    def estado(self):
        if self.desembarque is not None:
            return CONCLUIDA
        return EMBARCADA if self.embarque is not None else AGUARDANDO

    @property
    def espera_s(self):
        return None if self.embarque is None else self.embarque - self.registro

    @property
    def viagem_s(self):
        if self.embarque is None or self.desembarque is None:
            return None
        return self.desembarque - self.embarque

    def como_dicionario(self):
        return {"id": self.id, "id_esp32": self.id_esp32,
                "origem": self.origem, "destino": self.destino,
                "cabine": self.cabine, "registro": self.registro,
                "embarque": self.embarque, "desembarque": self.desembarque}


class RegistroDeChamadas:
    def __init__(self, arquivo_de_estado, arquivo_de_viagens, relogio=time.time):
        self._arquivo_de_estado = arquivo_de_estado
        self._arquivo_de_viagens = arquivo_de_viagens
        self._relogio = relogio
        self._trava = threading.RLock()
        self.pendentes = {}
        self.concluidas = 0
        self.soma_espera_s = 0.0
        self.soma_viagem_s = 0.0
        self.recentes = []          # ultimas concluidas, para a interface
        self.carregadas = 0
        self.epoca = 0
        self.ultimo_id_esp32 = 0

    # ------------------------------------------------------------ disco
    def carrega(self):
        try:
            with open(self._arquivo_de_estado) as entrada:
                dados = json.load(entrada)
        except FileNotFoundError:
            return 0
        except (OSError, json.JSONDecodeError):
            os.replace(self._arquivo_de_estado, self._arquivo_de_estado + ".corrompido")
            return 0
        with self._trava:
            for item in dados.get("pendentes", []):
                chamada = Chamada(item["id"], item["origem"], item["destino"],
                                  item["cabine"], item["registro"],
                                  item.get("embarque"), item.get("desembarque"),
                                  item.get("id_esp32"))
                self.pendentes[chamada.id] = chamada
            self.epoca = dados.get("epoca", 0)
            self.ultimo_id_esp32 = dados.get("ultimo_id_esp32", 0)
            self.concluidas = dados.get("concluidas", 0)
            self.soma_espera_s = dados.get("soma_espera_s", 0.0)
            self.soma_viagem_s = dados.get("soma_viagem_s", 0.0)
            self.carregadas = len(self.pendentes)
        return self.carregadas

    def _salva(self):
        dados = {
            "salvo_em": _horario(self._relogio()),
            "pendentes": [c.como_dicionario() for c in self.pendentes.values()],
            "concluidas": self.concluidas,
            "soma_espera_s": self.soma_espera_s,
            "soma_viagem_s": self.soma_viagem_s,
            "epoca": self.epoca,
            "ultimo_id_esp32": self.ultimo_id_esp32,
        }
        os.makedirs(os.path.dirname(self._arquivo_de_estado) or ".", exist_ok=True)
        temporario = self._arquivo_de_estado + ".tmp"
        with open(temporario, "w") as saida:
            json.dump(dados, saida, indent=1)
            saida.flush()
            os.fsync(saida.fileno())
        os.replace(temporario, self._arquivo_de_estado)

    def _registra_viagem(self, chamada):
        os.makedirs(os.path.dirname(self._arquivo_de_viagens) or ".", exist_ok=True)
        novo = not os.path.exists(self._arquivo_de_viagens)
        with open(self._arquivo_de_viagens, "a", newline="") as saida:
            escritor = csv.writer(saida)
            if novo:
                escritor.writerow(COLUNAS)
            escritor.writerow((chamada.id_esp32, chamada.origem, chamada.destino,
                               chamada.cabine, _horario(chamada.registro),
                               _horario(chamada.embarque),
                               _horario(chamada.desembarque),
                               "%.1f" % chamada.espera_s, "%.1f" % chamada.viagem_s))

    # --------------------------------------------------------- operacoes
    def chave(self, id_esp32):
        return self.epoca * CHAVES_POR_EPOCA + id_esp32

    def ja_atribuida(self, id_esp32, origem, destino):
        """A chamada na cabeca da fila e uma que ja atribuimos e cujo pop se
        perdeu? (mesmo id, mesmos andares, ainda pendente)"""
        with self._trava:
            chamada = self.pendentes.get(self.chave(id_esp32))
            return chamada is not None and (chamada.origem, chamada.destino) == \
                (origem, destino)

    def observa(self, id_esp32, origem, destino):
        """Chamada na cabeca da fila. Um id menor que o ultimo atribuido (ou o
        mesmo, sem ser o pop perdido) e a ESP32 reiniciada: abre uma epoca e
        descarta as pendentes, que nao existem mais no simulador. Devolve as
        descartadas, ou None se nada mudou."""
        with self._trava:
            if not self.ultimo_id_esp32 or id_esp32 > self.ultimo_id_esp32 or (
                    id_esp32 == self.ultimo_id_esp32
                    and self.ja_atribuida(id_esp32, origem, destino)):
                return None
            self.epoca += 1
            self.ultimo_id_esp32 = 0
            descartadas = list(self.pendentes.values())
            self.pendentes.clear()
            self._salva()
            return descartadas

    def nova(self, id_esp32, origem, destino, cabine):
        with self._trava:
            chamada = Chamada(self.chave(id_esp32), origem, destino, cabine,
                              self._relogio(), id_esp32=id_esp32)
            self.pendentes[chamada.id] = chamada
            self.ultimo_id_esp32 = max(self.ultimo_id_esp32, id_esp32)
            self._salva()
            return chamada

    def aplica_evento(self, cabine, evento):
        """Evento de embarque/desembarque relatado pela cabine. Devolve a
        chamada se o evento e novo, None se ja era conhecido."""
        with self._trava:
            chamada = self.pendentes.get(evento.get("id"))
            if chamada is None or chamada.cabine != cabine:
                return None
            instante = float(evento["t"])
            if evento["evento"] == "embarque" and chamada.embarque is None:
                chamada.embarque = instante
            elif evento["evento"] == "desembarque" and chamada.desembarque is None:
                if chamada.embarque is None:
                    chamada.embarque = instante
                chamada.desembarque = instante
                del self.pendentes[chamada.id]
                self.concluidas += 1
                self.soma_espera_s += chamada.espera_s
                self.soma_viagem_s += chamada.viagem_s
                self.recentes = (self.recentes + [chamada])[-20:]
                self._registra_viagem(chamada)
            else:
                return None
            self._salva()
            return chamada

    def pendentes_da_cabine(self, cabine):
        with self._trava:
            return [c for c in self.pendentes.values() if c.cabine == cabine]

    def lista_pendentes(self):
        with self._trava:
            return sorted(self.pendentes.values(), key=lambda c: c.id)

    def metricas(self):
        with self._trava:
            agora = self._relogio()
            esperando = [agora - c.registro for c in self.pendentes.values()
                         if c.embarque is None]
            return {
                "concluidas": self.concluidas,
                "espera_media_s": self.soma_espera_s / self.concluidas
                if self.concluidas else None,
                "viagem_media_s": self.soma_viagem_s / self.concluidas
                if self.concluidas else None,
                "maior_espera_atual_s": max(esperando) if esperando else 0.0,
            }

    def finaliza(self):
        with self._trava:
            self._salva()
