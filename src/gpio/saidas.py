"""Saidas digitais: on/off e PWM."""
from . import pinos


class SaidaDigital:
    """Saida on/off. Usada em DIR1 e DIR2 (Tabela 2 do enunciado)."""

    def __init__(self, backend, pino, valor_inicial=0):
        self._backend = backend
        self.pino = pino
        self.nome = pinos.NOME.get(pino, str(pino))
        self._valor = 1 if valor_inicial else 0
        backend.configura_saida(pino, self._valor)

    @property
    def valor(self):
        return self._valor

    def escreve(self, valor):
        self._valor = 1 if valor else 0
        self._backend.escreve(self.pino, self._valor)


class SaidaPWM:
    """Saida PWM a 1 kHz, duty de 0 a 100% (requisito 4).

    O duty e saturado na faixa valida em vez de levantar excecao: o chamador e
    uma malha de controle, e um alvo fora de faixa deve virar o extremo mais
    proximo, nao derrubar o controle da cabine.
    """

    def __init__(self, backend, pino, frequencia_hz=pinos.FREQUENCIA_PWM_HZ):
        self._canal = backend.cria_pwm(pino, frequencia_hz)
        self.pino = pino
        self.frequencia_hz = frequencia_hz
        self._duty = 0.0
        self._canal.ajusta(0.0)

    @property
    def duty(self):
        return self._duty

    def ajusta(self, duty_porcento):
        self._duty = max(0.0, min(100.0, float(duty_porcento)))
        self._canal.ajusta(self._duty)
        return self._duty

    def finaliza(self):
        self._duty = 0.0
        self._canal.ajusta(0.0)
        self._canal.finaliza()
