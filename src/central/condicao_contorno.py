"""Condicao de Contorno: BMP280 por I2C -> registradores 5 e 6 do predio.

O simulador deriva a capacidade do barramento da temperatura escrita aqui e
mantem um watchdog de 30 s sobre ela. Sem escrita nesse prazo, o barramento
cai para 3000 mA e as tres cabines andam na velocidade minima - por isso o
enunciado diz que sem a cadeia I2C -> MODBUS o predio nao anda.

O periodo de 4 s fica abaixo do maximo de 5 s pedido, e deixa o watchdog
tolerar varias escritas perdidas seguidas antes de expirar.

A thread dorme em Event.wait() entre ciclos; para() acorda e encerra na hora.
"""
import threading
import time

PERIODO_PADRAO_S = 4.0
PERIODO_MAXIMO_S = 5.0


class ServicoCondicaoContorno:
    def __init__(self, sensor, elevadores, periodo_s=PERIODO_PADRAO_S, eco=print):
        if not 0 < periodo_s <= PERIODO_MAXIMO_S:
            raise ValueError("periodo de %.1f s; o enunciado exige no maximo %.0f s"
                             % (periodo_s, PERIODO_MAXIMO_S))
        self._sensor = sensor
        self._elevadores = elevadores
        self.periodo_s = periodo_s
        self._eco = eco or (lambda _texto: None)
        self._parar = threading.Event()
        self._thread = None
        self.ultima_leitura = None
        self.ultima_escrita = None       # time.monotonic() da ultima escrita
        self.ultimo_erro = None
        self.escritas = 0
        self.falhas = 0
        self.verboso = False

    @property
    def ativo(self):
        return self._thread is not None and self._thread.is_alive()

    def executa_uma_vez(self):
        """Le o sensor e escreve no simulador. Devolve a leitura."""
        leitura = self._sensor.le()
        self.ultima_leitura = leitura
        self._elevadores.escreve_condicao_contorno(
            leitura.temperatura_c, leitura.pressao_hpa)
        self.ultima_escrita = time.monotonic()
        self.escritas += 1
        return leitura

    def inicia(self):
        if self.ativo:
            return
        self._parar.clear()
        self._thread = threading.Thread(target=self._laco, daemon=True,
                                        name="condicao-contorno")
        self._thread.start()

    def para(self):
        self._parar.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _laco(self):
        # Escreve ja na partida, sem esperar o primeiro periodo: se o watchdog
        # estiver expirado, cada segundo a mais e um segundo de barramento no
        # piso.
        while not self._parar.is_set():
            self._ciclo()
            self._parar.wait(self.periodo_s)

    def _ciclo(self):
        try:
            leitura = self.executa_uma_vez()
        except Exception as erro:
            # Qualquer excecao, nao so ErroComunicacao e OSError: se a thread
            # morrer, o watchdog expira 30 s depois sem ninguem perceber.
            self.falhas += 1
            mensagem = "%s: %s" % (type(erro).__name__, erro)
            # Imprime so quando o erro muda, para nao inundar o terminal a
            # cada 4 s com a mesma falha.
            if mensagem != self.ultimo_erro:
                self._eco("[CONTORNO] falha: %s" % mensagem)
            self.ultimo_erro = mensagem
            return
        if self.ultimo_erro is not None:
            self._eco("[CONTORNO] recuperado apos %d falha(s)" % self.falhas)
            self.ultimo_erro = None
        if self.verboso:
            self._eco("[CONTORNO] %.2f C, %.2f hPa escritos no predio"
                      % (leitura.temperatura_c, leitura.pressao_hpa))
