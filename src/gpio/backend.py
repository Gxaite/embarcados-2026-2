"""Interface de acesso a GPIO.

Todo o resto do projeto conversa com esta interface, nunca com a RPi.GPIO
diretamente. Isso permite trocar a placa real por um modelo em software sem
tocar em uma linha do codigo de controle - e e o que torna possivel desenvolver
e testar longe da bancada, que e um recurso escasso e compartilhado.
"""
from abc import ABC, abstractmethod

# Resistores internos
SEM_PULL = "sem_pull"
PULL_UP = "pull_up"
PULL_DOWN = "pull_down"

# Bordas de interrupcao
BORDA_SUBIDA = "subida"
BORDA_DESCIDA = "descida"
AMBAS = "ambas"


class CanalPWM(ABC):
    """Uma saida PWM ja iniciada em um pino."""

    @abstractmethod
    def ajusta(self, duty_porcento):
        """Define o duty cycle, saturado na faixa 0..100."""

    @abstractmethod
    def finaliza(self):
        """Para o PWM e libera o canal."""


class Backend(ABC):
    """Acesso a GPIO da placa."""

    @abstractmethod
    def configura_saida(self, pino, valor_inicial=0):
        """Poe o pino em modo saida com um nivel inicial conhecido."""

    @abstractmethod
    def configura_entrada(self, pino, pull=SEM_PULL):
        """Poe o pino em modo entrada, com ou sem resistor interno."""

    @abstractmethod
    def escreve(self, pino, valor):
        """Escreve 0 ou 1 em um pino de saida."""

    @abstractmethod
    def le(self, pino):
        """Le o nivel logico de um pino. Retorna 0 ou 1."""

    @abstractmethod
    def cria_pwm(self, pino, frequencia_hz):
        """Inicia PWM no pino e devolve o CanalPWM correspondente."""

    @abstractmethod
    def registra_interrupcao(self, pino, borda, callback):
        """Chama callback(pino, valor) a cada borda, em outra thread.

        O valor vem lido no momento do disparo: a RPi.GPIO so entrega o numero
        do pino, e quem trata precisa saber para que nivel ele foi.
        """

    @abstractmethod
    def remove_interrupcao(self, pino):
        """Cancela a interrupcao registrada no pino."""

    @abstractmethod
    def limpa(self):
        """Libera todos os recursos de GPIO.

        Obrigatorio ao encerrar: as placas do laboratorio sao compartilhadas e
        um pino deixado configurado atrapalha o proximo da fila.
        """
