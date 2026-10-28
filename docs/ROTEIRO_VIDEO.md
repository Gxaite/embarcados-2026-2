# Roteiro do Vídeo da Entrega Final

O enunciado pede (Seção 8): vídeo de **até 10 min**, com o **sistema em
funcionamento** e as **partes mais importantes do código**, gravado com a
**câmera ligada mostrando o rosto** dos integrantes. O link vai na tabela de
Vídeos do README, e a entrega é a tag `v3.0` no gitlab.

Não há roteiro oficial para a Final. Este segue a Tabela 2 da avaliação: cada
bloco mostra um item funcionando e o código que o implementa.

## Antes de gravar

1. Placa com BMP280 (`i2cdetect -y 1` mostra `76`); sem ele o watchdog expira
   e as cabines andam a 1000 mA.
2. Roteiro de verificação da seção 10 do [BANCADA.md](BANCADA.md) completo,
   sem falha, na mesma placa.
3. Dashboard da placa aberto na aba do edifício, com o quiosque visível.
4. Editor com os arquivos abaixo já abertos, para não perder tempo na troca.
5. A calibração e o Cenário de Tráfego são longos: gravar inteiros e cortar na
   edição, ou disparar o cenário cedo e voltar a ele no fim.

## Blocos

| Tempo | Item (peso) | Na tela | Código |
|:-:|:--|:--|:--|
| 0:00 | Apresentação | os dois na câmera; diagrama de arquitetura do README | — |
| 0:30 | TCP (1,0) | `./elevador placa`; central sobe antes das cabines e espera por elas; painel com as três `ok` | `src/rede/cliente.py` (`ClienteReconectavel`), `src/rede/protocolo.py` |
| 1:30 | Calibração (0,5) | log de uma cabine: bandeirolas da subida e da descida, tabela final, nivelamento; widget mostrando a cabine nivelada | `src/distribuido/bandeirola.py` (bordas por interrupção), `calibracao.py`, reancoragem em `cabine.py` (`_ao_cruzar_bandeirola`) |
| 3:00 | PID (1,5) | `vai 1 3` no painel: `CHEGADA ... erro` abaixo de 10 mm, porta abre e fecha; gráfico de sintonia do README | `src/distribuido/pid.py` (`calcula`), `malha.py` (rampa, atrito estático), `src/gpio/encoder.py` |
| 4:30 | Cortina | "Obstruir porta" no dashboard durante o fechamento; log com o fechamento inibido e reiniciado | `src/distribuido/porta.py` (`ao_mudar_cortina`) |
| 5:00 | Cota e Degradado (1,0) | painel: temperatura do BMP280, `barramento_max_ma`, watchdog e Cotas somando no máximo o barramento. Com uma cabine andando, `corta-cota 2 20`: ela reduz, pousa no próximo andar, abre a porta e espera a Cota voltar | `src/distribuido/cota.py` (`duty_maximo_de`), `src/central/cotas.py` (`RepartidorDeCotas`), `cabine.py` (`_ciclo_degradado`) |
| 6:30 | Despacho (1,5) | duas ou três chamadas pelo quiosque e a cabine escolhida no painel; um Cenário de Tráfego com a maior espera em curso e as médias | `src/central/despacho.py` (`custo`), `src/distribuido/itinerario.py` (SCAN e origem urgente) |
| 8:00 | Reconexão e SIGINT (Qualidade 1,5) | Ctrl+C numa cabine (motor em freio, painel marca a queda) e subir de novo: reconecta sozinha. Ctrl+C no central e subir de novo: estado e chamadas pendentes restaurados | `src/distribuido/__main__.py` (sinais), `cabine.py` (`finaliza`), `src/central/registro.py` |
| 9:00 | README (0,5) | gráficos dos experimentos e tabela dos cenários | — |

## Comandos do painel usados

| Comando | Bloco |
|:--|:--|
| `vai <cabine> <andar>` | PID |
| `corta-cota <cabine> <segundos>` | Cota e Degradado |
| `status` | qualquer um, se o painel em tela cheia não couber na gravação |
