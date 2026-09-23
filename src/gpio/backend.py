"""Interface de acesso a GPIO usada por todo o resto do programa.

O pacote controle/ nunca fala com a RPi.GPIO diretamente: ele recebe um
BackendGPIO. Existem duas implementacoes:

  - BackendRPi      (gpio/rpi_backend.py) -> placa real, via RPi.GPIO
  - BackendSimulado (gpio/sim_backend.py) -> modelo do elevador em software

E o mesmo codigo de controle nos dois casos, o que permite desenvolver e testar
a logica sem a bancada montada.
"""
from abc import ABC, abstractmethod

# Bordas aceitas em registra_interrupcao()
SUBIDA = "subida"
DESCIDA = "descida"
AMBAS = "ambas"

# Resistores internos
PULL_NENHUM = "nenhum"
PULL_CIMA = "cima"
PULL_BAIXO = "baixo"


class CanalPWM(ABC):
    """Um canal de PWM ja associado a um pino e a uma frequencia."""

    @abstractmethod
    def inicia(self, duty):
        """Liga o canal com o duty cycle dado (0 a 100)."""

    @abstractmethod
    def ajusta(self, duty):
        """Troca o duty cycle sem reiniciar o canal."""

    @abstractmethod
    def para(self):
        """Desliga o canal (duty efetivo 0)."""


class BackendGPIO(ABC):
    """Operacoes elementares de GPIO. Uma implementacao por "mundo"."""

    @abstractmethod
    def configura_saida(self, pino, valor_inicial=0):
        """Declara o pino como saida digital."""

    @abstractmethod
    def configura_entrada(self, pino, pull=PULL_NENHUM):
        """Declara o pino como entrada digital, com resistor interno opcional."""

    @abstractmethod
    def escreve(self, pino, valor):
        """Escreve 0 ou 1 numa saida digital."""

    @abstractmethod
    def le(self, pino):
        """Le o nivel logico de uma entrada (0 ou 1)."""

    @abstractmethod
    def registra_interrupcao(self, pino, borda, callback):
        """Chama callback(pino, valor) a cada borda indicada.

        O callback roda na thread de interrupcao do backend: deve ser curto e
        nao pode bloquear.
        """

    @abstractmethod
    def cria_pwm(self, pino, frequencia_hz):
        """Devolve um CanalPWM para o pino, na frequencia dada."""

    @abstractmethod
    def finaliza(self):
        """Libera os recursos de GPIO. Chamado no encerramento do programa."""
