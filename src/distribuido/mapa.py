"""Posicoes calibradas dos andares de uma cabine (Secao 3.3).

Para cada andar guarda as duas bordas da bandeirola, cada uma medida nas duas
varreduras: a inferior e a borda de entrada na subida e a de saida na
descida; a superior, o contrario. A media de cada borda nos dois sentidos
cancela o erro que depende do sentido (latencia de interrupcao, quantizacao),
e a posicao do andar e a media das duas bordas, como o enunciado pede.

As bordas medias ficam guardadas porque sao a referencia da reancoragem: cada
vez que a cabine cruza uma borda, a contagem e conferida contra o valor
calibrado daquela borda.
"""
import json
import os
import time

ANDARES = tuple(range(6))
POCO_MM = 400.0
VAO_NOMINAL_MM = 3000.0
# Um vao medido fora disto nao e um andar: e medicao errada.
VAO_MINIMO_MM = 2500.0
VAO_MAXIMO_MM = 3500.0


class ErroDeCalibracao(ValueError):
    pass


class MapaDeAndares:
    def __init__(self, bordas):
        """bordas: {andar: {"inferior_subindo", "superior_subindo",
        "superior_descendo", "inferior_descendo"}} em contagens do encoder."""
        faltando = [a for a in ANDARES if a not in bordas]
        if faltando:
            raise ErroDeCalibracao("andares sem medicao: %s" % faltando)
        self.bordas = {a: dict(bordas[a]) for a in ANDARES}
        self.inferior = {}
        self.superior = {}
        self.posicao = {}
        for andar in ANDARES:
            b = self.bordas[andar]
            self.inferior[andar] = (b["inferior_subindo"] + b["inferior_descendo"]) / 2.0
            self.superior[andar] = (b["superior_subindo"] + b["superior_descendo"]) / 2.0
            centro_subida = (b["inferior_subindo"] + b["superior_subindo"]) / 2.0
            centro_descida = (b["inferior_descendo"] + b["superior_descendo"]) / 2.0
            self.posicao[andar] = (centro_subida + centro_descida) / 2.0
        self._valida()

    def _valida(self):
        for andar in ANDARES:
            if self.superior[andar] <= self.inferior[andar]:
                raise ErroDeCalibracao("andar %d: borda superior abaixo da "
                                       "inferior" % andar)
        for andar in ANDARES[1:]:
            vao = self.posicao[andar] - self.posicao[andar - 1]
            if not VAO_MINIMO_MM <= vao <= VAO_MAXIMO_MM:
                raise ErroDeCalibracao("vao de %.0f mm entre os andares %d e %d"
                                       % (vao, andar - 1, andar))

    # ------------------------------------------------------------ consultas
    def largura(self, andar):
        return self.superior[andar] - self.inferior[andar]

    @property
    def limite_inferior_mm(self):
        return self.posicao[ANDARES[0]] - POCO_MM

    @property
    def limite_superior_mm(self):
        return self.posicao[ANDARES[-1]] + POCO_MM

    def andar_mais_proximo(self, mm):
        return min(ANDARES, key=lambda a: abs(mm - self.posicao[a]))

    def andar_nivelado(self, mm, tolerancia_mm):
        andar = self.andar_mais_proximo(mm)
        return andar if abs(mm - self.posicao[andar]) <= tolerancia_mm else None

    def proximo_andar_no_sentido(self, mm, sentido, folga_mm):
        """Primeiro andar a frente de mm, a pelo menos folga_mm, no sentido."""
        if sentido > 0:
            candidatos = [a for a in ANDARES if self.posicao[a] >= mm + folga_mm]
            return min(candidatos) if candidatos else ANDARES[-1]
        candidatos = [a for a in ANDARES if self.posicao[a] <= mm - folga_mm]
        return max(candidatos) if candidatos else ANDARES[0]

    def borda_cruzada(self, mm, borda, distancia_maxima_mm):
        """Andar cuja borda ("inferior"/"superior") calibrada esta mais perto
        de mm, ou None se nenhuma estiver a menos de distancia_maxima_mm."""
        valores = self.inferior if borda == "inferior" else self.superior
        andar = min(ANDARES, key=lambda a: abs(mm - valores[a]))
        if abs(mm - valores[andar]) > distancia_maxima_mm:
            return None
        return andar, valores[andar]

    # ---------------------------------------------------------- persistencia
    def salva(self, arquivo, cabine):
        os.makedirs(os.path.dirname(arquivo) or ".", exist_ok=True)
        dados = {
            "cabine": cabine,
            "instante": time.strftime("%Y-%m-%d %H:%M:%S"),
            "posicoes_mm": {str(a): round(self.posicao[a], 1) for a in ANDARES},
            "larguras_mm": {str(a): round(self.largura(a), 1) for a in ANDARES},
            "bordas": {str(a): self.bordas[a] for a in ANDARES},
        }
        temporario = arquivo + ".tmp"
        with open(temporario, "w") as saida:
            json.dump(dados, saida, indent=2)
        os.replace(temporario, arquivo)

    def resumo(self):
        return {str(a): {"posicao_mm": round(self.posicao[a], 1),
                         "largura_mm": round(self.largura(a), 1)}
                for a in ANDARES}
