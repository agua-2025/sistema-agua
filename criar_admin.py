import sqlite3
from werkzeug.security import generate_password_hash

# Conectar ao banco de dados correto
conn = sqlite3.connect("a_g_santa_maria.db")
cursor = conn.cursor()

# Criar a tabela se ela não existir
cursor.execute("""
CREATE TABLE IF NOT EXISTS usuarios_admin (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    senha_hash TEXT NOT NULL
)
""")
# Criar o usuário admin
senha_hash = generate_password_hash("1234")
try:
    cursor.execute("INSERT INTO usuarios_admin (username, senha_hash) VALUES (?, ?)", ("admin", senha_hash))
    print("✅ Usuário 'admin' criado com sucesso! Senha: 1234")
except sqlite3.IntegrityError:
    print("⚠️ Usuário 'admin' já existe no banco.")

conn.commit()
conn.close()
