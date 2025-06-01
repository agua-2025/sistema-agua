import sqlite3

conn = sqlite3.connect("a_g_santa_maria.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS configuracoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hidr_geral_anterior INTEGER NOT NULL,
    hidr_geral_atual INTEGER NOT NULL,
    consumo_geral INTEGER,
    valor_litro REAL NOT NULL,
    taxa_minima_consumo REAL NOT NULL,
    data_ultima_config TEXT NOT NULL,
    dias_uteis_para_vencimento INTEGER DEFAULT 5,
    multa_percentual REAL DEFAULT 2.0,
    juros_diario_percentual REAL DEFAULT 0.33
)
""")

print("✅ Tabela 'configuracoes' criada com sucesso.")
conn.commit()
conn.close()
