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
- **I2C** — BMP280, e a escrita da Condição de Contorno que alimenta o watchdog

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

---

## 3. Entrega 1 — o que precisa existir

Escopo reduzido: **Cabine 1**, andares 0, 1 e 2, nas posições **0, 3000 e
6000 mm**.

### 3.1 Pinagem — Cabine 1 (BCM)

| Sinal | Função | BCM | Pino físico | Direção |
|:--|:--|:-:|:-:|:--|
| `PWM` | potência do motor | 12 | 32 | saída PWM 1 kHz |
| `DIR1` | direção 1 | 17 | 11 | saída on/off |
| `DIR2` | direção 2 | 27 | 13 | saída on/off |
| `ENC_A` | encoder canal A | 5 | 29 | entrada por interrupção |
| `ENC_B` | encoder canal B | 6 | 31 | entrada por interrupção |
| `CORTINA` | cortina de luz | 16 | 36 | entrada on/off |
| `SENSOR_ANDAR` | bandeirola | 11 | 23 | entrada on/off |

> **BCM ≠ pino físico.** `DIR1` é GPIO 17 no pino 11; `SENSOR_ANDAR` é GPIO 11 no
> pino 23. Os dois trocam exatamente um pelo outro — é o erro clássico.

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
| BCM 11 (`SENSOR_ANDAR`, Cab. 1) | **SPI0 SCLK** | com SPI ligado, o pino não responde e **não há erro** |
| BCM 7, 8 (encoder da Cab. 3) | SPI0 CE1/CE0 | idem |
| BCM 0, 1 (`SENSOR_ANDAR` Cab. 2 e 3) | ID_SD/ID_SC, EEPROM de HAT | conferir se há shield no barramento |
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

### Estado conferido na rasp42 (23/09/2026)

- SPI **desabilitado** → BCM 11 livre (`func=INPUT pull=NONE`)
- `RPi.GPIO 0.7.1a4` no Python do sistema — **não precisa de venv**

---

## 6. Sincronizando com a placa

```bash
git clone https://github.com/Gxaite/embarcados-2026-2.git   # primeira vez
git pull                                                     # nos slots seguintes
```

O repositório é público para dispensar credencial na placa compartilhada. **Não
comitar matrícula, senha ou chave aqui.**
