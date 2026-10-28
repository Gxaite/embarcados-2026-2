"""Teste de aceitacao da Entrega Final, de ponta a ponta.

    python3 -m ferramentas.teste_placa                 # na Raspberry Pi, dentro do tmux
    python3 -m ferramentas.teste_placa --pula despacho reinicio
    python3 -m ferramentas.teste_placa --simulado      # sem placa, contra o predio simulado

Sobe as tres cabines como processos separados (python3 -m src.distribuido) e
o Servidor Central dentro deste processo, percorre o roteiro da secao 10 do
docs/BANCADA.md e imprime um relatorio por item da avaliacao.

Os invariantes da Secao 7.5 sao vigiados o tempo todo pelos registradores
MODBUS, que sao o que o simulador ve, e nao pelo que as cabines dizem de si:
porta so abre nivelada, soma das Cotas dentro do barramento, corrente dentro
da Cota e espera abaixo de 90 s.

Duas etapas pedem acao no dashboard (cortina e despacho); o teste avisa a
hora e espera. Tudo vai para dados/teste_<data>_<hora>/: o log de cada
processo, os CSVs dos graficos (pid_cabineN.csv e potencia.csv), o registro
de viagens e o relatorio.
"""
import argparse
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time

from src import configuracao

RAIZ = configuracao.RAIZ
CABINES = (1, 2, 3)
ETAPAS = ("conexao", "contorno", "calibracao", "viagem", "cortina", "degradado",
          "reconexao", "despacho", "reinicio")
TITULOS = {
    "conexao": "Comunicacao TCP: tres cabines conectadas",
    "contorno": "BMP280 -> Condicao de Contorno -> barramento",
    "calibracao": "Calibracao pelas bandeirolas",
    "viagem": "PID: viagens com nivelamento",
    "cortina": "Cortina de luz inibe o fechamento",
    "degradado": "Cota cortada: Modo Degradado e pouso",
    "reconexao": "Queda de TCP e reinicio do central",
    "despacho": "Despacho: chamadas do quiosque e cenario",
    "reinicio": "SIGINT numa cabine e nova subida",
}
OK, FALHOU, PARCIAL, PULADA = "OK", "FALHOU", "PARCIAL", "PULADA"

TOLERANCIA_MM = 10.0
PORTA_FECHADA, PORTA_ABRINDO, PORTA_ABERTA, PORTA_FECHANDO, PORTA_OBSTRUIDA = range(5)
PORTA_NAO_FECHADA = (PORTA_ABRINDO, PORTA_ABERTA, PORTA_OBSTRUIDA)
COTA_MINIMA_MA = 1000
DUTY_DO_DEGRADADO = 100.0 * COTA_MINIMA_MA / 6000.0
FOLGA_DE_CORRENTE_MA = 100
ESPERA_MAXIMA_S = 90.0
VAO_MINIMO_MM, VAO_MAXIMO_MM = 2500.0, 3500.0


def espera(condicao, prazo_s, passo_s=0.25):
    """Valor da condicao assim que for verdadeiro, ou None no fim do prazo."""
    fim = time.monotonic() + prazo_s
    while True:
        valor = condicao()
        if valor:
            return valor
        if time.monotonic() >= fim:
            return None
        time.sleep(passo_s)


# ===================================================================== bancadas
class _Bancada:
    """O que o teste precisa da placa (ou do simulador): o central, as cabines
    como processos, e os botoes do dashboard."""

    def __init__(self, pasta, verboso):
        self.pasta = pasta
        self.verboso = verboso
        self.central = None
        self._linhas = {n: [] for n in CABINES}
        self._trava = threading.Lock()
        self._arquivos = {n: open(os.path.join(pasta, "cabine%d.log" % n), "a")
                          for n in CABINES}

    def _registra_linha(self, numero, linha):
        with self._trava:
            self._linhas[numero].append((time.monotonic(), linha))
            self._arquivos[numero].write(linha + "\n")
            self._arquivos[numero].flush()
        if self.verboso:
            print("  | " + linha, flush=True)

    def linhas(self, numero, desde=0.0):
        with self._trava:
            return [texto for instante, texto in self._linhas[numero] if instante >= desde]

    def _eco_do_central(self, linha):
        if self.verboso:
            print("  | central: " + linha, flush=True)

    def fecha_logs(self):
        for arquivo in self._arquivos.values():
            arquivo.close()


class BancadaPlaca(_Bancada):
    simulada = False

    def __init__(self, pasta, verboso, matricula):
        super().__init__(pasta, verboso)
        from src.central.registro_potencia import RegistroDePotencia
        from src.comunicacao import abre_sensor, obtem_matricula
        from src.uart import modbus
        from src.uart.elevadores import Elevadores
        from src.uart.porta import PortaSerial
        self._config = _config_do_central(pasta)
        self._porta = PortaSerial(self._config["uart"])
        self._elevadores = Elevadores(modbus.ClienteModbus(
            self._porta, obtem_matricula(matricula), eco=None,
            timeout_s=self._config["timeout_s"]))
        self._sensor, self._i2c = abre_sensor(False, self._config["i2c"])
        self._potencia = RegistroDePotencia(os.path.join(pasta, "potencia.csv"))
        self._processos = {}
        self._subidas = {n: 0 for n in CABINES}

    def inicia_cabine(self, numero):
        self._subidas[numero] += 1
        sufixo = "" if self._subidas[numero] == 1 else "_subida%d" % self._subidas[numero]
        comando = [sys.executable, "-u", "-m", "src.distribuido", "--cabine", str(numero),
                   "--registra-pid", os.path.join(self.pasta, "pid_cabine%d%s.csv"
                                                  % (numero, sufixo))]
        processo = subprocess.Popen(comando, cwd=RAIZ, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, bufsize=1)
        self._processos[numero] = processo
        threading.Thread(target=self._le_saida, args=(numero, processo), daemon=True,
                         name="saida-cabine%d" % numero).start()

    def _le_saida(self, numero, processo):
        for linha in processo.stdout:
            self._registra_linha(numero, linha.rstrip("\n"))

    def para_cabine(self, numero):
        """SIGINT, como o Ctrl+C na janela da cabine. Devolve (encerrou bem, texto)."""
        processo = self._processos.get(numero)
        if processo is None or processo.poll() is not None:
            return False, "processo da cabine %d ja tinha terminado" % numero
        desde = time.monotonic()
        processo.send_signal(signal.SIGINT)
        try:
            codigo = processo.wait(timeout=15)
        except subprocess.TimeoutExpired:
            processo.kill()
            return False, "nao terminou 15 s depois do SIGINT (morto com SIGKILL)"
        espera(lambda: any("encerrada com seguranca" in l
                           for l in self.linhas(numero, desde)), 2.0)
        seguro = any("encerrada com seguranca" in l for l in self.linhas(numero, desde))
        return codigo == 0 and seguro, "codigo de saida %s%s" % (
            codigo, ", 'encerrada com seguranca' no log" if seguro else "")

    def processo_vivo(self, numero):
        processo = self._processos.get(numero)
        return processo is not None and processo.poll() is None

    def inicia_central(self):
        from src.central.condicao_contorno import PERIODO_PADRAO_S, ServicoCondicaoContorno
        from src.central.servidor_central import ServidorCentral
        servidor = ServidorCentral(self._config, self._elevadores, eco=self._eco_do_central,
                                   registro_de_potencia=self._potencia)
        if self._sensor is not None:
            servidor.contorno = ServicoCondicaoContorno(
                self._sensor, self._elevadores, periodo_s=PERIODO_PADRAO_S, eco=servidor.log)
        else:
            servidor.log("AVISO: sem BMP280 o watchdog expira e o barramento cai a 3000 mA")
        servidor.inicia()
        self.central = servidor

    def reinicia_central(self):
        self.central.finaliza()
        time.sleep(3.0)
        self.inicia_central()

    # Botoes do dashboard: aqui quem aperta e o usuario.
    def pede(self, texto):
        print("\n  >>> " + texto.replace("\n", "\n  >>> "), flush=True)
        try:
            resposta = input("  >>> Enter para continuar, 'p' para pular esta etapa: ")
        except EOFError:
            return False
        return resposta.strip().lower() != "p"

    def obstrui(self, _numero):
        pass

    def chamadas(self, _lista):
        pass

    def cenario(self, _nome, _duracao_s):
        pass

    def encerra(self):
        for numero, processo in self._processos.items():
            if processo.poll() is None:
                processo.send_signal(signal.SIGINT)
        for processo in self._processos.values():
            try:
                processo.wait(timeout=15)
            except subprocess.TimeoutExpired:
                processo.kill()
        if self.central is not None:
            self.central.finaliza()
        self._potencia.fecha()
        self._porta.fecha()
        if self._i2c is not None:
            self._i2c.fecha()
        self.fecha_logs()


class BancadaSimulada(_Bancada):
    """Mesmo teste contra src/simulacao, num processo so. As portas TCP sao
    deslocadas para nao colidir com uma placa simulada ja aberta."""
    simulada = True
    DESLOCAMENTO_DE_PORTAS = 50

    def __init__(self, pasta, verboso):
        super().__init__(pasta, verboso)
        from src.simulacao.__main__ import monta
        self._sistema = monta(perda_de_transicoes=0.0002, registra_pid=True, pasta=pasta,
                              deslocamento_de_portas=self.DESLOCAMENTO_DE_PORTAS)
        self._cabines = self._sistema["cabines"]
        for numero, cabine in self._cabines.items():
            cabine._eco_externo = lambda texto, n=numero: self._registra_linha(n, texto)
        self._iniciadas = set()

    def inicia_cabine(self, numero):
        if numero in self._iniciadas:
            from src.distribuido.cabine import ServidorDistribuido
            from src.simulacao.backend import BackendDoPoco
            antiga = self._cabines[numero]
            self._cabines[numero] = ServidorDistribuido(
                antiga.configuracao, BackendDoPoco(self._sistema["predio"].fisicas[numero]),
                eco=lambda texto, n=numero: self._registra_linha(n, texto))
        self._iniciadas.add(numero)
        self._cabines[numero].inicia()

    def para_cabine(self, numero):
        self._cabines[numero].finaliza()
        return True, "simulado: finaliza() chamado direto, sem processo"

    def processo_vivo(self, numero):
        return True

    def inicia_central(self):
        from src.central.condicao_contorno import ServicoCondicaoContorno
        from src.central.servidor_central import ServidorCentral
        from src.i2c import bmp280
        modelo = self._sistema["central"]
        servidor = ServidorCentral(modelo.configuracao, modelo.elevadores,
                                   eco=self._eco_do_central)
        servidor.contorno = ServicoCondicaoContorno(
            bmp280.BMP280(self._sistema["i2c"]), modelo.elevadores, eco=servidor.log)
        servidor.inicia()
        self.central = servidor

    def reinicia_central(self):
        self.central.finaliza()
        time.sleep(3.0)
        self.inicia_central()

    def pede(self, texto):
        print("\n  >>> (simulado, automatico) " + texto.splitlines()[0], flush=True)
        return True

    def obstrui(self, numero, segundos=3.0):
        fisica = self._sistema["predio"].fisicas[numero]
        fisica.aciona_cortina(True)
        threading.Timer(segundos, fisica.aciona_cortina, args=(False,)).start()

    def chamadas(self, lista):
        for origem, destino in lista:
            self._sistema["predio"].registra_chamada(origem, destino)

    def cenario(self, nome, duracao_s):
        self._sistema["predio"].inicia_cenario(nome, duracao_s=duracao_s)

    def encerra(self):
        if self.central is not None:
            self.central.finaliza()
        for cabine in self._cabines.values():
            cabine.finaliza()
        for registro in self._sistema["registros"]:
            registro.fecha()
        self._sistema["predio"].encerra()
        self.fecha_logs()


def _config_do_central(pasta):
    config = configuracao.le_central()
    config.update(arquivo_de_estado=os.path.join(pasta, "central_estado.json"),
                  arquivo_de_viagens=os.path.join(pasta, "viagens.csv"),
                  arquivo_de_eventos=os.path.join(pasta, "central.log"))
    return config


# ====================================================================== vigia
class Vigia:
    """Invariantes da Secao 7.5, conferidos a cada 0,5 s durante o teste todo."""

    def __init__(self, bancada):
        self._bancada = bancada
        self.amostras = 0
        self.violacoes = {}
        self.maior_espera_s = 0.0
        self.maior_excesso_ma = 0
        self.falhas_de_registrador = {}
        self._parar = threading.Event()
        self._thread = threading.Thread(target=self._laco, daemon=True, name="vigia")

    def inicia(self):
        self._thread.start()

    def para(self):
        self._parar.set()
        self._thread.join(timeout=2.0)

    def _viola(self, tipo, texto):
        lista = self.violacoes.setdefault(tipo, [])
        if len(lista) < 5:
            lista.append("%s %s" % (time.strftime("%H:%M:%S"), texto))
        else:
            lista[-1] = "... e mais (ultima %s %s)" % (time.strftime("%H:%M:%S"), texto)

    def _laco(self):
        while not self._parar.wait(0.5):
            central = self._bancada.central
            if central is None:
                continue
            try:
                self._confere(central)
            except Exception as erro:          # o vigia nao pode derrubar o teste
                self._viola("erro do vigia", repr(erro))

    def _confere(self, central):
        self.amostras += 1
        capacidade = central.capacidade_ma()
        soma = central.cotas.soma_em_uso()
        if capacidade is not None and soma > capacidade:
            self._viola("soma das Cotas acima do barramento",
                        "%d mA > %d mA" % (soma, capacidade))
        agora = time.monotonic()
        for numero, cabine in central.cabines.items():
            registradores = cabine.registradores
            estado = cabine.estado_recente(agora)
            if not registradores:
                continue
            if registradores["porta_estado"] in PORTA_NAO_FECHADA \
                    and not registradores["nivelado"]:
                self._viola("porta aberta fora do nivel",
                            "cabine %d no andar %d, posicao %d mm"
                            % (numero, registradores["andar_atual"],
                               registradores["posicao_mm"]))
            if registradores["falha"]:
                self.falhas_de_registrador[numero] = registradores["falha"]
            if estado is not None:
                cota = estado.get("cota_ma") if estado.get("cota_valida") else COTA_MINIMA_MA
                excesso = registradores["corrente_ma"] - (cota or COTA_MINIMA_MA)
                if excesso > 0:
                    self.maior_excesso_ma = max(self.maior_excesso_ma, excesso)
                if excesso > FOLGA_DE_CORRENTE_MA:
                    self._viola("corrente acima da Cota",
                                "cabine %d: %d mA com Cota de %d mA"
                                % (numero, registradores["corrente_ma"], cota))
        espera_atual = central.registro.metricas()["maior_espera_atual_s"]
        self.maior_espera_s = max(self.maior_espera_s, espera_atual)
        if espera_atual > ESPERA_MAXIMA_S:
            self._viola("espera acima de 90 s", "%.0f s" % espera_atual)


# ====================================================================== teste
class Resultado:
    def __init__(self, etapa):
        self.etapa = etapa
        self.situacao = None
        self.detalhes = []
        self.duracao_s = 0.0

    def nota(self, texto):
        self.detalhes.append(texto)
        print("    " + texto, flush=True)


class Teste:
    def __init__(self, bancada, args):
        self.b = bancada
        self.args = args
        self.vigia = Vigia(bancada)
        self.resultados = []

    # ------------------------------------------------------------ acesso
    def cabine(self, numero):
        return self.b.central.cabines[numero]

    def estado(self, numero):
        return self.cabine(numero).estado_recente(time.monotonic())

    def registradores(self, numero):
        return self.cabine(numero).registradores or {}

    def andar_atual(self, numero):
        return self.registradores(numero).get("andar_atual", 0)

    def porta(self, numero):
        return self.registradores(numero).get("porta_estado")

    def mapa(self, numero):
        estado = self.estado(numero) or {}
        return {int(a): v for a, v in (estado.get("mapa") or {}).items()}

    def resumo_da_cabine(self, numero):
        estado = self.estado(numero) or {}
        registradores = self.registradores(numero)
        return ("C%d: modo %s, calibracao %s, fase %s, posicao %s mm, andar MODBUS %s, "
                "porta %s, falha %s" % (
                    numero, estado.get("modo"), estado.get("calibracao"), estado.get("fase"),
                    estado.get("posicao_mm"), registradores.get("andar_atual"),
                    registradores.get("porta_estado"), estado.get("falha")))

    # ------------------------------------------------------------ roteiro
    def roda(self):
        pula = set(self.args.pula or ())
        print("Subindo as cabines antes do central (a ordem nao importa).", flush=True)
        for numero in CABINES:
            self.b.inicia_cabine(numero)
        time.sleep(2.0)
        self.b.inicia_central()
        self.vigia.inicia()
        for etapa in ETAPAS:
            resultado = Resultado(etapa)
            self.resultados.append(resultado)
            if etapa in pula:
                resultado.situacao = PULADA
                continue
            print("\n=== %s ===" % TITULOS[etapa], flush=True)
            inicio = time.monotonic()
            try:
                resultado.situacao = getattr(self, "etapa_" + etapa)(resultado)
            except KeyboardInterrupt:
                resultado.situacao = FALHOU
                resultado.nota("interrompido com Ctrl+C")
                raise
            except Exception as erro:
                resultado.situacao = FALHOU
                resultado.nota("erro no teste: %r" % (erro,))
            finally:
                resultado.duracao_s = time.monotonic() - inicio
            print("  -> %s (%.0f s)" % (resultado.situacao, resultado.duracao_s), flush=True)
            if etapa == "calibracao" and resultado.situacao == FALHOU:
                print("\nSem calibracao as etapas seguintes nao tem como passar; "
                      "encerrando.", flush=True)
                break

    # ------------------------------------------------------------ etapas
    def etapa_conexao(self, r):
        conectadas = espera(lambda: all(self.estado(n) for n in CABINES), 30)
        for numero in CABINES:
            cabine = self.cabine(numero)
            r.nota("cabine %d: %s na porta %d" % (
                numero, "conectada" if cabine.conectada else "SEM CONEXAO", cabine.porta))
        r.nota("as cabines subiram antes do central; o central conectou nelas sozinho")
        return OK if conectadas else FALHOU

    def etapa_contorno(self, r):
        central = self.b.central
        if central.contorno is None:
            r.nota("BMP280 nao abriu: sem Condicao de Contorno o watchdog expira e o "
                   "barramento cai a 3000 mA (as cabines andam devagar)")
            espera(lambda: central.predio, 10)
            if central.predio:
                r.nota("barramento_max_ma = %d, watchdog_ambiente = %d" % (
                    central.predio["barramento_max_ma"], central.predio["watchdog_ambiente"]))
            return FALHOU

        def pronto():
            predio, leitura = central.predio, central.contorno.ultima_leitura
            return predio and leitura and central.contorno.ultima_escrita \
                and predio["watchdog_ambiente"] == 0 and (predio, leitura)

        achado = espera(pronto, 45)
        if not achado:
            r.nota("watchdog_ambiente nao foi a 0 em 45 s; falhas do contorno: %d (%s)"
                   % (central.contorno.falhas, central.contorno.ultimo_erro))
            return FALHOU
        predio, leitura = achado
        esperado = 12000 - 200 * max(0.0, leitura.temperatura_c - 25.0)
        r.nota("BMP280: %.2f C, %.1f hPa" % (leitura.temperatura_c, leitura.pressao_hpa))
        r.nota("watchdog_ambiente = 0; barramento_max_ma = %d (esperado %.0f pela formula)"
               % (predio["barramento_max_ma"], esperado))
        return OK if abs(predio["barramento_max_ma"] - esperado) <= 250 else PARCIAL

    def etapa_calibracao(self, r):
        prazo = self.args.prazo_calibracao
        fim = time.monotonic() + prazo
        proximo_aviso = time.monotonic() + 30
        print("    calibrando (ate %d s)..." % prazo, flush=True)
        while not all((self.estado(n) or {}).get("modo") == "operando" for n in CABINES):
            if time.monotonic() > fim:
                for numero in CABINES:
                    r.nota(self.resumo_da_cabine(numero))
                    for linha in self.b.linhas(numero)[-4:]:
                        r.nota("  ultima linha: " + linha)
                return FALHOU
            if time.monotonic() > proximo_aviso:
                proximo_aviso += 30
                for numero in CABINES:
                    print("    " + self.resumo_da_cabine(numero), flush=True)
            time.sleep(0.5)
        niveladas = espera(lambda: all(self.registradores(n).get("nivelado")
                                       and (self.estado(n) or {}).get("fase") != "rastreando"
                                       for n in CABINES), 120)
        situacao = OK if niveladas else FALHOU
        for numero in CABINES:
            mapa = self.mapa(numero)
            posicoes = [mapa[a]["posicao_mm"] for a in sorted(mapa)]
            larguras = [mapa[a]["largura_mm"] for a in sorted(mapa)]
            vaos = [b - a for a, b in zip(posicoes, posicoes[1:])]
            bandeirolas = sum("bandeirola" in l for l in self.b.linhas(numero))
            r.nota("cabine %d: andares %s mm" % (numero, ", ".join("%.0f" % p for p in posicoes)))
            r.nota("  vaos %s mm; larguras %s mm; %d bordas de bandeirola no log" % (
                ", ".join("%.0f" % v for v in vaos), ", ".join("%.0f" % l for l in larguras),
                bandeirolas))
            if len(posicoes) != 6 or not all(VAO_MINIMO_MM <= v <= VAO_MAXIMO_MM for v in vaos):
                r.nota("  ** vao fora de %d..%d mm" % (VAO_MINIMO_MM, VAO_MAXIMO_MM))
                situacao = FALHOU
            if len({round(l) for l in larguras}) < 2:
                r.nota("  ** todas as bandeirolas com a mesma largura: suspeito")
                situacao = PARCIAL if situacao == OK else situacao
            r.nota("  depois de calibrar: andar %s, nivelado (MODBUS) = %s" % (
                self.andar_atual(numero), self.registradores(numero).get("nivelado")))
        return situacao

    def _viaja(self, r, numero, alvo, prazo_s=150):
        desde = time.monotonic()
        self.b.central.envia_cabine_ao_andar(numero, alvo)
        chegou = espera(lambda: self.andar_atual(numero) == alvo
                        and self.porta(numero) in (PORTA_ABRINDO, PORTA_ABERTA), prazo_s)
        duracao = time.monotonic() - desde
        if not chegou:
            r.nota("cabine %d ao andar %d: nao abriu a porta em %d s; %s"
                   % (numero, alvo, prazo_s, self.resumo_da_cabine(numero)))
            return False
        nivelado = self.registradores(numero).get("nivelado")
        erro = None
        for linha in self.b.linhas(numero, desde):
            achado = re.search(r"CHEGADA .*erro ([+-]?\d+(?:\.\d+)?) mm", linha)
            if achado:
                erro = float(achado.group(1))
        if erro is None:
            estado, mapa = self.estado(numero) or {}, self.mapa(numero)
            erro = estado.get("posicao_mm", 0.0) - mapa.get(alvo, {}).get("posicao_mm", 0.0)
        fechou = espera(lambda: self.porta(numero) == PORTA_FECHADA, 40)
        bom = bool(nivelado) and abs(erro) <= TOLERANCIA_MM and bool(fechou)
        r.nota("cabine %d ao andar %d: %.1f s, erro %+.1f mm, nivelado (MODBUS) = %s, "
               "porta %s%s" % (numero, alvo, duracao, erro, nivelado,
                               "abriu e fechou" if fechou else "NAO FECHOU",
                               "" if bom else "  **"))
        return bom

    def etapa_viagem(self, r):
        boas = total = 0
        for numero in CABINES:
            atual = self.andar_atual(numero)
            longe = 5 if atual <= 2 else 0
            perto = longe - 1 if longe == 5 else 1
            for alvo in (longe, perto):
                total += 1
                boas += self._viaja(r, numero, alvo)
        r.nota("%d de %d viagens dentro de +-%d mm" % (boas, total, TOLERANCIA_MM))
        return OK if boas == total else (PARCIAL if boas else FALHOU)

    def etapa_cortina(self, r):
        numero = 1
        if not self.b.pede("Cortina: a porta da CABINE 1 vai abrir e fechar em ciclos por ate "
                           "90 s.\nNo dashboard, clique em 'Obstruir porta' da Cabine 1 "
                           "enquanto a porta estiver aberta ou fechando."):
            return PULADA
        desde = time.monotonic()
        fim = desde + 90
        reabriu_em = 0.0
        obstruiu = vista = False
        while time.monotonic() < fim:
            linhas = self.b.linhas(numero, desde)
            inibido = any("fechamento inibido" in l for l in linhas)
            reiniciado = any("fechamento reiniciado" in l for l in linhas)
            estado = self.estado(numero) or {}
            vista = vista or bool(estado.get("cortina"))
            if inibido and reiniciado and self.porta(numero) == PORTA_FECHADA \
                    and not estado.get("cortina"):
                break
            agora = time.monotonic()
            if self.porta(numero) == PORTA_FECHADA and agora - reabriu_em > 3.0 \
                    and estado.get("porta_ciclo") in (None, "ociosa"):
                self.b.central.envia_cabine_ao_andar(numero, self.andar_atual(numero))
                reabriu_em = agora
            if self.b.simulada and not obstruiu and self.porta(numero) == PORTA_FECHANDO:
                self.b.obstrui(numero)
                obstruiu = True
            time.sleep(0.2)
        linhas = self.b.linhas(numero, desde)
        inibido = any("fechamento inibido" in l for l in linhas)
        reiniciado = any("fechamento reiniciado" in l for l in linhas)
        fechou = espera(lambda: self.porta(numero) == PORTA_FECHADA, 30)
        r.nota("interrupcao da cortina vista pela cabine: %s" % ("sim" if vista else "nao"))
        for linha in linhas:
            if "PORTA:" in linha:
                r.nota("log: " + linha)
        r.nota("porta fechada no fim: %s" % ("sim" if fechou else "NAO"))
        if inibido and reiniciado and fechou:
            return OK
        if vista:
            r.nota("a obstrucao nao pegou a porta aberta ou fechando: repita clicando durante "
                   "o fechamento")
            return PARCIAL
        return FALHOU

    def etapa_degradado(self, r):
        numero = 2
        atual = self.andar_atual(numero)
        alvo = 5 if atual <= 2 else 0
        sentido = 1 if alvo > atual else -1
        mapa = self.mapa(numero)
        partida = (self.estado(numero) or {}).get("posicao_mm", 0.0)
        self.b.central.envia_cabine_ao_andar(numero, alvo)
        andando = espera(lambda: abs((self.estado(numero) or {}).get("posicao_mm", partida)
                                     - partida) > 600, 60)
        if not andando:
            r.nota("a cabine nao saiu do lugar em 60 s; " + self.resumo_da_cabine(numero))
            return FALHOU
        posicao_no_corte = self.estado(numero)["posicao_mm"]
        proximo = min((a for a in mapa if (mapa[a]["posicao_mm"] - posicao_no_corte) * sentido > 0),
                      key=lambda a: abs(mapa[a]["posicao_mm"] - posicao_no_corte), default=alvo)
        desde = time.monotonic()
        self.b.central.corta_cota(numero, 600)
        entrou = espera(lambda: (self.estado(numero) or {}).get("modo") == "degradado", 6)
        r.nota("Cota cortada a %.0f mm, %s; modo degradado em %s" % (
            posicao_no_corte, "subindo" if sentido > 0 else "descendo",
            "%.1f s" % (time.monotonic() - desde) if entrou else "NAO ENTROU"))
        maior_duty_maximo = maior_duty = 0.0
        pouso = None
        fim = time.monotonic() + 150
        while time.monotonic() < fim:
            estado = self.estado(numero) or {}
            if estado.get("modo") == "degradado":
                maior_duty_maximo = max(maior_duty_maximo, estado.get("duty_maximo") or 0.0)
                maior_duty = max(maior_duty, estado.get("duty") or 0.0)
            for linha in self.b.linhas(numero, desde):
                achado = re.search(r"pouso de emergencia no andar (\d)", linha)
                if achado:
                    pouso = int(achado.group(1))
            registradores = self.registradores(numero)
            if pouso is not None and registradores.get("andar_atual") == pouso \
                    and registradores.get("porta_estado") in (PORTA_ABRINDO, PORTA_ABERTA) \
                    and registradores.get("nivelado"):
                break
            time.sleep(0.2)
        else:
            r.nota("nao pousou com a porta aberta em 150 s; " + self.resumo_da_cabine(numero))
            self.b.central.corta_cota(numero, 0)
            return FALHOU
        r.nota("pouso no andar %d (proximo andar a frente: %d, destino original: %d)"
               % (pouso, proximo, alvo))
        r.nota("teto de duty no degradado: %.1f%% (Cota de 1000 mA = %.1f%%); maior duty %.1f%%"
               % (maior_duty_maximo, DUTY_DO_DEGRADADO, maior_duty))
        manteve = True
        for _ in range(16):
            time.sleep(0.5)
            manteve = manteve and self.porta(numero) in PORTA_NAO_FECHADA
        r.nota("porta aberta durante 8 s sem Cota: %s" % ("sim" if manteve else "NAO"))
        self.b.central.corta_cota(numero, 0)
        saiu = espera(lambda: (self.estado(numero) or {}).get("modo") == "operando", 8)
        fechou = espera(lambda: self.porta(numero) == PORTA_FECHADA, 25)
        r.nota("Cota de volta: %s, porta %s" % ("operando" if saiu else "NAO SAIU do degradado",
                                                "fechou" if fechou else "NAO FECHOU"))
        if alvo != pouso:
            seguiu = espera(lambda: self.andar_atual(numero) == alvo
                            and self.porta(numero) in (PORTA_ABRINDO, PORTA_ABERTA), 150)
            r.nota("seguiu ate o destino original (andar %d): %s" % (alvo, "sim" if seguiu else "nao"))
            espera(lambda: self.porta(numero) == PORTA_FECHADA, 40)
        bom = entrou and pouso in (proximo, proximo + sentido) \
            and maior_duty_maximo <= DUTY_DO_DEGRADADO + 0.5 and manteve and saiu and fechou
        return OK if bom else FALHOU

    def etapa_reconexao(self, r):
        cabine = self.cabine(1)
        cabine.cliente.suspende(5.0)
        caiu = espera(lambda: not self.cabine(1).conectada, 4)
        voltou = espera(lambda: self.cabine(1).conectada and self.estado(1), 20)
        operando = espera(lambda: (self.estado(1) or {}).get("modo") == "operando"
                          and (self.estado(1) or {}).get("calibrada"), 20)
        r.nota("TCP da cabine 1 derrubado por 5 s: caiu %s, reconectou %s, operando de novo "
               "sem recalibrar %s" % ("sim" if caiu else "NAO", "sim" if voltou else "NAO",
                                       "sim" if operando else "NAO"))
        self.b.reinicia_central()
        voltaram = espera(lambda: all(self.estado(n) for n in CABINES), 20)
        operando_todas = espera(lambda: all((self.estado(n) or {}).get("modo") == "operando"
                                            for n in CABINES), 25)
        fechadas = espera(lambda: all(self.porta(n) == PORTA_FECHADA for n in CABINES), 30)
        r.nota("central reiniciado: cabines reconectaram %s, operando %s, portas fechadas %s"
               % ("sim" if voltaram else "NAO", "sim" if operando_todas else "NAO",
                  "sim" if fechadas else "NAO"))
        return OK if caiu and voltou and operando and voltaram and operando_todas else FALHOU

    def _espera_atender(self, prazo_s):
        return espera(lambda: not self.b.central.registro.lista_pendentes(), prazo_s, 1.0)

    def etapa_despacho(self, r):
        situacao = OK
        concluidas_antes = self.b.central.registro.concluidas
        if self.b.pede("Despacho: no dashboard (Quiosque de Destino), registre 3 chamadas com "
                       "origens diferentes,\npor exemplo 0->4, 5->1 e 2->3. O teste espera ate "
                       "3 min por elas e as acompanha."):
            self.b.chamadas([(0, 4), (5, 1), (2, 3)])
            chegou = espera(lambda: self.b.central.registro.lista_pendentes()
                            or self.b.central.registro.concluidas > concluidas_antes, 180, 1.0)
            if not chegou:
                r.nota("nenhuma chamada chegou da fila em 3 min")
                situacao = FALHOU
            else:
                time.sleep(10.0)    # as outras chamadas registradas logo depois
                atendidas = self._espera_atender(300)
                for chamada in self.b.central.registro.recentes[-6:]:
                    r.nota("chamada %d: %d -> %d na cabine %d, espera %.1f s, viagem %.1f s"
                           % (chamada.id, chamada.origem, chamada.destino, chamada.cabine,
                              chamada.espera_s, chamada.viagem_s))
                if not atendidas:
                    r.nota("chamadas ainda pendentes depois de 5 min")
                    situacao = FALHOU
        else:
            situacao = PARCIAL
        if not self.b.pede("Cenario: no dashboard, dispare um Cenario de Trafego (sugestao: "
                           "down-peak, o mais dificil).\nO teste acompanha os 5 min e espera o "
                           "ultimo passageiro desembarcar."):
            return PARCIAL if situacao == OK else situacao
        self.b.cenario(self.args.cenario, self.args.duracao_cenario)
        predio_ativo = espera(lambda: (self.b.central.predio or {}).get("cenario_ativo"), 300, 1.0)
        if not predio_ativo:
            r.nota("nenhum cenario ativo em 5 min")
            return FALHOU
        self.vigia.maior_espera_s = 0.0
        r.nota("cenario %d ativo; acompanhando" % predio_ativo)
        espera(lambda: not (self.b.central.predio or {}).get("cenario_ativo"),
               self.args.duracao_cenario + 300, 2.0)
        atendidas = self._espera_atender(300)
        predio = self.b.central.predio or {}
        r.nota("simulador: %s geradas, %s atendidas, espera media %.1f s, viagem media %.1f s"
               % (predio.get("cenario_geradas"), predio.get("cenario_atendidas"),
                  predio.get("espera_media_s_x10", 0) / 10.0,
                  predio.get("viagem_media_s_x10", 0) / 10.0))
        metricas = self.b.central.registro.metricas()
        r.nota("central: maior espera no cenario %.1f s; media acumulada do registro %s s"
               % (self.vigia.maior_espera_s, "%.1f" % metricas["espera_media_s"]
                  if metricas["espera_media_s"] is not None else "-"))
        if not atendidas or predio.get("cenario_geradas") != predio.get("cenario_atendidas"):
            r.nota("** nem todas as chamadas do cenario foram atendidas")
            situacao = FALHOU
        if self.vigia.maior_espera_s > ESPERA_MAXIMA_S:
            r.nota("** alguma chamada esperou mais de 90 s")
            situacao = FALHOU
        return situacao

    def etapa_reinicio(self, r):
        numero = 3
        seguro, texto = self.b.para_cabine(numero)
        r.nota("SIGINT na cabine %d: %s" % (numero, texto))
        caiu = espera(lambda: not self.cabine(numero).conectada, 10)
        posicoes, correntes = [], []
        for _ in range(8):
            time.sleep(0.5)
            registradores = self.registradores(numero)
            posicoes.append(registradores.get("posicao_mm", 0))
            correntes.append(registradores.get("corrente_ma", 0))
        parada = max(posicoes) - min(posicoes) <= 5 and max(correntes) == 0
        r.nota("depois do SIGINT: central viu a queda %s; corrente %d mA, posicao variou "
               "%d mm em 4 s" % ("sim" if caiu else "NAO", max(correntes),
                                 max(posicoes) - min(posicoes)))
        self.b.inicia_cabine(numero)
        voltou = espera(lambda: self.estado(numero), 30)
        print("    cabine %d de volta; recalibrando (ate %d s)..."
              % (numero, self.args.prazo_calibracao), flush=True)
        operando = espera(lambda: (self.estado(numero) or {}).get("modo") == "operando",
                          self.args.prazo_calibracao, 1.0)
        r.nota("subiu de novo: reconectou %s, recalibrou e voltou a operar %s"
               % ("sim" if voltou else "NAO", "sim" if operando else "NAO"))
        return OK if seguro and caiu and parada and voltou and operando else FALHOU

    # ------------------------------------------------------------ relatorio
    def relatorio(self, pasta):
        linhas = ["", "=" * 78,
                  "RELATORIO DO TESTE DA ENTREGA FINAL  (%s, %s)"
                  % (os.uname().nodename, time.strftime("%Y-%m-%d %H:%M")),
                  "=" * 78]
        for resultado in self.resultados:
            linhas.append("[%-7s] %s" % (resultado.situacao or "-", TITULOS[resultado.etapa]))
            linhas.extend("           " + d for d in resultado.detalhes)
        linhas += ["", "Invariantes da Secao 7.5 (%d amostras de 0,5 s):" % self.vigia.amostras]
        tipos = ("porta aberta fora do nivel", "soma das Cotas acima do barramento",
                 "corrente acima da Cota", "espera acima de 90 s")
        for tipo in tipos + tuple(t for t in self.vigia.violacoes if t not in tipos):
            ocorrencias = self.vigia.violacoes.get(tipo)
            linhas.append("  %-38s %s" % (tipo + ":", "nenhuma" if not ocorrencias
                                          else "VIOLADO"))
            linhas.extend("      " + o for o in ocorrencias or ())
        linhas.append("  maior excesso de corrente sobre a Cota: %d mA (tolerado %d mA)"
                      % (self.vigia.maior_excesso_ma, FOLGA_DE_CORRENTE_MA))
        if self.vigia.falhas_de_registrador:
            linhas.append("  registrador 'falha' diferente de zero: %s"
                          % self.vigia.falhas_de_registrador)
        relativa = os.path.relpath(pasta, RAIZ)
        linhas += ["", "Arquivos em %s/" % relativa,
                   "Graficos, no PC (a placa nao tem matplotlib):",
                   "  scp -r -P <porta> <usuario>@<placa>:embarcados-2026-2/%s ." % relativa,
                   "  python3 -m ferramentas.graficos --pid %s/pid_cabine1.csv --potencia "
                   "%s/potencia.csv" % (os.path.basename(pasta), os.path.basename(pasta))]
        texto = "\n".join(linhas)
        print(texto, flush=True)
        with open(os.path.join(pasta, "relatorio.txt"), "w") as saida:
            saida.write(texto + "\n")
        with open(os.path.join(pasta, "relatorio.json"), "w") as saida:
            json.dump({"etapas": [{"etapa": r.etapa, "situacao": r.situacao,
                                   "duracao_s": round(r.duracao_s, 1), "detalhes": r.detalhes}
                                  for r in self.resultados],
                       "violacoes": self.vigia.violacoes,
                       "maior_espera_s": self.vigia.maior_espera_s,
                       "maior_excesso_de_corrente_ma": self.vigia.maior_excesso_ma},
                      saida, indent=2)


# ================================================================ pre-checagem
def verifica_a_placa():
    """Problemas que impedem o teste (lista) e avisos (lista)."""
    impedimentos, avisos = [], []
    try:
        outros = subprocess.run(["pgrep", "-af", r"src\.(central|distribuido)"],
                                capture_output=True, text=True).stdout.strip()
    except OSError:
        outros = ""
    if outros:
        impedimentos.append("ja ha processos do elevador rodando (feche o tmux com "
                            "'tmux kill-session -t elevador'):\n      " + outros)
    if not os.path.exists("/dev/serial0"):
        impedimentos.append("/dev/serial0 nao existe")
    elif not os.access("/dev/serial0", os.R_OK | os.W_OK):
        impedimentos.append("sem permissao em /dev/serial0 (grupo dialout)")
    if not os.path.exists("/dev/i2c-1"):
        avisos.append("/dev/i2c-1 nao existe: sem BMP280 o barramento fica em 3000 mA")
    if any(n.startswith("spidev") for n in os.listdir("/dev")):
        avisos.append("SPI habilitado (/dev/spidev*): ocupa pinos das cabines 2 e 3")
    if not os.environ.get("TMUX"):
        avisos.append("fora do tmux: uma queda do SSH encerra o teste no meio")
    return impedimentos, avisos


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--simulado", action="store_true",
                        help="contra o predio simulado, sem placa")
    parser.add_argument("--pula", nargs="+", choices=ETAPAS, metavar="ETAPA",
                        help="etapas a pular: %s" % ", ".join(ETAPAS))
    parser.add_argument("--matricula", help="matricula; usa os 6 ultimos digitos")
    parser.add_argument("--prazo-calibracao", type=int, default=600,
                        help="segundos para as tres cabines calibrarem (padrao 600)")
    parser.add_argument("--cenario", default="down-peak",
                        choices=("up-peak", "down-peak", "interfloor"),
                        help="cenario disparado no modo simulado")
    parser.add_argument("--duracao-cenario", type=float, default=None,
                        help="duracao do cenario em s (placa: 300, do simulador; "
                             "simulado: 120)")
    parser.add_argument("--verboso", action="store_true",
                        help="mostra o log das cabines e do central no terminal")
    args = parser.parse_args(argv)
    if args.duracao_cenario is None:
        args.duracao_cenario = 120.0 if args.simulado else 300.0

    pasta = os.path.join(RAIZ, "dados", "teste_" + time.strftime("%Y%m%d_%H%M%S"))
    os.makedirs(pasta, exist_ok=True)
    if args.simulado:
        bancada = BancadaSimulada(pasta, args.verboso)
    else:
        impedimentos, avisos = verifica_a_placa()
        for aviso in avisos:
            print("AVISO: " + aviso, flush=True)
        if impedimentos:
            for impedimento in impedimentos:
                print("IMPEDIMENTO: " + impedimento, flush=True)
            return 1
        try:
            bancada = BancadaPlaca(pasta, args.verboso, args.matricula)
        except OSError as erro:
            print("IMPEDIMENTO: nao abriu a UART: %s" % erro, flush=True)
            return 1

    def encerra_por_sinal(numero_do_sinal, _quadro):
        raise KeyboardInterrupt(signal.Signals(numero_do_sinal).name)

    signal.signal(signal.SIGTERM, encerra_por_sinal)
    signal.signal(signal.SIGHUP, encerra_por_sinal)

    teste = Teste(bancada, args)
    print("Teste da Entrega Final (%s). Registro em %s"
          % ("simulado" if args.simulado else "placa", os.path.relpath(pasta, RAIZ)), flush=True)
    try:
        teste.roda()
    except KeyboardInterrupt:
        print("\nInterrompido: encerrando as cabines com seguranca.", flush=True)
    finally:
        teste.vigia.para()
        bancada.encerra()
    teste.relatorio(pasta)
    falhas = [r for r in teste.resultados if r.situacao == FALHOU]
    return 1 if falhas or teste.vigia.violacoes else 0


if __name__ == "__main__":
    sys.exit(main())
