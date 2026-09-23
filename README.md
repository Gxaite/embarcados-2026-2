# Fundamentos de Sistemas Embarcados 2026/2 — Trabalho 1

Repositório de trabalho do grupo, sincronizado com a Raspberry Pi da bancada.
Este arquivo é o **contexto do projeto**: o que precisa existir, o que vale nota,
e o que a bancada impõe. Consulte antes de decidir qualquer coisa.

- **Integrantes:** Gabriel Reis Scheidt Paulino, Samuel Afonso
- **Turma:** ver `CLAUDE.md` / a definir no README final
- **Enunciado oficial:** `gitlab.com/fse_fga/trabalhos-2026_2/trabalho-1-2026-2`

---

## 1. O sistema, em uma página

Sistema **distribuído** de controle de um grupo de elevadores: edifício
comercial de **6 andares** servido por **3 cabines**, operando em **Despacho por
Destino** — não há botão de sobe/desce nos andares; o passageiro declara origem
e destino num quiosque e o sistema escolhe a cabine.

Quatro processos independentes, todos na Raspberry Pi:

| Processo | Papel |
|:--|:--|
| Servidor Central | recebe as chamadas, decide qual cabine atende, coordena o grupo |
| Servidor Distribuído × 3 | um por cabine: PID de posição, encoder, sensor de andar, cortina |

Eles conversam por **TCP/IP**. O simulador do edifício roda numa **ESP32**, com
dashboard web em tempo real. Os três barramentos do trabalho:

- **GPIO** — motor (PWM + direção), encoder em quadratura, cortina, sensor de andar
- **UART / MODBUS RTU** — registradores das cabines (`0x11`–`0x13`) e do prédio (`0x20`)
- **I2C** — sensor de temperatura na Casa de Máquinas, e a escrita da Condição
  de Contorno que alimenta o watchdog

> Divergência a confirmar para a Entrega 2: o texto do enunciado fala em
> **BMP280** e o diagrama de arquitetura em **BME280**. São sensores diferentes
> (o BME também mede umidade) e o registrador de calibração não é o mesmo.

---

## 2. Entregas e prazos

| Entrega | Escopo | Data |
|:--|:--|:--|
| **Entrega 1** | Módulo da GPIO — controle de **uma** cabine, 3 andares | **30/09/2026** |
| **Entrega 2** | Módulos UART/MODBUS e I2C | *a definir* |
| **Entrega Final** | PID, calibração, cota de potência, despacho, TCP/IP | *a definir* |

> As datas são as da **nossa turma**, que usa o mesmo enunciado mas calendário
> próprio. O enunciado publicado no GitLab traz as datas da turma do Prof. Renato
> (20/09, 04/10 e 12/10) — **não são as nossas**. Entregas 2 e Final ainda não
> foram anunciadas.

Entregáveis de toda entrega: **repositório com README e instruções de execução**
(`requirements.txt` em Python, `Makefile` em C/C++) e **vídeo** — até 5 min na
Entrega 1, até 10 min na Final, **com a câmera aberta mostrando o rosto de todos
os integrantes**.

### Como entregar (Seção 4.1 do enunciado)

A entrega é **no GitLab**, não neste repositório do GitHub:

1. **Código** na branch `main`, e a entrega se dá pela **tag `v1.0`** no commit
   correspondente:
   ```bash
   git tag -a v1.0 -m "Entrega 1 - Modulo da GPIO"
   git push origin v1.0
   ```
2. **Vídeo** de até 5 min, no próprio repositório ou com link público
   (YouTube, Drive) no README da entrega.

> Este repositório do GitHub é público e existe só para levar o código até a
> placa sem precisar de credencial. **A entrega avaliada é a do GitLab.**

---

## 3. Entrega 1 — o que precisa existir

Escopo reduzido: **Cabine 1**, andares 0, 1 e 2, nas posições **0, 3000 e
6000 mm**.

### 3.1 Pinagem — Cabine 1 (BCM)

| Sinal | Função | BCM | Pino físico | Direção |
|:--|:--|:-:|:-:|:--|
| `PWM` | potência do motor | **13** | 33 | saída PWM 1 kHz |
| `DIR1` | direção 1 | **22** | 15 | saída on/off |
| `DIR2` | direção 2 | **23** | 16 | saída on/off |
| `ENC_A` | encoder canal A | **20** | 38 | entrada por interrupção |
| `ENC_B` | encoder canal B | **21** | 40 | entrada por interrupção |
| `CORTINA` | cortina de luz | **26** | 37 | entrada on/off |
| `SENSOR_ANDAR` | bandeirola | **0** | 27 | entrada on/off |

> **BCM ≠ pino físico.** `SENSOR_ANDAR` é o GPIO 0, que fica no pino 27 — não no
> pino 1. Contar pinos no conector achando que são números BCM é o erro clássico.

### Divergência em aberto — pinagem antiga × nova

O enunciado **trocou as colunas das Cabines 1 e 2** (commit *Mudança de Pinos —
Cabine 1*). A tabela acima é a nova, e é o padrão do código. Mas o dashboard da
bancada ainda rotula o Sensor de Andar como **"BCM 11"**, que é o número antigo.

| Sinal | Antiga | Nova |
|:--|:-:|:-:|
| `PWM` | 12 | 13 |
| `DIR1` | 17 | 22 |
| `DIR2` | 27 | 23 |
| `ENC_A` | 5 | 20 |
| `ENC_B` | 6 | 21 |
| `CORTINA` | 16 | 26 |
| `SENSOR_ANDAR` | 11 | 0 |

Enquanto o professor não confirmar, as duas estão selecionáveis. Dois minutos de
bancada resolvem — a que reagir ao widget é a certa:

```bash
python3 -m ferramentas.bringup entradas --pinagem nova
python3 -m ferramentas.bringup entradas --pinagem antiga
```

**Tabela de direção:** livre `00`, subir `10`, descer `01`, freio `11` (DIR1 DIR2).

### 3.2 Requisitos (Seção 4 do enunciado)

| # | Requisito |
|:-:|:--|
| 1 | Python, C/C++ ou Rust |
| 2 | **Mínimo dois níveis**: módulo de GPIO (baixo) e lógica de controle (alto). Arquivo único **zera a nota de qualidade** |
| 3 | Saídas on/off comandando `DIR1`/`DIR2` conforme a tabela de direção |
| 4 | PWM a **1 kHz**, duty de 0 a 100% |
| 5 | Cortina com **debounce** e impressão imediata dos eventos |
| 6 | Encoder **por interrupção nos dois canais**, com sentido e contador de **32 bits com sinal** |
| 7 | Sensor de Andar com as **duas bordas**, contagem em cada uma e centro pela média |
| 8 | Parada nos andares 0–2 dentro de **±10 mm** — e o widget precisa mostrar a cabine nivelada |
| 9 | **Sem busy-wait** |
| 10 | **SIGINT** tratado |
| 11 | `requirements.txt`/`Makefile` e instruções no README |
| 12 | Vídeo até 5 min: comando `andar` nos três andares, encoder acompanhando o widget, teste da cortina, e **medição de uma bandeirola** |

### 3.3 Critérios de avaliação — Entrega 1 (1,0 ponto)

| Item | Valor |
|:--|:-:|
| Saídas on/off — livre, subir, descer, freio | 0,15 |
| Saída PWM — 1 kHz, 0–100%, rampa de aceleração | 0,15 |
| Entrada on/off — cortina com debounce e log imediato | 0,20 |
| Entrada por interrupção — encoder em quadratura, sentido, 32 bits | 0,20 |
| Entrada on/off — Sensor de Andar, duas bordas e centro pela média | 0,10 |
| Controle de posição — ±10 mm, sem busy-wait, SIGINT | 0,20 |

> **Atenção ao critério global do Módulo da GPIO** (1,0 ponto na Tabela 2 do
> enunciado geral): ele pede entradas **"por polling e por interrupção"**. A
> tabela da Entrega 1 acima só cobra interrupção, mas o módulo precisa expor os
> **dois caminhos** de leitura para não perder esse ponto.

---

## 4. Limitações e restrições

### 4.1 Físicas e do simulador

- **Atrito estático:** o motor **não arranca abaixo de ~10% de duty**. Em
  movimento, qualquer duty move. Partida sempre em **rampa**, nunca em degrau.
- **Encoder:** 1000 pulsos/metro em quadratura 4× → **1 contagem = 1 mm**;
  3000 contagens por andar.
- **Tolerância de nivelamento: ±10 mm.**
- **Bandeirola muito mais larga que a tolerância**, e de **largura diferente em
  cada andar** — parar assim que o sensor sobe **não** nivela, e não dá para
  deduzir o centro por uma borda só. Daí a média das duas.
- **Cortina repica de propósito:** o simulador emite bounce em cada borda. Sem
  debounce, obstruções fantasmas.
- **Fim de curso:** não comandar movimento além de 6000 mm nem abaixo de 0 mm.

### 4.2 Elétricas

- GPIO da Raspberry Pi é **3,3 V e não tolera 5 V**. Não há fusível no caminho.
- **GND comum obrigatório** entre Raspberry Pi e ESP32.
- 16 mA por pino, 50 mA no total. O PWM é **sinal de comando** — o motor não é
  alimentado pela placa.

### 4.3 Conflitos de periférico

| Pino | Função alternativa | Consequência |
|:--|:--|:--|
| **BCM 0** (`SENSOR_ANDAR`, Cab. 1) | **ID_SD — EEPROM de identificação de HAT** | a Raspberry Pi sonda esse pino no boot. Funciona como GPIO comum depois que o sistema sobe, **mas não se houver um shield com EEPROM no barramento**. É o pino a vigiar com a pinagem nova |
| BCM 1 (`SENSOR_ANDAR`, Cab. 3) | ID_SC | idem |
| BCM 7, 8 (encoder da Cab. 3) | SPI0 CE1/CE0 | com SPI ligado, o pino não responde e **não há erro** |
| BCM 11 (`PWM` da Cab. 2) | SPI0 SCLK | idem |
| BCM 2, 3 | I2C1 — BMP280 | habilitar I2C, não usar como GPIO |
| BCM 14, 15 | UART — MODBUS | habilitar serial, **desabilitar o console** |

### 4.4 Da bancada remota

As placas são **compartilhadas, acessadas por SSH e usadas em slot cronometrado**
— o que invalida boa parte do procedimento de bancada presencial:

- **Sem `raspi-config`, sem reboot.** Mudar SPI/I2C/UART derruba quem está na
  fila. O que estiver configurado na placa é o que você tem.
- **Nada de montagem física.** A fiação já está feita; não dá para conferir fio
  a fio antes de energizar.
- **Protocolo obrigatório:** avisar placa e duração no subcanal do Discord →
  SSH → **limpar a GPIO ao terminar** → `exit`.
- **Queda de SSH mata o processo com o motor girando.** Trate `SIGHUP` além de
  `SIGINT`/`SIGTERM`, e rode dentro de `tmux`.
- **Tempo de bancada é o recurso escasso.** Código se escreve offline; medição,
  não. Todo slot deve entrar com um roteiro pronto.

---

## 5. Acesso à bancada

```bash
ssh <primeironome><ultimonome>@164.41.98.2 -p <porta>
```

Usuário = primeiro + último nome (ex.: *Gabriel Reis Scheidt Paulino* →
`gabrielpaulino`). Senha inicial = matrícula; troque no primeiro acesso, senha
vencida bloqueia o cadastro no bot do Discord.

| Placa | Porta |
|:--|:-:|
| rasp31 | 15021 *(offline)* |
| rasp32 | 15022 |
| rasp33 | 15023 |
| rasp34 | 15024 |
| rasp35 | 15025 |

As portas mudam — confira sempre o cabeçalho do subcanal.

**Bot do Discord:** `/cadastrar` associa a conta Discord ao login do SSH;
`/reiniciar_senha` devolve a senha à matrícula.

### Dashboard (widget do simulador)

O widget é um dashboard **ThingsBoard**, um por placa. É onde a cabine aparece,
onde fica o botão **"Obstruir porta"** e onde se confere o nivelamento exigido
pelo requisito 8. Link da rasp42:

```
https://tb.fse.lappis.rocks/dashboard/2f3c9990-b11b-11f1-9a0b-0359851b5c05?publicId=86d17ff0-e010-11ef-9ab8-4774ff1517e8
```

Abas: **Elevador Único** (a da Entrega 1), **Terminal UART** (MODBUS, Entrega 2)
e **Edifício** (prédio completo de 6 andares e 3 cabines, Entrega Final).

Na aba **Elevador Único**, o painel "Bancada de Controle — Cabine 1" oferece:

| Controle | Para que serve no nosso roteiro |
|:--|:--|
| **Enviar cabine ao andar 0 / 1 / 2** | move a cabine **sem passar pelo nosso código** — é como estimular `SENSOR_ANDAR` e o encoder antes de confiar no motor |
| **Obstruir porta (3 s)** | o estímulo da cortina exigido pelo requisito 12 |
| **Sensor de Andar** | mostra se a cabine está dentro da bandeirola ou entre andares |
| **Ocupação (depuração)** | número de passageiros |
| **Resetar bancada** | **zera a Posição sem mover a cabine** |

> **"Resetar bancada" importa mais do que parece.** A posição da bancada é
> absoluta e não começa em zero — ela guarda o que a sessão anterior deixou, e
> pode estar negativa. Sem resetar no início do slot, a contagem do nosso
> encoder e a do widget falam de referências diferentes, e todo o nivelamento
> parece errado sem que haja nada errado no código. O painel também mostra
> região de **sobrecurso** acima do andar 2.

> **Confira sempre de qual placa é a aba aberta.** A URL do ThingsBoard carrega
> o histórico de navegação no parâmetro `state`, e é fácil acabar com a aba do
> elevador apontada para o dispositivo de outra rasp. Se o que você comanda não
> aparece no widget, é a primeira coisa a checar. Os links das demais placas
> estão na seção "Links dos Dashboards" do enunciado.

### Estado conferido na rasp42 (23/09/2026)

- SPI **desabilitado** — com a pinagem nova isso deixou de importar para a
  Cabine 1 (o BCM 11 saiu), mas o **BCM 0** entrou e traz o conflito de EEPROM
  de HAT descrito acima. A conferir na próxima sessão.
- `RPi.GPIO 0.7.1a4` no Python do sistema — **não precisa de venv**

---

## 6. Arquitetura e execucao

O codigo esta nos dois niveis exigidos pelo requisito 2. O pacote
`src/controle/` **nunca importa `RPi.GPIO`**: ele so conversa com as classes de
`src/gpio/`, que por sua vez falam com um *backend* intercambiavel.

```
src/
├── gpio/                  BAIXO NIVEL - pino, nivel logico, duty, borda
│   ├── pinos.py           mapa BCM da Cabine 1 e tabela de direcao
│   ├── backend.py         interface abstrata de acesso a GPIO
│   ├── rpi_backend.py     implementacao real, via RPi.GPIO
│   ├── sim_backend.py     modelo do poco em software
│   ├── saidas.py          saida on/off e saida PWM a 1 kHz
│   ├── entradas.py        entrada por POLLING e entrada por INTERRUPCAO
│   └── encoder.py         quadratura 4x por interrupcao nos dois canais
├── controle/              ALTO NIVEL - andar, milimetro, nivelamento
│   ├── posicao.py         conversoes, tolerancia de +-10 mm, limites do poco
│   ├── motor.py           tabela de direcao e rampa de duty
│   ├── cortina.py         eventos de obstrucao e liberacao
│   ├── sensor_andar.py    medicao da bandeirola pelas duas bordas
│   └── cabine.py          malha de posicao a 50 ms
├── cli.py                 interface de terminal
└── main.py                ponto de entrada e tratamento de sinais

ferramentas/bringup.py     ativacao da placa por etapas
```

O ganho dessa separacao e o backend simulado: a mesma logica de controle roda
contra um modelo do poco em software, o que permite desenvolver e testar **sem
gastar slot de bancada**.

### Na Raspberry Pi

```bash
git pull
python3 -m src.main
```

A RPi.GPIO ja vem no Python do sistema da placa do laboratorio — nao e preciso
venv nem `pip install`.

### Sem a placa

```bash
python3 -m src.main --simulado
```

### Comandos

```
andar <0|1|2>            viaja ate o andar (malha fechada no encoder)
ir <mm>                  viaja ate uma posicao em mm
motor <direcao> <duty>   acionamento direto; direcao = livre|subir|descer|freio
parar                    zera o PWM e aplica o freio
estado                   imprime o estado completo da cabine
zera [mm]                redefine a contagem do encoder
medicoes                 lista as bandeirolas ja medidas
ancora                   corrige a contagem pela ultima bandeirola medida
obstruir | liberar       (so no modo simulado) aciona a cortina de luz
sair                     encerra o programa em seguranca
```

Na bancada, a cortina e estimulada pelo botao **"Obstruir porta"** do widget.

### Quando a contagem e o widget discordam

A contagem do encoder e **relativa**: ela mede deslocamento desde onde foi
zerada. O widget tem o proprio contador, e o botao **"Resetar bancada" zera o
dele sem avisar a Raspberry**. Apertar esse botao com o programa rodando faz os
dois passarem a falar de referencias diferentes — voce manda ir ao andar 1 e o
widget mostra a cabine chegando no 0.

Nao ha canal para a bancada avisar a Raspberry disso na Entrega 1; isso so
chega na Entrega 2, por MODBUS. As saidas sao duas:

1. **Nao apertar "Resetar bancada" com o programa rodando.** Se precisar,
   reinicie o programa depois.
2. **Reancorar pela bandeirola.** As bandeirolas estao em posicoes absolutas
   conhecidas, entao uma travessia completa diz onde a cabine realmente esta:

   ```
   andar 2      # atravessa a bandeirola do andar 1 por inteiro
   ancora       # corrige a contagem pelo centro medido
   ```

   O comando so funciona depois de uma travessia **completa** — parar dentro da
   bandeirola nao produz borda de saida, e sem as duas bordas nao ha centro.

> Na Entrega Final a reancoragem deixa de ser comando e passa a ser automatica
> a cada passagem por bandeirola — e um item da tabela de avaliacao. O que esta
> aqui e o nucleo daquele procedimento.

### Fim de curso: manual e malha fechada sao casos diferentes

O andar 2 fica em **6000 mm, que e o proprio limite do poco**. Uma margem de
seguranca aplicada em malha fechada cortaria a viagem antes da chegada, entao
ela vale **so no acionamento manual**, onde nao ha rampa de aproximacao
freando antes e a inercia precisa ser absorvida.

> Medido na rasp42: com margem de 5 mm, o `motor subir` parou em **6010 mm** —
> a inercia levou 15 mm alem do ponto de corte. A margem manual passou para
> **25 mm**.

### Renivelamento

O motor nao arranca abaixo de ~10% de duty, entao existe uma velocidade minima
e, com ela, uma **distancia minima de frenagem**. Quando essa distancia supera a
tolerancia de +-10 mm, nao existe ganho que acerte em uma tacada so.

> Medido na rasp42: o `andar 2` freou no ponto certo e a inercia levou ate
> **6016 mm** — 16 mm alem do nominal, fora da tolerancia.

A solucao e a dos elevadores de verdade: parar, deixar **assentar**, medir de
novo e corrigir com **pulsos curtos** de duty minimo. Cada pulso dura poucos
ciclos da malha e e seguido de nova medicao, o que faz a correcao convergir
como uma bisseccao em vez de oscilar. A duracao do pulso e proporcional ao que
falta — pulso fixo ou nao sai de erro grande, ou passa do ponto no pequeno.

A chegada passa a informar quantos renivelamentos foram necessarios:

```
CHEGADA: 3008 mm (destino 3000 mm, erro +8 mm, andar 1, 2 renivelamento(s))
```

> Os pulsos nao passam pela rampa do motor. Pela rampa o duty subiria poucos
> pontos por ciclo e nunca venceria o atrito estatico: a cabine ficaria zumbindo
> sem sair do lugar.

### Protecao contra travamento

Se o destino for inalcancavel — tipicamente porque a contagem derivou e aponta
para fora do poco fisico — a cabine encosta no batente e o encoder para de
contar. Sem tratamento, a malha comandaria motor indefinidamente contra o fim
de curso mecanico. A malha aborta apos **3 segundos** de motor comandado sem a
cabine sair do lugar, e sugere o `ancora`.

### Roteiro de bancada

Da etapa mais segura para a menos — entradas antes de saidas, saidas antes de
movimento. As duas ultimas pedem confirmacao e movem o motor:

```bash
python3 -m ferramentas.bringup mapa       # confere a pinagem, nao toca na GPIO
python3 -m ferramentas.bringup entradas   # so le CORTINA e SENSOR_ANDAR
python3 -m ferramentas.bringup encoder    # conta bordas e transicoes invalidas
python3 -m ferramentas.bringup direcao    # MOVE: percorre a tabela de direcao
python3 -m ferramentas.bringup pwm        # MOVE: mede o duty de arranque
python3 -m ferramentas.bringup limpa      # libera a GPIO ao encerrar o slot
```

Use `--simulado` para ensaiar o roteiro antes de entrar na placa.

### Testes

```bash
python3 -m pytest tests/ -q
```

Os testes de integracao rodam em tempo real e levam cerca de tres minutos.

---

## 7. Onde cada requisito esta atendido

| # | Requisito | Onde |
|:-:|:--|:--|
| 1 | Python | Python 3 |
| 2 | Dois niveis | `src/gpio/` e `src/controle/`; `controle/` nao importa `RPi.GPIO` |
| 3 | `DIR1`/`DIR2` pela tabela | `gpio/pinos.py::DIRECOES`, `controle/motor.py` |
| 4 | PWM 1 kHz, 0–100% | `gpio/saidas.py::SaidaPWM` |
| 5 | Cortina com debounce e log imediato | `gpio/entradas.py::EntradaInterrupcao`, `controle/cortina.py` |
| 6 | Encoder por interrupcao nos dois canais, 32 bits | `gpio/encoder.py` |
| 7 | Sensor de Andar, duas bordas e centro pela media | `controle/sensor_andar.py` |
| 8 | Parada em +-10 mm | `controle/cabine.py::_passo_de_controle` |
| 9 | Sem busy-wait | malha em `Event.wait(0.050)`, debounce em `threading.Timer`, CLI em `input()` |
| 10 | SIGINT tratado | `src/main.py::encerra` (e tambem SIGTERM e SIGHUP) |
| 11 | `requirements.txt` e instrucoes | este arquivo |
| 12 | Video ate 5 min | *(a gravar)* |
| — | Entradas por **polling e por interrupcao** | `gpio/entradas.py`: `EntradaPolling` e `EntradaInterrupcao`, ambas em uso em `controle/cabine.py` |

---

## 8. Medicoes da bancada — rasp42, 23/09/2026

Medido com a **pinagem nova**, que e a que a bancada usa (ver Secao 3).

| Grandeza | Valor medido | Observacao |
|:--|:--|:--|
| Bandeirola do andar 0 | ~190 mm | saida da borda em 95 mm, partindo do centro |
| Bandeirola do andar 1 | **242 mm** e **241 mm** | duas travessias independentes |
| Bandeirola do andar 2 | ~142 mm | entrada em 5929 mm |
| Centro medido — andar 1 | **3000,0 mm** e **3002,5 mm** | erro **+0,0 mm** e **+2,5 mm** |
| Erro de parada — `andar 1` | **-2 mm** | tolerancia e +-10 mm |
| `transicoes_invalidas` | **1** na sessao inteira | a 40% de duty |
| Fim de curso | parou em 6010 mm | manual; a margem foi de 5 para 25 mm |
| Inercia de frenagem | ~16 mm | `andar 2` parou em 6016 mm; originou o renivelamento |
| Encoder vs. widget | **6010 mm contra 6011 mm** | 1 mm de erro em 6 m de curso |
| Cortina | obstruida e liberada com 3 s | botao "Obstruir porta (3 s)" |

As tres bandeirolas tem **larguras diferentes** — 190, 242 e 142 mm — o que
confirma na pratica por que o centro precisa da media das duas bordas: sao
larguras de ate 242 mm contra uma tolerancia de +-10 mm, e nao ha como deduzir
o centro a partir de uma borda so.

### Ainda a medir

| Grandeza | Onde ajustar |
|:--|:--|
| Duty minimo de arranque | `ferramentas/bringup.py pwm` |
| `transicoes_invalidas` em duty maximo | se crescer, reduzir `DUTY_MAXIMO` |
| `GANHO_P`, `DUTY_MAXIMO` | `src/controle/cabine.py` |
| `TAXA_RAMPA_POR_S` | `src/controle/motor.py` |

> **Sobre `transicoes_invalidas`.** No simulador ele fica em zero; na bancada
> nao vai ficar, porque ha ruido eletrico real. Um outro grupo relatou de 2% a
> 27% de bordas invalidas. Na nossa sessao deu **1 ocorrencia** a 40% de duty.
> O decodificador **descarta** a transicao impossivel em vez de chutar contagem,
> entao o erro vira posicao perdida, nao posicao errada — mas ele acumula, e e
> por isso que o Sensor de Andar existe como referencia absoluta.

## 9. Sincronizando com a placa

```bash
git clone https://github.com/Gxaite/embarcados-2026-2.git   # primeira vez
git pull                                                     # nos slots seguintes
```

O repositório é público para dispensar credencial na placa compartilhada. **Não
comitar matrícula, senha ou chave aqui.**
