"""Mapa de pinos da Cabine 1 (Tabela 1 do enunciado da Entrega 1).

Numeracao BCM, ou seja o numero "GPIOxx" e nao a posicao fisica no header.
Se a bancada mudar, este e o unico arquivo a alterar.
"""

# --- Motor de tracao ---
PWM = 12   # saida PWM, potencia do motor (1 kHz)
DIR1 = 17  # saida on/off, direcao 1
DIR2 = 27  # saida on/off, direcao 2

# --- Encoder em quadratura (entrada por interrupcao nos dois canais) ---
ENC_A = 5
ENC_B = 6

# --- Entradas on/off ---
CORTINA = 16       # cortina de luz da porta: alta enquanto obstruida
SENSOR_ANDAR = 11  # bandeirola: alta enquanto a cabine esta dentro dela

# Posicao fisica de cada GPIO no header de 40 pinos da Raspberry Pi.
# Usada pelas ferramentas de bring-up e pelo docs/BANCADA.md - o numero BCM nao
# tem relacao nenhuma com a posicao no conector, e trocar os dois e o erro de
# montagem mais comum.
PINO_FISICO = {
    2: 3, 3: 5, 4: 7, 14: 8, 15: 10, 17: 11, 18: 12, 27: 13, 22: 15, 23: 16,
    24: 18, 10: 19, 9: 21, 25: 22, 11: 23, 8: 24, 7: 26, 0: 27, 1: 28, 5: 29,
    6: 31, 12: 32, 13: 33, 19: 35, 16: 36, 26: 37, 20: 38, 21: 40,
}

# Sinais da Cabine 1 em ordem de leitura, para relatorios e diagnostico.
SINAIS_CABINE_1 = [
    ("PWM", PWM, "saida (PWM 1 kHz)"),
    ("DIR1", DIR1, "saida on/off"),
    ("DIR2", DIR2, "saida on/off"),
    ("ENC_A", ENC_A, "entrada (interrupcao)"),
    ("ENC_B", ENC_B, "entrada (interrupcao)"),
    ("CORTINA", CORTINA, "entrada on/off"),
    ("SENSOR_ANDAR", SENSOR_ANDAR, "entrada on/off"),
]

# Pinagem das outras cabines, para a Entrega Final (Tabela 1 do README geral).
CABINE_2 = {"PWM": 13, "DIR1": 22, "DIR2": 23, "ENC_A": 20, "ENC_B": 21,
            "CORTINA": 26, "SENSOR_ANDAR": 0}
CABINE_3 = {"PWM": 18, "DIR1": 24, "DIR2": 25, "ENC_A": 7, "ENC_B": 8,
            "CORTINA": 19, "SENSOR_ANDAR": 1}
