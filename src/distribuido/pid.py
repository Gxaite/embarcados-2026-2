"""Controlador PID de posicao (Secao 7.1).

Forma discreta por amostra, a mesma do pid.c de referencia da disciplina:

    u[k] = Kp*e[k] + Ki*soma(e) + Kd*(e[k] - e[k-1])

sem dividir nem multiplicar pelo periodo. Com o periodo fixo de 50 ms isso so
muda a escala dos ganhos, e e nessa escala que os valores sugeridos (0,5;
0,05; 40) fazem sentido: com e em milimetros e u em pontos de duty, Kp = 0,5
satura em 100% a 200 mm do destino.

Duas mudancas em relacao a forma de livro, cada uma com motivo:

- a derivada e tomada sobre a MEDIDA, nao sobre o erro. Quando o destino muda
  (nova parada no meio da viagem) o erro salta, e a derivada do erro daria um
  pulso de duty enorme num unico ciclo. A derivada da medida ignora o salto e
  continua freando pela velocidade, que e o que interessa.
- anti-windup por integracao condicional: o termo integral so acumula quando
  a saida nao esta saturada, ou quando o erro puxa para fora da saturacao.
  Saturado pela Cota, o integral cresceria a viagem inteira e a cabine
  passaria do andar na chegada. O integral tambem tem teto proprio.
- separacao do integral: ele so acumula a menos de zona_integral_mm do
  destino, e e zerado fora dela. Medido no simulador: integrando a viagem
  inteira, na desaceleracao (fora da saturacao, com erro de centenas de mm) o
  integral chegava ao teto e a cabine passava 30 mm do andar, qualquer que
  fosse o Kd. O papel dele e vencer o atrito no fim, e e la que ele age.
"""


class PID:
    def __init__(self, kp, ki, kd, limite_integral=30.0, zona_integral_mm=50.0):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.limite_integral = limite_integral
        self.zona_integral_mm = zona_integral_mm
        self.integral = 0.0
        self._medida_anterior = None
        self.ultimos_termos = (0.0, 0.0, 0.0)

    def reinicia(self):
        self.integral = 0.0
        self._medida_anterior = None
        self.ultimos_termos = (0.0, 0.0, 0.0)

    def desloca_medida(self, delta):
        """A reancoragem moveu a medida por delta sem a cabine se mover; sem
        isto a derivada leria o salto como velocidade."""
        if self._medida_anterior is not None:
            self._medida_anterior += delta

    def calcula(self, referencia, medida, limite_saida, integra=True):
        """Devolve o sinal de controle saturado em +-limite_saida."""
        erro = referencia - medida
        derivada = 0.0 if self._medida_anterior is None \
            else -(medida - self._medida_anterior)
        self._medida_anterior = medida

        proporcional = self.kp * erro
        derivativo = self.kd * derivada
        if abs(erro) > self.zona_integral_mm:
            self.integral = 0.0
        elif integra:
            candidato = self.integral + self.ki * erro
            candidato = max(-self.limite_integral,
                            min(self.limite_integral, candidato))
            saida = proporcional + candidato + derivativo
            saturada = abs(saida) > limite_saida
            if not saturada or (saida > 0) != (erro > 0):
                self.integral = candidato
        saida = proporcional + self.integral + derivativo
        self.ultimos_termos = (proporcional, self.integral, derivativo)
        return max(-limite_saida, min(limite_saida, saida))
