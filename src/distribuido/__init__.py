"""Servidor Distribuido: o processo de uma cabine (Secao 2.2 do enunciado).

  pid.py          controlador PID discreto com anti-windup
  cota.py         Cota de Potencia vigente e o limite de duty que ela da
  bandeirola.py   Sensor de Andar por interrupcao, com a contagem de cada borda
  mapa.py         posicoes calibradas dos 6 andares e das bordas das bandeirolas
  calibracao.py   varredura de subida e de descida que levanta o mapa
  malha.py        malha de posicao a 50 ms: PID, rampa, nivelamento, fim de curso
  porta.py        ciclo da porta, pedido ao central, inibido pela cortina
  itinerario.py   chamadas atribuidas a cabine e a ordem das paradas
  cabine.py       o Servidor Distribuido: junta tudo e fala TCP com o central
  __main__.py     ponto de entrada: python3 -m src.distribuido --cabine N

So este processo toca as GPIOs da sua cabine. Tudo o que e MODBUS (porta,
andar_atual) e pedido ao Servidor Central, o unico dono da UART.
"""
