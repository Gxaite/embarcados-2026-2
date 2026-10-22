"""Backend de GPIO de uma cabine, ligado a fisica do poco simulado."""
from ..gpio import backend as bk
from ..gpio.backend import Backend, CanalPWM


class _CanalPWMDoPoco(CanalPWM):
    def __init__(self, cabine):
        self._cabine = cabine

    def ajusta(self, duty_porcento):
        with self._cabine.trava:
            self._cabine.duty = max(0.0, min(100.0, float(duty_porcento)))

    def finaliza(self):
        self.ajusta(0.0)


class BackendDoPoco(Backend):
    def __init__(self, cabine_fisica):
        self._cabine = cabine_fisica
        self.limpou = False

    def configura_saida(self, pino, valor_inicial=0):
        self.escreve(pino, valor_inicial)

    def configura_entrada(self, pino, pull=bk.SEM_PULL):
        pass

    def escreve(self, pino, valor):
        with self._cabine.trava:
            self._cabine.niveis[pino] = 1 if valor else 0

    def le(self, pino):
        with self._cabine.trava:
            return self._cabine.niveis.get(pino, 0)

    def cria_pwm(self, pino, frequencia_hz):
        return _CanalPWMDoPoco(self._cabine)

    def registra_interrupcao(self, pino, borda, callback):
        if borda == bk.AMBAS:
            filtrado = callback
        else:
            nivel = 1 if borda == bk.BORDA_SUBIDA else 0

            def filtrado(p, valor):
                if valor == nivel:
                    callback(p, valor)
        with self._cabine.trava:
            self._cabine.interrupcoes[pino] = filtrado

    def remove_interrupcao(self, pino):
        with self._cabine.trava:
            self._cabine.interrupcoes.pop(pino, None)

    def limpa(self, preserva=()):
        self.limpou = True
        with self._cabine.trava:
            self._cabine.interrupcoes.clear()
            self._cabine.duty = 0.0
