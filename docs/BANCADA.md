# Guia da Bancada

Operação da Raspberry Pi remota para a Cabine 1: acesso, restrições da placa
compartilhada, verificação por etapas e diagnóstico.

## 1. Acesso

As placas são acessadas por SSH, em horários reservados no Discord da
disciplina. Porta e endereço de cada placa estão no cabeçalho do subcanal.

Procedimento de cada sessão:

1. anunciar a placa e a duração no subcanal;
2. conectar por SSH e abrir uma sessão `tmux`;
3. atualizar o código com `git pull`;
4. ao final, liberar a GPIO com `python3 -m ferramentas.bringup limpa`;
5. encerrar a sessão.

## 2. Restrições da placa compartilhada

| Restrição | Consequência |
|:--|:--|
| Sem `raspi-config` e sem reboot | a configuração de SPI, I2C e UART é a que estiver na placa |
| Fiação já montada | não há conferência física; a pinagem é validada pela etapa `entradas` |
| Queda de SSH encerra o processo | o programa trata `SIGHUP` e deve rodar dentro de `tmux` |
| `RPi.GPIO` 0.7.1a4 no Python do sistema | não é necessário ambiente virtual |

## 3. Regras elétricas

1. A GPIO da Raspberry Pi opera em 3,3 V e não tolera 5 V.
2. Raspberry Pi e ESP32 devem compartilhar o GND.
3. Corrente máxima de 16 mA por pino e 50 mA no total. O pino de PWM é sinal de
   comando; o motor não é alimentado pela placa.

## 4. Conflitos de periférico

Com o periférico habilitado, o kernel assume o pino e a GPIO deixa de responder
sem emitir erro.

| Pino | Função alternativa | Impacto |
|:--|:--|:--|
| BCM 0, `SENSOR_ANDAR` da Cabine 1 | ID_SD, EEPROM de HAT | sondado no boot; funciona como GPIO depois, desde que não haja HAT com EEPROM |
| BCM 1, `SENSOR_ANDAR` da Cabine 3 | ID_SC | idem |
| BCM 7 e 8, encoder da Cabine 3 | SPI0 CE1 e CE0 | exige SPI desabilitado |
| BCM 11, `PWM` da Cabine 2 | SPI0 SCLK | exige SPI desabilitado |
| BCM 2 e 3 | I2C1 | reservados ao sensor de temperatura da Entrega 2 |
| BCM 14 e 15 | UART | reservados ao MODBUS da Entrega 2 |

Verificação:

```bash
ls /dev/spidev*       # não deve listar nada
raspi-gpio get 0      # modo atual do SENSOR_ANDAR
```

## 5. Dashboard

O simulador é exibido em um dashboard ThingsBoard, um por placa. A Entrega 1
usa a aba "Elevador Único".

```
https://tb.fse.lappis.rocks/dashboard/d39cd4a0-b11b-11f1-9a0b-0359851b5c05?publicId=86d17ff0-e010-11ef-9ab8-4774ff1517e8
```

| Controle | Uso |
|:--|:--|
| Enviar cabine ao andar 0, 1 ou 2 | move a cabine sem passar pelo programa; útil para validar encoder e sensor de andar antes do motor |
| Obstruir porta (3 s) | estímulo da cortina |
| Sensor de Andar | indica se a cabine está dentro de uma bandeirola |
| Resetar bancada | zera a posição do simulador sem mover a cabine |

A URL do ThingsBoard guarda o histórico de navegação no parâmetro `state` e
pode passar a apontar para o dispositivo de outra placa. Se um comando não se
reflete no dashboard, a primeira verificação é o dispositivo exibido.

## 6. Verificação por etapas

A ordem vai da menor para a maior consequência: entradas antes de saídas,
saídas antes de movimento. As etapas `direcao` e `pwm` movem o motor e pedem
confirmação.

```bash
python3 -m ferramentas.bringup mapa       # imprime a pinagem, sem acessar a GPIO
python3 -m ferramentas.bringup entradas   # lê CORTINA e SENSOR_ANDAR
python3 -m ferramentas.bringup encoder    # contagem e transições inválidas
python3 -m ferramentas.bringup direcao    # percorre a tabela de direção
python3 -m ferramentas.bringup pwm        # rampa de 0 a 30% e duty de arranque
python3 -m ferramentas.bringup limpa      # PWM em zero, DIR em freio, GPIO liberada
```

Opções: `--simulado` para ensaiar sem a placa, `--segundos` para a duração das
etapas de leitura e `--pinagem nova|antiga` para escolher a tabela de pinos.

| Etapa | Critério de aprovação |
|:--|:--|
| `entradas` | "Obstruir porta" leva `CORTINA` a 1 e de volta a 0; `SENSOR_ANDAR` vai a 1 dentro da bandeirola |
| `encoder` | a contagem sobe ao subir e desce ao descer; `transicoes_invalidas` permanece em zero ou próximo disso |
| `direcao` | cada linha da tabela produz o movimento esperado |
| `pwm` | a cabine só se move a partir de aproximadamente 10% de duty |

Se nenhuma entrada reagir ao dashboard com a pinagem nova, repetir a etapa
`entradas` com `--pinagem antiga`.

## 7. Diagnóstico

| Sintoma | Causa provável |
|:--|:--|
| Entrada fixa em 0 ou em 1 | pinagem divergente, GND não comum ou periférico ocupando o pino |
| Contagem anda no sentido oposto | `ENC_A` e `ENC_B` invertidos |
| Contagem anda pela metade | um dos canais sem interrupção |
| `transicoes_invalidas` crescendo | bordas perdidas; reduzir `DUTY_MAXIMO` em `src/controle/cabine.py` |
| Obstruções duplicadas | debounce insuficiente em `src/controle/cortina.py` |
| Motor não arranca | duty abaixo de 10%, atrito estático |
| Cabine sobe ao comandar descer | `DIR1` e `DIR2` invertidos |
| Contagem e dashboard divergem | "Resetar bancada" acionado com o programa em execução; ver ancoragem no README |
| Cabine desce após encerrar o programa | `DIR1`/`DIR2` liberados; encerrar pelo programa ou pela etapa `limpa` |

## 8. Parâmetros de ajuste

| Parâmetro | Valor atual | Arquivo |
|:--|:-:|:--|
| `GANHO_P` | 0,06 %/mm | `src/controle/cabine.py` |
| `DUTY_MAXIMO` | 60% | `src/controle/cabine.py` |
| `DUTY_DE_APROXIMACAO` | 15% | `src/controle/cabine.py` |
| `DISTANCIA_DE_APROXIMACAO_MM` | 300 mm | `src/controle/cabine.py` |
| `MARGEM_DE_FIM_DE_CURSO_MM` | 25 mm | `src/controle/cabine.py` |
| `TAXA_RAMPA_POR_S` | 120 %/s | `src/controle/motor.py` |
| `DEBOUNCE_MS` da cortina | 20 ms | `src/controle/cortina.py` |
| `DEBOUNCE_MS` do sensor de andar | 2 ms | `src/controle/sensor_andar.py` |
| `LARGURA_MINIMA_MM` | 60 mm | `src/controle/sensor_andar.py` |

## 9. UART e I2C (Entrega 2)

### Verificação da placa

```bash
ls -l /dev/serial0            # deve apontar para ttyS0 ou ttyAMA0
grep -o 'console=serial0[^ ]*' /proc/cmdline   # não deve listar nada
ls /dev/i2c-1
i2cdetect -y 1                # o BMP280 aparece em 76
groups                        # precisa de dialout e i2c
```

Se o console do kernel estiver na `serial0`, um `getty` disputa os bytes com o
programa. Sem `raspi-config` não é possível corrigir na sessão: registrar no
subcanal e trocar de placa.

### Sequência de verificação

Da menor para a maior consequência. Nenhuma etapa move cabine.

```bash
python3 -m src.comunicacao
uart> p1 pede-int        # Parte 1: a resposta tem 4 bytes
uart> p2 pede-int        # Parte 2: confere CRC e formato da resposta
uart> cabine 1           # Parte 3: 23 bytes de resposta
uart> bmp                # temperatura plausível para a sala
uart> contorno           # watchdog_ambiente vai a 0
uart> predio
```

O widget **uart** do ThingsBoard mostra cada quadro recebido pela ESP32, com o
protocolo identificado e a matrícula em destaque. Se a Raspberry Pi registra
timeout e o widget mostra o quadro, o problema está na resposta; se o widget
não mostra nada, está no envio.

### Diagnóstico

| Sintoma | Causa provável |
|:--|:--|
| Timeout em todos os protocolos | porta errada (`--porta /dev/ttyS0`), console serial ativo ou GND não comum |
| Timeout só nas Partes 2 e 3 | CRC rejeitado pela ESP32; conferir no widget o quadro recebido |
| Timeout só na Parte 1 | comando fora da faixa, comportamento esperado da Seção 1.3 |
| `CrcInvalido` frequente | ruído na linha; as retentativas absorvem casos isolados |
| `RespostaInvalida` na Parte 2 | formato de resposta não previsto; registrar os bytes do RX para ajuste |
| Exceção `0x02` em leitura válida | `qtd` ou `reg` fora do mapa; conferir a ordem little-endian |
| Exceção `0x03` | `porta_comando` fora de 0 a 2 ou `atribuicao_cabine` fora de 1 a 3 |
| `Permission denied` em `/dev/serial0` ou `/dev/i2c-1` | usuário fora dos grupos `dialout` ou `i2c` |
| `Remote I/O error` no BMP280 | sensor ausente no endereço `0x76`; conferir `i2cdetect` |
| `watchdog_ambiente` volta a 1 | escrita automática desligada; `auto on` ou `--contorno-auto` |
