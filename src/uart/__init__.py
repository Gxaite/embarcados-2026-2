"""Modulo UART da Entrega 2.

Tres protocolos dividem a mesma porta serial com a ESP32:

  simplificado.py     Parte 1, sem endereco e sem CRC
  modbus_didatico.py  Parte 2, wrapper MODBUS sobre os comandos da Parte 1
  modbus.py           Parte 3, funcoes 0x03 e 0x10 sobre o simulador
  elevadores.py       Parte 3, mapa de registradores das cabines e do predio

Nada aqui imprime por conta propria a nao ser pelo `eco` recebido, e nada
importa a CLI: o Servidor Central e os Servidores Distribuidos da Entrega
Final importam estes modulos diretamente (requisito 7 da Secao 4).
"""
