"""Entradas digitais on/off lidas por interrupcao, com debounce.

Usada pela cortina de luz e pelo Sensor de Andar.

Como o debounce e feito: a cada borda crua reinicia-se um temporizador de
`debounce_ms`. So quando o pino fica quieto por esse tempo o nivel e lido de
novo; se ele mudou em relacao ao ultimo estado estavel, o evento e emitido.
Repique gera varias bordas dentro da janela e produz um unico evento.

Detalhe que importa para o Sensor de Andar: o instante e a captura (a contagem
do encoder) sao os da PRIMEIRA borda crua da janela, nao os do fim do
temporizador. Se registrassemos a contagem depois do atraso de debounce, a
cabine ja teria andado e a medicao do centro da bandeirola sairia enviesada.

Nao ha busy-wait: quem conta o tempo e um threading.Timer.
"""
import threading
import time

from . import backend


class EntradaDigital:
    def __init__(self, backend_gpio, pino, nome="", debounce_ms=20.0,
                 pull=backend.PULL_NENHUM, ao_mudar=None, captura=None):
        """
        ao_mudar: callback(evento) chamado a cada mudanca confirmada.
        captura:  funcao sem argumentos avaliada no instante da borda crua;
                  o resultado vai em evento.captura (usamos a contagem do
                  encoder).
        """
        self._gpio = backend_gpio
        self._pino = pino
        self.nome = nome or "GPIO%d" % pino
        self._debounce_s = debounce_ms / 1000.0
        self._ao_mudar = ao_mudar
        self._captura = captura

        self._gpio.configura_entrada(pino, pull)
        self._estado = self._gpio.le(pino)
        self._timer = None
        self._borda_pendente = None   # (instante, captura) da 1a borda crua
        self._lock = threading.Lock()

        self._gpio.registra_interrupcao(pino, backend.AMBAS, self._na_borda)

    @property
    def estado(self):
        """Ultimo nivel estavel conhecido (0 ou 1)."""
        return self._estado

    def ativa(self):
        return self._estado == 1

    def _na_borda(self, pino, valor):
        instante = time.monotonic()
        captura = self._captura() if self._captura else None
        with self._lock:
            if self._borda_pendente is None:
                self._borda_pendente = (instante, captura)
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self._debounce_s, self._confirma)
            self._timer.daemon = True
            self._timer.start()

    def _confirma(self):
        with self._lock:
            pendente = self._borda_pendente
            self._borda_pendente = None
            self._timer = None
        nivel = self._gpio.le(self._pino)
        if pendente is None or nivel == self._estado:
            return  # repique que voltou ao estado anterior: nao houve mudanca
        self._estado = nivel
        if self._ao_mudar:
            instante, captura = pendente
            self._ao_mudar(EventoEntrada(self.nome, self._pino, nivel,
                                         instante, captura))

    def finaliza(self):
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None


class EventoEntrada:
    """Uma mudanca de nivel ja confirmada pelo debounce."""

    __slots__ = ("nome", "pino", "nivel", "instante", "captura")

    def __init__(self, nome, pino, nivel, instante, captura):
        self.nome = nome
        self.pino = pino
        self.nivel = nivel          # 1 = subiu, 0 = desceu
        self.instante = instante    # time.monotonic() da borda crua
        self.captura = captura      # contagem do encoder naquele instante

    @property
    def subida(self):
        return self.nivel == 1

    def __repr__(self):
        return "EventoEntrada(%s, nivel=%d, captura=%r)" % (
            self.nome, self.nivel, self.captura)
