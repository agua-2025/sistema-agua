import sqlite3

conn = sqlite3.connect("a_g_santa_maria.db")
cursor = conn.cursor()

cursor.execute("DROP TABLE IF EXISTS configuracoes")

cursor.execute("""
CREATE TABLE configuracoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hidr_geral_anterior INTEGER NOT NULL,
    hidr_geral_atual INTEGER NOT NULL,
    consumo_geral INTEGER,
    valor_litro REAL NOT NULL,
    taxa_minima_consumo REAL NOT NULL,
    data_ultima_config TEXT NOT NULL,
    dias_uteis_para_vencimento INTEGER DEFAULT 5
)
""")

print("✅ Tabela 'configuracoes' foi zerada e criada do zero com sucesso.")

conn.commit()
conn.close()
