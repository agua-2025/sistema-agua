import sqlite3

conn = sqlite3.connect("a_g_santa_maria.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS consumidores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,
    cpf TEXT NOT NULL UNIQUE,
    rg TEXT,
    endereco TEXT,
    telefone TEXT,
    hidrometro_num TEXT NOT NULL UNIQUE
)
""")
print("Tabela 'consumidores' criada com sucesso!")

conn.commit()
conn.close()
