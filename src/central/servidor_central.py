"""Servidor Central (Secoes 2.1 e 6.2).

Unico dono da UART e do I2C. Threads, cada uma dormindo em Event.wait():

  contorno   BMP280 -> registradores 5 e 6 do predio a cada 4 s (Entrega 2)
  predio     le os 16 registradores do 0x20 a cada 1 s: barramento, watchdog,
             cenario e metricas do simulador
  cabines    le os registradores das tres cabines a cada 500 ms e encaminha
             cada leitura a sua cabine por TCP (porta, corrente, andar)
  fila       consome a fila de Chamadas de Destino a cada 500 ms
  cotas      reparte o barramento e renova as Cotas a cada 1 s

mais uma thread TCP por cabine (rede/cliente.py), que reconecta sozinha.

Todas falam MODBUS pelo mesmo ClienteModbus; a trava da porta serial
(uart/porta.py) garante que pedido e resposta ocupem a linha juntos.
"""
import threading
import time
from collections import deque

from ..rede import protocolo as p
from ..rede.cliente import ClienteReconectavel
from ..uart.erros import ErroComunicacao
from . import despacho
from ..distribuido.cota import duty_maximo_de
from .cotas import CAPACIDADE_DESCONHECIDA_MA, COTA_MAXIMA_MA, RepartidorDeCotas
from .registro import RegistroDeChamadas

PERIODO_DO_PREDIO_S = 1.0
PERIODO_DAS_CABINES_S = 0.5
PERIODO_DA_FILA_S = 0.5
PERIODO_DAS_COTAS_S = 1.0
ESTADO_VELHO_S = 2.0
LEITURA_FRESCA_S = 0.15
EVENTOS_NA_TELA = 200
CENARIO_UP_PEAK = 1                 # registrador cenario_ativo (Secao 5.3)


class Cabine:
    """O que o central sabe de uma cabine, e o canal ate ela."""

    def __init__(self, numero, host, porta, endereco_modbus):
        self.numero = numero
        self.host = host
        self.porta = porta
        self.endereco_modbus = endereco_modbus
        self.cliente = None
        self.estado = None
        self.estado_em = 0.0
        self.registradores = None
        self.registradores_em = 0.0
        self.falhas_modbus = 0
        # mm/s por ponto de duty, medido nos relatorios: e o que o despacho
        # usa para estimar tempo de viagem com a Cota de cada cabine.
        self.velocidade_por_duty = None

    def aprende_velocidade(self, estado):
        velocidade = abs(estado.get("velocidade_mm_s") or 0.0)
        duty = abs(estado.get("duty") or 0.0)
        if duty < 20.0 or velocidade < 100.0:
            return
        medida = velocidade / duty
        self.velocidade_por_duty = medida if self.velocidade_por_duty is None \
            else 0.9 * self.velocidade_por_duty + 0.1 * medida

    @property
    def conectada(self):
        return self.cliente is not None and self.cliente.conectado

    def estado_recente(self, agora):
        if not self.conectada or self.estado is None:
            return None
        return self.estado if agora - self.estado_em <= ESTADO_VELHO_S else None


class ServidorCentral:
    def __init__(self, configuracao, elevadores, servico_contorno=None,
                 eco=None, relogio=time.monotonic, registro_de_potencia=None):
        self.configuracao = configuracao
        self.elevadores = elevadores
        self.contorno = servico_contorno
        self._eco_externo = eco
        self._relogio = relogio
        self.cabines = {n: Cabine(n, c["host"], c["porta"], c["endereco_modbus"])
                        for n, c in sorted(configuracao["cabines"].items())}
        self.registro = RegistroDeChamadas(configuracao["arquivo_de_estado"],
                                           configuracao["arquivo_de_viagens"])
        self.cotas = RepartidorDeCotas(relogio=relogio)
        self.registro_de_potencia = registro_de_potencia
        self.predio = None
        self.predio_em = 0.0
        self.fila_sem_cabine = 0
        self.ultima_escolha = None
        self._cotas_cortadas_ate = {}
        self._estacionada_em = {}
        self.eventos = deque(maxlen=EVENTOS_NA_TELA)
        self._arquivo_de_eventos = configuracao.get("arquivo_de_eventos")
        self._trava_do_log = threading.Lock()
        self._encerrar = threading.Event()
        self._threads = []

    # ============================================================ log
    def log(self, texto):
        linha = "%s %s" % (time.strftime("%H:%M:%S"), texto)
        with self._trava_do_log:
            self.eventos.append(linha)
            if self._arquivo_de_eventos:
                try:
                    with open(self._arquivo_de_eventos, "a") as saida:
                        saida.write(linha + "\n")
                except OSError:
                    pass
        if self._eco_externo is not None:
            self._eco_externo(linha)

    # ======================================================= ciclo de vida
    def inicia(self):
        import os
        if self._arquivo_de_eventos:
            os.makedirs(os.path.dirname(self._arquivo_de_eventos) or ".", exist_ok=True)
        carregadas = self.registro.carrega()
        if carregadas:
            self.log("estado restaurado: %d chamada(s) pendente(s) do disco" % carregadas)
        for cabine in self.cabines.values():
            cabine.cliente = ClienteReconectavel(
                cabine.host, cabine.porta,
                ao_conectar=lambda c, cab=cabine: self._ao_conectar(cab, c),
                ao_receber=lambda c, m, cab=cabine: self._ao_receber(cab, m),
                ao_desconectar=lambda c, cab=cabine: self._ao_desconectar(cab),
                nome="cabine%d" % cabine.numero).inicia()
        if self.contorno is not None:
            self.contorno.inicia()
        for nome, periodo, funcao in (
                ("predio", PERIODO_DO_PREDIO_S, self._le_predio),
                ("cabines", PERIODO_DAS_CABINES_S, self._le_cabines),
                ("fila", PERIODO_DA_FILA_S, self._consome_fila),
                ("cotas", PERIODO_DAS_COTAS_S, self._renova_cotas)):
            thread = threading.Thread(target=self._periodica, args=(periodo, funcao),
                                      daemon=True, name=nome)
            thread.start()
            self._threads.append(thread)
        self.log("Servidor Central iniciado; conectando as cabines %s"
                 % ", ".join("%d em %s:%d" % (c.numero, c.host, c.porta)
                             for c in self.cabines.values()))
        return self

    def _periodica(self, periodo, funcao):
        while not self._encerrar.is_set():
            try:
                funcao()
            except Exception as erro:            # a thread nao pode morrer
                self.log("ERRO em %s: %r" % (funcao.__name__, erro))
            self._encerrar.wait(periodo)

    def finaliza(self):
        self._encerrar.set()
        for thread in self._threads:
            thread.join(timeout=2.0)
        if self.contorno is not None:
            self.contorno.para()
        for cabine in self.cabines.values():
            if cabine.cliente is not None:
                cabine.cliente.encerra()
        self.registro.finaliza()

    # ============================================================ MODBUS
    def _le_predio(self):
        try:
            self.predio = self.elevadores.le_estado_predio()
            self.predio_em = self._relogio()
        except ErroComunicacao as erro:
            self.log("MODBUS predio: %s" % erro)
            return
        self._estaciona_no_terreo()

    def _estaciona_no_terreo(self):
        """No up-peak (cenario_ativo = 1) a cabine ociosa volta ao terreo, de
        onde saem 80% das chamadas. Com a lotacao limitada, quem chegava ao
        terreo com as tres cabines no alto esperava uma voltar: na rasp52 a pior
        espera passou de 90 s."""
        if self.predio.get("cenario_ativo") != CENARIO_UP_PEAK:
            return
        agora = self._relogio()
        for numero, cabine in self.cabines.items():
            estado = cabine.estado_recente(agora)
            if estado is None or estado.get("modo") != "operando" \
                    or estado.get("paradas") or estado.get("andar") in (None, 0) \
                    or estado.get("fase") not in ("livre", "chegou") \
                    or estado.get("porta_ciclo") not in (None, "ociosa") \
                    or self.registro.pendentes_da_cabine(numero) \
                    or agora - self._estacionada_em.get(numero, -1e9) < 5.0:
                continue
            self._estacionada_em[numero] = agora
            cabine.cliente.envia({"tipo": p.VAI_ANDAR, "andar": 0})
            self.log("up-peak: cabine %d ociosa volta ao terreo" % numero)

    def _le_cabines(self):
        for cabine in self.cabines.values():
            dados = self._le_cabine(cabine)
            if dados is not None and cabine.conectada:
                cabine.cliente.envia({"tipo": p.REGISTRADORES, "dados": dados})

    def _le_cabine(self, cabine, idade_maxima_s=0.0):
        agora = self._relogio()
        if cabine.registradores is not None and \
                agora - cabine.registradores_em <= idade_maxima_s:
            return cabine.registradores
        try:
            dados = self.elevadores.le_estado_cabine(cabine.numero)
        except ErroComunicacao as erro:
            cabine.falhas_modbus += 1
            if cabine.falhas_modbus in (1, 10) or cabine.falhas_modbus % 100 == 0:
                self.log("MODBUS cabine %d: %s (%d falhas)"
                         % (cabine.numero, erro, cabine.falhas_modbus))
            return None
        cabine.registradores, cabine.registradores_em = dados, self._relogio()
        return dados

    # ============================================================ fila
    def _consome_fila(self):
        """Fluxo da Secao 5.3: le, escolhe, atribui, retira, avisa a cabine."""
        while not self._encerrar.is_set():
            try:
                chamada = self.elevadores.le_chamada_da_fila()
            except ErroComunicacao as erro:
                self.log("MODBUS fila: %s" % erro)
                return
            if chamada is None:
                self.fila_sem_cabine = 0
                return
            identificador = chamada["id"]
            origem, destino = chamada["origem"], chamada["destino"]
            descartadas = self.registro.observa(identificador, origem, destino)
            if descartadas is not None:
                self._esquece(identificador, descartadas)
            if self.registro.ja_atribuida(identificador, origem, destino):
                # A atribuicao valeu, mas o pop da rodada anterior falhou.
                self._retira(identificador)
                continue
            agora = self._relogio()
            estados = {n: self._estado_para_despacho(c, agora)
                       for n, c in self.cabines.items()}
            escolhida, custos = despacho.escolhe(estados, origem, destino)
            if escolhida is None:
                if not self.fila_sem_cabine:
                    self.log("chamada %d (%d->%d) aguardando cabine disponivel"
                             % (identificador, origem, destino))
                self.fila_sem_cabine = chamada["na_fila"]
                return
            self.fila_sem_cabine = 0
            try:
                self.elevadores.atribui_chamada(identificador, escolhida)
            except ErroComunicacao as erro:
                self.log("MODBUS atribuicao da chamada %d: %s" % (identificador, erro))
                return
            registrada = self.registro.nova(identificador, origem, destino, escolhida)
            self.ultima_escolha = (identificador, escolhida, custos)
            self.log("chamada %d: %d -> %d atribuida a cabine %d (custos %s)"
                     % (identificador, origem, destino, escolhida,
                        ", ".join("C%d %.0f s" % (n, c) for n, c in sorted(custos.items()))))
            self._retira(identificador)
            self._envia_chamada(self.cabines[escolhida], registrada)

    def _estado_para_despacho(self, cabine, agora):
        """Ultimo estado da cabine, com as paradas das chamadas que o central
        ja atribuiu e que ela ainda nao relatou: numa rajada de chamadas o
        relatorio de 500 ms ainda nao as tem, e o despacho mandaria todas
        para a mesma cabine."""
        estado = cabine.estado_recente(agora)
        if estado is None:
            return None
        paradas = set(estado.get("paradas") or [])
        agora_de_parede = time.time()
        pendentes = self.registro.pendentes_da_cabine(cabine.numero)
        chamadas = [{"origem": c.origem, "destino": c.destino,
                     "embarcada": c.embarque is not None,
                     "idade_s": agora_de_parede - c.registro} for c in pendentes]
        for chamada in pendentes:
            paradas.add(chamada.destino if chamada.embarque else chamada.origem)
        # A viagem e estimada na fatia de um terco do barramento, a Cota que a
        # cabine tem com as tres ocupadas, convertida pelo modelo de corrente
        # dela. Com a Cota de agora, alta enquanto as outras estao ociosas, a
        # espera saia otimista e passava dos 90 s quando elas arrancavam.
        capacidade = self.capacidade_ma() or CAPACIDADE_DESCONHECIDA_MA
        duty_previsto = duty_maximo_de(min(COTA_MAXIMA_MA, capacidade / len(self.cabines)),
                                       estado.get("corrente_parada_ma"),
                                       estado.get("corrente_por_duty_ma"))
        return dict(estado, paradas=sorted(paradas), chamadas_do_central=chamadas,
                    comprometidos=len(pendentes),
                    velocidade_por_duty=cabine.velocidade_por_duty,
                    duty_maximo=duty_previsto)

    def _retira(self, identificador):
        try:
            self.elevadores.remove_chamada_da_fila(identificador)
        except ErroComunicacao as erro:
            # Fica na cabeca da fila; a proxima rodada ve que ja foi atribuida
            # e so repete o pop.
            self.log("MODBUS pop da chamada %d: %s" % (identificador, erro))

    def _esquece(self, identificador, descartadas):
        self.log("ESP32 reiniciada (chamada %d depois da %d): %d pendente(s) "
                 "descartada(s), epoca %d" % (identificador, max(
                     [c.id_esp32 for c in descartadas], default=0), len(descartadas),
                     self.registro.epoca))
        for numero, cabine in self.cabines.items():
            ids = [c.id for c in descartadas if c.cabine == numero]
            if ids and cabine.conectada:
                cabine.cliente.envia({"tipo": p.ESQUECE, "ids": ids})

    def _envia_chamada(self, cabine, chamada):
        if cabine.conectada:
            cabine.cliente.envia({"tipo": p.CHAMADA, "id": chamada.id,
                                  "origem": chamada.origem, "destino": chamada.destino,
                                  "estado": chamada.estado,
                                  "espera_s": time.time() - chamada.registro})

    # ============================================================ cotas
    def capacidade_ma(self):
        if self.predio is None or self._relogio() - self.predio_em > 5.0:
            return None
        return self.predio["barramento_max_ma"]

    def _renova_cotas(self):
        agora = self._relogio()
        ativas, ociosas, sem_cota = [], [], []
        for numero, cabine in self.cabines.items():
            estado = cabine.estado_recente(agora)
            if estado is None or self._cotas_cortadas_ate.get(numero, 0) > agora:
                sem_cota.append(numero)
                continue
            ocupada = estado.get("modo") == "calibrando" or estado.get("paradas") \
                or estado.get("fase") in ("rastreando", "assentando", "pulso", "constante")
            (ativas if ocupada else ociosas).append(numero)
        for numero, (cota, sequencia) in self.cotas.reparte(
                self.capacidade_ma(), ativas, ociosas, sem_cota).items():
            enviada = self.cabines[numero].cliente.envia(
                {"tipo": p.COTA, "cota_ma": cota, "validade_s": 2.0, "seq": sequencia})
            if not enviada:
                self.cotas.cancela(numero, sequencia)
        if self.registro_de_potencia is not None:
            self.registro_de_potencia(self)

    # ============================================================ TCP
    def _ao_conectar(self, cabine, _conexao):
        self.log("cabine %d conectada (%s:%d)" % (cabine.numero, cabine.host, cabine.porta))
        for chamada in self.registro.pendentes_da_cabine(cabine.numero):
            self._envia_chamada(cabine, chamada)

    def _ao_desconectar(self, cabine):
        self.log("cabine %d desconectada; reconectando" % cabine.numero)

    def _ao_receber(self, cabine, mensagem):
        tipo = mensagem["tipo"]
        if tipo == p.ESTADO:
            self._recebe_estado(cabine, mensagem)
        elif tipo == p.PEDIDO:
            self._atende_pedido(cabine, mensagem)
        elif tipo == p.OLA and mensagem.get("cabine") != cabine.numero:
            self.log("AVISO: o processo em %s:%d diz ser a cabine %s, nao a %d"
                     % (cabine.host, cabine.porta, mensagem.get("cabine"), cabine.numero))

    def _recebe_estado(self, cabine, estado):
        anterior = cabine.estado
        cabine.estado, cabine.estado_em = estado, self._relogio()
        cabine.aprende_velocidade(estado)
        self.cotas.confirma(cabine.numero, estado.get("cota_seq"))
        for evento in estado.get("eventos", []):
            chamada = self.registro.aplica_evento(cabine.numero, evento)
            if chamada is None:
                continue
            if evento["evento"] == "embarque":
                self.log("embarque da chamada %d na cabine %d, andar %d (espera %.1f s)"
                         % (chamada.id_esp32, cabine.numero, chamada.origem, chamada.espera_s))
            else:
                self.log("desembarque da chamada %d na cabine %d, andar %d "
                         "(viagem %.1f s)" % (chamada.id_esp32, cabine.numero,
                                              chamada.destino, chamada.viagem_s))
        if anterior is None or anterior.get("modo") != estado.get("modo"):
            self.log("cabine %d: %s" % (cabine.numero, estado.get("modo")))
        # Chamadas que a cabine nao tem (reiniciou, ou a mensagem se perdeu na
        # queda) sao reenviadas; a cabine ignora as repetidas.
        conhecidas = {c["id"] for c in estado.get("chamadas", [])}
        for chamada in self.registro.pendentes_da_cabine(cabine.numero):
            if chamada.id not in conhecidas:
                self._envia_chamada(cabine, chamada)

    def _atende_pedido(self, cabine, pedido):
        op = pedido.get("op")
        resposta = {"tipo": p.RESPOSTA, "pedido": pedido.get("pedido"), "ok": False}
        try:
            if op == p.OP_LE_CABINE:
                dados = self._le_cabine(cabine, idade_maxima_s=LEITURA_FRESCA_S)
                if dados is not None:
                    resposta.update(ok=True, dados=dados)
            elif op == p.OP_PORTA:
                self.elevadores.comanda_porta(cabine.numero, pedido["comando"])
                resposta["ok"] = True
                self.log("cabine %d: porta <- %s" % (cabine.numero, pedido["comando"]))
            else:
                resposta["erro"] = "operacao desconhecida: %r" % op
        except (ErroComunicacao, ValueError, KeyError) as erro:
            resposta["erro"] = str(erro)
            self.log("pedido %s da cabine %d falhou: %s" % (op, cabine.numero, erro))
        cabine.cliente.envia(resposta)

    # ======================================================== comandos
    def envia_cabine_ao_andar(self, numero, andar):
        cabine = self.cabines.get(numero)
        if cabine is None:
            raise ValueError("cabine invalida: %r" % numero)
        if not 0 <= andar <= 5:
            raise ValueError("andar invalido: %r (0 a 5)" % andar)
        if not cabine.conectada:
            raise ValueError("cabine %d desconectada" % numero)
        cabine.cliente.envia({"tipo": p.VAI_ANDAR, "andar": andar})
        self.log("comando manual: cabine %d ao andar %d" % (numero, andar))

    def corta_cota(self, numero, segundos):
        """Para de renovar a Cota da cabine por `segundos`, sem derrubar o TCP
        nem o MODBUS. A Cota vence em 2 s e a cabine entra em Modo Degradado:
        e o ensaio do pouso de emergencia com o central ainda capaz de abrir
        a porta."""
        if numero not in self.cabines:
            raise ValueError("cabine invalida: %r" % numero)
        self._cotas_cortadas_ate[numero] = self._relogio() + float(segundos)
        self.log("Cota da cabine %d suspensa por %.0f s" % (numero, segundos))

    # ======================================================= interface
    def resumo(self):
        """Tudo o que a interface mostra, num dicionario so."""
        agora = self._relogio()
        cabines = {}
        for numero, cabine in self.cabines.items():
            cabines[numero] = {
                "conectada": cabine.conectada,
                "estado": cabine.estado_recente(agora),
                "registradores": cabine.registradores,
                "cota_ma": self.cotas.ultimas.get(numero),
                "reconexoes": cabine.cliente.reconexoes if cabine.cliente else 0,
            }
        contorno = None
        if self.contorno is not None:
            leitura = self.contorno.ultima_leitura
            contorno = {
                "temperatura_c": leitura.temperatura_c if leitura else None,
                "pressao_hpa": leitura.pressao_hpa if leitura else None,
                "idade_s": None if self.contorno.ultima_escrita is None
                else time.monotonic() - self.contorno.ultima_escrita,
                "falhas": self.contorno.falhas,
            }
        return {
            "predio": self.predio,
            "capacidade_ma": self.capacidade_ma(),
            "cotas_em_uso_ma": self.cotas.soma_em_uso(),
            "cabines": cabines,
            "contorno": contorno,
            "pendentes": self.registro.lista_pendentes(),
            "recentes": list(self.registro.recentes),
            "metricas": self.registro.metricas(),
            "fila_sem_cabine": self.fila_sem_cabine,
            "eventos": list(self.eventos),
        }
