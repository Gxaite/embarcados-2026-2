"""Interface de terminal do Servidor Central (requisito 6.2.6).

Painel em tela cheia (curses), redesenhado a cada 250 ms, com uma linha de
comando embaixo. A espera por tecla e o proprio timeout do getch: o processo
dorme entre um quadro e outro, sem busy-wait.

O painel mostra: estado das tres cabines (andar, sentido, porta, corrente e
Cota vigente), capacidade do barramento e watchdog, chamadas pendentes e
atribuidas, tempos medios de espera e de viagem e os ultimos eventos.

Sem terminal capaz (ou com --sem-tela), o mesmo painel sai em texto pelo
comando `status`, e os eventos vao direto para a saida.
"""
import time

from ..uart.elevadores import CENARIOS, ESTADOS_DA_PORTA

INTERVALO_DE_QUADRO_MS = 250

AJUDA = ("vai <cabine> <andar>  |  corta-cota <cabine> [s]  |  status  |  "
         "ajuda  |  sair")


def _ou(valor, formato="%s", vazio="-"):
    return vazio if valor is None else formato % valor


def linhas_do_painel(resumo, largura=110):
    """Painel como lista de (texto, estilo). Estilos: titulo, ok, alerta,
    erro, fraco, normal."""
    linhas = []
    predio = resumo["predio"] or {}
    capacidade = resumo["capacidade_ma"]
    watchdog = predio.get("watchdog_ambiente")
    contorno = resumo["contorno"] or {}

    linhas.append(("FSE 2026/2 - Servidor Central - Despacho por Destino".ljust(largura - 8)
                   + time.strftime("%H:%M:%S"), "titulo"))
    texto_contorno = "BMP280 indisponivel"
    if contorno.get("temperatura_c") is not None:
        texto_contorno = "BMP280 %.1f C  %.0f hPa  (escrito ha %s)" % (
            contorno["temperatura_c"], contorno["pressao_hpa"],
            _ou(contorno.get("idade_s"), "%.0f s"))
    estilo = "erro" if watchdog == 1 or capacidade is None else "ok"
    linhas.append(("Barramento %s   watchdog %s   cotas em uso %d mA   %s" % (
        _ou(capacidade, "%d mA", "desconhecido"),
        {0: "OK", 1: "EXPIRADO (piso 3000 mA)"}.get(watchdog, "?"),
        resumo["cotas_em_uso_ma"], texto_contorno), estilo))

    metricas = resumo["metricas"]
    linhas.append(("Cenario %s   geradas %s   atendidas %s   espera media %s   "
                   "viagem media %s   (simulador)" % (
                       CENARIOS.get(predio.get("cenario_ativo"), "-"),
                       _ou(predio.get("cenario_geradas")),
                       _ou(predio.get("cenario_atendidas")),
                       _ou(None if predio.get("espera_media_s_x10") is None
                           else predio["espera_media_s_x10"] / 10.0, "%.1f s"),
                       _ou(None if predio.get("viagem_media_s_x10") is None
                           else predio["viagem_media_s_x10"] / 10.0, "%.1f s")),
                   "normal"))
    maior = metricas["maior_espera_atual_s"]
    linhas.append(("Central: %d concluidas   espera media %s   viagem media %s   "
                   "maior espera em curso %.0f s" % (
                       metricas["concluidas"], _ou(metricas["espera_media_s"], "%.1f s"),
                       _ou(metricas["viagem_media_s"], "%.1f s"), maior),
                   "erro" if maior > 90 else ("alerta" if maior > 60 else "normal")))
    linhas.append(("-" * largura, "fraco"))
    linhas.append(("Cab  Conexao   Modo                Andar  Posicao    Sentido   "
                   "Porta       Corrente   Cota      Duty   Paradas", "titulo"))
    for numero, cabine in sorted(resumo["cabines"].items()):
        estado = cabine["estado"] or {}
        registradores = cabine["registradores"] or {}
        if not cabine["conectada"]:
            linhas.append((" %d   OFFLINE   (reconexoes: %d)" % (numero, cabine["reconexoes"]),
                           "erro"))
            continue
        modo = estado.get("modo", "?")
        if estado.get("modo") == "calibrando":
            modo = "calib. %s" % (estado.get("calibracao") or "")
        andar = estado.get("andar")
        andar_texto = "-" if andar is None else "%d%s" % (
            andar, " =" if estado.get("nivelado") else "  ")
        porta = ESTADOS_DA_PORTA.get(registradores.get("porta_estado"),
                                     estado.get("porta", "?"))
        if estado.get("cortina"):
            porta += " (cortina)"
        sentido = {"subindo": "^ subindo", "descendo": "v descendo"}.get(
            estado.get("sentido"), "  parado")
        texto = " %d   %-8s  %-18s  %-5s  %7s mm %-10s %-11s %7s mA %6s mA  %5s  %s" % (
            numero, "ok", modo[:18], andar_texto,
            _ou(estado.get("posicao_mm"), "%.0f"), sentido, porta[:11],
            _ou(registradores.get("corrente_ma")),
            _ou(estado.get("cota_ma") if estado.get("cota_valida") else None, "%.0f",
                "VENCIDA"),
            _ou(estado.get("duty"), "%.0f%%"),
            " ".join(str(a) for a in estado.get("paradas", [])) or "-")
        estilo = {"operando": "ok", "degradado": "erro"}.get(estado.get("modo"), "alerta")
        if estado.get("atraso_maximo_ms") is not None:
            texto += "  malha +%.0fms" % estado["atraso_maximo_ms"]
            if estado.get("ciclos_perdidos"):
                texto += " (%d perdidos)" % estado["ciclos_perdidos"]
        if estado.get("falha"):
            texto += "  FALHA: %s" % estado["falha"][:40]
            estilo = "erro"
        linhas.append((texto[:largura], estilo))
    linhas.append(("-" * largura, "fraco"))
    pendentes = resumo["pendentes"]
    agora = time.time()
    titulo = "Chamadas pendentes: %d" % len(pendentes)
    if resumo["fila_sem_cabine"]:
        titulo += "   (%d na fila do simulador sem cabine disponivel)" % \
            resumo["fila_sem_cabine"]
    linhas.append((titulo, "titulo"))
    itens = ["#%d %d->%d C%d %s %.0fs" % (
        c.id, c.origem, c.destino, c.cabine,
        "embarcada" if c.embarque else "espera", agora - (c.embarque or c.registro))
        for c in pendentes]
    linha = ""
    for item in itens:
        if len(linha) + len(item) + 3 > largura:
            linhas.append((linha, "normal"))
            linha = ""
        linha += ("   " if linha else "") + item
    if linha:
        linhas.append((linha, "normal"))
    return linhas


class InterfaceDeTela:
    """Painel curses. executa_comando(linha) devolve texto de resposta, ou
    None para sair."""

    def __init__(self, servidor, executa_comando):
        self._servidor = servidor
        self._executa = executa_comando
        self._resposta = AJUDA

    def roda(self):
        import curses
        curses.wrapper(self._laco)

    def _laco(self, tela):
        import curses
        curses.curs_set(1)
        tela.timeout(INTERVALO_DE_QUADRO_MS)
        cores = {}
        if curses.has_colors():
            curses.use_default_colors()
            for indice, (nome, cor) in enumerate((
                    ("titulo", curses.COLOR_CYAN), ("ok", curses.COLOR_GREEN),
                    ("alerta", curses.COLOR_YELLOW), ("erro", curses.COLOR_RED),
                    ("fraco", curses.COLOR_BLUE)), start=1):
                curses.init_pair(indice, cor, -1)
                cores[nome] = curses.color_pair(indice)
        cores["titulo"] = cores.get("titulo", 0) | curses.A_BOLD
        comando = ""
        while True:
            self._desenha(tela, cores, comando)
            try:
                tecla = tela.get_wch()
            except curses.error:        # timeout do getch: hora do proximo quadro
                continue
            if tecla in ("\n", "\r", curses.KEY_ENTER):
                resposta = self._executa(comando)
                if resposta is None:
                    return
                self._resposta, comando = resposta, ""
            elif tecla in (curses.KEY_BACKSPACE, "\b", "\x7f"):
                comando = comando[:-1]
            elif tecla == "\x1b":
                comando = ""
            elif isinstance(tecla, str) and tecla.isprintable():
                comando += tecla

    def _desenha(self, tela, cores, comando):
        altura, largura = tela.getmaxyx()
        tela.erase()
        resumo = self._servidor.resumo()
        linhas = linhas_do_painel(resumo, max(40, largura - 1))
        espaco_de_eventos = max(0, altura - len(linhas) - 4)
        eventos = resumo["eventos"][-espaco_de_eventos:] if espaco_de_eventos else []
        linhas.append(("Eventos", "titulo"))
        for evento in eventos:
            estilo = "erro" if ("ERRO" in evento or "DEGRADADO" in evento
                                or "FALHA" in evento) else "fraco"
            linhas.append((evento, estilo))
        for y, (texto, estilo) in enumerate(linhas[:altura - 2]):
            self._escreve(tela, y, texto[:largura - 1], cores.get(estilo, 0))
        self._escreve(tela, altura - 2, self._resposta[:largura - 1], cores.get("alerta", 0))
        self._escreve(tela, altura - 1, ("> " + comando)[:largura - 1], 0)
        tela.refresh()

    @staticmethod
    def _escreve(tela, y, texto, atributo):
        try:
            tela.addstr(y, 0, texto, atributo)
        except Exception:
            pass                    # ultima coluna da ultima linha: ignorado


def painel_em_texto(servidor):
    resumo = servidor.resumo()
    return "\n".join(texto for texto, _ in linhas_do_painel(resumo))
