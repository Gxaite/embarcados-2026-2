"""Mapa de pinos da Cabine 1 e tabela de direcao do motor.

Numeracao BCM, nunca BOARD. O numero BCM NAO e a posicao no conector, e
confundir os dois e o erro de montagem mais comum.

DUAS PINAGENS, e o motivo de existirem as duas:

O enunciado trocou as colunas das Cabines 1 e 2 (commit "Mudanca de Pinos -
Cabine 1"), mas o dashboard da bancada ainda rotula o Sensor de Andar como
"BCM 11", que e o numero ANTIGO. Enquanto essa divergencia nao for resolvida
pelo professor, da para descobrir qual vale em dois minutos de bancada:

    python3 -m ferramentas.bringup entradas --pinagem nova
    python3 -m ferramentas.bringup entradas --pinagem antiga

A que reagir ao widget e a correta. O padrao e a NOVA, porque e a que o
enunciado manda hoje.
"""

# Cada pinagem: BCM por sinal. Os nomes dos sinais sao os do enunciado.
PINAGENS = {
    # Tabela 1 atualizada - Cabine 1 passou a usar a coluna que era da Cabine 2.
    "nova": {
        "PWM": 13, "DIR1": 22, "DIR2": 23,
        "ENC_A": 20, "ENC_B": 21,
        "CORTINA": 26, "SENSOR_ANDAR": 0,
    },
    # Tabela 1 original, ainda refletida no rotulo do dashboard.
    "antiga": {
        "PWM": 12, "DIR1": 17, "DIR2": 27,
        "ENC_A": 5, "ENC_B": 6,
        "CORTINA": 16, "SENSOR_ANDAR": 11,
    },
}

# BCM -> pino fisico no header de 40 pinos. Serve para conferencia visual.
_FISICO = {
    0: 27, 1: 28, 5: 29, 6: 31, 7: 26, 8: 24, 11: 23, 12: 32, 13: 33,
    16: 36, 17: 11, 18: 12, 19: 35, 20: 38, 21: 40, 22: 15, 23: 16,
    24: 18, 25: 22, 26: 37, 27: 13,
}

SINAIS = ("PWM", "DIR1", "DIR2", "ENC_A", "ENC_B", "CORTINA", "SENSOR_ANDAR")

FUNCAO = {
    "PWM": "saida (PWM 1 kHz)",
    "DIR1": "saida on/off",
    "DIR2": "saida on/off",
    "ENC_A": "entrada (interrupcao)",
    "ENC_B": "entrada (interrupcao)",
    "CORTINA": "entrada on/off",
    "SENSOR_ANDAR": "entrada on/off",
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

# Preenchidos por aplica(), chamado no fim deste modulo.
pinagem_em_uso = None
PWM = DIR1 = DIR2 = ENC_A = ENC_B = CORTINA = SENSOR_ANDAR = None
PINO_FISICO = {}
NOME = {}


def aplica(nome="nova"):
    """Seleciona a pinagem ativa. Chamar ANTES de instanciar qualquer coisa."""
    if nome not in PINAGENS:
        raise ValueError("pinagem desconhecida: %r (use %s)"
                         % (nome, " ou ".join(sorted(PINAGENS))))
    mapa = PINAGENS[nome]
    globais = globals()
    globais["pinagem_em_uso"] = nome
    for sinal in SINAIS:
        globais[sinal] = mapa[sinal]
    globais["PINO_FISICO"] = {mapa[s]: _FISICO[mapa[s]] for s in SINAIS}
    globais["NOME"] = {mapa[s]: s for s in SINAIS}
    return nome


aplica("nova")
