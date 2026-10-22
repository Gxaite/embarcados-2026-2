"""Simulador do edificio da Entrega Final, para rodar sem a placa.

  poco.py     fisica de uma cabine: motor, encoder, bandeirolas, porta e cortina
  predio.py   as tres cabines e o Controlador do Predio (0x20) sobre a mesma
              ESP32 simulada da Entrega 2: fila, atribuicao, cenarios e metricas
  backend.py  Backend de GPIO de uma cabine ligado a fisica do poco

Como o da Entrega 1, ele serve para validar logica, nao para sintonia: o
atrito, a inercia e a latencia de interrupcao da bancada so se medem nela.
"""
