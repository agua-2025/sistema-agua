-- Remove tabelas existentes para garantir um começo limpo
DROP TABLE IF EXISTS usuarios_admin, consumidores, leituras, pagamentos, configuracoes, despesas CASCADE;

-- Criação da tabela de administradores
CREATE TABLE usuarios_admin (
    id SERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    senha_hash TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    reset_token TEXT,
    reset_expira_em TIMESTAMP
);

-- Criação da tabela de consumidores
CREATE TABLE consumidores (
    id SERIAL PRIMARY KEY,
    nome TEXT NOT NULL,
    cpf TEXT UNIQUE,
    rg TEXT,
    endereco TEXT NOT NULL,
    telefone TEXT,
    hidrometro_num TEXT UNIQUE NOT NULL
);

-- Criação da tabela de configurações
CREATE TABLE configuracoes (
    id SERIAL PRIMARY KEY,
    hidr_geral_anterior INTEGER,
    hidr_geral_atual INTEGER,
    consumo_geral INTEGER,
    valor_litro NUMERIC(10, 5) NOT NULL,
    taxa_minima_consumo NUMERIC(10, 2) NOT NULL,
    data_ultima_config DATE NOT NULL,
    dias_uteis_para_vencimento INTEGER NOT NULL,
    multa_percentual NUMERIC(10, 2) NOT NULL,
    juros_diario_percentual NUMERIC(10, 5) NOT NULL
);

-- Criação da tabela de leituras
CREATE TABLE leituras (
    id SERIAL PRIMARY KEY,
    consumidor_id INTEGER NOT NULL REFERENCES consumidores(id),
    leitura_anterior NUMERIC(10, 2),
    leitura_atual NUMERIC(10, 2) NOT NULL,
    data_leitura_anterior DATE,
    data_leitura_atual DATE NOT NULL,
    qtd_dias_utilizados INTEGER,
    litros_consumidos NUMERIC(10, 2),
    media_por_dia NUMERIC(10, 2),
    valor_original NUMERIC(10, 2) NOT NULL,
    taxa_minima_aplicada TEXT,
    valor_taxa_minima NUMERIC(10, 2),
    vencimento DATE,
    foto_hidrometro TEXT
);

-- Criação da tabela de pagamentos
CREATE TABLE pagamentos (
    id SERIAL PRIMARY KEY,
    leitura_id INTEGER NOT NULL REFERENCES leituras(id),
    consumidor_id INTEGER NOT NULL REFERENCES consumidores(id),
    data_pagamento DATE NOT NULL,
    forma_pagamento TEXT NOT NULL,
    valor_pago NUMERIC(10, 2) NOT NULL,
    dias_atraso INTEGER,
    valor_multa NUMERIC(10, 2),
    valor_juros NUMERIC(10, 2),
    total_corrigido NUMERIC(10, 2),
    saldo_devedor NUMERIC(10, 2),
    saldo_credor NUMERIC(10, 2)
);

-- Criação da tabela de despesas
CREATE TABLE despesas (
    id SERIAL PRIMARY KEY,
    data_despesa DATE NOT NULL,
    descricao TEXT NOT NULL,
    valor NUMERIC(10, 2) NOT NULL,
    categoria TEXT,
    observacoes TEXT
);