# Script correto para criar a tabela 'leituras' com todos os campos atualizados e consistentes

import sqlite3

# Conecta ao banco de dados
conn = sqlite3.connect("a_g_santa_maria.db")
cursor = conn.cursor()

# Criação da tabela 'leituras' com todos os campos necessários
cursor.execute("""
CREATE TABLE IF NOT EXISTS leituras (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    consumidor_id INTEGER NOT NULL,
    leitura_anterior INTEGER NOT NULL,
    data_leitura_anterior TEXT NOT NULL,
    leitura_atual INTEGER NOT NULL,
    data_leitura_atual TEXT NOT NULL,
    qtd_dias_utilizados INTEGER,
    litros_consumidos INTEGER,
    media_por_dia REAL,
    foto_hidrometro TEXT,
    vencimento TEXT,
    valor_original REAL,
    taxa_minima_aplicada TEXT,
    valor_taxa_minima REAL,
    status_pagamento TEXT,
    FOREIGN KEY(consumidor_id) REFERENCES consumidores(id)
)
""")

# Mensagem de sucesso
print("✅ Tabela 'leituras' criada com sucesso!")

# Salva e fecha a conexão
conn.commit()
conn.close()
