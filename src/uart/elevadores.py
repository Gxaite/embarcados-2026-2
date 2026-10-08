"""Parte 3 - registradores das cabines e do Controlador do Predio.

Mapas das Secoes 5.2 e 5.3 do enunciado. Cada funcao pedida na Secao 3.4 da
Entrega 2 e um metodo daqui, com o mesmo nome. Os metodos devolvem dicionarios
com os campos ja decodificados, para que o Servidor Central da Entrega Final
nao precise saber em que offset fica cada coisa.
"""
from .modbus import int16_de

ENDERECO_DAS_CABINES = {1: 0x11, 2: 0x12, 3: 0x13}
ENDERECO_DO_PREDIO = 0x20

CAMPOS_DA_CABINE = (
    "andar_atual", "nivelado", "porta_estado", "porta_comando", "corrente_ma",
    "carga_kg", "passageiros", "posicao_mm", "falha",
)
# posicao_mm e o unico registrador com sinal: fica negativo dentro do poco.
CAMPOS_COM_SINAL = {"posicao_mm"}
REGISTRADOR_PORTA_COMANDO = 3

ESTADOS_DA_PORTA = {0: "fechada", 1: "abrindo", 2: "aberta", 3: "fechando",
                    4: "obstruida"}
COMANDOS_DA_PORTA = {"nenhum": 0, "abrir": 1, "fechar": 2}

CAMPOS_DO_PREDIO = (
    "chamadas_na_fila", "chamada_origem", "chamada_destino", "chamada_id",
    "chamada_pop", "ambiente_temp_c_x10", "ambiente_press_hpa",
    "barramento_max_ma", "watchdog_ambiente", "atribuicao_chamada_id",
    "atribuicao_cabine", "cenario_ativo", "cenario_geradas",
    "cenario_atendidas", "espera_media_s_x10", "viagem_media_s_x10",
)
REGISTRADOR_CHAMADAS_NA_FILA = 0
REGISTRADOR_CHAMADA_POP = 4
REGISTRADOR_AMBIENTE_TEMP = 5
REGISTRADOR_ATRIBUICAO_ID = 9

CENARIOS = {0: "nenhum", 1: "up-peak", 2: "down-peak", 3: "interfloor"}


def _decodifica(nomes, valores):
    campos = {}
    for nome, valor in zip(nomes, valores):
        campos[nome] = int16_de(valor) if nome in CAMPOS_COM_SINAL else valor
    return campos


def endereco_da_cabine(cabine):
    try:
        return ENDERECO_DAS_CABINES[int(cabine)]
    except (KeyError, ValueError):
        raise ValueError("cabine invalida: %r (use 1, 2 ou 3)" % (cabine,))


class Elevadores:
    """Operacoes do simulador sobre um ClienteModbus."""

    def __init__(self, cliente):
        self.cliente = cliente

    # ----------------------------------------------------------- cabines
    def le_estado_cabine(self, cabine):
        valores = self.cliente.le_registradores(
            endereco_da_cabine(cabine), 0, len(CAMPOS_DA_CABINE))
        return _decodifica(CAMPOS_DA_CABINE, valores)

    def comanda_porta(self, cabine, comando):
        """comando: 'abrir', 'fechar', 'nenhum' ou o codigo 0..2."""
        codigo = COMANDOS_DA_PORTA.get(comando, comando)
        self.cliente.escreve_registradores(
            endereco_da_cabine(cabine), REGISTRADOR_PORTA_COMANDO, [int(codigo)])

    # ------------------------------------------------------------- predio
    def le_estado_predio(self):
        valores = self.cliente.le_registradores(
            ENDERECO_DO_PREDIO, 0, len(CAMPOS_DO_PREDIO))
        return _decodifica(CAMPOS_DO_PREDIO, valores)

    def le_chamada_da_fila(self):
        """Chamada na cabeca da fila, ou None se a fila estiver vazia.

        Os quatro primeiros registradores vem numa leitura so: ler o tamanho
        da fila e a chamada em transacoes separadas abriria uma janela em que
        a fila muda entre uma e outra.
        """
        valores = self.cliente.le_registradores(
            ENDERECO_DO_PREDIO, REGISTRADOR_CHAMADAS_NA_FILA, 4)
        campos = _decodifica(CAMPOS_DO_PREDIO[:4], valores)
        if campos["chamadas_na_fila"] == 0:
            return None
        return {"na_fila": campos["chamadas_na_fila"],
                "origem": campos["chamada_origem"],
                "destino": campos["chamada_destino"],
                "id": campos["chamada_id"]}

    def remove_chamada_da_fila(self):
        self.cliente.escreve_registradores(
            ENDERECO_DO_PREDIO, REGISTRADOR_CHAMADA_POP, [1])

    def atribui_chamada(self, chamada_id, cabine):
        """Escreve atribuicao_chamada_id e atribuicao_cabine juntos.

        Uma escrita so, nos offsets 9 e 10: em duas, o simulador poderia ver o
        id novo com a cabine da atribuicao anterior.
        """
        endereco_da_cabine(cabine)       # valida antes de ir para a linha
        self.cliente.escreve_registradores(
            ENDERECO_DO_PREDIO, REGISTRADOR_ATRIBUICAO_ID,
            [int(chamada_id), int(cabine)])

    def escreve_condicao_contorno(self, temperatura_c, pressao_hpa):
        """Temperatura em decimos de grau e pressao em hPa, offsets 5 e 6."""
        self.cliente.escreve_registradores(
            ENDERECO_DO_PREDIO, REGISTRADOR_AMBIENTE_TEMP,
            [int(round(temperatura_c * 10)), int(round(pressao_hpa))])
