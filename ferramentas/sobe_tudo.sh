#!/bin/sh
# Sobe o Servidor Central e as tres cabines numa sessao tmux, um por janela.
#
#   ferramentas/sobe_tudo.sh                 # na Raspberry Pi
#   ferramentas/sobe_tudo.sh --registra      # grava dados/pid_cabineN.csv e dados/potencia.csv
#
# Janelas: 0 central, 1..3 cabines (Ctrl+b e o numero troca de janela). Cada
# processo pode ser parado com Ctrl+C e subido de novo na sua janela: os outros
# reconectam sozinhos. A ordem de subida nao importa.
set -e
SESSAO=elevador
cd "$(dirname "$0")/.."
mkdir -p dados

PID_CSV=""
POTENCIA=""
if [ "$1" = "--registra" ]; then
    POTENCIA="--registra-potencia dados/potencia.csv"
    PID_CSV=1
fi

if tmux has-session -t "$SESSAO" 2>/dev/null; then
    echo "sessao '$SESSAO' ja existe: tmux attach -t $SESSAO (ou tmux kill-session -t $SESSAO)"
    exit 1
fi

segura='; echo; echo "processo encerrado - Enter fecha a janela"; read _'
tmux new-session -d -s "$SESSAO" -n central "python3 -m src.central $POTENCIA $segura"
for n in 1 2 3; do
    extra=""
    [ -n "$PID_CSV" ] && extra="--registra-pid dados/pid_cabine$n.csv"
    tmux new-window -t "$SESSAO" -n "cabine$n" "python3 -m src.distribuido --cabine $n $extra $segura"
done
tmux select-window -t "$SESSAO:central"
exec tmux attach -t "$SESSAO"
