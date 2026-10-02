# Elevador Embarcado: Trabalho 1, Entrega 1

Fundamentos de Sistemas Embarcados, 2026/2.

Controle da Cabine 1 de um elevador por GPIO em uma Raspberry Pi, contra o
simulador de edifício executado na ESP32 da bancada. Esta entrega cobre o
módulo de GPIO e a malha de posição para os andares 0, 1 e 2.

## Integrantes

Listados no repositório de entrega.

## Vídeo

Link a ser adicionado.

## Sumário

1. [Execução](#1-execução)
2. [Arquitetura](#2-arquitetura)
3. [Pinagem](#3-pinagem)
4. [Implementação](#4-implementação)
5. [Atendimento aos requisitos](#5-atendimento-aos-requisitos)
6. [Medições em bancada](#6-medições-em-bancada)
7. [Testes](#7-testes)

## 1. Execução

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
├── cli.py                 interface de terminal
└── main.py                ponto de entrada e tratamento de sinais

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
