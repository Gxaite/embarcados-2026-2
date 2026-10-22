# Elevador Embarcado: Trabalho 1

Fundamentos de Sistemas Embarcados, 2026/2. Controle de um grupo de três
elevadores com Despacho por Destino em uma Raspberry Pi, contra o simulador de
edifício da ESP32 da bancada.

| Entrega | Conteúdo | Tag | Comando |
|:--|:--|:-:|:--|
| 1 | GPIO e malha de posição da Cabine 1 | `v1.0` | `python3 -m src.main` |
| 2 | UART-MODBUS (Partes 1, 2 e 3) e I2C | `v2.0` | `python3 -m src.comunicacao --matricula <matricula>` |
| Final | Servidor Central e três Servidores Distribuídos | `v3.0` | `ferramentas/sobe_tudo.sh` |

## Integrantes

Listados no repositório de entrega.

## Vídeos

| Entrega | Link |
|:--|:--|
| 1 | https://youtu.be/LKAWTPL8WLw |
| 2 | https://youtu.be/ICxFs3GONZo |
| Final | a ser adicionado |

## Entrega Final

### Instalação

Python 3, sem dependências além da biblioteca padrão e da `RPi.GPIO`, que já
vem no Python da Raspberry Pi do laboratório. Em outra máquina (modo simulado,
testes e gráficos): `pip install -r requirements.txt`.

```bash
git clone https://github.com/Gxaite/embarcados-2026-2.git && cd embarcados-2026-2
echo <matricula> > matricula      # matrícula dos quadros MODBUS (ignorado pelo git)
```

### Configuração

Cada processo lê um arquivo em `config/`:

| Arquivo | Conteúdo |
|:--|:--|
| `cabine1.json`, `cabine2.json`, `cabine3.json` | pinos BCM (Tabela 1), endereço MODBUS, porta TCP, ganhos do PID, duty da calibração, tempo de porta aberta |
| `central.json` | UART, barramento I2C, endereço e porta TCP de cada cabine, arquivos de estado e de log |

As portas TCP padrão são 10101, 10102 e 10103, em `127.0.0.1`: os quatro
processos rodam na mesma placa. Para distribuir em máquinas diferentes basta
trocar o `host` de cada cabine no `central.json`.

### Execução

Os quatro processos sobem **em qualquer ordem**, cada um no seu terminal. O
script abaixo abre uma sessão `tmux` com uma janela para cada (Ctrl+b e o
número troca de janela):

```bash
ferramentas/sobe_tudo.sh               # ou, para gravar os CSVs dos gráficos:
ferramentas/sobe_tudo.sh --registra    # dados/pid_cabineN.csv e dados/potencia.csv
```

Ou à mão:

```bash
python3 -m src.central                 # painel em tela cheia; --sem-tela para texto
python3 -m src.distribuido --cabine 1
python3 -m src.distribuido --cabine 2
python3 -m src.distribuido --cabine 3
```

Ao conectar, cada cabine calibra sozinha (varredura de subida e de descida) e
vai nivelar no andar mais próximo; a partir daí atende as chamadas feitas no
quiosque do dashboard ou os Cenários de Tráfego.

Comandos do painel do Servidor Central:

| Comando | Função |
|:--|:--|
| `vai <cabine> <andar>` | envia a cabine ao andar (comando manual) |
| `corta-cota <cabine> [s]` | suspende a Cota da cabine por `s` segundos (padrão 15): ensaio do Modo Degradado |
| `status` | painel em texto |
| `sair` | encerra (o mesmo que Ctrl+C) |

![Painel do Servidor Central](docs/imagens/painel.png)

Ctrl+C em qualquer processo encerra com segurança: a cabine zera o PWM, põe a
direção em freio e libera GPIO e TCP; o central salva o estado e fecha UART,
I2C e TCP. Subindo de novo, os outros reconectam sozinhos e o central reenvia
às cabines as chamadas pendentes salvas em disco.

### Sem a placa: modo simulado

```bash
python3 -m src.simulacao
```

Sobe num processo só o prédio simulado (`src/simulacao/`), as três cabines e o
central, com o mesmo código da placa e TCP de verdade em localhost. Comandos a
mais no painel: `chamada <origem> <destino>`, `cenario up-peak|down-peak|interfloor`,
`obstrui <cabine> [s]`, `derruba <cabine> [s]` (queda de TCP), `calor <°C>` e
`violacoes`.

## Arquitetura

```
                       Raspberry Pi
 +--------------------------------------------------------------+
 |  Servidor Central (src/central)       UART /dev/serial0 ------+--> ESP32: cabines 0x11-0x13
 |   contorno | predio | cabines | fila | cotas  I2C 0x76 (BMP280) |    e prédio 0x20
 |       |  TCP 10101   |  TCP 10102   |  TCP 10103              |
 |  Cabine 1         Cabine 2         Cabine 3  (src/distribuido)|
 |  GPIO 13,22,23..  GPIO 11,17,27..  GPIO 18,24,25..  ----------+--> motor, encoder, cortina,
 +--------------------------------------------------------------+    sensor de andar
```

- **Servidor Central** é o único dono da UART e do I2C. Cada cabine pede a ele
  o que é MODBUS da cabine (comando de porta, leitura de `andar_atual` e
  `porta_estado`), e ele encaminha a cada uma os registradores dela a cada 500 ms.
- **Servidores Distribuídos** são os únicos donos das GPIOs da sua cabine:
  PWM, direção, encoder, cortina e Sensor de Andar.
- **TCP**: cada cabine escuta na sua porta e o central conecta nas três,
  tentando de novo a cada segundo. Mensagens são um objeto JSON por linha
  (`src/rede/protocolo.py`):

| Sentido | Mensagem | Quando |
|:--|:--|:--|
| central → cabine | `cota` (mA, validade 2 s, número de sequência) | a cada 1 s |
| central → cabine | `chamada` (id, origem, destino) | atribuição do Despacho; reenviada após reconexão |
| central → cabine | `vai_andar`, `registradores`, `resposta` | comando manual, leitura MODBUS, resposta a pedido |
| cabine → central | `estado` (posição, andar, sentido, porta, corrente, Cota, paradas, eventos de embarque/desembarque) | a cada 500 ms |
| cabine → central | `pedido` (`le_cabine`, `porta abrir/fechar`) | ciclo de porta e calibração |

Uma conexão sem mensagem por 5 s é dada como morta, e cai para os dois lados.
Os eventos de embarque e desembarque vão repetidos nos relatórios de estado e o
central descarta os que já conhece, de modo que uma queda no meio não perde
evento.

## Implementação

**Controle PID de posição** (`src/distribuido/pid.py`, `malha.py`)

- Malha de 50 ms sobre a contagem do encoder (quadratura 4x por interrupção
  nos dois canais, 1 contagem = 1 mm, inteiro de 32 bits). O `posicao_mm` do
  MODBUS não é usado em lugar nenhum da malha.
- PID discreto por amostra, `u = Kp·e + Ki·Σe + Kd·Δ`, com a derivada sobre a
  medida (troca de destino no meio da viagem não dá chute), anti-windup por
  integração condicional e separação do integral (só acumula a menos de 50 mm
  do destino). A saída vira duty de 0 a 100% e direção (`DIR1`/`DIR2`).
- Rampa de aceleração de 100 %/s na subida do duty; reduzir é imediato.
- Atrito estático: parado, com a saída abaixo de 12% e erro acima de 30 mm, a
  saída vai ao arranque; abaixo de 30 mm o integral é congelado (sem windup) e
  o erro residual é corrigido por pulsos de arranque, cada um seguido de freio
  e nova medição. A cabine só é dada como chegada parada e a menos de 6 mm.
- Fim de curso: 300 mm além dos andares extremos calibrados o movimento é
  cortado; travamento (duty sem deslocamento por 2,5 s) também.

**Calibração e Sensor de Andar** (`bandeirola.py`, `calibracao.py`, `mapa.py`)

- O Sensor de Andar é lido por interrupção nas duas bordas, com a contagem e o
  sentido do encoder capturados na borda crua, antes do debounce.
- Na partida a cabine desce até sair da bandeirola do andar 0, sobe
  atravessando as seis (varredura de subida) e desce de novo (varredura de
  descida). A qual andar pertence cada bandeirola é perguntado ao central
  (`andar_atual`, registrador 0) na entrada dela. O registrador `nivelado`
  nunca é consultado.
- Cada borda é a média das duas varreduras; o andar é a média das duas
  bordas. O mapa vai para `dados/calibracao_cabineN.json`.
- **Reancoragem**: cada borda cruzada na operação é classificada (inferior ou
  superior, pelo sentido) e a contagem é corrigida para o valor calibrado
  daquela borda. Correção acima de 80 mm é recusada como ruído.

**Cota de Potência e Modo Degradado** (`cota.py`, `src/central/cotas.py`)

- A cabine satura o PID em `duty_max = cota / 6000 × 100`, aplicado no
  instante em que a Cota chega e um ciclo antes de ela vencer.
- O central reparte `barramento_max_ma`: 1000 mA para cada cabine, o resto
  para as que têm viagem, até 6000 mA cada. Uma Cota enviada conta como em uso
  até a cabine confirmar uma posterior (número de sequência no relatório) ou
  vencer: assim uma redução sempre chega antes do aumento que ela libera, e a
  soma nunca passa do barramento nem no transitório. Cabine sem Cota (caída ou
  suspensa) fica com 1000 mA reservados, que é o que ela usa em degradado.
- Sem Cota válida a cabine entra em Modo Degradado: teto de 1000 mA, pouso no
  próximo andar no sentido do movimento, nivelamento, porta aberta até voltar
  a Cota.

**Despacho por Destino** (`src/central/despacho.py`)

- Cada chamada vai para a cabine de menor custo estimado: tempo até a porta
  abrir na origem, percorrendo o itinerário da cabine na ordem em que ela o
  executa (SCAN), mais o atraso imposto aos passageiros já atribuídos e uma
  fração da viagem do passageiro novo. Origem que já é parada da cabine não
  custa parada nova: é o agrupamento de passageiros.
- Só entram cabines calibradas e operando. Sem nenhuma, a chamada fica na fila
  do simulador: toda chamada retirada é atribuída e atendida.
- Fluxo da Seção 5.3: lê a fila, atribui (offsets 9 e 10 numa escrita só),
  retira (`chamada_pop`, sem repetir às cegas) e avisa a cabine.
- Log persistente em `dados/viagens.csv` (id, origem, destino, cabine,
  registro, embarque, desembarque, espera, viagem) e estado em
  `dados/central_estado.json`, regravado de forma atômica a cada mudança.

**Porta e cortina** (`src/distribuido/porta.py`)

- Abrir, esperar `tempo_aberta_s`, fechar; a cabine só anda com a porta
  confirmada fechada pelo MODBUS. Cortina por interrupção com debounce de
  20 ms: obstruída, o fechar não é enviado; obstrução durante o fechamento
  inibe o ciclo, que é reiniciado 0,5 s depois de a obstrução cessar.

**Qualidade**: nenhum laço sem espera (todas as threads dormem em
`Event.wait`, `select` ou no `recv` do socket); SIGINT, SIGTERM e SIGHUP
tratados nos quatro processos.

## Experimentos

Os gráficos abaixo saíram do prédio simulado (`src/simulacao/`), que reproduz
atrito estático, inércia, quadratura, bandeirolas de largura variável e perda
de bordas do encoder, mas não o motor da bancada. Os ganhos ficam no arquivo de
configuração para serem reajustados na placa; os mesmos gráficos saem dos CSVs
gravados nela com `ferramentas/sobe_tudo.sh --registra` e
`python3 -m ferramentas.graficos --pid dados/pid_cabine1.csv --potencia dados/potencia.csv`.

### Sintonia do PID

Partimos dos valores sugeridos (Kp = 0,5, Ki = 0,05, Kd = 40) e variamos o Kd,
numa viagem de 3 andares com Cota de 4000 mA (`python3 -m ferramentas.experimentos pid`):

![Sintonia do PID](docs/imagens/pid_sintonia.png)

| Kd | 1 andar | 3 andares | Observação |
|:-:|:-:|:-:|:--|
| 40 | 24,4 s | 33,7 s | amortecimento excessivo: constante de tempo Kd/Kp·T = 4 s na aproximação; a derivada sobre a contagem quantizada em 1 mm faz o duty chavear |
| **15** | **11,2 s** | **20,3 s** | escolhido: sobrepasso de até 4 mm, sem pulsos de renivelamento |
| 5 | 9,0 s | 18,6 s | passa cerca de 19 mm do andar e volta por pulsos |

Duas correções saíram da sintonia: o integral, acumulado na viagem inteira,
fazia a cabine passar 30 mm do andar com qualquer Kd (daí a separação do
integral), e com Kd = 40 a cabine levava mais tempo na aproximação do que em
toda a viagem.

![Chegada](docs/imagens/pid_chegada.png)

### Saturação pela Cota

Viagem do andar 0 ao 5 com a Cota caindo de 6000 para 3000 mA e depois para
1000 mA (`python3 -m ferramentas.experimentos cota`). O duty acompanha o teto
no mesmo ciclo e nunca o ultrapassa:

![Saturação pela Cota](docs/imagens/pid_cota.png)

### Cenários de Tráfego

Sistema completo, três cenários de 5 minutos, com semente fixa e uma chamada a
cada 5 s em média (`python3 -m ferramentas.experimentos cenarios`):

Resultados da rodada no simulador: em atualização (`docs/experimentos/cenarios.json`).

## Estrutura

```
src/
├── gpio/          Entrega 1: saídas on/off e PWM, entradas por polling e interrupção, encoder
├── controle/      Entrega 1: motor, cortina, sensor de andar e malha da Cabine 1
├── uart/          Entrega 2: porta serial, CRC-16, MODBUS (usado pelo Servidor Central)
├── i2c/           Entrega 2: driver do BMP280
├── rede/          Final: TCP com JSON por linha, servidor (cabine) e cliente com reconexão (central)
├── distribuido/   Final: Servidor Distribuído (PID, calibração, cota, porta, itinerário)
├── central/       Final: Servidor Central (despacho, cotas, Condição de Contorno, registro, painel)
├── simulacao/     Final: prédio simulado para rodar e testar sem a placa
├── configuracao.py   leitura de config/*.json
├── main.py        ponto de entrada da Entrega 1
└── comunicacao.py ponto de entrada da Entrega 2
config/            um arquivo por cabine e um do central
ferramentas/       sobe_tudo.sh, experimentos, gráficos, bring-up da Entrega 1
```

## Testes

```bash
python3 -m pytest tests/ -q -m "not lento"   # unidades, segundos
python3 -m pytest tests/ -q                  # inclui o sistema completo no simulador (minutos)
```

## Entregas anteriores

### Entrega 1: GPIO

```bash
python3 -m src.main
```

Antes de iniciar, posicionar a cabine no andar 0 e acionar "Resetar bancada"
no dashboard. Comandos: `andar <0|1|2>`, `ir <mm>`,
`motor <livre|subir|descer|freio> <duty>`, `parar`, `estado`, `sair`.

### Entrega 2: UART e I2C

```bash
python3 -m src.comunicacao --matricula <matricula>
```

Menu com as Partes 1 (protocolo simplificado), 2 (MODBUS didático) e 3
(demonstração de watchdog, porta, fila e exceções) e um terminal de comandos
(`ajuda` lista). São usados os 6 últimos dígitos da matrícula.

Matrícula em destaque no terminal UART:

![Matrícula no terminal UART](images/Terminal_UART2.jpeg)
![Matrícula no terminal UART](images/Terminal_UART1.jpeg)

A verificação da placa por etapas está em [docs/BANCADA.md](docs/BANCADA.md).
