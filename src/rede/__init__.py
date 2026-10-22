"""Comunicacao TCP/IP entre o Servidor Central e os Servidores Distribuidos.

  protocolo.py  mensagens: um objeto JSON por linha
  conexao.py    uma conexao estabelecida: envio com trava e leitura em thread
  servidor.py   lado da cabine: escuta na porta do arquivo de configuracao
  cliente.py    lado do central: conecta e reconecta sozinho

Cada Servidor Distribuido escuta na sua porta e o Servidor Central conecta nos
tres. Assim qualquer processo pode subir primeiro: a cabine espera a conexao
chegar, e o central insiste ate a cabine aparecer, a cada segundo.
"""
