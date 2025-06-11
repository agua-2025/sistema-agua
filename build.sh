#!/bin/bash
# Este script sai imediatamente se qualquer comando falhar
set -e

echo "Iniciando processo de build..."

# 1. Instala as dependências do Python
echo "Instalando dependências de requirements.txt..."
pip install -r requirements.txt

# 2. Conecta ao PostgreSQL e executa o schema.sql para criar as tabelas
# A variável DATABASE_URL é configurada por você no ambiente do Render
echo "Executando schema.sql para criar as tabelas..."
psql -v ON_ERROR_STOP=1 --quiet --no-psqlrc -d "$DATABASE_URL" -f schema.sql

# 3. Insere o usuário administrador padrão
echo "Inserindo usuário admin padrão..."
# Gera o hash da senha 'admin123' na hora para segurança
ADMIN_HASH=$(python -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('admin123'))")
# Executa o comando INSERT. O -c significa que estamos passando um comando direto
psql -v ON_ERROR_STOP=1 --quiet --no-psqlrc -d "$DATABASE_URL" -c "INSERT INTO usuarios_admin (username, senha_hash, email) VALUES ('admin', '$ADMIN_HASH', 'admin@example.com');"

echo "Build finalizado com sucesso!"