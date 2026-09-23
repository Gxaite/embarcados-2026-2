"""Mapa de pinos da Cabine 1 e tabela de direcao do motor.

Numeracao BCM, nunca BOARD. O numero BCM NAO e a posicao no conector: DIR1 e
o GPIO 17, que fica no pino fisico 11; SENSOR_ANDAR e o GPIO 11, que fica no
pino fisico 23. Os dois trocam exatamente um pelo outro, e e o erro de
montagem mais comum. PINO_FISICO existe so para conferencia visual na bancada.
"""

PWM = 12
DIR1 = 17
DIR2 = 27
ENC_A = 5
ENC_B = 6
CORTINA = 16
SENSOR_ANDAR = 11

PINO_FISICO = {
    PWM: 32,
    DIR1: 11,
    DIR2: 13,
    ENC_A: 29,
    ENC_B: 31,
    CORTINA: 36,
    SENSOR_ANDAR: 23,
}

NOME = {
    PWM: "PWM",
    DIR1: "DIR1",
    DIR2: "DIR2",
    ENC_A: "ENC_A",
    ENC_B: "ENC_B",
    CORTINA: "CORTINA",
    SENSOR_ANDAR: "SENSOR_ANDAR",
}

# Tabela 2 do enunciado: (DIR1, DIR2) para cada acao do motor.
LIVRE = "livre"
SUBIR = "subir"
DESCER = "descer"
FREIO = "freio"

DIRECOES = {
    LIVRE: (0, 0),
    SUBIR: (1, 0),
    DESCER: (0, 1),
    FREIO: (1, 1),
}

FREQUENCIA_PWM_HZ = 1000
