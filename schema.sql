-- Remove tabelas existentes para garantir um começo limpo
DROP TABLE IF EXISTS usuarios_admin;
DROP TABLE IF EXISTS consumidores;
DROP TABLE IF EXISTS leituras;
DROP TABLE IF EXISTS pagamentos;
DROP TABLE IF EXISTS configuracoes;
DROP TABLE IF EXISTS despesas;

-- Criação da tabela de administradores
CREATE TABLE usuarios_admin (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    senha_hash TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    reset_token TEXT,
    reset_expira_em DATETIME
);

-- Criação da tabela de consumidores
CREATE TABLE consumidores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,
    cpf TEXT UNIQUE,
    rg TEXT,
    endereco TEXT NOT NULL,
    telefone TEXT,
    hidrometro_num TEXT UNIQUE NOT NULL
);

-- Criação da tabela de configurações
CREATE TABLE configuracoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hidr_geral_anterior INTEGER,
    hidr_geral_atual INTEGER,
    consumo_geral INTEGER,
    valor_litro REAL NOT NULL,
    taxa_minima_consumo REAL NOT NULL,
    data_ultima_config DATE NOT NULL,
    dias_uteis_para_vencimento INTEGER NOT NULL,
    multa_percentual REAL NOT NULL,
    juros_diario_percentual REAL NOT NULL
);

-- Criação da tabela de leituras
CREATE TABLE leituras (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    consumidor_id INTEGER NOT NULL,
    leitura_anterior REAL,
    leitura_atual REAL NOT NULL,
    data_leitura_anterior DATE,
    data_leitura_atual DATE NOT NULL,
    qtd_dias_utilizados INTEGER,
    litros_consumidos REAL,
    media_por_dia REAL,
    valor_original REAL NOT NULL,
    taxa_minima_aplicada TEXT,
    valor_taxa_minima REAL,
    vencimento DATE,
    foto_hidrometro TEXT,
    FOREIGN KEY (consumidor_id) REFERENCES consumidores (id)
);

-- Criação da tabela de pagamentos
CREATE TABLE pagamentos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    leitura_id INTEGER NOT NULL,
    consumidor_id INTEGER NOT NULL,
    data_pagamento DATE NOT NULL,
    forma_pagamento TEXT NOT NULL,
    valor_pago REAL NOT NULL,
    dias_atraso INTEGER,
    valor_multa REAL,
    valor_juros REAL,
    total_corrigido REAL,
    saldo_devedor REAL,
    saldo_credor REAL,
    FOREIGN KEY (leitura_id) REFERENCES leituras (id),
    FOREIGN KEY (consumidor_id) REFERENCES consumidores (id)
);

-- Criação da tabela de despesas
CREATE TABLE despesas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    data_despesa DATE NOT NULL,
    descricao TEXT NOT NULL,
    valor REAL NOT NULL,
    categoria TEXT,
    observacoes TEXT
);

-- Inserção do usuário administrador padrão
-- Este usuário será criado toda vez que o banco de dados for inicializado.
-- Usuário: admin
-- Senha:   admin123
-- É MUITO IMPORTANTE alterar esta senha ou cadastrar um novo usuário após o primeiro login.
INSERT INTO usuarios_admin (username, senha_hash, email) VALUES (
    'admin',
    'pbkdf2:sha256:600000$Vp3v7bNl2aYkRzXw$c81b7e9b3a2d5f4c1e0d9b8a7c6d5e4f3a2b1c0d9e8f7a6b5c4d3e2f1a0b9c8d', -- Hash para 'admin123'
    'admin@example.com'
);
