"""Edificio simulado: tres cabines e o Controlador do Predio.

Estende a ESP32 simulada da Entrega 2, que ja responde aos quadros MODBUS com
o CRC e as excecoes da bancada, trocando as cabines de mentira por cabines com
fisica e acrescentando o que a Entrega Final usa: a corrente e a porta de cada
cabine, a atribuicao das chamadas, os Cenarios de Trafego com semente
deterministica e as metricas de espera e de viagem.

Espera e viagem sao medidas como o enunciado define: espera do registro ate a
porta da cabine atribuida abrir no andar de origem; viagem desse instante ate
a porta abrir no andar de destino.
"""
import random
import threading
import time

from ..gpio import pinos
from ..uart.esp32_simulada import Esp32Simulada
from . import poco
from .poco import CabineFisica

PASSO_DA_FISICA_S = 0.002
DURACAO_DO_CENARIO_S = 300.0
INTERVALO_MEDIO_DO_CENARIO_S = 7.0
CENARIOS = {"up-peak": 1, "down-peak": 2, "interfloor": 3}
ESPERA_MAXIMA_S = 90.0


class _Chamada:
    def __init__(self, identificador, origem, destino, registro):
        self.id = identificador
        self.origem = origem
        self.destino = destino
        self.registro = registro
        self.cabine = None
        self.embarque = None
        self.desembarque = None
        self.cenario = 0


class Esp32Predio(Esp32Simulada):
    def __init__(self, andar_inicial=(0, 0, 0), perda_de_transicoes=0.0,
                 relogio=time.monotonic):
        super().__init__(relogio=relogio)
        self.fisicas = {}
        for numero in (1, 2, 3):
            andares, larguras = poco.andares_de_exemplo(numero)
            self.fisicas[numero] = CabineFisica(
                numero, pinos.PINAGENS_DAS_CABINES[numero], andares, larguras,
                andar_inicial=andar_inicial[numero - 1],
                perda_de_transicoes=perda_de_transicoes, semente=numero)
        # O Esp32Simulada roteia por este dicionario: endereco -> cabine.
        self.cabines = {0x10 + n: f for n, f in self.fisicas.items()}
        self.chamadas = {}
        self._trava_das_chamadas = threading.RLock()
        self.cenario_ativo = 0
        self._cenario_inicio = None
        self.sobrecargas = 0           # passos da fisica com o barramento estourado
        self._parar = threading.Event()
        self._fisica = threading.Thread(target=self._laco_da_fisica, daemon=True,
                                        name="fisica-do-predio")
        self._fisica.start()

    def encerra(self):
        self._parar.set()
        self._fisica.join(timeout=1.0)

    # ------------------------------------------------------- quiosque
    def registra_chamada(self, origem, destino, cenario=0):
        with self._trava_das_chamadas:
            identificador = self._proximo_id
            super().registra_chamada(origem, destino)
            chamada = _Chamada(identificador, origem, destino, self._relogio())
            chamada.cenario = cenario
            self.chamadas[identificador] = chamada
            return identificador

    def inicia_cenario(self, nome, semente=2026,
                       duracao_s=DURACAO_DO_CENARIO_S,
                       intervalo_medio_s=INTERVALO_MEDIO_DO_CENARIO_S):
        codigo = CENARIOS[nome]
        self.cenario_ativo = codigo
        self._cenario_inicio = self._relogio()
        sorteio = random.Random(semente + codigo)

        def gera():
            fim = time.monotonic() + duracao_s
            while not self._parar.is_set() and time.monotonic() < fim \
                    and self.cenario_ativo == codigo:
                origem, destino = self._sorteia(codigo, sorteio)
                self.registra_chamada(origem, destino, cenario=codigo)
                self._parar.wait(sorteio.expovariate(1.0 / intervalo_medio_s))
            if self.cenario_ativo == codigo:
                self.cenario_ativo = 0

        threading.Thread(target=gera, daemon=True, name="cenario").start()

    @staticmethod
    def _sorteia(codigo, sorteio):
        andares = list(range(6))
        while True:
            origem, destino = sorteio.choice(andares), sorteio.choice(andares)
            if codigo == 1 and sorteio.random() < 0.8:
                origem = 0
            elif codigo == 2 and sorteio.random() < 0.8:
                destino = 0
            if origem != destino:
                return origem, destino

    # ------------------------------------------------------- metricas
    def metricas(self, so_do_cenario=True):
        with self._trava_das_chamadas:
            chamadas = [c for c in self.chamadas.values()
                        if not so_do_cenario or c.cenario]
        esperas = [c.embarque - c.registro for c in chamadas if c.embarque]
        viagens = [c.desembarque - c.embarque for c in chamadas if c.desembarque]
        return {
            "geradas": len(chamadas),
            "atendidas": len(viagens),
            "espera_media_s": sum(esperas) / len(esperas) if esperas else 0.0,
            "viagem_media_s": sum(viagens) / len(viagens) if viagens else 0.0,
            "espera_maxima_s": max(esperas) if esperas else 0.0,
        }

    def violacoes(self):
        return {n: list(f.violacoes) for n, f in self.fisicas.items()}

    # ------------------------------------------------------- fisica
    def _laco_da_fisica(self):
        anterior = time.monotonic()
        while not self._parar.wait(PASSO_DA_FISICA_S):
            agora = time.monotonic()
            dt, anterior = agora - anterior, agora
            # Sobrecarga: a soma das correntes acima da capacidade derruba o
            # barramento, e nenhum motor tem torque enquanto ela durar. E a
            # hipotese para os travamentos vistos na bancada sem BMP280.
            total = sum(f.corrente_ma for f in self.fisicas.values())
            sobrecarga = total > self.barramento_max_ma() + 1
            if sobrecarga:
                self.sobrecargas += 1
            for numero, fisica in self.fisicas.items():
                fisica.sem_energia = sobrecarga
                fisica.dispara(fisica.passo(dt, agora))
                with fisica.trava:
                    abriu = fisica.atualiza_porta(agora)
                if abriu:
                    self._porta_abriu(numero, fisica, agora)

    def _porta_abriu(self, numero, fisica, agora):
        andar = fisica.andar_mais_proximo()
        with self._trava_das_chamadas:
            for chamada in self.chamadas.values():
                if chamada.cabine != numero:
                    continue
                if chamada.embarque is None and chamada.origem == andar:
                    chamada.embarque = agora
                    fisica.passageiros += 1
                elif chamada.embarque is not None and chamada.desembarque is None \
                        and chamada.destino == andar and chamada.embarque < agora:
                    chamada.desembarque = agora
                    fisica.passageiros = max(0, fisica.passageiros - 1)

    # ---------------------------------------------------- registradores
    def _registradores(self, endereco):
        if endereco == 0x20:
            return self._registradores_do_predio()
        fisica = self.cabines[endereco]
        with fisica.trava:
            return [fisica.andar_mais_proximo(), int(fisica.nivelado()),
                    fisica.porta_estado, fisica.porta_comando,
                    int(round(fisica.corrente_ma)), 75 * fisica.passageiros,
                    fisica.passageiros, int(round(fisica.posicao_mm)),
                    fisica.falha]

    def _registradores_do_predio(self):
        valores = super()._registradores_do_predio()
        metricas = self.metricas()
        valores[11] = self.cenario_ativo
        valores[12] = metricas["geradas"]
        valores[13] = metricas["atendidas"]
        valores[14] = int(round(metricas["espera_media_s"] * 10))
        valores[15] = int(round(metricas["viagem_media_s"] * 10))
        return valores

    def _escreve(self, endereco, registrador, valores):
        if endereco != 0x20:
            comando = valores[0]
            if comando > 2:
                return 0x03
            fisica = self.cabines[endereco]
            with fisica.trava:
                fisica.comanda_porta(comando, self._relogio())
            return None
        codigo = super()._escreve(endereco, registrador, valores)
        novos = dict(zip(range(registrador, registrador + len(valores)), valores))
        if codigo is None and 9 in novos and 10 in novos:
            with self._trava_das_chamadas:
                chamada = self.chamadas.get(novos[9])
                if chamada is not None and chamada.cabine is None:
                    chamada.cabine = novos[10]
        return codigo
