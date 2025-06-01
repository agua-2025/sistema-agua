import sqlite3

def adicionar_campo(conn, nome_campo, tipo_sql):
    cursor = conn.cursor()
    try:
        cursor.execute(f"ALTER TABLE configuracoes ADD COLUMN {nome_campo} {tipo_sql}")
        print(f"✅ Campo '{nome_campo}' adicionado.")
    except sqlite3.OperationalError as e:
        if f"duplicate column name: {nome_campo}" in str(e).lower():
            print(f"ℹ️ Campo '{nome_campo}' já existe.")
        else:
            print(f"❌ Erro ao adicionar campo '{nome_campo}': {e}")

conn = sqlite3.connect("a_g_santa_maria.db")

# Adiciona os novos campos necessários
adicionar_campo(conn, "multa_percentual", "REAL DEFAULT 0.0")
adicionar_campo(conn, "juros_diario_percentual", "REAL DEFAULT 0.0")

conn.commit()
conn.close()
print("✅ Atualização da tabela 'configuracoes' concluída.")
