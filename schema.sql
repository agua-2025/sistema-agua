-- schema.sql

-- Tabela de Usuários Admin
CREATE TABLE IF NOT EXISTS usuarios_admin (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    senha_hash TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    papel TEXT NOT NULL DEFAULT 'normal',
    reset_token TEXT,
    reset_expira_em DATETIME
);

-- Tabela de Consumidores
CREATE TABLE IF NOT EXISTS consumidores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,
    cpf TEXT UNIQUE NOT NULL,
    rg TEXT,
    endereco TEXT NOT NULL,
    telefone TEXT,
    hidrometro_num TEXT UNIQUE
);

-- Tabela de Configurações
CREATE TABLE IF NOT EXISTS configuracoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    multa_percentual REAL NOT NULL DEFAULT 2.0,
    juros_diario_percentual REAL NOT NULL DEFAULT 0.033,
    valor_litro REAL NOT NULL DEFAULT 0.0,
    taxa_minima_consumo REAL NOT NULL DEFAULT 0.0,
    dias_uteis_para_vencimento INTEGER NOT NULL DEFAULT 5,
    hidr_geral_anterior INTEGER NOT NULL DEFAULT 0,
    hidr_geral_atual INTEGER NOT NULL DEFAULT 0,
    consumo_geral INTEGER NOT NULL DEFAULT 0,
    data_ultima_config DATE NOT NULL DEFAULT CURRENT_DATE
);

-- Tabela de Leituras
CREATE TABLE IF NOT EXISTS leituras (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    consumidor_id INTEGER NOT NULL,
    leitura_anterior REAL NOT NULL,
    leitura_atual REAL NOT NULL,
    data_leitura_anterior DATE,
    data_leitura_atual DATE NOT NULL,
    qtd_dias_utilizados INTEGER,
    litros_consumidos REAL,
    media_por_dia REAL,
    valor_original REAL NOT NULL,
    taxa_minima_aplicada TEXT, -- Sim ou Não
    valor_taxa_minima REAL,
    vencimento DATE NOT NULL,
    foto_hidrometro TEXT, -- Caminho/nome do arquivo da foto
    FOREIGN KEY (consumidor_id) REFERENCES consumidores (id)
);

-- Tabela de Pagamentos
CREATE TABLE IF NOT EXISTS pagamentos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    leitura_id INTEGER NOT NULL,
    consumidor_id INTEGER NOT NULL,
    data_pagamento DATE NOT NULL,
    forma_pagamento TEXT NOT NULL,
    valor_pago REAL NOT NULL,
    dias_atraso INTEGER DEFAULT 0,
    valor_multa REAL DEFAULT 0.0,
    valor_juros REAL DEFAULT 0.0,
    total_corrigido REAL DEFAULT 0.0,
    saldo_devedor REAL DEFAULT 0.0,
    saldo_credor REAL DEFAULT 0.0,
    FOREIGN KEY (leitura_id) REFERENCES leituras (id),
    FOREIGN KEY (consumidor_id) REFERENCES consumidores (id)
);

-- Tabela de Despesas
CREATE TABLE IF NOT EXISTS despesas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    data_despesa DATE NOT NULL,
    descricao TEXT NOT NULL,
    valor REAL NOT NULL,
    categoria TEXT,
    observacoes TEXT
);