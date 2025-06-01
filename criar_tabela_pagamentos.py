import sqlite3

conn = sqlite3.connect("a_g_santa_maria.db")
cursor = conn.cursor()

cursor.execute("PRAGMA table_info(pagamentos)")
colunas = [col[1] for col in cursor.fetchall()]

if not all(col in colunas for col in ['consumidor_id', 'valor_juros', 'total_corrigido']):
    print("🔧 Atualizando a tabela 'pagamentos' com as colunas necessárias...")

    # Renomeia tabela atual
    cursor.execute("ALTER TABLE pagamentos RENAME TO pagamentos_backup")

    # Cria nova tabela com as colunas atualizadas
    cursor.execute("""
        CREATE TABLE pagamentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            consumidor_id INTEGER,
            leitura_id INTEGER NOT NULL,
            data_pagamento TEXT NOT NULL,
            forma_pagamento TEXT NOT NULL,
            valor_pago REAL NOT NULL,
            dias_atraso INTEGER,
            valor_multa REAL,
            valor_juros REAL,
            total_corrigido REAL,
            saldo_credor REAL,
            saldo_devedor REAL,
            FOREIGN KEY(leitura_id) REFERENCES leituras(id),
            FOREIGN KEY(consumidor_id) REFERENCES consumidores(id)
        )
    """)

    # Copia dados existentes para nova tabela (valores novos ficarão nulos)
    cursor.execute("""
        INSERT INTO pagamentos (
            id, consumidor_id, leitura_id, data_pagamento, forma_pagamento,
            valor_pago, dias_atraso, valor_multa, saldo_credor, saldo_devedor
        )
        SELECT
            id, NULL, leitura_id, data_pagamento, forma_pagamento,
            valor_pago, dias_atraso, valor_multa, saldo_credor, saldo_devedor
        FROM pagamentos_backup
    """)

    # Exclui tabela antiga
    cursor.execute("DROP TABLE pagamentos_backup")

    print("✅ Tabela 'pagamentos' atualizada com sucesso!")
else:
    print("✅ Todas as colunas já existem. Nenhuma alteração foi necessária.")

conn.commit()
conn.close()
