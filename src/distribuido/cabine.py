"""Servidor Distribuido de uma cabine.

Duas threads proprias, alem das de interrupcao e da TCP:

- controle, a cada 50 ms: decide o que a cabine faz (calibrar, viajar, abrir
  a porta, pousar em Modo Degradado) e roda um passo da malha de posicao;
- relatorio, a cada 500 ms: manda o estado ao Servidor Central (6.1.9).

Modos, na ordem em que aparecem:

  aguardando central  sem conexao ou sem Cota, ainda sem calibracao
  calibrando          varreduras de subida e descida (calibracao.py)
  operando            atende as chamadas do itinerario
  degradado           sem Cota valida: pouso no proximo andar e porta aberta

As duas threads e as interrupcoes dividem a mesma trava, para que uma
reancoragem nunca aconteca no meio de um ciclo da malha.
"""
import itertools
import threading
import time

from ..controle.cortina import Cortina
from ..controle.motor import Motor
from ..gpio.encoder import EncoderQuadratura
from ..rede import protocolo as p
from .. import tempo_real
from ..rede.servidor import ServidorTCP
from . import malha as malha_mod
from .bandeirola import SensorDeAndar
from .calibracao import CONCLUIDA, FALHOU, Calibracao
from .cota import CotaDePotencia
from .itinerario import Itinerario
from .malha import MalhaDePosicao
from .pid import PID
from .porta import NOMES as NOMES_DA_PORTA
from .porta import CicloDaPorta

PERIODO_DO_RELATORIO_S = 0.5
PRAZO_DOS_PEDIDOS_S = 3.0
ESPERA_PARA_RECALIBRAR_S = 5.0

AGUARDANDO_CENTRAL = "aguardando central"
CALIBRANDO = "calibrando"
OPERANDO = "operando"
DEGRADADO = "degradado"

# Reancoragem: uma borda medida longe demais da calibrada nao e deriva, e
# ruido ou bandeirola errada, e e recusada.
CORRECAO_MAXIMA_MM = 80.0
# Folga para escolher o andar de pouso no Modo Degradado: o andar tem de estar
# a frente o bastante para a cabine frear nele a velocidade minima.
FOLGA_DO_POUSO_MM = 60.0
# Para trocar o destino no meio da viagem por uma parada nova no caminho.
TEMPO_DE_FRENAGEM_S = 1.0
FOLGA_DE_FRENAGEM_MM = 150.0


def _imprime(texto):
    print(texto, flush=True)


class ServidorDistribuido:
    def __init__(self, configuracao, backend, eco=_imprime, registro_pid=None,
                 relogio=time.monotonic, tempo_real_ativo=False):
        self.numero = configuracao["cabine"]
        self.configuracao = configuracao
        self._backend = backend
        self._eco_externo = eco
        self._relogio = relogio
        self._trava = threading.RLock()
        pinagem = configuracao["pinos"]
        self._pinos_de_freio = (pinagem["DIR1"], pinagem["DIR2"])

        self.encoder = EncoderQuadratura(backend, pinagem["ENC_A"], pinagem["ENC_B"])
        self.motor = Motor(backend, pinagem)
        self.cortina = Cortina(backend, ao_evento=self._ao_mudar_cortina,
                               pino=pinagem["CORTINA"], eco=self._log)
        self.sensor = SensorDeAndar(backend, pinagem["SENSOR_ANDAR"], self.encoder,
                                    self._ao_cruzar_bandeirola)
        self.pid = PID(configuracao["kp"], configuracao["ki"], configuracao["kd"])
        self.malha = MalhaDePosicao(self.motor, self.encoder, self.pid, eco=self._log,
                                    ao_registrar=registro_pid, relogio=relogio)
        self.cota = CotaDePotencia(relogio=relogio)
        self.porta = CicloDaPorta(
            self._pede_porta, self._pede_leitura, lambda: self.cortina.obstruida,
            tempo_aberta_s=configuracao["tempo_de_porta_aberta_s"], eco=self._log,
            relogio=relogio)
        self.itinerario = Itinerario()
        self.calibracao = Calibracao(self.malha, self.encoder, self._pede_andar_atual,
                                     configuracao["duty_de_calibracao"], eco=self._log,
                                     relogio=relogio,
                                     dentro_da_bandeirola=lambda: self.sensor.dentro)
        self.mapa = None
        self.modo = AGUARDANDO_CENTRAL
        self.registradores = {}
        self.andar_alvo = None
        self._andar_da_porta = None
        self._pouso = None
        self._falhou_em = None
        self.reancoragens = 0
        self.ultima_correcao_mm = 0.0

        self._pedidos = {}
        self._sequencia = itertools.count(1)
        self.tcp = ServidorTCP(configuracao["tcp_porta"], self._ao_conectar,
                               self._ao_receber, self._ao_desconectar,
                               endereco=configuracao["tcp_endereco"],
                               nome="cabine%d" % self.numero)
        self._encerrar = threading.Event()
        # Malha em tempo absoluto (src/tempo_real.py). A prioridade de tempo
        # real so e pedida no processo da placa: no simulador as tres cabines
        # dividem um processo.
        self.periodo = tempo_real.LacoPeriodico(malha_mod.PERIODO_S, self._encerrar)
        self.tempo_real = tempo_real_ativo
        self._threads = [
            threading.Thread(target=self._laco_de_controle, daemon=True,
                             name="controle%d" % self.numero),
            threading.Thread(target=self._laco_de_relatorio, daemon=True,
                             name="relatorio%d" % self.numero),
        ]

    def inicia(self):
        self.tcp.inicia()
        for thread in self._threads:
            thread.start()
        self._log("Cabine %d: escutando o Servidor Central na porta TCP %d"
                  % (self.numero, self.tcp.porta))
        return self

    def _log(self, texto):
        self._eco_externo("[cabine %d] %s" % (self.numero, texto))

    # ============================================================ controle
    def _laco_de_controle(self):
        if self.tempo_real:
            self._log(tempo_real.eleva_prioridade())
        self.periodo.roda(self._ciclo_protegido)

    def _ciclo_protegido(self):
        try:
            with self._trava:
                self._ciclo()
        except Exception as erro:                  # a malha nao pode morrer
            self._log("ERRO no ciclo de controle: %r" % (erro,))
            self.malha.para()

    def _ciclo(self):
        self._expira_pedidos()
        self.malha.duty_maximo = self.cota.duty_maximo_durante(malha_mod.PERIODO_S)
        if self.mapa is None:
            self._ciclo_sem_mapa()
        elif not self.cota.valida:
            self._ciclo_degradado()
        else:
            self._ciclo_operando()
        self.porta.passo()
        self.malha.passo(malha_mod.PERIODO_S)

    # ------------------------------------------------------ calibracao
    def _ciclo_sem_mapa(self):
        if not self.tcp.conectado or not self.cota.valida:
            if self.calibracao.ativa:
                self._log("CALIBRACAO interrompida: sem central ou sem Cota; "
                          "recomeca quando voltarem")
                self.calibracao.fase = None
            self.modo = AGUARDANDO_CENTRAL
            self.malha.para()
            return
        self.modo = CALIBRANDO
        if not self.calibracao.ativa:
            if self.calibracao.fase == FALHOU and self._falhou_em is None:
                self._falhou_em = self._relogio()
            if self._falhou_em is not None and \
                    self._relogio() - self._falhou_em < ESPERA_PARA_RECALIBRAR_S:
                return
            # A cabine nao se move de porta aberta, nem para calibrar.
            if not self.porta.fechada:
                if not self.porta.ocupada:
                    self.porta.fecha()
                return
            self._falhou_em = None
            self.calibracao.inicia()
            return
        self.calibracao.passo()
        if self.calibracao.fase == CONCLUIDA:
            self._assume_mapa(self.calibracao.mapa)

    def _assume_mapa(self, mapa):
        self.mapa = mapa
        self.malha.limites_mm = (mapa.limite_inferior_mm + 100.0,
                                 mapa.limite_superior_mm - 100.0)
        try:
            mapa.salva(self.configuracao["arquivo_de_calibracao"], self.numero)
        except OSError as erro:
            self._log("AVISO: calibracao nao foi salva: %s" % erro)
        andar = mapa.andar_mais_proximo(self.malha.posicao_mm)
        self._log("assumindo o controle; indo nivelar no andar %d" % andar)
        self.malha.vai_para(mapa.posicao[andar])
        self.andar_alvo = None
        self.modo = OPERANDO

    # --------------------------------------------------------- degradado
    def _ciclo_degradado(self):
        """Secao 7.3: velocidade minima (o teto de 1000 mA ja esta na malha),
        proximo andar no sentido atual, nivelar, abrir e esperar Cota."""
        if self.modo != DEGRADADO:
            self._log("MODO DEGRADADO: sem Cota valida; velocidade minima e "
                      "pouso no proximo andar")
            self.modo = DEGRADADO
        posicao = self.malha.posicao_mm
        if self.malha.fase == malha_mod.RASTREANDO and self._pouso is None:
            sentido = self.malha.sentido or (1 if self.malha.alvo_mm > posicao else -1)
            # Rapida, a cabine ainda anda um trecho ate cair a velocidade
            # minima: o andar de pouso tem de estar alem dele.
            folga = FOLGA_DO_POUSO_MM + 0.4 * abs(self.malha.velocidade_mm_s)
            self._pouso = self.mapa.proximo_andar_no_sentido(posicao, sentido, folga)
            posicao_pouso = self.mapa.posicao[self._pouso]
            self._log("pouso de emergencia no andar %d" % self._pouso)
            # O teto de 1000 mA ja esta na malha; so o destino muda.
            if self.malha.alvo_mm != posicao_pouso:
                self.malha.vai_para(posicao_pouso)
            self.andar_alvo = self._pouso
            return
        if self.malha.ocupada:
            return
        if self.malha.fase == malha_mod.CHEGOU:
            # Chegou ao pouso (ou ao destino normal): a parada e tratada aqui, e
            # a porta abre uma vez so.
            self.malha.para()
            self.andar_alvo = None
        aqui = self._andar_nivelado()
        if aqui is None:
            # Parada entre andares (falha, Cota perdida no meio de uma correcao
            # ou pouso fora da tolerancia): nivela no pouso ou no mais proximo.
            if self._pouso is None:
                self._pouso = self.mapa.andar_mais_proximo(posicao)
            self.malha.vai_para(self.mapa.posicao[self._pouso])
            return
        if not self.porta.manter_aberta:
            self._andar_da_porta = aqui
            self.porta.abre(manter=True)
        self._consome_abertura()

    # ---------------------------------------------------------- operando
    def _ciclo_operando(self):
        if self.modo == DEGRADADO:
            self._log("Cota valida de novo: saindo do Modo Degradado")
            self._pouso = None
            if self.porta.manter_aberta:
                self.porta.manter_aberta = False
        self.modo = OPERANDO
        self._consome_abertura()
        if self.porta.ocupada:
            return
        if not self.porta.fechada:
            self.porta.fecha()
            return
        fase = self.malha.fase
        if fase == malha_mod.RASTREANDO:
            self._talvez_troque_o_destino()
            return
        if fase in (malha_mod.ASSENTANDO, malha_mod.PULSO, malha_mod.CONSTANTE):
            return
        if fase == malha_mod.CHEGOU:
            self.malha.para()
            if self.malha.fora_de_nivel:
                self._log("parada fora da tolerancia; porta nao abre")
            elif self.andar_alvo is not None:
                self._andar_da_porta = self.andar_alvo
                self.andar_alvo = None
                self.porta.abre()
                return
            self.andar_alvo = None
        aqui = self._andar_nivelado()
        proxima = self.itinerario.proxima_parada(self.malha.posicao_mm, self.mapa, aqui)
        if proxima is None:
            return
        if proxima == aqui:
            self._andar_da_porta = aqui
            self.porta.abre()
            return
        self.andar_alvo = proxima
        self.malha.vai_para(self.mapa.posicao[proxima])

    def _talvez_troque_o_destino(self):
        posicao = self.malha.posicao_mm
        proxima = self.itinerario.proxima_parada(posicao, self.mapa, None)
        if proxima is None or proxima == self.andar_alvo or self.andar_alvo is None:
            return
        destino = self.mapa.posicao[proxima]
        atual = self.mapa.posicao[self.andar_alvo]
        sentido = 1 if atual > posicao else -1
        a_frente = (destino - posicao) * sentido
        antes_do_atual = (atual - destino) * sentido > 0
        frenagem = abs(self.malha.velocidade_mm_s) * TEMPO_DE_FRENAGEM_S \
            + FOLGA_DE_FRENAGEM_MM
        if antes_do_atual and a_frente > frenagem:
            self._log("parada nova no caminho: andar %d antes do %d"
                      % (proxima, self.andar_alvo))
            self.andar_alvo = proxima
            self.malha.vai_para(destino)

    def _consome_abertura(self):
        if not self.porta.abriu:
            return
        self.porta.abriu = False
        andar = self._andar_da_porta
        if andar is None:
            return
        for evento in self.itinerario.porta_abriu(andar):
            self._log("%s da chamada %d no andar %d"
                      % (evento["evento"].upper(), evento["id"], andar))

    def _andar_nivelado(self):
        if self.mapa is None or not self.malha.parada:
            return None
        return self.mapa.andar_nivelado(self.malha.posicao_mm, malha_mod.TOLERANCIA_MM)

    # ====================================================== interrupcoes
    def _ao_cruzar_bandeirola(self, borda):
        with self._trava:
            if self.calibracao.ativa:
                self.calibracao.ao_cruzar(borda)
                return
            # Operacao: corrige a contagem para o valor calibrado da borda.
            if self.mapa is not None and borda.lado is not None:
                resultado = self.mapa.borda_cruzada(
                    borda.contagem, borda.lado, distancia_maxima_mm=CORRECAO_MAXIMA_MM
                )
                if resultado is not None:
                    andar, contagem_calibrada = resultado
                    delta_mm = contagem_calibrada - borda.contagem

                    if abs(delta_mm) >= 1.0:
                        self.encoder.desloca(delta_mm)
                        self.malha.reancorou(delta_mm)
                        self.reancoragens += 1
                        self.ultima_correcao_mm = delta_mm
                        if abs(delta_mm) >= 3.0:
                            self._log("reancorado na borda %s do andar %d: %+.0f mm"
                                      % (borda.lado, andar, delta_mm))

    def _ao_mudar_cortina(self, nivel):
        with self._trava:
            self.porta.ao_mudar_cortina(nivel == 1)

    # ============================================================ TCP
    def _ao_conectar(self, conexao):
        self._log("Servidor Central conectado")
        conexao.envia({"tipo": p.OLA, "cabine": self.numero})

    def _ao_desconectar(self, _conexao):
        self._log("conexao com o Servidor Central caiu; aguardando reconexao")
        with self._trava:
            pendentes, self._pedidos = self._pedidos, {}
        for callback, _instante in pendentes.values():
            callback(None)

    def _ao_receber(self, _conexao, mensagem):
        tipo = mensagem["tipo"]
        if tipo == p.COTA:
            self.cota.recebe(mensagem["cota_ma"], mensagem.get("validade_s", 2.0),
                             mensagem.get("seq"))
            with self._trava:
                self.malha.limita(self.cota.duty_maximo_durante(malha_mod.PERIODO_S))
        elif tipo == p.CHAMADA:
            if self.itinerario.atribui(mensagem["id"], mensagem["origem"],
                                       mensagem["destino"],
                                       mensagem.get("estado", "aguardando"),
                                       mensagem.get("espera_s", 0.0)):
                self._log("chamada %d atribuida: %d -> %d" % (
                    mensagem["id"], mensagem["origem"], mensagem["destino"]))
        elif tipo == p.VAI_ANDAR:
            self.itinerario.manual(int(mensagem["andar"]))
            self._log("comando manual: ir ao andar %d" % int(mensagem["andar"]))
        elif tipo == p.REGISTRADORES:
            self._recebe_registradores(mensagem["dados"])
        elif tipo == p.RESPOSTA:
            with self._trava:
                callback, _ = self._pedidos.pop(mensagem.get("pedido"), (None, None))
            if callback is not None:
                callback(mensagem.get("dados") if mensagem.get("ok") else None)

    def _recebe_registradores(self, dados):
        if not dados:
            return
        with self._trava:
            self.registradores = dict(dados)
            self.cota.mede_corrente(dados.get("corrente_ma"), self.malha.comando)
            if "porta_estado" in dados:
                self.porta.registradores(dados["porta_estado"], self._relogio())

    def _pede(self, op, callback=None, **campos):
        with self._trava:
            identificador = next(self._sequencia)
            if callback is not None:
                self._pedidos[identificador] = (callback, self._relogio())
        enviado = self.tcp.envia(dict({"tipo": p.PEDIDO, "pedido": identificador,
                                       "op": op}, **campos))
        if not enviado and callback is not None:
            with self._trava:
                self._pedidos.pop(identificador, None)
            callback(None)

    def _expira_pedidos(self):
        agora = self._relogio()
        vencidos = [i for i, (_, instante) in self._pedidos.items()
                    if agora - instante > PRAZO_DOS_PEDIDOS_S]
        for identificador in vencidos:
            callback, _ = self._pedidos.pop(identificador)
            callback(None)

    def _pede_leitura(self):
        self._pede(p.OP_LE_CABINE, self._recebe_registradores)

    def _pede_andar_atual(self, callback):
        def recebe(dados):
            self._recebe_registradores(dados)
            callback(None if not dados else dados.get("andar_atual"))
        self._pede(p.OP_LE_CABINE, recebe)

    def _pede_porta(self, comando):
        self._pede(p.OP_PORTA, comando=comando)

    # ====================================================== relatorio
    def estado(self):
        with self._trava:
            posicao = self.malha.posicao_mm
            porta = self.registradores.get("porta_estado")
            return {
                "tipo": p.ESTADO,
                "cabine": self.numero,
                "modo": self.modo,
                "calibrada": self.mapa is not None,
                "calibracao": self.calibracao.fase,
                "posicao_mm": round(posicao, 1),
                "andar": None if self.mapa is None
                else self.mapa.andar_mais_proximo(posicao),
                "nivelado": self._andar_nivelado() is not None,
                "sentido": {1: "subindo", -1: "descendo"}.get(self.malha.sentido,
                                                              "parado"),
                "velocidade_mm_s": round(self.malha.velocidade_mm_s, 1),
                "porta": NOMES_DA_PORTA.get(porta, "?"),
                "porta_ciclo": self.porta.fase,
                "cortina": self.cortina.obstruida,
                "corrente_ma": self.registradores.get("corrente_ma"),
                "duty": round(self.malha.comando, 1),
                "duty_maximo": round(self.malha.duty_maximo, 1),
                "cota_ma": self.cota.cota_ma,
                "cota_valida": self.cota.valida,
                "cota_seq": self.cota.sequencia,
                "fator_de_corrente": round(self.cota.fator_de_corrente, 3),
                "fase": self.malha.fase,
                "alvo": self.andar_alvo,
                "paradas": sorted(self.itinerario.paradas()),
                "chamadas": self.itinerario.lista(),
                "eventos": self.itinerario.ultimos_eventos(),
                "reancoragens": self.reancoragens,
                "ultima_correcao_mm": round(self.ultima_correcao_mm, 1),
                "falha": self.malha.falha,
                "atraso_maximo_ms": round(self.periodo.atraso_maximo_s * 1000, 1),
                "ciclos_perdidos": self.periodo.ciclos_perdidos,
                "mapa": None if self.mapa is None else self.mapa.resumo(),
            }

    def _laco_de_relatorio(self):
        while not self._encerrar.wait(PERIODO_DO_RELATORIO_S):
            if self.tcp.conectado:
                try:
                    self.tcp.envia(self.estado())
                except Exception as erro:
                    self._log("ERRO no relatorio: %r" % (erro,))

    # ======================================================= encerramento
    def finaliza(self):
        """SIGINT: PWM em zero, direcao em freio, GPIO e TCP liberados."""
        self._encerrar.set()
        self._log("malha: %d ciclos, atraso medio %.2f ms, maximo %.2f ms, %d perdidos"
                  % (self.periodo.ciclos, self.periodo.atraso_medio_s * 1000,
                     self.periodo.atraso_maximo_s * 1000, self.periodo.ciclos_perdidos))
        for thread in self._threads:
            if thread.is_alive() and thread is not threading.current_thread():
                thread.join(timeout=1.0)
        self.motor.finaliza()
        self.cortina.finaliza()
        self.sensor.finaliza()
        self.encoder.finaliza()
        self.tcp.encerra()
        # DIR1/DIR2 seguram o freio: liberados, flutuam e a bancada os le
        # como DESCER (medido na Entrega 1).
        self._backend.limpa(preserva=self._pinos_de_freio)
