"""Entradas digitais nos dois modos que o enunciado cobra.

O criterio do Modulo da GPIO pede entradas "por polling e por interrupcao".
Sao estrategias com custos diferentes, e cada uma serve a um sinal deste
trabalho:

- EntradaPolling le o pino quando alguem pergunta. Simples, sem thread, sem
  borda perdida - mas so enxerga o que estiver la no instante da leitura.
  Serve para sinais de nivel, que interessam pelo estado atual.
- EntradaInterrupcao e avisada pela borda, em outra thread. Enxerga transicoes
  rapidas demais para o polling, ao custo de concorrencia e de repique.

Nem toda leitura deve ser em laco: consultar EntradaPolling dentro de um loop
apertado e busy-wait, que o requisito 9 proibe. Ela e feita para ser consultada
dentro de uma malha que ja dorme entre ciclos.
"""
import threading

from . import backend as bk
from . import pinos


class EntradaPolling:
    """Entrada on/off lida por consulta direta ao pino."""

    def __init__(self, backend, pino, pull=bk.SEM_PULL):
        self._backend = backend
        self.pino = pino
        self.nome = pinos.NOME.get(pino, str(pino))
        backend.configura_entrada(pino, pull)

    def le(self):
        return self._backend.le(self.pino)

    @property
    def ativa(self):
        return self.le() == 1


class EntradaInterrupcao:
    """Entrada on/off por interrupcao, com debounce por temporizador.

    O simulador emite repique de proposito em cada borda da cortina. Sem
    tratamento, uma unica obstrucao vira varias.

    O debounce funciona por silencio: cada borda crua reinicia um temporizador,
    e o nivel so e reavaliado quando o pino fica quieto pela janela inteira.

    Detalhe que importa para o Sensor de Andar: a borda crua tambem captura um
    "instantaneo" no momento em que ela acontece, via o callable instantanea.
    Se a contagem do encoder fosse lida no fim do temporizador, a cabine ja
    teria andado durante a janela de debounce e a medicao do centro da
    bandeirola sairia enviesada.
    """

    def __init__(self, backend, pino, ao_evento, debounce_ms=5.0,
                 pull=bk.SEM_PULL, instantanea=None):
        self._backend = backend
        self.pino = pino
        self.nome = pinos.NOME.get(pino, str(pino))
        self._ao_evento = ao_evento
        self._debounce_s = debounce_ms / 1000.0
        self._instantanea = instantanea

        self._trava = threading.Lock()
        self._temporizador = None
        self._instantanea_da_borda = None
        self._bordas_cruas = 0

        backend.configura_entrada(pino, pull)
        self._nivel = backend.le(pino)
        backend.registra_interrupcao(pino, bk.AMBAS, self._na_borda_crua)

    @property
    def nivel(self):
        return self._nivel

    @property
    def bordas_cruas(self):
        """Quantas bordas chegaram antes do debounce. Diagnostico de repique."""
        return self._bordas_cruas

    def _na_borda_crua(self, pino, valor):
        with self._trava:
            self._bordas_cruas += 1
            if self._instantanea is not None:
                self._instantanea_da_borda = self._instantanea()
            if self._temporizador is not None:
                self._temporizador.cancel()
            self._temporizador = threading.Timer(self._debounce_s, self._assenta)
            self._temporizador.daemon = True
            self._temporizador.start()

    def _assenta(self):
        with self._trava:
            nivel = self._backend.le(self.pino)
            if nivel == self._nivel:
                return          # repique que voltou ao mesmo nivel: nao e evento
            self._nivel = nivel
            instantanea = self._instantanea_da_borda

        # Fora da trava: o tratador do nivel de cima pode demorar, e segurar a
        # trava aqui bloquearia as proximas bordas.
        self._ao_evento(nivel, instantanea)

    def finaliza(self):
        with self._trava:
            if self._temporizador is not None:
                self._temporizador.cancel()
                self._temporizador = None
        self._backend.remove_interrupcao(self.pino)
