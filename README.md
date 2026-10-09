# Elevador Embarcado: Trabalho 1

Fundamentos de Sistemas Embarcados, 2026/2.

Controle de um grupo de elevadores em uma Raspberry Pi, contra o simulador de
edifício executado na ESP32 da bancada.

| Entrega | Conteúdo | Tag | Executável |
|:--|:--|:-:|:--|
| 1 | módulo de GPIO e malha de posição da Cabine 1, andares 0 a 2 | `v1.0` | `python3 -m src.main` |
| 2 | módulos UART-MODBUS (Partes 1, 2 e 3) e I2C com a Condição de Contorno | `v2.0` | `python3 -m src.comunicacao` |

## Integrantes

Listados no repositório de entrega.

## Vídeos

| Entrega | Link |
|:--|:--|
| 1 | https://youtu.be/LKAWTPL8WLw |
| 2 | a ser adicionado |

## Sumário

1. [Execução](#1-execução)
2. [Arquitetura](#2-arquitetura)
3. [Pinagem](#3-pinagem)
4. [Implementação](#4-implementação)
5. [Atendimento aos requisitos](#5-atendimento-aos-requisitos)
6. [Medições em bancada](#6-medições-em-bancada)
7. [Testes](#7-testes)
8. [Entrega 2: UART-MODBUS e I2C](#8-entrega-2-uart-modbus-e-i2c)

## 1. Execução

Esta seção cobre o programa da Entrega 1. O da Entrega 2 está na
[Seção 8.1](#81-execução).

### Dependências

Python 3. Na Raspberry Pi do laboratório a biblioteca `RPi.GPIO`
já está instalada no Python do sistema (versão 0.7.1a4), portanto não é
necessário ambiente virtual. Em outras máquinas:

```bash
pip install -r requirements.txt
```

O `requirements.txt` só instala a `RPi.GPIO` em arquitetura ARM. Na máquina de
desenvolvimento ele instala apenas o `pytest`.

### Na Raspberry Pi

```bash
git pull
python3 -m src.main
```

Recomenda-se executar dentro de uma sessão `tmux`, para que a queda da conexão
SSH não interrompa o programa no meio de uma viagem.

### Sem a placa

```bash
python3 -m src.main --simulado
```

O modo simulado substitui a GPIO por um modelo do poço em software, com atrito
estático, inércia, quadratura real no encoder, bandeirolas de larguras
diferentes e repique na cortina.

### Opções

| Opção | Efeito |
|:--|:--|
| `--simulado` | usa o backend simulado |
| `--posicao-inicial <mm>` | posição da cabine no início, em mm (padrão 0) |
| `--pinagem nova\|antiga` | tabela de pinos da Cabine 1 (padrão `nova`, ver [Seção 3](#3-pinagem)) |

### Comandos do terminal

| Comando | Descrição |
|:--|:--|
| `andar <0\|1\|2>` | viaja até o andar, em malha fechada pelo encoder |
| `ir <mm>` | viaja até uma posição absoluta |
| `motor <direcao> <duty>` | acionamento direto; direção `livre`, `subir`, `descer` ou `freio` |
| `parar` | zera o PWM e aplica o freio |
| `estado` | imprime contagem, posição, direção, duty, cortina e sensor de andar |
| `zera [mm]` | redefine a contagem do encoder |
| `medicoes` | lista as bandeirolas medidas |
| `ancora` | corrige a contagem pela última bandeirola medida |
| `ancoragem [on\|off]` | liga ou desliga a correção automática a cada travessia |
| `obstruir`, `liberar` | aciona a cortina (apenas no modo simulado) |
| `sair` | encerra com segurança |

Na bancada, a cortina é acionada pelo botão "Obstruir porta" do dashboard.

### Preparação da bancada

A posição exibida pelo dashboard é absoluta e persiste entre sessões, enquanto
a contagem do encoder começa em zero quando o programa inicia. Para que as duas
referências coincidam:

1. posicionar a cabine no andar 0;
2. acionar "Resetar bancada" no dashboard;
3. iniciar o programa.

Acionar "Resetar bancada" com o programa em execução desloca a referência do
simulador sem que a Raspberry Pi seja informada. A ancoragem automática corrige
isso na próxima travessia de bandeirola (ver [Seção 4.6](#46-ancoragem-pela-bandeirola)).

## 2. Arquitetura

O código é dividido em dois níveis. O pacote `src/controle` não importa
`RPi.GPIO`: toda interação com o hardware passa pelas classes de `src/gpio`,
que por sua vez dependem de uma interface abstrata `Backend` com duas
implementações, a real e a simulada.

```
src/
├── gpio/                  baixo nível: pino, nível lógico, duty, borda
│   ├── pinos.py           mapa BCM da Cabine 1 e tabela de direção
│   ├── backend.py         interface abstrata de acesso à GPIO
│   ├── rpi_backend.py     implementação sobre RPi.GPIO
│   ├── sim_backend.py     modelo do poço em software
│   ├── saidas.py          saída on/off e saída PWM a 1 kHz
│   ├── entradas.py        entrada por polling e entrada por interrupção
│   └── encoder.py         quadratura 4x por interrupção nos dois canais
├── controle/              alto nível: andar, milímetro, nivelamento
│   ├── posicao.py         conversões, tolerância e limites do poço
│   ├── motor.py           tabela de direção e rampa de duty
│   ├── cortina.py         eventos de obstrução e liberação
│   ├── sensor_andar.py    medição da bandeirola pelas duas bordas
│   └── cabine.py          malha de posição a 50 ms
├── uart/                  Entrega 2: UART com a ESP32
│   ├── porta.py           porta serial por termios e select
│   ├── crc16.py           CRC-16/ARC (valor inicial zero)
│   ├── matricula.py       6 dígitos em bytes crus
│   ├── carga.py           int32, float e string das Partes 1 e 2
│   ├── simplificado.py    Parte 1, sem endereço e sem CRC
│   ├── modbus_didatico.py Parte 2, MODBUS com sub-código
│   ├── modbus.py          Parte 3, funções 0x03 e 0x10
│   ├── elevadores.py      Parte 3, registradores das cabines e do prédio
│   └── esp32_simulada.py  ESP32 em software para --simulado e testes
├── i2c/                   Entrega 2: barramento I2C
│   ├── barramento.py      acesso ao /dev/i2c-N
│   ├── bmp280.py          driver e compensação do datasheet
│   └── bmp280_simulado.py sensor em software
├── central/
│   └── condicao_contorno.py  BMP280 -> registradores 5 e 6, a cada 4 s
├── cli.py                 interface de terminal da Entrega 1
├── main.py                ponto de entrada da Entrega 1
├── cli_comunicacao.py     interface de terminal da Entrega 2
├── tela.py                cores do terminal da Entrega 2
└── comunicacao.py         ponto de entrada da Entrega 2

ferramentas/bringup.py     verificação da placa por etapas
tests/                     testes unitários e de integração
docs/BANCADA.md            guia de operação da bancada remota
```

### Concorrência

| Thread | Função | Como aguarda |
|:--|:--|:--|
| principal | leitura de comandos | bloqueada em `input()` |
| malha de controle | fim de curso, controle de posição, rampa | `Event.wait(0.050)` |
| callbacks da `RPi.GPIO` | encoder, cortina, sensor de andar | interrupção por borda |
| temporizadores de debounce | assentamento do nível lógico | `threading.Timer` |

Nenhuma thread executa laço de espera ativa. O contador do encoder é protegido
por `threading.Lock`, pois é escrito pelos callbacks e lido pela malha.

## 3. Pinagem

Numeração BCM, Cabine 1.

| Sinal | Função | BCM | Pino físico | Tipo |
|:--|:--|:-:|:-:|:--|
| `PWM` | potência do motor | 13 | 33 | saída PWM, 1 kHz |
| `DIR1` | direção 1 | 22 | 15 | saída on/off |
| `DIR2` | direção 2 | 23 | 16 | saída on/off |
| `ENC_A` | encoder, canal A | 20 | 38 | entrada por interrupção |
| `ENC_B` | encoder, canal B | 21 | 40 | entrada por interrupção |
| `CORTINA` | cortina de luz | 26 | 37 | entrada on/off |
| `SENSOR_ANDAR` | bandeirola | 0 | 27 | entrada on/off |

O enunciado trocou a pinagem das Cabines 1 e 2 durante o semestre. A tabela
anterior (PWM 12, DIR 17/27, encoder 5/6, cortina 16, sensor 11) continua
disponível por `--pinagem antiga`.

### Tabela de direção

| Estado | DIR1 | DIR2 |
|:--|:-:|:-:|
| livre | 0 | 0 |
| subir | 1 | 0 |
| descer | 0 | 1 |
| freio | 1 | 1 |

## 4. Implementação

### 4.1 Saídas digitais e PWM

`SaidaDigital` escreve nível lógico em `DIR1` e `DIR2` a partir da tabela de
direção definida em `gpio/pinos.py`. `SaidaPWM` opera a 1 kHz, com duty
limitado ao intervalo de 0 a 100%.

A rampa de aceleração é implementada por limitação da taxa de variação do duty
(120 pontos percentuais por segundo), aplicada uma vez por ciclo da malha. Não
há espera bloqueante na rampa.

| Parâmetro | Valor | Arquivo |
|:--|:-:|:--|
| Taxa da rampa | 120 %/s | `controle/motor.py` |
| Duty mínimo de movimento | 10% | `controle/motor.py` |
| Duty máximo em viagem | 40% | `controle/cabine.py` |
| Teto nos últimos 300 mm | 15% | `controle/cabine.py` |

Duty diferente de zero nunca é aplicado abaixo de 10%: nesse regime o motor
parado não vence o atrito estático.

### 4.2 Cortina de luz

Entrada por interrupção em ambas as bordas, com debounce de 20 ms por
temporizador. Cada borda crua reinicia o temporizador, e o evento só é emitido
quando o nível permanece estável durante a janela. A impressão ocorre no
próprio tratador, no instante em que o nível assenta. Formato da saída:

```
[1234.567] CORTINA: porta OBSTRUIDA
[1237.571] CORTINA: porta LIBERADA
```

O comando `estado` informa o número de eventos e o número de bordas cruas
recebidas. A diferença entre os dois é o repique filtrado.

### 4.3 Encoder em quadratura

Interrupção em ambas as bordas dos canais A e B, o que resulta em decodificação
4x. Com 1000 pulsos por metro, uma contagem corresponde a 1 mm.

O par (A, B) percorre o ciclo de Gray `00, 01, 11, 10` ao subir e o ciclo
inverso ao descer. Cada transição é consultada em uma tabela que devolve +1 ou
-1. Um salto entre estados não adjacentes, como `00` para `11`, indica borda
perdida. A transição é contabilizada em `transicoes_invalidas` e conta dois
passos no sentido do último passo válido, já que a cabine não inverte o sentido
entre duas bordas.

O contador é de 32 bits com sinal e satura em `-2^31` e `2^31 - 1`.

### 4.4 Sensor de Andar

Entrada por interrupção em ambas as bordas, com debounce de 2 ms. A contagem do
encoder é capturada na borda crua, antes do debounce, para que o deslocamento
da cabine durante a janela não desloque a medição.

Ao final de uma travessia completa são impressas as duas bordas, a largura e o
centro, calculado como a média aritmética das contagens de entrada e saída:

```
SENSOR_ANDAR: entrou na bandeirola em 2870 mm
SENSOR_ANDAR: saiu da bandeirola em 3111 mm
  bandeirola: largura 241.0 mm | centro 2990.5 mm | erro -9.5 mm
```

Travessias com largura inferior a 60 mm são descartadas. Elas ocorrem quando a
cabine entra na bandeirola e sai pelo mesmo lado, caso em que a média não
representa o centro. O limite foi definido a partir das larguras medidas em
bancada (142 a 242 mm).

O mesmo pino também é lido por polling, a cada consulta de estado, para
informar se a cabine está dentro da bandeirola.

### 4.5 Controle de posição

A malha executa a cada 50 ms, na seguinte ordem:

1. supervisão de fim de curso, em todo ciclo, inclusive no acionamento manual;
2. supervisão de travamento;
3. cálculo do duty alvo, proporcional ao erro (0,06 % por mm);
4. um passo da rampa do motor.

A 3 mm do destino o motor é freado e a malha aguarda a cabine assentar, isto é,
permanecer 400 ms sem se deslocar mais que 1 mm. Só então o erro é medido.

Como existe um duty mínimo de movimento, existe também uma distância mínima de
frenagem, que em bancada chegou a 16 mm, acima da tolerância de ±10 mm. Quando
o erro após o assentamento excede a tolerância, a cabine é renivelada por
pulsos curtos no duty mínimo, com duração proporcional ao erro e limitada a
10 ciclos. Cada pulso é seguido de novo assentamento e nova medição, até o erro
entrar na tolerância ou atingir o máximo de 12 renivelamentos. Exemplo de
saída:

```
RENIVELANDO (1/12): parou em 6016 mm, faltam -16 mm
CHEGADA: 6004 mm (destino 6000 mm, erro +4 mm, andar 2, 1 renivelamento(s))
```

### 4.6 Ancoragem pela bandeirola

A contagem do encoder é relativa e acumula erro por bordas perdidas. As
bandeirolas estão em posições absolutas conhecidas (0, 3000 e 6000 mm). A cada
travessia completa, a diferença entre o centro medido e a posição nominal do
andar é aplicada como correção à contagem:

```
  bandeirola: largura 241.0 mm | centro 2990.5 mm | erro -9.5 mm
  ancorado no andar 1: contagem corrigida em +9.5 mm
```

O encoder continua sendo a única realimentação da malha. O sensor de andar
apenas corrige a referência do contador. Correções acima de 100 mm são
recusadas automaticamente e podem ser aplicadas pelo comando `ancora`.

### 4.7 Proteções

| Proteção | Comportamento |
|:--|:--|
| Destino fora do poço | comando recusado fora de 0 a 6000 mm |
| Fim de curso | movimento interrompido nos limites do poço; no acionamento manual com margem de 25 mm, dimensionada pela inércia medida |
| Travamento | viagem abortada após 6 s de motor acionado sem deslocamento de 3 mm |
| Exceção na malha | registrada no terminal sem encerrar a thread de controle |

### 4.8 Encerramento

`SIGINT`, `SIGTERM` e `SIGHUP` são tratados pelo mesmo procedimento: o PWM vai
a zero, `DIR1` e `DIR2` são levados ao estado de freio, as interrupções são
removidas e a GPIO é liberada.

```
SIGINT recebido: zerando PWM, aplicando freio e liberando a GPIO...
encerrado com seguranca.
```

`DIR1` e `DIR2` são mantidos fora da liberação da GPIO. Com os pinos em alta
impedância a bancada interpreta a combinação como descer, e a cabine se
deslocaria após o encerramento. `SIGHUP` é tratado porque a bancada é acessada
por SSH, e a queda da conexão não pode deixar o motor acionado.

## 5. Atendimento aos requisitos

| # | Requisito | Implementação |
|:-:|:--|:--|
| 1 | Python, C/C++ ou Rust | Python 3 |
| 2 | Módulo de GPIO e lógica de controle separados | `src/gpio` e `src/controle` |
| 3 | `DIR1`/`DIR2` conforme a Tabela 2 | `gpio/pinos.py`, `controle/motor.py` |
| 4 | PWM a 1 kHz, duty de 0 a 100% | `gpio/saidas.py`, `controle/motor.py` |
| 5 | Cortina com debounce e impressão imediata | `gpio/entradas.py`, `controle/cortina.py` |
| 6 | Encoder por interrupção nos dois canais, sentido, 32 bits | `gpio/encoder.py` |
| 7 | Sensor de Andar: duas bordas, contagem em cada uma e centro pela média | `controle/sensor_andar.py` |
| 8 | Parada nos andares 0, 1 e 2 dentro de ±10 mm | `controle/cabine.py` |
| 9 | Sem busy-wait | [Seção 2, Concorrência](#concorrência) |
| 10 | Tratamento de SIGINT | `src/main.py` |
| 11 | `requirements.txt` e instruções | [Seção 1](#1-execução) |
| 12 | Vídeo de até 5 min | [Vídeo](#vídeo) |

O módulo de GPIO oferece entrada por polling (`EntradaPolling`) e por
interrupção (`EntradaInterrupcao`), ambas utilizadas pela lógica de controle.

## 6. Medições em bancada

Placa rasp42, pinagem nova, 23/09/2026.

| Grandeza | Valor |
|:--|:--|
| Largura da bandeirola, andar 0 | 190 mm |
| Largura da bandeirola, andar 1 | 241 e 242 mm, em duas travessias |
| Largura da bandeirola, andar 2 | 142 mm |
| Centro medido, andar 1 | 3000,0 e 3002,5 mm |
| Erro de parada, `andar 1` | -2 mm |
| Sobrepasso por inércia, `andar 2` | 16 mm, antes do renivelamento |
| Sobrepasso no acionamento manual | 15 mm além do ponto de corte |
| Contagem do encoder contra dashboard | 6010 mm contra 6011 mm |
| Transições inválidas | 1 na sessão, a 40% de duty |

As larguras diferentes entre andares confirmam que o centro não pode ser obtido
a partir de uma única borda.

## 7. Testes

```bash
python3 -m pytest tests/ -q
```

São 61 testes, executados contra o backend simulado. Os de integração rodam em
tempo real e levam cerca de três minutos.

A verificação da placa, etapa por etapa, está descrita em
[docs/BANCADA.md](docs/BANCADA.md).

## 8. Entrega 2: UART-MODBUS e I2C

Comunicação com a ESP32 pela UART, nos três protocolos que ela atende ao mesmo
tempo, e leitura do BMP280 pelo I2C para manter a Condição de Contorno do
simulador.

### 8.1 Execução

Não há dependência além do Python 3: a porta serial é aberta pelo `termios` e
o barramento I2C pelo `/dev/i2c-1`, ambos do próprio Linux. Não é preciso
instalar `pyserial` nem `smbus2` na placa.

A matrícula vai em todos os quadros e não fica no código, porque o repositório
é público. Ela é lida do argumento `--matricula`, da variável `FSE_MATRICULA`
ou do arquivo `matricula` na raiz do repositório (ignorado pelo git), nessa
ordem. Sem nenhum dos três, o programa pergunta. Basta a matrícula completa:
são usados os 6 últimos dígitos.

```bash
echo <matricula> > matricula      # uma vez por placa
python3 -m src.comunicacao
python3 -m src.comunicacao --contorno-auto   # já mantém o watchdog satisfeito
python3 -m src.comunicacao --simulado        # sem placa
```

| Opção | Efeito |
|:--|:--|
| `--simulado` | ESP32 e BMP280 em software |
| `--porta <dispositivo>` | UART, padrão `/dev/serial0` |
| `--i2c <n>` | barramento I2C, padrão 1 |
| `--matricula <número>` | matrícula; usa os 6 últimos dígitos |
| `--timeout <s>` | timeout de cada tentativa, entre 0,2 e 0,5 s (padrão 0,3) |
| `--contorno-auto` | liga a escrita periódica da Condição de Contorno na partida |
| `--sem-cor` | terminal sem cores (também desligadas com `NO_COLOR` ou saída redirecionada) |

### 8.2 Comandos do terminal

Nas Partes 1 e 2 o protocolo é escolhido antes de cada comando: `p1` para o
simplificado e `p2` para o MODBUS.

| Comando | Função |
|:--|:--|
| `p1 pede-int`, `p2 pede-int` | `0xA1`, solicita inteiro |
| `p1 pede-float`, `p2 pede-float` | `0xA2`, solicita float |
| `p1 pede-string`, `p2 pede-string` | `0xA3`, solicita string |
| `p1 envia-int <n>`, `p2 envia-int <n>` | `0xB1`, envia inteiro |
| `p1 envia-float <x>`, `p2 envia-float <x>` | `0xB2`, envia float |
| `p1 envia-string <texto>`, `p2 envia-string <texto>` | `0xB3`, envia string |
| `p1 cru <byte>...` | envia bytes crus em hexa, para provocar o erro de sintaxe |
| `cabine <1\|2\|3>` | `le_estado_cabine()` |
| `porta <1\|2\|3> <abrir\|fechar\|nenhum>` | `comanda_porta()` |
| `predio` | `le_estado_predio()` |
| `fila` | `le_chamada_da_fila()` |
| `atribui <id> <cabine>` | `atribui_chamada()` |
| `pop` | `remove_chamada_da_fila()` |
| `contorno [<°C> <hPa>]` | `escreve_condicao_contorno()`; sem argumentos, lê o BMP280 |
| `le <end> <reg> <qtd>` | função `0x03` em qualquer faixa |
| `escreve <end> <reg> <valor>...` | função `0x10` em qualquer registrador |
| `monitora cabine <n> [<s>]`, `monitora predio [<s>]` | leitura contínua a cada 1 s, até teclar Enter ou por `<s>` segundos |
| `bmp` | lê temperatura e pressão do BMP280 |
| `auto [on\|off\|log]` | escrita periódica da Condição de Contorno |
| `chamada <origem> <destino>` | registra chamada (apenas no modo simulado) |
| `<comando> ; <comando>` | executa vários comandos em sequência na mesma linha |
| `roteiro 1`, `roteiro 3 [<cabine>]`, `roteiro tudo [<cabine>]` | executa a demonstração da [Seção 8.5](#85-roteiro-de-demonstração) sozinho |

Todo comando imprime um cabeçalho, os bytes enviados (`TX`) e recebidos
(`RX`), os campos decodificados e, na linha `=>`, o resultado. No terminal,
`TX`, `RX`, exceções e timeouts saem em cores diferentes:

```
uart> contorno
[I2C] BMP280 0x76: 27.50 C, 887.00 hPa
[MODBUS 0x10] escreve [275, 887] a partir do registrador 5 no dispositivo 0x20
  TX (19 B): 20 10 05 00 02 00 04 13 01 77 03 06 05 04 03 02 01 B7 49
  RX (8 B): 20 10 00 05 00 02 57 63
  campos: endereco=0x20 funcao=0x10 reg=5 qtd=2 CRC=57 63
  => Condicao de Contorno escrita: 275 (decimos de C), 887 hPa
```

### 8.3 Implementação

**Porta serial.** 115200 bps, 8N1, sem controle de fluxo, em modo cru: sem
isso o `0x03` e o `0x11`, presentes em quase todo quadro, seriam interpretados
pelo terminal como Ctrl+C e XON. A espera por bytes é feita com `select()`,
sem laço ativo. Antes de cada requisição o buffer de recepção é descartado,
para que a resposta atrasada de uma tentativa anterior não seja lida como a
resposta atual. Uma trava serializa as transações, porque a CLI e o serviço da
Condição de Contorno dividem a mesma porta.

**CRC-16.** Polinômio `0xA001` (refletido) com valor inicial **zero**, isto é,
CRC-16/ARC. O MODBUS RTU padrão começa em `0xFFFF`, e é assim que bibliotecas
como pymodbus e libmodbus calculam; contra este simulador elas errariam todos
os quadros. A variante foi determinada a partir dos quatro exemplos da Seção
3.3 do enunciado, que estão nos testes.

**Parte 1.** Sem CRC não é possível distinguir resposta corrompida de resposta
correta, então não há retentativa: o timeout é registrado e reportado. É assim
que o comando desconhecido aparece para a Raspberry Pi, já que o dispositivo
descarta o pacote sem responder.

**Parte 2.** O enunciado define a requisição byte a byte, mas não o envelope da
resposta (endereço `0x00` ou `0x01`, sub-código ecoado ou não). A resposta é
lida até a linha ficar 20 ms em silêncio e interpretada pelo tamanho: o CRC
valida o quadro inteiro e cada tipo tem tamanho conhecido, então apenas um dos
formatos possíveis é consistente. Timeout e CRC inválido são repetidos até 3
vezes; resposta com bit de erro é reportada sem repetir.

**Parte 3.** O tamanho da resposta é determinístico, então ela é lida campo a
campo: os dois primeiros bytes indicam exceção ou resposta normal, e o
restante decorre deles. Isso evita esperar silêncio na linha a cada
transação. Antes de usar a resposta são conferidos CRC, endereço, função,
`byte_count = 2·qtd` (`0x03`) e o eco de registrador e quantidade (`0x10`).

| Situação | Tratamento |
|:--|:--|
| timeout ou resposta incompleta | repete, até 3 tentativas |
| CRC inválido | descarta e repete |
| endereço, função ou `byte_count` divergentes | repete |
| exceção `0x01`, `0x02` ou `0x03` | reporta código e significado, sem repetir |

Ordem dos bytes, conforme a Seção 3.1: `reg`, `qtd` e valores da requisição em
little-endian; valores da resposta `0x03` e eco da resposta `0x10` em
big-endian; CRC com o byte baixo primeiro. `posicao_mm` é decodificado como
`int16` com sinal.

O texto da Seção 3.1 informa 12 bytes para a requisição `0x03` e 13 + 2·qtd
para a `0x10`, mas os exemplos da Seção 3.3 têm 14 e 15 + 2·qtd. A diferença
são os 2 dígitos a mais da matrícula; o código segue os exemplos.

**Uso na Entrega Final.** `src/uart/modbus.py` e `src/uart/elevadores.py` não
dependem da CLI. O Servidor Central importa `Elevadores` e chama os mesmos
métodos usados aqui.

**BMP280.** Na inicialização o driver confere o chip id (`0x58`), lê os 12
coeficientes de calibração e configura sobreamostragem x2 na temperatura, x16
na pressão, filtro IIR 4 e modo normal. A leitura é feita em rajada nos 6
bytes de dados, para que temperatura e pressão venham da mesma conversão, e
convertida pelas fórmulas de compensação do datasheet. A temperatura é
calculada antes da pressão porque a compensação da pressão depende dela.

**Condição de Contorno.** Uma thread lê o BMP280 e escreve temperatura, em
décimos de grau, e pressão, em hPa, nos registradores 5 e 6 do prédio a cada
4 s, abaixo do máximo de 5 s exigido e bem dentro do watchdog de 30 s. A
primeira escrita ocorre na partida. Entre ciclos a thread dorme em
`Event.wait()`. Uma falha é impressa apenas quando muda, e a recuperação é
informada; a thread não termina por exceção. O serviço usa um cliente MODBUS
próprio, sem impressão de bytes, para não encher o terminal a cada 4 s.

**Encerramento.** `SIGINT`, `SIGTERM` e `SIGHUP` param a thread da Condição de
Contorno e fecham a UART e o I2C.

### 8.4 Atendimento aos requisitos

| Requisito | Implementação |
|:--|:--|
| Parte 1, 6 comandos sem CRC | `uart/simplificado.py` |
| Parte 2, 6 comandos com CRC e matrícula de 6 dígitos | `uart/modbus_didatico.py`, `uart/crc16.py` |
| Parte 2, bit de erro e código de exceção | `ModbusDidatico.interpreta` |
| Parte 2, escolha do protocolo antes de cada comando | prefixo `p1` ou `p2` |
| Parte 3, funções `0x03` e `0x10` | `uart/modbus.py` |
| Parte 3, validação, timeout e 3 tentativas | `ClienteModbus._transacao` |
| Parte 3, exceções sem repetição | `ExcecaoModbus` em `uart/erros.py` |
| Parte 3, uma opção por função e leitura contínua | `cli_comunicacao.py`, `monitora` |
| Bytes enviados e recebidos em tela | todos os comandos |
| Funções independentes e utilitários | `envia_pacote`, `le_resposta`, `calcula_crc`, entre outros |
| Módulo da Parte 3 importável | `uart/modbus.py` e `uart/elevadores.py`, sem dependência da CLI |
| BMP280 e Condição de Contorno | `i2c/bmp280.py`, `central/condicao_contorno.py` |

### 8.5 Roteiro de demonstração

Sequência da Seção 3.4, item 5, da Entrega 2. O comando `roteiro` a executa
inteira, com 3 s entre os comandos para que cada um apareça no widget: `roteiro 1`
cobre as Partes 1 e 2, `roteiro 3 <cabine>` a Parte 3 e `roteiro tudo <cabine>`
as duas. Se o watchdog estiver válido, o roteiro desliga a escrita automática e
espera 32 s para ele expirar. Antes da fila ele pausa até um Enter, para dar
tempo de registrar a chamada no quiosque.

Toda consulta do roteiro aparece no terminal como um comando, e a escrita
automática só liga no final: na rasp50, depois de uns 30 eventos em 40 s, o
widget passou mais de um minuto sem receber eventos, embora a ESP32 continuasse
respondendo, e a escrita a cada 4 s gera sozinha 2 eventos por escrita.

1. Watchdog: iniciar sem `--contorno-auto`, aguardar mais de 30 s e executar
   `predio`, que deve mostrar `watchdog_ambiente = 1` e `barramento_max = 3000`.
   Executar `contorno` e `predio` de novo: watchdog em 0 e barramento conforme
   `12000 − 200 × max(0, T − 25)`. O `auto on` fica para o fim do roteiro.
2. Porta: com uma cabine nivelada, `porta 1 abrir ; monitora cabine 1 3`,
   que acompanha `fechada → abrindo → aberta`, e logo `porta 1 fechar ;
   monitora cabine 1 5`, que acompanha `fechando → fechada`. Os comandos vão na
   mesma linha porque a porta do simulador abre em uns 2 s, fica uns 3 s aberta
   e fecha sozinha: digitado depois, o `monitora` já a encontra fechando, e o
   `fechar` não teria efeito visível.
3. Fila: registrar uma chamada no quiosque do dashboard, `fila`,
   `atribui <id> <cabine>`, `pop` e `fila` novamente.
4. Exceções: `escreve 0x11 0 5` (registrador somente leitura) e
   `le 0x11 0 20` (faixa fora do mapa) devem retornar a exceção `0x02`.

As Partes 1 e 2 são demonstradas pelos 12 comandos `p1` e `p2` da
[Seção 8.2](#82-comandos-do-terminal). O comando `p1 cru C7 <matrícula>`
provoca o erro de sintaxe da Seção 1.3, registrado como timeout.

### 8.6 Matrícula no widget

Print do dashboard **uart** com a matrícula em destaque: a ser adicionado após
a sessão de bancada.

### 8.7 Testes

```bash
python3 -m pytest tests/test_modbus.py tests/test_uart_didatico.py \
    tests/test_i2c_e_contorno.py tests/test_porta_serial.py -q
```

São 60 testes, executados em cerca de um segundo:

| Arquivo | Cobre |
|:--|:--|
| `test_modbus.py` | CRC e quadros contra os exemplos da Seção 3.3, ordem dos bytes, retentativas, validação da resposta, exceções e as funções da Parte 3 |
| `test_uart_didatico.py` | os 12 comandos das Partes 1 e 2, os formatos de resposta aceitos, a matrícula e os erros de tamanho |
| `test_i2c_e_contorno.py` | compensação do BMP280 contra o exemplo do datasheet, driver e serviço da Condição de Contorno |
| `test_porta_serial.py` | a `PortaSerial` real contra um pseudo-terminal: modo cru, prazo de leitura e descarte do buffer |

Os testes usam a ESP32 simulada, que segue o enunciado mas não substitui a
bancada: o formato da resposta da Parte 2 e o comportamento exato do
simulador só são confirmados na placa.
