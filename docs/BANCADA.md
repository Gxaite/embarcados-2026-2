# Guia da Bancada — Raspberry Pi, Cabine 1

Documento de montagem, configuração e diagnóstico da placa para o Trabalho 1.
Siga na ordem: pinagem → conflitos → configuração do SO → bring-up.

> **O que este documento afirma e o que não afirma.** Os números de GPIO vêm da
> Tabela 1 do enunciado; as posições físicas no header e os conflitos de
> periférico vêm do mapa de pinos da Raspberry Pi 3. **O enunciado não
> especifica o conector físico entre a Raspberry Pi e a ESP32** que roda o
> simulador — isso é dado na bancada. A Seção 7 lista o que vocês precisam
> confirmar no laboratório antes de energizar.

---

## 1. Pinagem da Cabine 1

| Sinal | Função | BCM | Pino físico | Direção |
|:--|:--|:-:|:-:|:--|
| `PWM` | Potência do motor de tração | 12 | **32** | Saída (PWM 1 kHz) |
| `DIR1` | Direção 1 | 17 | **11** | Saída on/off |
| `DIR2` | Direção 2 | 27 | **13** | Saída on/off |
| `ENC_A` | Encoder canal A | 5 | **29** | Entrada (interrupção) |
| `ENC_B` | Encoder canal B | 6 | **31** | Entrada (interrupção) |
| `CORTINA` | Cortina de luz da porta | 16 | **36** | Entrada on/off |
| `SENSOR_ANDAR` | Bandeirola de andar | 11 | **23** | Entrada on/off |

> **O número BCM não é a posição no conector.** `DIR1` é o GPIO 17, que fica no
> pino **11**; `SENSOR_ANDAR` é o GPIO 11, que fica no pino **23**. Contar pinos
> no header achando que são números BCM é o erro de montagem mais comum, e os
> dois casos acima trocam exatamente um pelo outro. O código usa
> `GPIO.setmode(GPIO.BCM)`, então **sempre** o número BCM.

### Header de 40 pinos — `◀` marca os pinos da Cabine 1

```
                      +-------------+
             3V3  ( 1)| o         o |( 2)  5V
    GPIO2  (SDA1) ( 3)| o         o |( 4)  5V
    GPIO3  (SCL1) ( 5)| o         o |( 6)  GND
    GPIO4         ( 7)| o         o |( 8)  GPIO14 (TXD)
             GND  ( 9)| o         o |(10)  GPIO15 (RXD)
 ◀  GPIO17  DIR1  (11)| o         o |(12)  GPIO18
 ◀  GPIO27  DIR2  (13)| o         o |(14)  GND
    GPIO22        (15)| o         o |(16)  GPIO23
             3V3  (17)| o         o |(18)  GPIO24
    GPIO10 (MOSI) (19)| o         o |(20)  GND
    GPIO9  (MISO) (21)| o         o |(22)  GPIO25
 ◀  GPIO11  SENSOR(23)| o         o |(24)  GPIO8  (CE0)
             GND  (25)| o         o |(26)  GPIO7  (CE1)
    GPIO0  (ID_SD)(27)| o         o |(28)  GPIO1  (ID_SC)
 ◀  GPIO5   ENC_A (29)| o         o |(30)  GND
 ◀  GPIO6   ENC_B (31)| o         o |(32)  GPIO12  PWM      ◀
    GPIO13        (33)| o         o |(34)  GND
    GPIO19        (35)| o         o |(36)  GPIO16  CORTINA  ◀
    GPIO26        (37)| o         o |(38)  GPIO20
             GND  (39)| o         o |(40)  GPIO21
                      +-------------+
```

**GND mais próximos de cada grupo:** pino 9 (perto de DIR1/DIR2), pino 25 (perto
do SENSOR_ANDAR) e pino 30 ou 34 (perto do encoder e do PWM). Use o GND mais
curto de cada grupo — fio de terra longo em sinal de encoder gera contagem
fantasma.

### Cabines 2 e 3 (Entrega Final, para planejar o chicote)

| Sinal | Cabine 2 (BCM / físico) | Cabine 3 (BCM / físico) |
|:--|:-:|:-:|
| `PWM` | 13 / 33 | 18 / 12 |
| `DIR1` | 22 / 15 | 24 / 18 |
| `DIR2` | 23 / 16 | 25 / 22 |
| `ENC_A` | 20 / 38 | 7 / 26 |
| `ENC_B` | 21 / 40 | 8 / 24 |
| `CORTINA` | 26 / 37 | 19 / 35 |
| `SENSOR_ANDAR` | 0 / 27 | 1 / 28 |

---

## 2. Conflitos com periféricos — leia antes de ligar

Vários pinos do trabalho têm função alternativa. Se o periférico correspondente
estiver habilitado, o kernel toma o pino e a GPIO simplesmente não responde —
sem mensagem de erro.

| Pino do trabalho | Função alternativa | O que fazer |
|:--|:--|:--|
| `SENSOR_ANDAR` = BCM 11 (Cab. 1) | **SPI0 SCLK** | Manter o **SPI desabilitado** |
| `ENC_A`/`ENC_B` = BCM 7, 8 (Cab. 3) | **SPI0 CE1 / CE0** | idem |
| `SENSOR_ANDAR` = BCM 0, 1 (Cab. 2 e 3) | **ID_SD / ID_SC**, EEPROM de HAT | Ver nota abaixo |
| BCM 2, 3 | **I2C1** — BMP280 da Entrega 2 | Habilitar I2C, **não usar como GPIO** |
| BCM 14, 15 | **UART** — MODBUS da Entrega 2 | Habilitar a serial, **desabilitar o console** |

> **BCM 0 e 1 (pinos 27 e 28)** são reservados à EEPROM de identificação de HAT.
> A Raspberry Pi os sonda no boot. Eles funcionam como GPIO comum depois que o
> sistema sobe, mas se houver um shield com EEPROM no barramento, esses pinos
> não estarão livres. Isso só afeta as Cabines 2 e 3, ou seja, a Entrega Final —
> **a Cabine 1 não usa nenhum dos dois**. Vale confirmar cedo, porque muda o
> plano de montagem.

Como conferir o que está ativo:

```bash
ls /dev/spidev*        # se listar algo, o SPI está ligado — desabilite
ls /dev/i2c-*          # esperado a partir da Entrega 2
ls -l /dev/serial0     # esperado a partir da Entrega 2
raspi-gpio get 11      # mostra o modo atual do pino (esperado: INPUT)
```

---

## 3. Regras elétricas

1. **A GPIO da Raspberry Pi é 3,3 V e não tolera 5 V.** Aplicar 5 V num pino de
   entrada danifica o SoC de forma permanente e não há fusível no caminho.
2. A ESP32 também é 3,3 V, então o enlace entre as duas é direto. **Qualquer
   sinal de 5 V na bancada exige conversor de nível** — confirme antes de ligar.
3. **GND comum é obrigatório.** Raspberry Pi e ESP32 precisam compartilhar
   referência, senão os níveis lógicos ficam indefinidos e as entradas oscilam.
4. Corrente máxima por pino: 16 mA, e 50 mA somados em todos os pinos. O motor
   **não** é alimentado pela Raspberry Pi — o pino de PWM é sinal de comando.
5. Faça toda a montagem com a placa **desenergizada**.

---

## 4. Configuração do sistema

```bash
sudo raspi-config
#  Interface Options > I2C    -> Enable    (BMP280, Entrega 2)
#  Interface Options > Serial -> login shell: NO / hardware: YES  (MODBUS)
#  Interface Options > SPI    -> Disable   (libera o BCM 11 = SENSOR_ANDAR)
sudo reboot
```

Projeto:

```bash
git clone git@github.com:Gxaite/Embarcados-trabalho-2026-2.git
cd Embarcados-trabalho-2026-2
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt   # aqui a RPi.GPIO instala de fato
```

Verificação rápida de que a biblioteca enxerga a placa:

```bash
.venv/bin/python -c "import RPi.GPIO as G; print(G.RPI_INFO)"
```

---

## 5. Bring-up — ordem de ativação

Não ligue tudo de uma vez. Cada etapa isola uma classe de falha, e a ordem é a
da menor para a maior consequência: **entradas antes de saídas, saídas antes de
movimento.**

```bash
.venv/bin/python -m ferramentas.bringup mapa       # 1. confere a pinagem
.venv/bin/python -m ferramentas.bringup entradas   # 2. só lê, não move nada
.venv/bin/python -m ferramentas.bringup encoder    # 3. conta bordas
.venv/bin/python -m ferramentas.bringup direcao    # 4. move o motor
.venv/bin/python -m ferramentas.bringup pwm        # 5. rampa de potência
```

### Etapa 1 — Pinagem
Imprime BCM ↔ pino físico. Confira fio a fio contra a Seção 1 **antes** de
energizar.

### Etapa 2 — Entradas (não move nada)
Mostra o nível de `CORTINA` e `SENSOR_ANDAR` em tempo real.

- Aperte **"Obstruir porta"** no widget → `CORTINA` deve ir a 1 e voltar a 0.
- Empurre a cabine pelo widget até um andar → `SENSOR_ANDAR` vai a 1 dentro da
  bandeirola.
- Se um pino fica preso em 1 ou 0, o problema é fiação ou periférico tomando o
  pino (Seção 2) — não é o código.

### Etapa 3 — Encoder
Mostra a contagem e o número de **transições inválidas**. Mova a cabine pelo
widget:

- A contagem deve **subir** ao subir e **descer** ao descer. Invertido → `ENC_A`
  e `ENC_B` estão trocados.
- 1 contagem = 1 mm. Um andar = 3000 contagens.
- `transicoes_invalidas` deve ficar em **zero**. Ver Seção 6.

### Etapa 4 — Direção (o motor se move)
Percorre as quatro linhas da Tabela 2 com confirmação a cada passo. Mantenha a
mão no Ctrl+C. Se **subir** desce, `DIR1` e `DIR2` estão trocados.

### Etapa 5 — PWM
Rampa de 0 a 30%. A cabine não deve sair do lugar abaixo de ~10% — é o atrito
estático descrito no enunciado, não defeito.

Passadas as cinco etapas, o programa principal está liberado:

```bash
.venv/bin/python -m src.main
```

---

## 6. Diagnóstico

| Sintoma | Causa provável |
|:--|:--|
| Entrada sempre em 0 ou sempre em 1 | Fio no pino errado (BCM × físico), GND não comum, ou periférico tomou o pino (Seção 2) |
| Contagem do encoder anda ao contrário | `ENC_A` e `ENC_B` trocados |
| Contagem anda pela metade ou aos saltos | Só um dos canais está ligado, ou um deles não gera interrupção |
| `transicoes_invalidas` subindo | O Python está perdendo bordas. Reduza `DUTY_MAXIMO` em `src/controle/cabine.py` e confirme se o número para de crescer |
| Cortina contando obstruções fantasmas | `DEBOUNCE_MS` curto demais em `src/controle/cortina.py` |
| Motor zumbe mas não anda | Duty abaixo de 10% — atrito estático, comportamento esperado |
| Cabine sobe quando manda descer | `DIR1`/`DIR2` trocados |
| Cabine para fora dos ±10 mm | Sintonia: ajuste `GANHO_P` e `DUTY_APROXIMACAO` |
| Nada responde e nenhum erro aparece | SPI habilitado tomando o BCM 11, ou `setmode` divergente |

> **`transicoes_invalidas` é o indicador mais importante da bancada.** Ele conta
> saltos de estado impossíveis na quadratura, que só acontecem quando uma borda
> de interrupção se perde. Se ele cresce durante uma viagem, a posição está
> derivando e o nivelamento vai falhar de forma intermitente — exatamente o tipo
> de defeito que não aparece no simulador.

---

## 7. A confirmar na bancada

- [ ] Como a Raspberry Pi se conecta fisicamente à ESP32 (conector, chicote, shield)
- [ ] Se há algum sinal em 5 V no caminho — se houver, conversor de nível é obrigatório
- [ ] Se o shield do BMP280 ocupa BCM 0 e 1 (afeta as Cabines 2 e 3, não a 1)
- [ ] Qual cabine física corresponde à Cabine 1 do enunciado
- [ ] Onde fica o botão "Obstruir porta" no widget

## 8. Registro de medições

Preencher no laboratório — estes números entram no README da entrega.

| Grandeza | Valor medido | Observação |
|:--|:--|:--|
| Largura da bandeirola do andar 0 | | pelas duas bordas |
| Largura da bandeirola do andar 1 | | |
| Largura da bandeirola do andar 2 | | |
| Erro do centro vs. nominal — andar 0 | | |
| Erro do centro vs. nominal — andar 1 | | |
| Erro do centro vs. nominal — andar 2 | | |
| `GANHO_P` final | | |
| `TAXA_RAMPA` final | | |
| `DUTY_MAXIMO` final | | |
| Duty mínimo de arranque medido | | enunciado sugere ~10% |
| `transicoes_invalidas` após 10 viagens | | deve ser 0 |
