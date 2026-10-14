# Elevador Embarcado: Trabalho 1

Fundamentos de Sistemas Embarcados, 2026/2. Controle de elevadores em uma
Raspberry Pi, contra o simulador de edifício da ESP32 da bancada.

| Entrega | Conteúdo | Tag | Comando |
|:--|:--|:-:|:--|
| 1 | GPIO e malha de posição da Cabine 1 | `v1.0` | `python3 -m src.main` |
| 2 | UART-MODBUS (Partes 1, 2 e 3) e I2C | `v2.0` | `python3 -m src.comunicacao --matricula <matricula>` |

## Integrantes

Listados no repositório de entrega.

## Vídeos

| Entrega | Link |
|:--|:--|
| 1 | https://youtu.be/LKAWTPL8WLw |
| 2 | a ser adicionado |

## Execução

Python 3. Na Raspberry Pi do laboratório não há nada a instalar; em outra
máquina, `pip install -r requirements.txt`.

### Entrega 1: GPIO

```bash
python3 -m src.main
```

Antes de iniciar, posicionar a cabine no andar 0 e acionar "Resetar bancada"
no dashboard.

| Comando | Função |
|:--|:--|
| `andar <0\|1\|2>` | viaja até o andar |
| `ir <mm>` | viaja até uma posição |
| `motor <livre\|subir\|descer\|freio> <duty>` | acionamento direto |
| `parar` | zera o PWM e freia |
| `estado` | encoder, posição, motor, cortina e sensor de andar |
| `sair` | encerra com segurança |

### Entrega 2: UART e I2C

```bash
python3 -m src.comunicacao --matricula <matricula>
```

São usados os 6 últimos dígitos da matrícula. O programa abre num menu:

```
1  Parte 1 - protocolo simplificado (sem CRC)   receber valores, enviar valores, comando inválido
2  Parte 2 - MODBUS didatico (com CRC)          receber valores, enviar valores
3  Parte 3 - demonstracao                       watchdog, porta, chamada e exceções
4  Terminal UART                                comandos digitados ('ajuda' lista)
0  Sair
```

Cada opção mostra o comando executado, os bytes enviados (`TX`) e recebidos
(`RX`) e os campos decodificados. A Parte 3 explica cada passo antes de
executá-lo e, na fila, espera uma chamada ser registrada no quiosque do
dashboard (qualquer origem e destino) e segue sozinha.

Principais comandos do terminal:

| Comando | Função |
|:--|:--|
| `p1 <cmd>`, `p2 <cmd>` | Partes 1 e 2: `pede-int`, `pede-float`, `pede-string`, `envia-int <n>`, `envia-float <x>`, `envia-string <texto>` |
| `cabine <n>`, `predio` | `le_estado_cabine()`, `le_estado_predio()` |
| `porta <n> <abrir\|fechar>` | `comanda_porta()` |
| `fila`, `atribui <id> <cabine>`, `pop` | `le_chamada_da_fila()`, `atribui_chamada()`, `remove_chamada_da_fila()` |
| `contorno` | `escreve_condicao_contorno()` com o BMP280 |
| `monitora cabine <n>`, `monitora predio` | leitura contínua a cada 1 s, até Enter |
| `bmp`, `auto on\|off` | lê o BMP280; liga ou desliga a escrita da Condição de Contorno a cada 4 s |

Matrícula em destaque no widget **uart**: print a ser adicionado.

## Estrutura

```
src/
├── gpio/        Entrega 1: saídas on/off e PWM, entradas por polling e interrupção, encoder
├── controle/    Entrega 1: motor, cortina, sensor de andar e malha de posição da cabine
├── uart/        Entrega 2: porta serial, CRC-16, Partes 1, 2 e 3
├── i2c/         Entrega 2: driver do BMP280
├── central/     Entrega 2: Condição de Contorno (BMP280 -> prédio, a cada 4 s)
├── main.py      ponto de entrada da Entrega 1
└── comunicacao.py  ponto de entrada da Entrega 2
```

`src/uart/modbus.py` e `src/uart/elevadores.py` não dependem da interface e
serão importados pela Entrega Final.

## Implementação

**Entrega 1**

- PWM a 1 kHz com rampa de 120 %/s; `DIR1`/`DIR2` pela tabela de direção.
- Encoder em quadratura 4x por interrupção nos dois canais, contador de 32
  bits protegido por lock.
- Cortina com debounce de 20 ms; Sensor de Andar pelas duas bordas, com o
  centro da bandeirola pela média das contagens.
- Malha de posição a 50 ms, parada dentro de ±10 mm, renivelamento por pulsos
  e reancoragem da contagem a cada bandeirola.
- Sem busy-wait. `SIGINT`, `SIGTERM` e `SIGHUP` zeram o PWM, freiam e liberam
  a GPIO.

**Entrega 2**

- UART a 115200 8N1 em modo cru, pelo `termios`, com espera por `select()`.
- CRC-16 com polinômio `0xA001` e valor inicial **zero** (CRC-16/ARC),
  conferido contra os exemplos do enunciado; o MODBUS padrão começa em
  `0xFFFF`.
- Parte 3: a resposta é validada (CRC, endereço, função, `byte_count`, eco) e
  repetida até 3 vezes em timeout ou CRC inválido; exceções são reportadas sem
  repetir. O `pop` da fila relê a fila antes de repetir, para não remover duas
  chamadas.
- BMP280 pelo `/dev/i2c-1`, com a compensação do datasheet. Uma thread escreve
  temperatura e pressão no prédio a cada 4 s, dentro do watchdog de 30 s.

## Testes

```bash
python3 -m pytest tests/ -q
```

A verificação da placa por etapas está em [docs/BANCADA.md](docs/BANCADA.md).
