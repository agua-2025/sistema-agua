#!/bin/bash
# Sai do script se qualquer comando falhar
set -e

# Instala as dependências
pip install -r requirements.txt

# Executa o comando para inicializar o banco de dados
# Isso garante que a tabela 'usuarios_admin' e outras sejam criadas no servidor
flask init-db