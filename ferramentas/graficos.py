"""Graficos do README a partir dos CSVs dos experimentos.

    python3 -m ferramentas.graficos                       # docs/experimentos -> docs/imagens
    python3 -m ferramentas.graficos --pid dados/pid1.csv  # um CSV da placa

Precisa da matplotlib, que nao vem na imagem da Raspberry Pi: os CSVs sao
gravados na placa e os graficos gerados na maquina de desenvolvimento.
"""
import argparse
import csv
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPERIMENTOS = os.path.join(RAIZ, "docs", "experimentos")
IMAGENS = os.path.join(RAIZ, "docs", "imagens")
CORES = ("#2a6fdb", "#e07b00", "#1a9e5a", "#c0392b")


def le_csv(arquivo):
    with open(arquivo) as entrada:
        linhas = list(csv.DictReader(entrada))
    colunas = {}
    for linha in linhas:
        for chave, valor in linha.items():
            try:
                valor = float(valor)
            except (TypeError, ValueError):
                pass
            colunas.setdefault(chave, []).append(valor)
    return colunas


def trechos(dados):
    """Separa o CSV da malha em viagens: o tempo salta entre uma e outra."""
    indices, inicio = [], 0
    alvos = dados["alvo_mm"]
    for i in range(1, len(alvos)):
        if alvos[i] != alvos[i - 1]:
            indices.append((inicio, i))
            inicio = i
    indices.append((inicio, len(alvos)))
    return indices


def grafico_pid(arquivos, saida, titulo):
    figura, (eixo_pos, eixo_duty) = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
    for cor, (rotulo, arquivo) in zip(CORES, arquivos):
        dados = le_csv(arquivo)
        inicio, fim = trechos(dados)[-1]
        t0 = dados["t_s"][inicio]
        t = [v - t0 for v in dados["t_s"][inicio:fim]]
        eixo_pos.plot(t, dados["posicao_mm"][inicio:fim], color=cor, label=rotulo)
        eixo_duty.plot(t, dados["duty"][inicio:fim], color=cor, label=rotulo)
        # Na placa cada cabine vai a um andar: o alvo de cada uma, na cor dela.
        eixo_pos.axhline(dados["alvo_mm"][inicio], color=cor, ls="--", lw=1, alpha=0.6)
    eixo_pos.plot([], [], color="gray", ls="--", lw=1, label="alvo")
    eixo_pos.set_ylabel("posicao (mm)")
    eixo_pos.set_title(titulo)
    eixo_pos.legend(loc="lower right")
    eixo_pos.grid(alpha=0.3)
    eixo_duty.set_ylabel("duty com sinal (%)")
    eixo_duty.set_xlabel("tempo desde a partida (s)")
    eixo_duty.grid(alpha=0.3)
    figura.tight_layout()
    figura.savefig(saida, dpi=110)
    plt.close(figura)
    return saida


def grafico_chegada(arquivo, saida, titulo):
    """Zoom nos ultimos 400 mm: rampa, aproximacao e nivelamento."""
    dados = le_csv(arquivo)
    inicio, fim = trechos(dados)[-1]
    alvo = dados["alvo_mm"][inicio]
    t0 = dados["t_s"][inicio]
    t = [v - t0 for v in dados["t_s"][inicio:fim]]
    erro = [p - alvo for p in dados["posicao_mm"][inicio:fim]]
    figura, eixo = plt.subplots(figsize=(10, 4))
    eixo.plot(t, erro, color=CORES[0], label="posicao - alvo")
    eixo.axhspan(-10, 10, color=CORES[2], alpha=0.15, label="tolerancia +-10 mm")
    eixo.set_ylim(-400, 60)
    eixo.set_ylabel("erro (mm)")
    eixo.set_xlabel("tempo desde a partida (s)")
    eixo.set_title(titulo)
    eixo.grid(alpha=0.3)
    eixo.legend(loc="lower right")
    figura.tight_layout()
    figura.savefig(saida, dpi=110)
    plt.close(figura)
    return saida


def grafico_cota(arquivo, saida):
    dados = le_csv(arquivo)
    t = dados["t_s"]
    figura, (eixo_duty, eixo_pos) = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
    eixo_duty.plot(t, [abs(d) for d in dados["duty"]], color=CORES[0], label="|duty| aplicado")
    eixo_duty.plot(t, dados["duty_maximo"], color=CORES[3], ls="--",
                   label="teto da Cota (cota/6000 x 100)")
    eixo_duty.set_ylabel("duty (%)")
    eixo_duty.set_title("Saturacao do PID pela Cota: 6000 -> 3000 -> 1000 mA")
    eixo_duty.legend(loc="upper right")
    eixo_duty.grid(alpha=0.3)
    eixo_pos.plot(t, dados["posicao_mm"], color=CORES[1])
    eixo_pos.set_ylabel("posicao (mm)")
    eixo_pos.set_xlabel("tempo (s)")
    eixo_pos.grid(alpha=0.3)
    figura.tight_layout()
    figura.savefig(saida, dpi=110)
    plt.close(figura)
    return saida


def grafico_potencia(arquivo, saida, janela_s=None):
    dados = le_csv(arquivo)
    t = dados["t_s"]
    if janela_s is not None:
        corte = [i for i, v in enumerate(t) if janela_s[0] <= v <= janela_s[1]]
        dados = {k: [v[i] for i in corte] for k, v in dados.items()}
        t = dados["t_s"]
    figura, (eixo_cota, eixo_corrente) = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
    eixo_cota.plot(t, dados["capacidade_ma"], color="black", lw=2, label="barramento_max_ma")
    eixo_cota.plot(t, dados["cotas_em_uso_ma"], color="gray", ls="--",
                   label="soma das Cotas em uso")
    for cor, n in zip(CORES, (1, 2, 3)):
        eixo_cota.step(t, dados["cota%d_ma" % n], color=cor, where="post",
                       label="Cota da cabine %d" % n)
        corrente = [c if c != "" else None for c in dados["corrente%d_ma" % n]]
        eixo_corrente.plot(t, corrente, color=cor, label="corrente da cabine %d" % n)
    soma = [sum(dados["corrente%d_ma" % n][i] or 0 for n in (1, 2, 3)
                if dados["corrente%d_ma" % n][i] != "")
            for i in range(len(t))]
    eixo_corrente.plot(t, soma, color="black", lw=1, ls=":", label="soma das correntes")
    eixo_cota.set_ylabel("mA")
    eixo_cota.set_title("Barramento de Potencia: Cotas concedidas"
                        + ("" if janela_s is None else " (%.0f a %.0f s)" % janela_s))
    eixo_cota.legend(loc="lower right", fontsize=8, ncol=2)
    eixo_cota.grid(alpha=0.3)
    eixo_corrente.set_ylabel("mA")
    eixo_corrente.set_xlabel("tempo (s)")
    eixo_corrente.set_title("Corrente medida (registrador corrente_ma)")
    eixo_corrente.legend(loc="upper right", fontsize=8, ncol=2)
    eixo_corrente.grid(alpha=0.3)
    figura.tight_layout()
    figura.savefig(saida, dpi=110)
    plt.close(figura)
    return saida


def main(argv=None):
    parser = argparse.ArgumentParser(description="Graficos do README")
    parser.add_argument("--pid", nargs="+", metavar="CSV",
                        help="CSVs de --registra-pid (ex.: gravados na placa)")
    parser.add_argument("--potencia", metavar="CSV", help="CSV de --registra-potencia")
    parser.add_argument("--janela", nargs=2, type=float, metavar=("INICIO", "FIM"),
                        help="trecho do CSV de potencia, em segundos")
    parser.add_argument("--saida", default=IMAGENS)
    args = parser.parse_args(argv)
    os.makedirs(args.saida, exist_ok=True)
    feitos = []
    if args.pid:
        feitos.append(grafico_pid([(os.path.basename(a), a) for a in args.pid],
                                  os.path.join(args.saida, "pid_placa.png"),
                                  "Viagens gravadas na placa"))
    if args.potencia:
        feitos.append(grafico_potencia(args.potencia,
                                       os.path.join(args.saida, "potencia_placa.png"),
                                       janela_s=tuple(args.janela) if args.janela else None))
    if not args.pid and not args.potencia:
        pid = [("Kd = %s" % kd, os.path.join(EXPERIMENTOS, "pid_kd%s.csv" % kd))
               for kd in ("40", "15", "5")]
        if all(os.path.exists(a) for _, a in pid):
            feitos.append(grafico_pid(pid, os.path.join(args.saida, "pid_sintonia.png"),
                                      "Sintonia: viagem de 3 andares, Kp = 0,5 e Ki = 0,05, "
                                      "Cota de 4000 mA"))
            feitos.append(grafico_chegada(pid[1][1],
                                          os.path.join(args.saida, "pid_chegada.png"),
                                          "Chegada com Kd = 15 (escolhido): aproximacao e nivelamento"))
        cota = os.path.join(EXPERIMENTOS, "cota.csv")
        if os.path.exists(cota):
            feitos.append(grafico_cota(cota, os.path.join(args.saida, "pid_cota.png")))
        potencia = os.path.join(EXPERIMENTOS, "potencia.csv")
        if os.path.exists(potencia):
            # Dois minutos no meio do primeiro cenario: os 20 minutos inteiros
            # viram um borrao.
            feitos.append(grafico_potencia(potencia,
                                           os.path.join(args.saida, "potencia.png"),
                                           janela_s=(200.0, 320.0)))
    for arquivo in feitos:
        print(os.path.relpath(arquivo, RAIZ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
