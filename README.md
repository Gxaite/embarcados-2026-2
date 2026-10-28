# Elevador Embarcado: Trabalho 1

Fundamentos de Sistemas Embarcados, 2026/2. Controle de um grupo de três
elevadores com Despacho por Destino em uma Raspberry Pi, contra o simulador de
edifício da ESP32 da bancada.

| Entrega | Conteúdo | Tag | Comando |
|:--|:--|:-:|:--|
| 1 | GPIO e malha de posição da Cabine 1 | `v1.0` | `python3 -m src.main` |
| 2 | UART-MODBUS (Partes 1, 2 e 3) e I2C | `v2.0` | `python3 -m src.comunicacao --matricula <matricula>` |
| Final | Servidor Central e três Servidores Distribuídos | `v3.0` | `./elevador placa` |

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

Todos os comandos passam pelo script `./elevador` (sem argumento, ele lista os
comandos):

| Comando | Função |
|:--|:--|
| `./elevador placa` | central e três cabines, uma janela do `tmux` cada, gravando `dados/pid_cabineN.csv` e `dados/potencia.csv` |
| `./elevador para` | Ctrl+C em cada processo (estado salvo, motores em freio) e fecha a sessão |
| `./elevador teste` | teste de aceitação na placa (seção [Testes](#testes)) |
| `./elevador simulado` | sistema completo sem placa (abaixo) |
| `./elevador graficos <pasta>` | gráficos dos CSVs copiados da placa ([Experimentos](#experimentos)) |

Antes de subir, confira no dashboard que nenhuma cabine está com falha
(registrador `falha` diferente de zero, borda vermelha na cabine): com falha
ativa a ESP32 ignora o motor e a calibração trava. O reset do dashboard limpa.

Na sessão do `./elevador placa`, `Ctrl+b` e o número troca de janela: 0 é o
painel do central, 1 a 3 são as cabines. Ctrl+C numa janela derruba só aquele
processo; `Ctrl+b c` abre uma janela nova para subi-lo de novo.

Os quatro processos sobem **em qualquer ordem**. À mão, um terminal para cada:

```bash
python3 -m src.central                 # painel em tela cheia; --sem-tela para texto
python3 -m src.distribuido --cabine 1  # uma de cada vez: subindo juntas no mesmo
python3 -m src.distribuido --cabine 2  # diretório, a lgpio disputa o pipe .lgd-nfy0
python3 -m src.distribuido --cabine 3  # e a cabine que perde morre no import
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
./elevador simulado                    # o mesmo que python3 -m src.simulacao
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

**Despacho por Destino** (`src/central/despacho.py`, `src/distribuido/itinerario.py`)

- Cada chamada vai para a cabine de menor custo estimado: tempo até a porta
  abrir na origem, percorrendo o itinerário da cabine na ordem em que ela o
  executa (SCAN), mais o atraso imposto aos passageiros já atribuídos e uma
  fração da viagem do passageiro novo. Origem que já é parada da cabine não
  custa parada nova: é o agrupamento de passageiros.
- Limite de 90 s: a viagem é estimada na velocidade da fatia de um terço do
  barramento (a Cota que a cabine tem com as três ocupadas, corrigida pelo
  fator de corrente medido), e a chamada que levaria alguém além de 75 s de
  espera é penalizada. Na cabine, uma origem esperando há mais de 50 s passa
  na frente da varredura. Parada num andar, a cabine informa o sentido da
  varredura, e a parada no andar em que ela está entra primeiro na estimativa.
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

### Na placa (rasp52, 28/10/2026)

`./elevador teste` na rasp52, que tem o BMP280 em `0x76`:

| Item | Resultado |
|:--|:--|
| Comunicação TCP | cabines subiram antes do central; as três conectadas em 1 s |
| Condição de Contorno | BMP280 a 24,5 °C, `watchdog_ambiente` = 0, `barramento_max_ma` = 12000 (a fórmula dá 12000) |
| Calibração | 98 s para as três juntas; vãos de 2865 a 3090 mm, bandeirolas de 121 a 281 mm |
| PID | 6 de 6 viagens niveladas pelo registrador `nivelado`, erro de chegada de −7,5 a +8,0 mm |
| Malha de 50 ms | 4393 ciclos, atraso médio 0,09 ms e máximo 2,6 ms, nenhum perdido, sem SCHED_FIFO (usuário comum) |

Posições de andar medidas, em mm:

| Cabine | Andar 0 | 1 | 2 | 3 | 4 | 5 | Larguras das bandeirolas (0 a 5) |
|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:--|
| 1 | 1 | 3001 | 6000 | 8946 | 11906 | 14862 | 192, 241, 141, 271, 171, 221 |
| 2 | 60 | 3115 | 6040 | 9130 | 12055 | 15110 | 261, 151, 211, 121, 281, 181 |
| 3 | 25 | 2890 | 5960 | 8876 | 11940 | 14896 | 162, 231, 252, 201, 131, 271 |

Viagens, cada cabine ao andar 5 e depois ao 4:

| Cabine | Ao andar 5 | Ao andar 4 |
|:-:|:-:|:-:|
| 1 | 31,8 s, +2,5 mm | 20,3 s, −7,5 mm |
| 2 | 39,5 s, +8,0 mm | 12,8 s, 0,0 mm |
| 3 | 28,3 s, −1,5 mm | 11,5 s, +0,5 mm |

O que a placa mostrou e o simulador não:

- na primeira rodada a ESP32 ligou a falha `0x0004` nas três cabines uns 90 mm
  abaixo do térreo, no começo da calibração, e passou a ignorar o motor
  (corrente sem movimento). Depois do reset do dashboard a mesma descida
  funcionou; a causa não foi confirmada. A cabine agora registra no log cada
  mudança do registrador `falha`;
- sem o programa, com os pinos liberados, as cabines escorregam até o fundo do
  poço;
- a `lgpio` (por baixo da `RPi.GPIO`) cria o pipe `.lgd-nfy0` no diretório
  corrente, e três cabines subindo juntas no mesmo diretório disputam o
  arquivo. O `./elevador placa` e o teste dão um diretório a cada uma.

Para gerar os gráficos a partir de uma rodada na placa (a placa não tem
matplotlib): copiar a pasta para o PC e rodar `./elevador graficos`, que grava
`docs/imagens/pid_placa.png` (última viagem de cada cabine: posição, alvo e
duty) e `docs/imagens/potencia_placa.png` (barramento, Cotas e correntes):

```bash
scp -r -P <porta> <usuario>@<placa>:embarcados-2026-2/dados/teste_<data>_<hora> .
./elevador graficos teste_<data>_<hora>
```

### No simulador

Os gráficos abaixo saíram do prédio simulado (`src/simulacao/`), que reproduz
atrito estático, inércia, quadratura, bandeirolas de largura variável e perda
de bordas do encoder, mas não o motor da bancada. Os ganhos ficam no arquivo de
configuração para serem reajustados na placa.

#### Sintonia do PID

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

#### Saturação pela Cota

Viagem do andar 0 ao 5 com a Cota caindo de 6000 para 3000 mA e depois para
1000 mA (`python3 -m ferramentas.experimentos cota`). O duty acompanha o teto
no mesmo ciclo e nunca o ultrapassa:

![Saturação pela Cota](docs/imagens/pid_cota.png)

#### Cenários de Tráfego

Sistema completo, três cenários de 5 minutos, com semente fixa e uma chamada a
cada 5 s em média (`python3 -m ferramentas.experimentos cenarios`):

| Cenário | Chamadas | Espera média | Espera máxima | Viagem média | Por cabine (1/2/3) |
|:--|:-:|:-:|:-:|:-:|:-:|
| Up-peak | 50 | 22,7 s | 76,7 s | 37,5 s | 15 / 16 / 19 |
| Down-peak | 52 | 27,6 s | **95,5 s** | 35,6 s | 16 / 19 / 17 |
| Interfloor | 46 | 18,9 s | 73,4 s | 41,4 s | 15 / 15 / 16 |

Nenhuma violação de porta, de fim de curso, de Cota ou de barramento nos três
(`docs/experimentos/cenarios.json`). No down-peak uma chamada passou dos 90 s:
a proteção do limite (penalidade no despacho e prioridade, na cabine, para
origem esperando há mais de 50 s) derrubou o pior caso do interfloor de 98 s
para 73 s, mas não cobre todos os casos com a velocidade do simulador. Estes
números são do simulador; os da bancada dependem da velocidade real do motor.

![Barramento de Potência](docs/imagens/potencia.png)

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
elevador           comandos da Entrega Final (placa, para, teste, simulado, graficos)
ferramentas/       sobe_tudo.sh, teste_placa, experimentos, gráficos, bring-up da Entrega 1
```

## Testes

```bash
python3 -m pytest tests/ -q -m "not lento"   # unidades, segundos
python3 -m pytest tests/ -q                  # inclui o sistema completo no simulador (minutos)
```

Teste de aceitação de ponta a ponta, na placa ou no simulador: sobe os quatro
processos, percorre o roteiro da seção 10 do [guia da bancada](docs/BANCADA.md)
(conexão, Condição de Contorno, calibração, viagens, cortina, Modo Degradado,
queda de TCP e reinício do central, despacho com cenário, SIGINT numa cabine),
vigia os invariantes da Seção 7.5 pelos registradores MODBUS e grava logs, CSVs
dos gráficos e relatório em `dados/teste_<data>_<hora>/`. A cortina e o
despacho pedem, na hora, o botão do dashboard.

```bash
./elevador teste                       # na Raspberry Pi, uns 25 min
./elevador teste --pula cortina reinicio   # etapas a pular
./elevador teste --simulado            # sem placa
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
