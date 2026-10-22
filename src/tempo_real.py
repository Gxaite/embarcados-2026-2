"""Periodo de controle no Linux: tempo absoluto, prioridade e memoria travada.

As tecnicas sao as do video de motor de passo da disciplina, aplicadas a
malha de 50 ms da cabine:

- clock_nanosleep com CLOCK_MONOTONIC e TIMER_ABSTIME: o laco dorme ate o
  instante do proximo ciclo, nao "50 ms a partir de agora". Com tempo
  relativo, o tempo de execucao de cada ciclo se soma ao periodo e o erro
  acumula; com tempo absoluto o periodo medio e exato e so sobra o jitter;
- prioridade de tempo real (SCHED_FIFO) para a thread da malha, para que uma
  sessao SSH ou outro processo da placa nao a atrase. Sem permissao (usuario
  comum, placa compartilhada), cai para nice e, sem isso, segue avisando;
- mlockall: as paginas do processo nao vao para o swap, e uma falta de pagina
  nao para a malha no meio de um ciclo;
- ciclo perdido nao e compensado: se a thread acordar atrasada mais de um
  periodo, os ciclos perdidos sao pulados em vez de executados em rajada. Uma
  rajada mandaria varios comandos ao motor de uma vez, que ele nao acompanha.
"""
import ctypes
import ctypes.util
import errno
import os
import resource
import threading
import time

CLOCK_MONOTONIC = 1
TIMER_ABSTIME = 1
MCL_CURRENT = 1
MCL_FUTURE = 2
PRIORIDADE_DA_MALHA = 50
MEMORIA_TRAVADA_MINIMA = 256 * 1024 * 1024


class _Timespec(ctypes.Structure):
    _fields_ = [("tv_sec", ctypes.c_long), ("tv_nsec", ctypes.c_long)]


def _libc():
    try:
        return ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6", use_errno=True)
    except OSError:
        return None


_LIBC = _libc()


def trava_memoria():
    """mlockall(MCL_CURRENT | MCL_FUTURE). Devolve o texto do resultado."""
    if _LIBC is None:
        return "mlockall indisponivel (sem libc)"
    # Com MCL_FUTURE, toda alocacao futura tambem fica travada: se o limite
    # de memoria travada for pequeno (o padrao do usuario comum e de poucos
    # MB), o Python passa a falhar ao alocar e a cabine cai. Sem folga, nao
    # trava.
    limite, _ = resource.getrlimit(resource.RLIMIT_MEMLOCK)
    if limite != resource.RLIM_INFINITY and limite < MEMORIA_TRAVADA_MINIMA:
        return ("mlockall nao usado: limite de memoria travada de %d kB "
                "(rode com sudo, ou ulimit -l unlimited)" % (limite // 1024))
    if _LIBC.mlockall(MCL_CURRENT | MCL_FUTURE) == 0:
        return "memoria travada (mlockall): sem swap para este processo"
    return "mlockall negado (%s): o processo pode ir para o swap" % os.strerror(
        ctypes.get_errno())


def eleva_prioridade(prioridade=PRIORIDADE_DA_MALHA):
    """Na thread que chama: SCHED_FIFO, ou nice -10, ou nada."""
    try:
        os.sched_setscheduler(0, os.SCHED_FIFO, os.sched_param(prioridade))
        return "malha em SCHED_FIFO, prioridade %d" % prioridade
    except (AttributeError, PermissionError, OSError):
        pass
    try:
        os.nice(-10)
        return "SCHED_FIFO negado; malha com nice -10"
    except (PermissionError, OSError):
        return "sem permissao para SCHED_FIFO nem nice (rode com sudo para tempo real)"


def _dorme_ate(instante):
    """Dorme ate `instante` no relogio de time.monotonic() (CLOCK_MONOTONIC)."""
    if _LIBC is not None and hasattr(_LIBC, "clock_nanosleep"):
        alvo = _Timespec(int(instante), int((instante % 1.0) * 1e9))
        # EINTR (sinal): volta a dormir ate o mesmo instante. Outro erro nao
        # deveria acontecer; se acontecer, cai para o sleep relativo.
        resultado = errno.EINTR
        while resultado == errno.EINTR:
            resultado = _LIBC.clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME,
                                              ctypes.byref(alvo), None)
        if resultado == 0:
            return
    restante = instante - time.monotonic()
    if restante > 0:
        time.sleep(restante)


class LacoPeriodico:
    """Chama funcao() a cada periodo_s, em tempo absoluto, ate encerrar."""

    def __init__(self, periodo_s, encerrar):
        self.periodo_s = periodo_s
        self._encerrar = encerrar
        self.ciclos = 0
        self.ciclos_perdidos = 0
        self.atraso_maximo_s = 0.0
        self._soma_dos_atrasos = 0.0
        self._trava = threading.Lock()

    @property
    def atraso_medio_s(self):
        return self._soma_dos_atrasos / self.ciclos if self.ciclos else 0.0

    def zera_estatistica(self):
        with self._trava:
            self.atraso_maximo_s = 0.0

    def roda(self, funcao):
        proximo = time.monotonic() + self.periodo_s
        while not self._encerrar.is_set():
            _dorme_ate(proximo)
            if self._encerrar.is_set():
                return
            atraso = time.monotonic() - proximo
            with self._trava:
                self.ciclos += 1
                self._soma_dos_atrasos += atraso
                self.atraso_maximo_s = max(self.atraso_maximo_s, atraso)
            funcao()
            proximo += self.periodo_s
            agora = time.monotonic()
            if agora > proximo:
                perdidos = int((agora - proximo) / self.periodo_s) + 1
                self.ciclos_perdidos += perdidos
                proximo += perdidos * self.periodo_s
