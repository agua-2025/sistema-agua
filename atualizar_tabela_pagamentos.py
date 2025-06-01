import sqlite3

conn = sqlite3.connect("a_g_santa_maria.db")
cursor = conn.cursor()

# Verifica as colunas atuais da tabela
cursor.execute("PRAGMA table_info(pagamentos)")
colunas = [col[1] for col in cursor.fetchall()]

# Campos que devem existir
novas_colunas = {
    'valor_juros': 'REAL',
    'total_corrigido': 'REAL'
}

for coluna, tipo in novas_colunas.items():
    if coluna not in colunas:
        print(f"🔧 Adicionando a coluna '{coluna}' à tabela 'pagamentos'...")
        cursor.execute(f"ALTER TABLE pagamentos ADD COLUMN {coluna} {tipo}")
    else:
        print(f"✅ A coluna '{coluna}' já existe.")

conn.commit()
conn.close()
