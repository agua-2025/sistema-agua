print("--- EXECUTANDO A VERSÃO MAIS RECENTE DO APP.PY ---")
from flask import Flask, render_template, request, redirect, url_for, session, g, jsonify, flash, make_response, send_file
#import sqlite3
from werkzeug.security import check_password_hash, generate_password_hash
import os
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta, date 
import secrets
import smtplib
from email.mime.text import MIMEText
from email.utils import formataddr
from functools import wraps
from urllib.parse import quote
import math
from flask import Response
from weasyprint import HTML
import logging
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
import json 
from flask import render_template, flash, redirect, url_for, request, session
from datetime import datetime
from urllib.parse import quote
from flask import session 
import base64
from mimetypes import guess_type
from datetime import date, datetime
import boto3
from botocore.exceptions import NoCredentialsError
import requests

# --- NOVO: O "Tradutor" de JSON Definitivo ---
class CustomJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        # Se o objeto for do tipo data ou data/hora, converte para o formato universal AAAA-MM-DD
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        return super(CustomJSONEncoder, self).default(obj)

# ----------------------------------------------

# Configuração básica do logger
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s in %(module)s: %(message)s')

load_dotenv(override=True)

# --- Configurações da Aplicação ---
app = Flask(__name__)
# Diz ao Flask para usar nosso novo "tradutor"
app.json_encoder = CustomJSONEncoder

# Chave secreta deve ser lida de variável de ambiente em produção
app.secret_key = os.environ.get('SECRET_KEY', 'sua-chave-super-secreta-para-desenvolvimento') # Mantenha esta linha para segurança

# --- NOVA CONFIGURAÇÃO DO BANCO DE DADOS (PostgreSQL com SQLAlchemy) ---
# Endereço do banco NOVO (Supabase)
DATABASE_URL = "postgresql://postgres.vxwfgtkbnjublwdyifmd:jkUGAClLrgjkhPid@aws-0-sa-east-1.pooler.supabase.com:6543/postgres"

# Cria o "adaptador universal"
engine = create_engine(DATABASE_URL)

#DATABASE = 'a_g_santa_maria.db' # Agora no local esperado

UPLOAD_FOLDER = 'static/fotos_hidrometros'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# --- Filtros Jinja2 Personalizados --- (COLOQUE O CÓDIGO DO FILTRO AQUI!)
@app.template_filter('date_format')
def date_format_filter(value, format="%d/%m/%Y"):
    if not value:
        return ""
    
    # MELHORIA: Se o valor for a string 'now', retorna a data atual já formatada.
    if isinstance(value, str) and value.lower() == 'now':
        return date.today().strftime(format)
    
    # Se o valor já for um objeto de data ou datetime, formata diretamente.
    if isinstance(value, (datetime, date)):
        return value.strftime(format)
        
    # Se for texto, tenta converter
    try:
        # Tenta o formato completo primeiro
        dt_obj = datetime.strptime(str(value), '%Y-%m-%d %H:%M:%S.%f')
    except ValueError:
        try:
            # Tenta apenas o formato de data
            dt_obj = datetime.strptime(str(value), '%Y-%m-%d')
        except ValueError:
            # Se tudo falhar, loga o aviso e retorna o valor original
            app.logger.warning(f"Erro ao formatar data '{value}': formato inválido.")
            return str(value) 

    return dt_obj.strftime(format)

# --- Funções Auxiliares ---

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- NOVAS FUNÇÕES DE CONEXÃO ---
def get_db():
    if 'db' not in g:
        # Usa o nosso "adaptador" (engine) para conectar
        g.db = engine.connect()
    return g.db

@app.teardown_appcontext
def close_db(error):
    # O adaptador sabe como fechar a conexão corretamente
    db = g.pop('db', None)
    if db is not None:
        db.close()

# Função para inicializar o banco de dados (criar tabelas) - Se você tiver schema.sql
def init_db():
    with app.app_context():
        db = get_db()
        # Abre o arquivo schema.sql e executa os comandos SQL
        try:
            with app.open_resource('schema.sql', mode='r') as f:
                db.cursor().executescript(f.read())
            db.commit()
            logging.info("Database initialized successfully from schema.sql.")
        except FileNotFoundError:
            logging.warning("schema.sql not found. Database tables might not be created. Proceeding without initialization.")
        except Exception as e:
            logging.error(f"Error initializing database from schema.sql: {e}", exc_info=True)


# Decorador para verificar se o usuário está logado
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'usuario' not in session:
            flash('Você precisa estar logado para acessar esta página.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# NOVO: Decorador para verificar se o usuário é ADMIN
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'usuario' not in session: # Se não estiver logado
            flash('Você precisa estar logado para acessar esta página.', 'warning')
            return redirect(url_for('login'))
        # VERIFICA O PAPEL DO USUÁRIO NA SESSÃO
        if session.get('papel') != 'admin': # Se logado, mas NÃO é admin
            flash('Acesso negado: Você não tem permissão para acessar esta funcionalidade.', 'danger')
            return redirect(url_for('dashboard')) # Redireciona para o dashboard
        return f(*args, **kwargs)
    return decorated_function

# Função auxiliar para obter as configurações mais recentes (VERSÃO CORRIGIDA)
def get_current_config():
    db = get_db()
    # Query agora também seleciona o ID
    resultado_bruto = db.execute(text('''
        SELECT id, COALESCE(multa_percentual, 2.0) AS multa_percentual,
               COALESCE(juros_diario_percentual, 0.033) AS juros_diario_percentual,
               COALESCE(valor_m3, 0.0) AS valor_m3,
               COALESCE(taxa_minima_consumo, 0.0) AS taxa_minima_consumo,
               COALESCE(dias_uteis_para_vencimento, 5) AS dias_uteis_para_vencimento,
               COALESCE(hidr_geral_anterior, 0) AS hidr_geral_anterior,
               COALESCE(hidr_geral_atual, 0) AS hidr_geral_atual,
               COALESCE(data_ultima_config, NOW()) AS data_ultima_config,
               COALESCE(consumo_geral, 0) AS consumo_geral,
               COALESCE(taxa_minima_franquia_m3, 10.0) AS taxa_minima_franquia_m3
        FROM configuracoes ORDER BY id DESC LIMIT 1
    ''')).fetchone()
    
    if resultado_bruto:
        return resultado_bruto._asdict()
    else:
        # Se não houver nenhuma configuração, retorna um dicionário sem ID
        return {
            'id': None, 'multa_percentual': 2.0, 'juros_diario_percentual': 0.033,
            'valor_m3': 0.0, 'taxa_minima_consumo': 0.0,
            'dias_uteis_para_vencimento': 5, 'hidr_geral_anterior': 0,
            'hidr_geral_atual': 0, 'data_ultima_config': date.today().strftime('%Y-%m-%d'),
            'consumo_geral': 0, 'taxa_minima_franquia_m3': 10.0
        }
    
# FUNÇÃO `calcular_penalidades` CORRIGIDA
def calcular_penalidades(valor_original_fatura, valor_base_para_juros, data_vencimento_obj, data_referencia_str, config_multa_percentual, config_juros_diario_percentual):
    """
    Calcula multas e juros para uma fatura atrasada.

    Args:
        valor_original_fatura (float): Valor original da fatura.
        valor_base_para_juros (float): Valor sobre o qual os juros serão calculados.
        data_vencimento_obj (datetime.date): Objeto de data de vencimento da fatura (vindo do banco).
        data_referencia_str (str): String da data de referência para o cálculo (ex: 'YYYY-MM-DD').
        config_multa_percentual (float): Percentual da multa (ex: 2.0 para 2%).
        config_juros_diario_percentual (float): Percentual dos juros diários (ex: 0.033 para 0.033%).

    Returns:
        tuple: (multa_calculada, juros_calculado, dias_atraso)
    """
    multa = 0.0
    juros = 0.0
    dias_atraso = 0

    try:
        # data_referencia_str É UMA STRING E PRECISA SER PARSEADA.
        data_referencia_dt = datetime.strptime(data_referencia_str, '%Y-%m-%d').date()
        
        # Garante que data_vencimento_obj é um objeto date (para caso venha datetime)
        # NÃO TENTE PARSEAR `data_vencimento_obj` COM `strptime`, POIS JÁ É UM OBJETO DATE/DATETIME.
        data_vencimento_date = data_vencimento_obj.date() if isinstance(data_vencimento_obj, datetime) else data_vencimento_obj

        dias_atraso = max((data_referencia_dt - data_vencimento_date).days, 0)
    except (ValueError, TypeError) as e:
        app.logger.warning(f"Erro ao parsear datas para cálculo de penalidades na função 'calcular_penalidades': {e}. "
                           f"Data Vencimento Recebida: '{data_vencimento_obj}' (Tipo: {type(data_vencimento_obj)}), "
                           f"Data Referência Recebida: '{data_referencia_str}' (Tipo: {type(data_referencia_str)})")
        dias_atraso = 0
        multa = 0.0
        juros = 0.0
    
    if dias_atraso > 0:
        multa = round(valor_original_fatura * (config_multa_percentual / 100), 2)
        juros = round(valor_base_para_juros * (config_juros_diario_percentual / 100) * dias_atraso, 2)
    
    return multa, juros, dias_atraso

# NOVA FUNÇÃO DE PARSE SEGURA
def parse_number_from_br_form(value_str):
    if not value_str:
        return 0.0
    
    s_value = str(value_str).strip()
    s_value = s_value.replace('R$', '').replace(' ', '')
    
    if ',' in s_value:
        s_value = s_value.replace('.', '')
        s_value = s_value.replace(',', '.')
    
    try:
        return float(s_value)
    except ValueError:
        app.logger.warning(f"Falha ao converter '{value_str}' (limpo para '{s_value}') para float. Retornando 0.0.")
        return 0.0

def adicionar_dias_uteis(data_inicial, dias_uteis):
    dias_adicionados = 0
    data_final = data_inicial
    while dias_adicionados < dias_uteis:
        data_final += timedelta(days=1)
        if data_final.weekday() < 5: # segunda a sexta (0=segunda, 4=sexta)
            dias_adicionados += 1
    return data_final

#--------------Validçaão do CPF------------------
def is_cpf_valido(cpf: str) -> bool:
    """Valida um CPF brasileiro. Retorna True se válido, False caso contrário."""
    # Remove caracteres não numéricos
    cpf = ''.join(filter(str.isdigit, str(cpf)))

    # Verifica se tem 11 dígitos
    if len(cpf) != 11:
        return False

    # Verifica se todos os dígitos são iguais (ex: 111.111.111-11), que são inválidos
    if cpf == cpf[0] * 11:
        return False

    # Cálculo do primeiro dígito verificador
    soma = sum(int(cpf[i]) * (10 - i) for i in range(9))
    resto = (soma * 10) % 11
    if resto == 10:
        resto = 0
    if resto != int(cpf[9]):
        return False

    # Cálculo do segundo dígito verificador
    soma = sum(int(cpf[i]) * (11 - i) for i in range(10))
    resto = (soma * 10) % 11
    if resto == 10:
        resto = 0
    if resto != int(cpf[10]):
        return False

    return True

# FUNÇÃO ENVIAR_EMAIL CORRIGIDA E ÚNICA
def enviar_email(destino, assunto, corpo):
    msg = MIMEText(corpo, 'plain', 'utf-8')
    msg['Subject'] = assunto
    msg['From'] = formataddr(('Águas de Santa Maria', os.environ.get('EMAIL_USER', 'seu-email@gmail.com')))
    msg['To'] = destino

    try:
        # ADICIONE ESTAS DUAS LINHAS DE DEBUG AQUI:
        print(f"DEBUG E-MAIL: EMAIL_USER visto: '{os.environ.get('EMAIL_USER')}'")
        print(f"DEBUG E-MAIL: EMAIL_PASS visto: '{os.environ.get('EMAIL_PASS')}'")

        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            # Credenciais do Gmail lidas de variáveis de ambiente
            server.login(os.environ.get('EMAIL_USER'), os.environ.get('EMAIL_PASS')) 
            server.sendmail(msg['From'], [destino], msg.as_string())
        app.logger.info(f"E-mail enviado com sucesso para {destino}")
        return True
    except Exception as e:
        app.logger.error(f"❌ Erro ao enviar e-mail para {destino}: {e}", exc_info=True)
        return False
    
# --- Rotas de Autenticação ---
@app.route('/')
def home():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form['username']
        senha = request.form['password']
        db = get_db()
        
        resultado_bruto = db.execute(
            text('SELECT * FROM usuarios_admin WHERE username = :username'), 
            {'username': username}
        ).fetchone()
        
        # --- A MUDANÇA ESTÁ AQUI ---
        # Trocamos dict() por ._asdict()
        user = resultado_bruto._asdict() if resultado_bruto else None

        # O resto do código continua igual e deve funcionar agora
        if user and check_password_hash(user['senha_hash'], senha):
            session['usuario'] = username
            session['papel'] = user['papel']
            flash('Login realizado com sucesso!', 'success')
            return redirect(url_for('dashboard'))
        else:
            error = 'Usuário ou senha inválidos.'
            flash(error, 'danger')
            
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.pop('usuario', None)
    flash('Você foi desconectado.', 'info')
    return redirect(url_for('login'))


# ------------- Dashboard -------------------
@app.route('/dashboard')
@login_required
def dashboard():
    """
    Busca os dados reais do sistema para exibir nos cards do dashboard.
    """
    try:
        db = get_db()
        
        # CORREÇÃO 1: A consulta agora conta as 'unidades_consumidoras' ativas.
        total_unidades_ativas = db.execute(text("SELECT COUNT(id) FROM unidades_consumidoras WHERE status = 'Ativo'")).fetchone()[0]
        
        # As outras consultas não são afetadas pela mudança, então permanecem iguais.
        total_usuarios = db.execute(text('SELECT COUNT(id) FROM usuarios_admin')).fetchone()[0]
        
        # --- CORREÇÃO PONTUAL AQUI: Conta o número de transações de pagamento do dia ---
        hoje = date.today().strftime('%Y-%m-%d')
        # Agora busca a CONTAGEM de pagamentos (COALESCE para garantir 0 se não houver pagamentos)
        valor_pagamentos_hoje = db.execute(text('SELECT COALESCE(COUNT(id), 0) FROM pagamentos WHERE data_pagamento = :data'), {'data': hoje}).fetchone()[0]
        
        faturas_pendentes = db.execute(text('''
            WITH PagamentosAgregados AS (
                SELECT
                    leitura_id,
                    SUM(valor_pago) as total_pago,
                    SUM(valor_multa) as total_multa,
                    SUM(valor_juros) as total_juros
                FROM pagamentos
                GROUP BY leitura_id
            )
            SELECT COUNT(l.id)
            FROM leituras l
            LEFT JOIN PagamentosAgregados p ON l.id = p.leitura_id
            WHERE (l.valor_original + COALESCE(p.total_multa, 0) + COALESCE(p.total_juros, 0)) > (COALESCE(p.total_pago, 0) + 0.001)
        ''')).fetchone()[0]

        return render_template(
            'dashboard.html', 
            user=session.get('usuario'),
            # CORREÇÃO 2: Passamos o novo valor, mas com o nome antigo da variável ('total_consumidores')
            # para não precisarmos mexer no arquivo HTML do dashboard.
            total_consumidores=total_unidades_ativas,
            total_usuarios=total_usuarios,
            # Passando o novo valor somado aqui, mantendo o nome da variável para compatibilidade com o template
            pagamentos_hoje=valor_pagamentos_hoje, 
            faturas_pendentes=faturas_pendentes
        )
    except Exception as e:
        app.logger.error(f"Erro ao carregar o dashboard: {e}", exc_info=True)
        flash("Ocorreu um erro ao carregar os dados do painel. Tente novamente.", "danger")
        # Se der erro, redireciona para o login para evitar um loop de erros no dashboard.
        return redirect(url_for('login'))


#---------Configurações----------
@app.route('/configuracoes', methods=['GET', 'POST'])
@admin_required
def configuracoes():
    if request.method == 'POST':
        form = request.form
        try:
            db = get_db()
            with db.begin():
                # Coleta todos os dados do formulário em um dicionário de parâmetros
                params = {
                    'h_ant': int(form.get('hidr_geral_anterior', 0)), 
                    'h_atu': int(form.get('hidr_geral_atual', 0)), 
                    'v_m3': parse_number_from_br_form(form.get('valor_m3')), 
                    't_min': parse_number_from_br_form(form.get('taxa_minima_consumo')), 
                    'd_conf': form.get('data_ultima_config') or date.today().strftime('%Y-%m-%d'),
                    'd_venc': int(form.get('dias_uteis_para_vencimento', 5)), 
                    'multa': parse_number_from_br_form(form.get('multa_percentual')), 
                    'juros': parse_number_from_br_form(form.get('juros_diario_percentual')),
                    'franquia_m3': parse_number_from_br_form(form.get('taxa_minima_franquia_m3'))
                }
                params['c_ger'] = params['h_atu'] - params['h_ant']

                # Verifica se já existe uma linha de configuração
                config_row = db.execute(text("SELECT id FROM configuracoes LIMIT 1")).fetchone()

                if config_row:
                    # SE EXISTE: ATUALIZA a linha existente (lógica de EDIÇÃO)
                    # Não precisamos de um WHERE, pois só haverá uma linha para ser atualizada.
                    db.execute(text("""
                        UPDATE configuracoes SET
                            hidr_geral_anterior = :h_ant, hidr_geral_atual = :h_atu, consumo_geral = :c_ger,
                            valor_m3 = :v_m3, taxa_minima_consumo = :t_min, data_ultima_config = :d_conf,
                            dias_uteis_para_vencimento = :d_venc, multa_percentual = :multa, 
                            juros_diario_percentual = :juros, taxa_minima_franquia_m3 = :franquia_m3
                    """), params)
                else:
                    # SE NÃO EXISTE: INSERE a primeira linha
                    db.execute(text("""
                        INSERT INTO configuracoes (
                            hidr_geral_anterior, hidr_geral_atual, consumo_geral, valor_m3, 
                            taxa_minima_consumo, data_ultima_config, dias_uteis_para_vencimento, 
                            multa_percentual, juros_diario_percentual, taxa_minima_franquia_m3
                        ) VALUES (
                            :h_ant, :h_atu, :c_ger, :v_m3, :t_min, :d_conf, :d_venc, 
                            :multa, :juros, :franquia_m3
                        )
                    """), params)
            
            flash("Configuração salva com sucesso!", 'success')
        except Exception as e:
            app.logger.error(f"Erro ao salvar configuração: {e}", exc_info=True)
            flash(f"Erro ao salvar configuração: {str(e)}", 'danger')
        
        return redirect(url_for('configuracoes'))
    
    # A lógica GET para exibir a página continua a mesma
    config = get_current_config()
    return render_template('configuracoes.html', config=config)

# --- API para Configurações (Juros e Multa) ---
@app.route('/api/configuracoes')
def api_configuracoes():
    config = get_current_config() # Usando a função auxiliar
    return jsonify({
        'multa_percentual': config['multa_percentual'],
        'juros_diario_percentual': config['juros_diario_percentual']
    })


#------------------------------Configurações de Leitura-------------
@app.route('/api/configuracoes-leitura')
#@login_required 
def api_configuracoes_leitura():
    config = get_current_config()
    return jsonify({
        'valor_m3': config.get('valor_m3', 0.0),
        'dias_uteis': config.get('dias_uteis_para_vencimento', 5),
        # Renomeado para clareza
        'taxa_minima_valor': config.get('taxa_minima_consumo', 0.0), 
        # ADICIONADO: Envia a franquia em m³
        'taxa_minima_franquia_m3': config.get('taxa_minima_franquia_m3', 10.0)
    })


#-----Cadastrar Cliente (VERSÃO FINAL COM CANCELAR INTELIGENTE)---------------------
@app.route('/cadastrar-cliente', methods=['GET', 'POST'])
@login_required
def cadastrar_cliente():
    if request.method == 'POST':
        try:
            # Coleta os dados pessoais (para a tabela 'clientes')
            nome = request.form.get('nome', '').strip()
            cpf = request.form.get('cpf', '').strip()
            rg = request.form.get('rg', '').strip()
            telefone = request.form.get('telefone', '').strip()

            # Coleta os dados da unidade (para a tabela 'unidades_consumidoras')
            endereco = request.form.get('endereco', '').strip()
            hidrometro_num = request.form.get('hidrometro', '').strip()
            data_ativacao_str = request.form.get('data_instalacao') or date.today().strftime('%Y-%m-%d')
            
            # Coleta os dados da leitura inicial (para a tabela 'leituras')
            leitura_inicial = int(parse_number_from_br_form(request.form.get('leitura_inicial', '0')))
            
            # Validações
            if not all([nome, cpf, endereco, telefone, hidrometro_num]):
                flash("Todos os campos marcados com * são obrigatórios.", "danger")
                return redirect(url_for('cadastrar_cliente'))

            if not is_cpf_valido(cpf):
                flash("O CPF informado não é válido. Por favor, verifique.", 'danger')
                return redirect(url_for('cadastrar_cliente'))

            data_ativacao_obj = datetime.strptime(data_ativacao_str, '%Y-%m-%d').date()
            
            db = get_db()
            with db.begin():
                # 1. Insere na tabela 'clientes' e pega o ID do novo cliente
                resultado_cliente = db.execute(text("""
                    INSERT INTO clientes (nome, cpf, rg, telefone)
                    VALUES (:nome, :cpf, :rg, :telefone)
                    RETURNING id
                """), {
                    'nome': nome, 'cpf': cpf, 'rg': rg, 'telefone': telefone
                }).fetchone()
                novo_cliente_id = resultado_cliente[0]

                # 2. Insere na tabela 'unidades_consumidoras', ligando ao cliente criado
                resultado_unidade = db.execute(text("""
                    INSERT INTO unidades_consumidoras (cliente_id, endereco, hidrometro_num, data_ativacao)
                    VALUES (:cliente_id, :endereco, :hidrometro_num, :data_ativacao)
                    RETURNING id
                """), {
                    'cliente_id': novo_cliente_id,
                    'endereco': endereco,
                    'hidrometro_num': hidrometro_num,
                    'data_ativacao': data_ativacao_obj
                }).fetchone()
                nova_unidade_id = resultado_unidade[0]

                # 3. Cria a primeira leitura informativa, ligada à nova unidade
                db.execute(text('''
                    INSERT INTO leituras (
                        unidade_id, leitura_anterior, data_leitura_anterior, 
                        leitura_atual, data_leitura_atual, consumo_m3, 
                        valor_original, vencimento, mes_competencia, ano_competencia
                    ) VALUES (:unidade_id, 0, NULL, :l_inicial, :d_ativacao, 0, NULL, NULL, :mes, :ano)
                '''), {
                    'unidade_id': nova_unidade_id,
                    'l_inicial': leitura_inicial,
                    'd_ativacao': data_ativacao_obj,
                    'mes': data_ativacao_obj.month,
                    'ano': data_ativacao_obj.year
                })

            flash('Cliente, sua unidade e leitura inicial foram cadastrados com sucesso!', 'success')
            return redirect(url_for('listar_clientes'))

        except IntegrityError:
            flash("CPF ou número do hidrômetro já cadastrado. Verifique os dados.", 'danger')
        except Exception as e:
            app.logger.error(f"Erro ao cadastrar cliente: {e}", exc_info=True)
            flash(f"Erro ao cadastrar cliente: {str(e)}", 'danger')
            
        return redirect(url_for('cadastrar_cliente'))

    # --- LÓGICA GET ATUALIZADA PARA O BOTÃO "CANCELAR" INTELIGENTE ---
    else:
        # Pega o parâmetro 'next' da URL, com um padrão seguro caso ele não exista.
        next_url = request.args.get('next', url_for('listar_clientes')) 
        return render_template(
            'cadastrar_cliente.html', 
            today_date=date.today().isoformat(),
            next_url=next_url # Envia a URL de retorno para o template
        )

#------Adicionar Nova Unidade Consumidora----------------------
@app.route('/cliente/<int:cliente_id>/adicionar-unidade', methods=['GET', 'POST'])
@login_required
def adicionar_unidade(cliente_id):
    db = get_db()

    # --- Lógica POST: Executada apenas quando o formulário é enviado ---
    if request.method == 'POST':
        try:
            # Coleta os dados do formulário
            endereco = request.form.get('endereco', '').strip()
            hidrometro_num = request.form.get('hidrometro', '').strip()
            leitura_inicial = int(parse_number_from_br_form(request.form.get('leitura_inicial', '0')))
            data_ativacao_str = request.form.get('data_ativacao') or date.today().strftime('%Y-%m-%d')
            
            if not all([endereco, hidrometro_num]):
                flash("Endereço e Número do Hidrômetro são obrigatórios.", "danger")
                return redirect(url_for('adicionar_unidade', cliente_id=cliente_id))

            data_ativacao_obj = datetime.strptime(data_ativacao_str, '%Y-%m-%d').date()

            # A transação começa aqui, envolvendo todas as operações de escrita no banco
            with db.begin():
                # Insere na tabela 'unidades_consumidoras'
                resultado_unidade = db.execute(text("""
                    INSERT INTO unidades_consumidoras (cliente_id, endereco, hidrometro_num, data_ativacao)
                    VALUES (:cliente_id, :endereco, :hidrometro_num, :data_ativacao)
                    RETURNING id
                """), {
                    'cliente_id': cliente_id,
                    'endereco': endereco,
                    'hidrometro_num': hidrometro_num,
                    'data_ativacao': data_ativacao_obj
                }).fetchone()
                nova_unidade_id = resultado_unidade[0]

                # Cria a primeira leitura informativa para a nova unidade
                db.execute(text('''
                    INSERT INTO leituras (unidade_id, leitura_anterior, data_leitura_anterior, leitura_atual, data_leitura_atual, consumo_m3, valor_original, vencimento, mes_competencia, ano_competencia)
                    VALUES (:unidade_id, 0, NULL, :l_inicial, :d_ativacao, 0, NULL, NULL, :mes, :ano)
                '''), {
                    'unidade_id': nova_unidade_id,
                    'l_inicial': leitura_inicial,
                    'd_ativacao': data_ativacao_obj,
                    'mes': data_ativacao_obj.month,
                    'ano': data_ativacao_obj.year
                })

            flash(f"Nova unidade consumidora adicionada com sucesso!", "success")
            return redirect(url_for('detalhes_cliente', cliente_id=cliente_id))

        except IntegrityError:
            flash("Número do hidrômetro já cadastrado. Verifique os dados.", 'danger')
        except Exception as e:
            app.logger.error(f"Erro ao adicionar unidade para o cliente {cliente_id}: {e}", exc_info=True)
            flash(f"Erro ao adicionar unidade: {str(e)}", 'danger')
        
        return redirect(url_for('adicionar_unidade', cliente_id=cliente_id))

    # --- Lógica GET: Executada apenas para carregar a página ---
    else:
        # A busca pelo cliente agora só acontece no GET, evitando o conflito de transação.
        cliente = db.execute(text("SELECT * FROM clientes WHERE id = :id"), {'id': cliente_id}).fetchone()
        if not cliente:
            flash("Cliente não encontrado.", "danger")
            return redirect(url_for('listar_clientes'))
            
        return render_template('adicionar_unidade.html', cliente=cliente, today_date=date.today().isoformat())


#----Datalhes do Cliente----------------
@app.route('/cliente/detalhes/<int:cliente_id>')
@login_required
def detalhes_cliente(cliente_id):
    db = get_db()
    try:
        # Busca os dados pessoais do cliente
        cliente_bruto = db.execute(text("SELECT * FROM clientes WHERE id = :id"), {'id': cliente_id}).fetchone()
        if not cliente_bruto:
            flash("Cliente não encontrado.", "danger")
            return redirect(url_for('listar_clientes'))
        cliente = cliente_bruto._asdict()

        # Busca todas as unidades consumidoras associadas a este cliente
        unidades_brutas = db.execute(text("""
            SELECT * FROM unidades_consumidoras 
            WHERE cliente_id = :cliente_id 
            ORDER BY endereco
        """), {'cliente_id': cliente_id}).fetchall()
        unidades = [u._asdict() for u in unidades_brutas]

        return render_template('detalhes_cliente.html', cliente=cliente, unidades=unidades)

    except Exception as e:
        app.logger.error(f"Erro ao buscar detalhes do cliente ID {cliente_id}: {e}", exc_info=True)
        flash("Ocorreu um erro ao carregar os detalhes do cliente.", "danger")
        return redirect(url_for('listar_clientes'))

# --- Listar Pagamentos (VERSÃO REESTRUTURADA) ---
@app.route('/pagamentos')
@login_required
def listar_pagamentos():
    try:
        db = get_db()
        
        page = request.args.get('page', 1, type=int)
        mes_filtro = request.args.get('mes', '')
        ano_filtro = request.args.get('ano', '')
        
        PER_PAGE = 20
        offset = (page - 1) * PER_PAGE
        
        # --- AJUSTE CIRÚRGICO AQUI ---
        # Trocamos 'consumidores' por 'clientes' e 'consumidor_id' por 'cliente_id'
        base_query = "FROM pagamentos p JOIN clientes c ON p.cliente_id = c.id"
        
        conditions = []
        params = {}
        
        if mes_filtro:
            conditions.append("TO_CHAR(p.data_pagamento, 'MM') = :mes")
            params['mes'] = mes_filtro.zfill(2)
        if ano_filtro:
            conditions.append("TO_CHAR(p.data_pagamento, 'YYYY') = :ano")
            params['ano'] = ano_filtro
        
        where_clause = ""
        if conditions:
            where_clause = " WHERE " + " AND ".join(conditions)
        
        summary_query = f"SELECT COUNT(p.id), COALESCE(SUM(p.valor_pago), 0) {base_query} {where_clause}"
        params_summary = params.copy()
        total_pagamentos_periodo, valor_arrecadado_periodo = db.execute(text(summary_query), params_summary).fetchone()

        data_query = f"SELECT p.*, c.nome as cliente_nome {base_query} {where_clause} ORDER BY p.data_pagamento DESC, p.id DESC LIMIT :limit OFFSET :offset"
        params['limit'] = PER_PAGE
        params['offset'] = offset
        pagamentos_brutos = db.execute(text(data_query), params).fetchall()

        pagamentos_formatados = [p._asdict() for p in pagamentos_brutos]

        total_pages = math.ceil(total_pagamentos_periodo / PER_PAGE) if total_pagamentos_periodo > 0 else 1
        pagination = {
            "page": page, "total_pages": total_pages,
            "has_prev": page > 1, "has_next": page < total_pages
        }

        return render_template(
            'listar_pagamentos.html', 
            pagamentos=pagamentos_formatados,
            pagination=pagination,
            mes_filtro=mes_filtro,
            ano_filtro=ano_filtro,
            ano_atual=datetime.now().year,
            total_pagamentos_periodo=total_pagamentos_periodo,
            valor_arrecadado_periodo=valor_arrecadado_periodo
        )
    except Exception as e:
        app.logger.error(f"Erro ao listar pagamentos: {e}", exc_info=True)
        flash("Ocorreu um erro ao carregar o relatório de pagamentos.", "danger")
        return redirect(url_for('dashboard'))


#---------função listar_clientes--------------
@app.route('/clientes')
@login_required
def listar_clientes():
    db = get_db()
    try:
        # A nova consulta busca os dados das duas tabelas, juntando-as e incluindo o RG.
        unidades_brutas = db.execute(text("""
            SELECT 
                u.id as unidade_id,
                u.endereco,
                u.hidrometro_num,
                c.id as cliente_id,
                c.nome as cliente_nome,
                c.cpf,
                c.rg,
                c.telefone
            FROM unidades_consumidoras u
            JOIN clientes c ON u.cliente_id = c.id
            ORDER BY c.nome, u.endereco
        """)).fetchall()
        unidades = [unidade._asdict() for unidade in unidades_brutas]
    except Exception as e:
        app.logger.error(f"Erro ao listar clientes e unidades: {e}", exc_info=True)
        flash("Ocorreu um erro ao buscar a lista de clientes.", "danger")
        unidades = []
    return render_template('clientes.html', unidades=unidades)


# Adicione esta NOVA função para lidar com a exclusão da unidade
@app.route('/unidade/excluir/<int:id>', methods=['POST'])
@login_required
def excluir_unidade(id):
    db = get_db()
    try:
        # A exclusão agora é na tabela 'unidades_consumidoras'
        with db.begin():
            db.execute(text("DELETE FROM unidades_consumidoras WHERE id = :id"), {'id': id})
        flash("Unidade consumidora excluída com sucesso.", "success")
    except IntegrityError:
        flash("Não é possível excluir esta unidade, pois ela possui leituras ou pagamentos associados.", "danger")
    except Exception as e:
        app.logger.error(f"Erro ao excluir unidade ID {id}: {e}", exc_info=True)
        flash("Ocorreu um erro ao tentar excluir a unidade.", "danger")
    return redirect(url_for('listar_clientes'))


#-----------------Cadastrar Leitura (VERSÃO COM UPLOAD S3 CORRIGIDO)----------------:
@app.route('/cadastrar-leitura', methods=['GET', 'POST'])
@login_required
def cadastrar_leitura():
    db = get_db()
    if request.method == 'POST':
        try:
            consumidor_id = int(request.form.get('consumidor_id'))
            leitura_atual = int(parse_number_from_br_form(request.form.get('leitura_atual')))
            data_leitura_obj = datetime.strptime(request.form.get('data_leitura_atual'), '%Y-%m-%d').date()
            
            foto_salva_nome = None
            if 'foto_hidrometro' in request.files:
                foto = request.files['foto_hidrometro']
                if foto and foto.filename != '' and allowed_file(foto.filename):
                    filename = secure_filename(foto.filename)
                    novo_nome = f"{int(datetime.now().timestamp())}_{filename}"
                    
                    s3 = boto3.client(
                        's3',
                        aws_access_key_id=os.environ.get('AWS_ACCESS_KEY_ID'),
                        aws_secret_access_key=os.environ.get('AWS_SECRET_ACCESS_KEY'),
                        region_name=os.environ.get('AWS_REGION')
                    )
                    S3_BUCKET = os.environ.get('S3_BUCKET_NAME')
                    try:
                        # --- CORREÇÃO CIRÚRGICA APLICADA AQUI ---
                        # Removemos a linha 'ACL': 'public-read' para ser compatível
                        # com as configurações modernas do S3.
                        s3.upload_fileobj(
                            foto,
                            S3_BUCKET,
                            novo_nome,
                            ExtraArgs={
                                'ContentType': foto.content_type
                            }
                        )
                        # --- FIM DA CORREÇÃO ---
                        
                        foto_salva_nome = novo_nome
                        app.logger.info(f"Upload para S3 bem-sucedido: {novo_nome}")
                    except NoCredentialsError:
                        app.logger.error("Credenciais da AWS não encontradas nas variáveis de ambiente.")
                        flash("Erro de configuração do servidor: credenciais de upload não encontradas.", "danger")
                        return redirect(url_for('cadastrar_leitura'))
                    except Exception as e:
                        app.logger.error(f"Erro no upload para o S3: {e}")
                        flash("Erro ao enviar a foto para o armazenamento.", "danger")
                        return redirect(url_for('cadastrar_leitura'))
            
            with db.begin():
                # Bloco de cálculo da fatura (mantido como estava)
                leitura_anterior_db = db.execute(text("SELECT id, leitura_atual, data_leitura_atual FROM leituras WHERE consumidor_id = :cid ORDER BY data_leitura_atual DESC, id DESC LIMIT 1"), {'cid': consumidor_id}).fetchone()
                config = get_current_config()
                consumo_m3 = 0
                valor_original = None
                data_vencimento = None
                leitura_anterior_valor = 0
                data_leitura_anterior_obj = None

                if leitura_anterior_db:
                    leitura_anterior_valor = int(leitura_anterior_db.leitura_atual)
                    data_leitura_anterior_obj = leitura_anterior_db.data_leitura_atual
                    if leitura_atual < leitura_anterior_valor:
                        raise ValueError('Leitura atual não pode ser menor que a anterior.')
                    consumo_m3 = leitura_atual - leitura_anterior_valor
                    
                    valor_original = 0.0
                    taxa_minima_valor = float(config.get('taxa_minima_consumo', 15.0))
                    taxa_minima_franquia = float(config.get('taxa_minima_franquia_m3', 10.0))
                    valor_m3_configurado = float(config.get('valor_m3', 0.0))
                    
                    if leitura_anterior_valor > 0:
                        valor_original = taxa_minima_valor
                        if consumo_m3 > taxa_minima_franquia:
                            consumo_excedente = consumo_m3 - taxa_minima_franquia
                            valor_excedente = consumo_excedente * valor_m3_configurado
                            valor_original = taxa_minima_valor + valor_excedente
                    
                    dias_para_vencimento = int(config.get('dias_uteis_para_vencimento', 5))
                    data_vencimento = adicionar_dias_uteis(data_leitura_obj, dias_para_vencimento)

                # INSERT no banco de dados
                resultado = db.execute(text('''
                    INSERT INTO leituras (
                        consumidor_id, leitura_anterior, data_leitura_anterior,
                        leitura_atual, data_leitura_atual, consumo_m3, valor_original, vencimento, foto_hidrometro,
                        valor_m3_usado, taxa_minima_valor_usada, taxa_minima_franquia_usada
                    ) VALUES (:cid, :l_ant, :d_ant, :l_atu, :d_atu, :consumo, :val_orig, :venc, :foto, :v_m3, :t_min_val, :t_min_fran)
                    RETURNING id
                '''), {
                    'cid': consumidor_id, 'l_ant': leitura_anterior_valor, 'd_ant': data_leitura_anterior_obj,
                    'l_atu': leitura_atual, 'd_atu': data_leitura_obj, 'consumo': consumo_m3,
                    'val_orig': valor_original, 'venc': data_vencimento, 'foto': foto_salva_nome,
                    'v_m3': config.get('valor_m3'), 't_min_val': config.get('taxa_minima_consumo'), 
                    't_min_fran': config.get('taxa_minima_franquia_m3')
                }).fetchone()
                nova_leitura_id = resultado[0]

            flash('Leitura cadastrada com sucesso!', 'success')
            return redirect(url_for('comprovante_leitura', leitura_id=nova_leitura_id))

        except Exception as e:
            app.logger.error(f'Erro ao salvar leitura: {e}', exc_info=True)
            flash(f'Ocorreu um erro inesperado: {str(e)}', 'danger')
            return redirect(url_for('cadastrar_leitura'))
    
    else: # Lógica GET (não muda)
        consumidores = db.execute(text('SELECT id, nome FROM consumidores ORDER BY nome')).fetchall()
        consumidor_selecionado = request.args.get('consumidor_id', type=int)
        leitura_anterior_valor = '0'
        data_leitura_anterior_str = 'N/A'
        data_leitura_anterior_iso = None

        if consumidor_selecionado:
            ultima_leitura = db.execute(text("SELECT leitura_atual, data_leitura_atual FROM leituras WHERE consumidor_id = :cid ORDER BY data_leitura_atual DESC, id DESC LIMIT 1"), {'cid': consumidor_selecionado}).fetchone()
            if ultima_leitura:
                leitura_anterior_valor = str(int(ultima_leitura.leitura_atual))
                data_leitura_anterior_str = ultima_leitura.data_leitura_atual.strftime('%d/%m/%Y')
                data_leitura_anterior_iso = ultima_leitura.data_leitura_atual.isoformat()

        return render_template('cadastrar_leitura.html', 
                               consumidores=consumidores, 
                               consumidor_selecionado=consumidor_selecionado,
                               leitura_anterior=leitura_anterior_valor,
                               data_leitura_anterior=data_leitura_anterior_str,
                               data_leitura_anterior_iso=data_leitura_anterior_iso,
                               today_date=date.today().isoformat())
    
# --- Registrar Pagamento (AGORA COM A LÓGICA WHATSAPP EMBUTIDA) ---
@app.route('/registrar-pagamento', methods=['GET', 'POST'])
@login_required
def registrar_pagamento():
    db = get_db()
    if request.method == 'POST':
        try:
            with db.begin():
                leitura_id = int(request.form['leitura_id'])
                unidade_id = int(request.form['unidade_id'])
                data_pagamento_str = request.form.get('data_pagamento') or date.today().strftime('%Y-%m-%d')
                forma_pagamento = request.form['forma_pagamento']
                valor_pago = parse_number_from_br_form(request.form.get('valor_pago', '0'))

                if valor_pago <= 0:
                    raise ValueError('O valor do pagamento deve ser maior que R$ 0,00.')
                
                leitura = db.execute(text('SELECT valor_original, vencimento FROM leituras WHERE id = :id'), {'id': leitura_id}).fetchone()
                unidade = db.execute(text('SELECT cliente_id FROM unidades_consumidoras WHERE id = :id'), {'id': unidade_id}).fetchone()

                if not leitura or not unidade:
                    raise ValueError("Fatura ou Unidade selecionada é inválida.")

                config = get_current_config()
                valor_original_fatura = safe_float(leitura.valor_original)
                data_vencimento = leitura.vencimento
                total_pago_acumulado_antes = db.execute(text("SELECT COALESCE(SUM(valor_pago), 0) FROM pagamentos WHERE leitura_id = :id"), {'id': leitura_id}).fetchone()[0]
                total_multa_acumulada_antes = db.execute(text("SELECT COALESCE(SUM(valor_multa), 0) FROM pagamentos WHERE leitura_id = :id"), {'id': leitura_id}).fetchone()[0]
                total_juros_acumulados_antes = db.execute(text("SELECT COALESCE(SUM(valor_juros), 0) FROM pagamentos WHERE leitura_id = :id"), {'id': leitura_id}).fetchone()[0]
                valor_base_antes = max(valor_original_fatura + total_multa_acumulada_antes + total_juros_acumulados_antes - total_pago_acumulado_antes, 0)
                multa_devida, juros_devido, dias_atraso = calcular_penalidades(valor_original_fatura, valor_base_antes, data_vencimento, data_pagamento_str, config['multa_percentual'], config['juros_diario_percentual'])
                multa_a_ser_paga = 0.0
                if dias_atraso > 0 and total_multa_acumulada_antes == 0:
                    multa_a_ser_paga = multa_devida
                total_corrigido = round(valor_base_antes + multa_a_ser_paga + juros_devido, 2)
                saldo_devedor = max(0, total_corrigido - valor_pago)
                saldo_credor = max(0, valor_pago - total_corrigido)

                db.execute(text('''
                    INSERT INTO pagamentos (leitura_id, cliente_id, data_pagamento, forma_pagamento, valor_pago, dias_atraso, valor_multa, valor_juros, total_corrigido, saldo_devedor, saldo_credor)
                    VALUES (:leitura_id, :cliente_id, :data_pagamento, :forma_pagamento, :valor_pago, :dias_atraso, :valor_multa, :valor_juros, :total_corrigido, :saldo_devedor, :saldo_credor)
                '''), {
                    'leitura_id': leitura_id, 'cliente_id': unidade.cliente_id, 'data_pagamento': data_pagamento_str, 'forma_pagamento': forma_pagamento, 'valor_pago': valor_pago,
                    'dias_atraso': dias_atraso, 'valor_multa': multa_a_ser_paga, 'valor_juros': juros_devido, 'total_corrigido': total_corrigido, 'saldo_devedor': saldo_devedor, 'saldo_credor': saldo_credor
                })
            flash('Pagamento registrado com sucesso!', 'success')
            return redirect(url_for('listar_pagamentos'))
        except ValueError as e:
            flash(str(e), 'warning')
            return redirect(url_for('registrar_pagamento'))
        except Exception as e:
            app.logger.error(f"Erro ao registrar pagamento: {e}", exc_info=True)
            flash(f'Erro inesperado ao registrar pagamento: {str(e)}', 'danger')
            return redirect(url_for('registrar_pagamento'))
    else:
        clientes = db.execute(text('SELECT id, nome FROM clientes ORDER BY nome')).fetchall()
        return render_template('registrar_pagamento.html', clientes=clientes, today_date=date.today().isoformat())

# --- API para obter detalhes da leitura (VERSÃO COM TRADUÇÃO MANUAL) ---
@app.route('/get-leitura-details/<int:leitura_id>')
@login_required
def get_leitura_details(leitura_id):
    db = get_db()
    resultado_bruto = db.execute(text('SELECT valor_original, vencimento FROM leituras WHERE id = :leitura_id'), {'leitura_id': leitura_id}).fetchone()
    
    if not resultado_bruto:
        return jsonify({'error': 'Leitura não encontrada'}), 404
        
    leitura = resultado_bruto._asdict()

    valor_original = float(leitura['valor_original'])
    data_vencimento = leitura['vencimento']
    
    config = get_current_config()
    data_referencia_calculo_str = request.args.get('data_pagamento_ref', date.today().strftime('%Y-%m-%d'))

    total_pago_acumulado_db = db.execute(text("SELECT COALESCE(SUM(valor_pago), 0) FROM pagamentos WHERE leitura_id = :leitura_id"), {'leitura_id': leitura_id}).fetchone()[0]
    total_multa_acumulada_db = db.execute(text("SELECT COALESCE(SUM(valor_multa), 0) FROM pagamentos WHERE leitura_id = :leitura_id"), {'leitura_id': leitura_id}).fetchone()[0]
    total_juros_acumulados_db = db.execute(text("SELECT COALESCE(SUM(valor_juros), 0) FROM pagamentos WHERE leitura_id = :leitura_id"), {'leitura_id': leitura_id}).fetchone()[0]

    valor_base_para_penalidades = max(
        valor_original + total_multa_acumulada_db + total_juros_acumulados_db - total_pago_acumulado_db, 0
    )

    multa_calc, juros_calc, dias_atraso = calcular_penalidades(
        valor_original, valor_base_para_penalidades, data_vencimento,
        data_referencia_calculo_str, config['multa_percentual'], config['juros_diario_percentual']
    )
    
    multa_para_exibir_na_api = 0.0
    if dias_atraso > 0 and total_multa_acumulada_db == 0:
        multa_para_exibir_na_api = multa_calc

    valor_a_pagar = round(valor_base_para_penalidades + multa_para_exibir_na_api + juros_calc, 2)

    # Dicionário com os dados a serem enviados
    dados_para_enviar = {
        'valor_original_fatura': round(valor_original, 2), 
        'data_vencimento': data_vencimento, 
        'multa': round(multa_para_exibir_na_api, 2), 
        'juros': round(juros_calc, 2),
        'dias_atraso': dias_atraso, 
        'total_corrigido': valor_a_pagar,
        'valor_base_para_novas_penalidades': round(valor_base_para_penalidades, 2)
    }

    # Tradução manual da data para um formato que o JavaScript entende
    if isinstance(dados_para_enviar['data_vencimento'], date):
        dados_para_enviar['data_vencimento'] = dados_para_enviar['data_vencimento'].isoformat()
        
    return jsonify(dados_para_enviar)

#------------ editar_leitura (VERSÃO FINAL REESTRUTURADA) ------------------
@app.route('/leitura/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def editar_leitura(id):
    db = get_db()

    # --- Lógica POST: Para salvar as alterações ---
    if request.method == 'POST':
        try:
            # Esta parte do código (lógica de salvar) já estava correta e foi mantida.
            with db.begin():
                pagamento_existente = db.execute(text("SELECT id FROM pagamentos WHERE leitura_id = :id LIMIT 1"), {'id': id}).fetchone()
                if pagamento_existente:
                    raise ValueError("Não é possível editar esta leitura, pois já existem pagamentos registrados para ela.")

                foto_salva_nome = None
                if 'foto_hidrometro' in request.files:
                    foto = request.files['foto_hidrometro']
                    if foto and foto.filename != '':
                        if not allowed_file(foto.filename): raise ValueError('Tipo de arquivo de foto inválido.')
                        
                        filename = secure_filename(foto.filename)
                        novo_nome = f"{int(datetime.now().timestamp())}_{filename}"
                        
                        s3 = boto3.client('s3', aws_access_key_id=os.environ.get('AWS_ACCESS_KEY_ID'), aws_secret_access_key=os.environ.get('AWS_SECRET_ACCESS_KEY'), region_name=os.environ.get('AWS_REGION'))
                        S3_BUCKET = os.environ.get('S3_BUCKET_NAME')
                        s3.upload_fileobj(foto, S3_BUCKET, novo_nome, ExtraArgs={'ContentType': foto.content_type})
                        foto_salva_nome = novo_nome
                        app.logger.info(f"Upload para S3 na edição bem-sucedido: {novo_nome}")

                nova_leitura_atual = parse_number_from_br_form(request.form['leitura_atual'])
                nova_data_leitura = request.form['data_leitura_atual']
                
                leitura_atual_db = db.execute(text("SELECT * FROM leituras WHERE id = :id"), {'id': id}).fetchone()
                leitura_anterior_valor = float(leitura_atual_db.leitura_anterior)

                if nova_leitura_atual < leitura_anterior_valor:
                    raise ValueError('A leitura atual não pode ser menor que a leitura anterior.')

                consumo_m3 = nova_leitura_atual - leitura_anterior_valor
                config = get_current_config()
                
                valor_original_recalculado = float(leitura_atual_db.valor_original) if leitura_atual_db.valor_original is not None else 0.0

                if leitura_atual_db.valor_original is not None:
                    taxa_minima_valor = float(leitura_atual_db.taxa_minima_valor_usada or config.get('taxa_minima_consumo', 15.0))
                    taxa_minima_franquia = float(leitura_atual_db.taxa_minima_franquia_usada or config.get('taxa_minima_franquia_m3', 10.0))
                    valor_m3_usado = float(leitura_atual_db.valor_m3_usado or config.get('valor_m3', 0.0))
                    
                    if consumo_m3 <= taxa_minima_franquia:
                        valor_original_recalculado = taxa_minima_valor
                    else:
                        consumo_excedente = consumo_m3 - taxa_minima_franquia
                        valor_excedente = consumo_excedente * valor_m3_usado
                        valor_original_recalculado = taxa_minima_valor + valor_excedente
                
                params = {
                    'l_atu': nova_leitura_atual, 'd_atu': nova_data_leitura,
                    'consumo': consumo_m3, 'val_orig': valor_original_recalculado, 'id': id
                }
                query_update_str = "UPDATE leituras SET leitura_atual = :l_atu, data_leitura_atual = :d_atu, consumo_m3 = :consumo, valor_original = :val_orig"
                
                if foto_salva_nome:
                    query_update_str += ", foto_hidrometro = :foto"
                    params['foto'] = foto_salva_nome
                
                query_update_str += " WHERE id = :id"
                db.execute(text(query_update_str), params)

            flash('Leitura atualizada com sucesso!', 'success')
            return redirect(url_for('listar_leituras'))

        except ValueError as e:
            flash(f'Erro de Validação: {str(e)}', 'danger')
            return redirect(url_for('editar_leitura', id=id))
        except Exception as e:
            flash('Ocorreu um erro inesperado ao atualizar a leitura.', 'danger')
            app.logger.error(f"Erro ao editar leitura ID {id}: {e}", exc_info=True)
            return redirect(url_for('editar_leitura', id=id))

    # --- Lógica para GET (Carregar a página) ---
    else:
        # ATUALIZADO: A consulta agora junta as 3 tabelas para buscar todos os dados necessários
        resultado_bruto = db.execute(text("""
            SELECT l.*, c.nome as cliente_nome, u.endereco, u.hidrometro_num
            FROM leituras l
            JOIN unidades_consumidoras u ON l.unidade_id = u.id
            JOIN clientes c ON u.cliente_id = c.id
            WHERE l.id = :id
        """), {'id': id}).fetchone()
        
        if not resultado_bruto:
            flash("Leitura não encontrada.", "danger")
            return redirect(url_for('listar_leituras'))

        leitura = resultado_bruto._asdict()
        foto_url_s3 = None
        if leitura.get('foto_hidrometro'):
            S3_BUCKET = os.environ.get('S3_BUCKET_NAME')
            AWS_REGION = os.environ.get('AWS_REGION')
            if S3_BUCKET and AWS_REGION:
                foto_url_s3 = f"https://{S3_BUCKET}.s3.{AWS_REGION}.amazonaws.com/{leitura['foto_hidrometro']}"

        pagamento_existente = db.execute(text("SELECT id FROM pagamentos WHERE leitura_id = :id LIMIT 1"), {'id': id}).fetchone()
        if pagamento_existente:
            flash("Esta leitura está bloqueada para edição pois já possui pagamentos associados.", "warning")

        return render_template('editar_leitura.html', 
                               leitura=leitura, 
                               bloqueado=bool(pagamento_existente),
                               foto_url_s3=foto_url_s3)
        
    
#------------------------Excluir Leitura----------------------Ajustando o x do Vercel    
@app.route('/leitura/excluir/<int:id>', methods=['POST'])
@login_required
def excluir_leitura(id):
    db = get_db()
    try:
        with db.begin(): 
            # Busca os dados da leitura que será excluída
            leitura_para_excluir = db.execute(
                text("SELECT consumidor_id, data_leitura_atual FROM leituras WHERE id = :id"), {'id': id}
            ).fetchone()

            if not leitura_para_excluir:
                flash("Leitura não encontrada para exclusão.", "warning")
                return redirect(url_for('listar_leituras'))

            # --- NOVA TRAVA DE SEGURANÇA 1 ---
            # Verifica se esta leitura é base para uma leitura futura (se é um elo do meio da corrente)
            leitura_posterior_existente = db.execute(text("""
                SELECT id FROM leituras 
                WHERE consumidor_id = :cid AND data_leitura_atual > :data_atual
                LIMIT 1
            """), {
                'cid': leitura_para_excluir.consumidor_id,
                'data_atual': leitura_para_excluir.data_leitura_atual
            }).fetchone()

            if leitura_posterior_existente:
                flash("Não é possível excluir esta leitura, pois ela é a base para cálculos de leituras futuras. Exclua sempre da mais recente para a mais antiga.", "danger")
                return redirect(url_for('listar_leituras'))

            # --- TRAVA DE SEGURANÇA 2 (já existente) ---
            # Verifica se existem pagamentos vinculados a esta leitura
            pagamento_existente = db.execute(
                text("SELECT id FROM pagamentos WHERE leitura_id = :id LIMIT 1"), {'id': id}
            ).fetchone()

            if pagamento_existente:
                flash("Não é possível excluir esta leitura, pois já existem pagamentos registrados para ela.", "danger")
                return redirect(url_for('listar_leituras'))

            # Se passar por todas as travas, prossegue com a exclusão
            db.execute(text("DELETE FROM leituras WHERE id = :id"), {'id': id})
            
            flash("Leitura excluída com sucesso.", "success")
    
    except Exception as e:
        app.logger.error(f"Erro ao excluir leitura ID {id}: {e}", exc_info=True)
        flash("Ocorreu um erro ao tentar excluir a leitura.", "danger")

    return redirect(url_for('listar_leituras'))

#----------Retorna Unidades Consumidoras--------------
@app.route('/api/unidades/<int:cliente_id>')
@login_required
def api_unidades(cliente_id):
    """Retorna as unidades consumidoras de um cliente específico."""
    db = get_db()
    unidades_brutas = db.execute(text("""
        SELECT id, endereco, hidrometro_num 
        FROM unidades_consumidoras 
        WHERE cliente_id = :cid 
        ORDER BY endereco
    """), {'cid': cliente_id}).fetchall()
    unidades = [u._asdict() for u in unidades_brutas]
    return jsonify(unidades)



#-------------Leituras.-------------------------------------------
@app.route('/api/leituras/<int:unidade_id>')
@login_required
def api_leituras(unidade_id):
    """Retorna as faturas PENDENTES de uma UNIDADE específica, com o saldo devedor real."""
    db = get_db()
    try:
        # Esta query busca todas as leituras da unidade e os totais de seus pagamentos.
        # Mantido como está, pois já agrega os pagamentos de forma eficiente.
        leituras_brutas = db.execute(text('''
            SELECT
                l.id,
                l.data_leitura_atual,
                l.vencimento,
                l.valor_original,
                COALESCE((SELECT SUM(p.valor_pago) FROM pagamentos p WHERE p.leitura_id = l.id), 0) AS total_pago,
                COALESCE((SELECT SUM(p.valor_multa) FROM pagamentos p WHERE p.leitura_id = l.id), 0) AS total_multa_paga,
                COALESCE((SELECT SUM(p.valor_juros) FROM pagamentos p WHERE p.leitura_id = l.id), 0) AS total_juros_pago
            FROM leituras l
            WHERE 
                l.unidade_id = :uid AND 
                l.valor_original IS NOT NULL
            ORDER BY l.data_leitura_atual DESC
        '''), {'uid': unidade_id}).fetchall()

        leituras_pendentes = []
        config = get_current_config() # Obtém as configurações uma vez
        hoje_str = date.today().isoformat() # Data de referência para cálculo de atraso (formato AAAA-MM-DD)
        
        for l_bruto in leituras_brutas:
            l = l_bruto._asdict()
            
            # Converte valores para float de forma segura
            valor_original_fatura = safe_float(l['valor_original'])
            total_pago_acumulado = safe_float(l['total_pago'])
            total_multa_acumulada_paga = safe_float(l['total_multa_paga'])
            total_juros_acumulados_pago = safe_float(l['total_juros_pago'])
            data_vencimento = l['vencimento'] # Já é um objeto date/datetime aqui
            
            # Calcula o saldo devedor base (considerando o que já foi pago de tudo)
            valor_base_para_penalidades = max(
                valor_original_fatura + total_multa_acumulada_paga + total_juros_acumulados_pago - total_pago_acumulado, 0
            )
            
            # Se a fatura já está quitada, não a inclui na lista de pendentes
            if valor_base_para_penalidades <= 0.01:
                continue

            # Calcula multa e juros aplicáveis à data de hoje para o dropdown
            # A função calcular_penalidades precisa do valor original para multa e
            # o saldo devedor atual (base para juros).
            multa_calc, juros_calc, dias_atraso = calcular_penalidades(
                valor_original_fatura, # Base para cálculo da multa
                valor_base_para_penalidades, # Base para cálculo dos juros (saldo devedor atual)
                data_vencimento,
                hoje_str, # Data de referência para o cálculo (hoje)
                config['multa_percentual'],
                config['juros_diario_percentual']
            )

            multa_a_cobrar_hoje = 0.0
            # Aplica a multa apenas se houver atraso e se ela ainda não foi paga anteriormente
            if dias_atraso > 0 and total_multa_acumulada_paga == 0:
                multa_a_cobrar_hoje = multa_calc

            # Calcula o saldo final a pagar, incluindo juros e multa atualizados
            saldo_a_pagar_com_penalidades = round(valor_base_para_penalidades + multa_a_cobrar_hoje + juros_calc, 2)
            
            leitura_info = {
                "id": l['id'],
                "vencimento": l['vencimento'], # Será formatado abaixo
                "saldo_a_pagar": saldo_a_pagar_com_penalidades # Envia o saldo real para o frontend
            }

            # Garante que 'vencimento' seja uma string no formato AAAA-MM-DD
            # que o JavaScript espera.
            if isinstance(leitura_info['vencimento'], date):
                leitura_info['vencimento'] = leitura_info['vencimento'].isoformat()
            elif leitura_info['vencimento'] is None:
                leitura_info['vencimento'] = None 
            
            leituras_pendentes.append(leitura_info)
        
        return jsonify(leituras_pendentes)

    except Exception as e:
        app.logger.error(f"Erro na API de leituras para unidade {unidade_id}: {e}", exc_info=True)
        return jsonify({'erro': 'Erro interno no servidor'}), 500
    
# --- ROTA PRINCIPAL DE DETALHES (CORRIGIDA) ---
@app.route('/detalhes-pagamento')
@login_required
def detalhes_pagamento():
    leitura_id = request.args.get('leitura_id')
    if not leitura_id:
        flash('Nenhum pagamento selecionado', 'error')
        return redirect(url_for('listar_pagamentos'))

    # Reutiliza a função auxiliar que já busca e calcula tudo
    contexto = _get_fatura_contexto(int(leitura_id))

    if contexto is None:
        flash('Fatura não encontrada.', 'danger')
        return redirect(url_for('listar_pagamentos'))
    
    # Renderiza o template com os dados já processados
    return render_template('detalhes_pagamento.html', **contexto)

# --- Recuperação de Senha ---
@app.route('/recuperar-senha', methods=['POST'])
def recuperar_senha():
    email = request.form.get('email', '').strip().lower()
    app.logger.info(f"Tentativa de recuperação de senha para: {email}")

    db = get_db()
    try:
        user = db.execute(text('SELECT id FROM usuarios_admin WHERE email = ?'), (email,)).fetchone()

        if not user:
            flash("E-mail não cadastrado.", "error")
            return redirect(url_for('login'))

        token = secrets.token_urlsafe(50)
        expires_at = datetime.now() + timedelta(hours=1)
        expires_at_str = expires_at.strftime('%Y-%m-%d %H:%M:%S')

        db.execute(text("""
            UPDATE usuarios_admin 
            SET reset_token = ?, reset_expira_em = ? 
            WHERE id = ?
        """), (token, expires_at_str, user['id']))
        db.commit()
        app.logger.info(f"Token de reset gerado para user_id {user['id']}")

        reset_link = url_for('redefinir_senha_form', token=token, _external=True)
        
        assunto = "Recuperação de Senha - Águas de Santa Maria"
        corpo = f"""
        Olá! Você solicitou a redefinição da sua senha.
        
        Clique no link abaixo para redefinir sua senha:
        {reset_link}
        
        O link será válido por 1 hora.
        
        Se você não solicitou a alteração, ignore esta mensagem.
        """
        sucesso = enviar_email(email, assunto, corpo)

        if sucesso:
            flash("Um link foi enviado para o seu e-mail.", "info")
        else:
            flash("Erro ao enviar e-mail. Verifique suas configurações e tente novamente.", "error")

        return redirect(url_for('login'))

    except Exception as e:
        app.logger.error(f"Erro ao processar recuperação de senha: {str(e)}", exc_info=True)
        flash("Ocorreu um erro ao processar sua solicitação.", "error")
        return redirect(url_for('login'))

@app.route('/redefinir-senha')
def redefinir_senha_form():
    token = request.args.get('token')
    if not token:
        flash("Token inválido ou ausente.", "error")
        return redirect(url_for('login'))
    
    db = get_db()
    user = db.execute(text("""
    SELECT id FROM usuarios_admin 
    WHERE reset_token = ? AND reset_expira_em > ?
"""), (token, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))).fetchone()
    
    if not user:
        flash("Token inválido ou expirado.", "error")
        return redirect(url_for('login'))
    return render_template('redefinir_senha.html', token=token)

@app.route('/atualizar-senha', methods=['POST'])
def atualizar_senha():
    token = request.form.get('token')
    nova_senha = request.form.get('nova_senha')
    confirmar_senha = request.form.get('confirmar_senha')

    if not nova_senha or len(nova_senha) < 6:
        flash("A senha deve ter pelo menos 6 caracteres.", "error")
        return render_template('redefinir_senha.html', token=token)

    if nova_senha != confirmar_senha:
        flash("As senhas não coincidem.", "error")
        return render_template('redefinir_senha.html', token=token)

    db = get_db()
    try:
        user = db.execute(text("""
            SELECT id FROM usuarios_admin 
            WHERE reset_token = ? AND reset_expira_em > ?
"""), (token, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))).fetchone()

        if user:
            db.execute(text("""
                UPDATE usuarios_admin 
                SET senha_hash = ?, reset_token = NULL, reset_expira_em = NULL 
                WHERE id = ?
"""), (generate_password_hash(nova_senha), user['id']))
            db.commit()
            flash("Senha alterada com sucesso!", "success")
            return redirect(url_for('login'))
        else:
            flash("Link inválido ou expirado.", "error")
            return render_template('redefinir_senha.html', token=token)
    except Exception as e:
        app.logger.error(f"Erro ao atualizar senha: {str(e)}", exc_info=True)
        flash("Ocorreu um erro. Tente novamente mais tarde.", "error")
        return render_template('redefinir_senha.html', token=token)

# --- Cadastrar Usuário (VERSÃO FINAL E CORRETA) ---
@app.route('/cadastrar-usuario', methods=['GET', 'POST'])
@admin_required
def cadastrar_usuario():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        email = request.form.get('email')
        # --- MUDANÇA 1: Lendo o 'papel' que você escolheu na tela ---
        papel = request.form.get('papel', 'normal') # 'normal' é o valor padrão se nada for escolhido

        if not username or not password or not email:
            flash("Preencha todos os campos.", "error")
            return redirect(url_for('cadastrar_usuario'))

        if len(password) < 6:
            flash("A senha deve ter pelo menos 6 caracteres.", "error")
            return redirect(url_for('cadastrar_usuario'))

        try:
            db = get_db()
            with db.begin():
                usuario_existente = db.execute(
                    text("SELECT id FROM usuarios_admin WHERE username = :username"),
                    {'username': username}
                ).fetchone()

                if usuario_existente:
                    flash("Este nome de usuário já está em uso.", "error")
                    return redirect(url_for('cadastrar_usuario'))

                email_existente = db.execute(
                    text("SELECT id FROM usuarios_admin WHERE email = :email"),
                    {'email': email}
                ).fetchone()

                if email_existente:
                    flash("Este e-mail já está cadastrado.", "error")
                    return redirect(url_for('cadastrar_usuario'))

                senha_hash = generate_password_hash(password)
                
                # --- MUDANÇA 2: Usando a variável 'papel' na inserção ---
                db.execute(text("""
                    INSERT INTO usuarios_admin (username, senha_hash, email, papel)
                    VALUES (:username, :senha_hash, :email, :papel)
                """), {
                    'username': username, 
                    'senha_hash': senha_hash, 
                    'email': email,
                    'papel': papel  # <-- AQUI ESTÁ A CORREÇÃO PRINCIPAL
                })
            
            flash("Usuário cadastrado com sucesso!", "success")
            return redirect(url_for('dashboard'))

        except Exception as e:
            app.logger.error(f"Erro ao cadastrar usuário: {str(e)}", exc_info=True)
            flash("Ocorreu um erro ao cadastrar o usuário. O nome de usuário ou e-mail podem já existir.", "danger")
            return redirect(url_for('cadastrar_usuario'))

    return render_template('cadastrar_usuario.html')

#----------Editar Consumidor (VERSÃO FINAL COM VALIDAÇÕES)---------------------
# Em app.py, substitua a função antiga por esta.

# RENOMEADO: A rota e a função agora usam 'cliente'
@app.route('/cliente/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def editar_cliente(id):
    db = get_db()
    
    if request.method == 'POST':
        try:
            # Coleta e valida os dados do formulário
            nome = request.form.get('nome', '').strip()
            cpf = request.form.get('cpf', '').strip()
            rg = request.form.get('rg', '').strip()
            telefone = request.form.get('telefone', '').strip()

            if not all([nome, cpf, telefone]):
                flash("Os campos Nome, CPF e Telefone são obrigatórios.", "danger")
                return redirect(url_for('editar_cliente', id=id))

            if not is_cpf_valido(cpf):
                flash("O CPF informado não é válido. Por favor, verifique.", 'danger')
                return redirect(url_for('editar_cliente', id=id))

            # ATUALIZADO: O UPDATE agora é na tabela 'clientes'
            with db.begin():
                db.execute(text("""
                    UPDATE clientes 
                    SET nome = :nome, cpf = :cpf, rg = :rg, telefone = :telefone
                    WHERE id = :id
                """), {
                    'nome': nome, 'cpf': cpf, 'rg': rg, 'telefone': telefone, 'id': id
                })
            
            flash("Dados do cliente atualizados com sucesso!", "success")
            return redirect(url_for('listar_clientes'))

        except IntegrityError:
            flash("O CPF informado já está em uso por outro cliente.", "danger")
            return redirect(url_for('editar_cliente', id=id))
        except Exception as e:
            app.logger.error(f"Erro ao editar cliente: {str(e)}", exc_info=True)
            flash(f"Erro ao editar o cliente: {str(e)}", "danger")
            return redirect(url_for('editar_cliente', id=id))

    # ATUALIZADO: A lógica GET agora busca na tabela 'clientes'
    else:
    # Busca os dados do cliente
        cliente_bruto = db.execute(text("SELECT * FROM clientes WHERE id = :id"), {'id': id}).fetchone()
    
    if not cliente_bruto:
        flash("Cliente não encontrado.", "error")
        return redirect(url_for('listar_clientes'))
    
    cliente = cliente_bruto._asdict()
    
    # LÓGICA DO REDIRECIONAMENTO INTELIGENTE
    # Pega o parâmetro 'next' da URL. Se não existir, o padrão é voltar para a página de detalhes.
    next_url = request.args.get('next', url_for('detalhes_cliente', cliente_id=id))
    
    return render_template('editar_cliente.html', cliente=cliente, next_url=next_url)


# --- Excluir Consumidor (VERSÃO CORRIGIDA) ---
@app.route('/excluir-consumidor/<int:id>')
@login_required
def excluir_consumidor(id):
    db = get_db()
    try:
        with db.begin(): # Garante a transação segura
            db.execute(text("DELETE FROM consumidores WHERE id = :id"), {'id': id})
        
        flash("Consumidor excluído com sucesso!", "success")
    except IntegrityError: # Erro se houver leituras/pagamentos vinculados
        flash("Não foi possível excluir o consumidor. Existem leituras ou pagamentos associados a ele.", "error")
    except Exception as e:
        app.logger.error(f"Erro ao excluir consumidor: {str(e)}", exc_info=True)
        flash("Erro ao excluir o consumidor.", "error")

    return redirect(url_for('listar_consumidores'))

#----------------- Get_Fatura_Contexto (VERSÃO CORRIGIDA) ----------------
def _get_fatura_contexto(leitura_id):
    """
    Busca e calcula todos os dados para um extrato de fatura/comprovante.
    VERSÃO REESTRUTURADA: Usa a nova estrutura de tabelas.
    """
    db = get_db()
    
    # --- CONSULTA PRINCIPAL ATUALIZADA COM OS JOINS CORRETOS ---
    resultado_bruto = db.execute(text('''
        SELECT 
            l.*, 
            c.id AS cliente_id,
            c.nome AS cliente_nome, 
            c.cpf AS cliente_cpf,
            c.telefone AS cliente_telefone,
            u.endereco AS unidade_endereco, 
            u.hidrometro_num
        FROM leituras l
        JOIN unidades_consumidoras u ON l.unidade_id = u.id
        JOIN clientes c ON u.cliente_id = c.id
        WHERE l.id = :id
    '''), {'id': leitura_id}).fetchone()

    if not resultado_bruto: return None
    
    leitura_data = resultado_bruto._asdict()

    # O resto da lógica da função para calcular pagamentos, juros, etc.,
    # continua muito parecida, pois ela já opera com os dados da leitura.
    pagamentos_feitos = [p._asdict() for p in db.execute(text("SELECT * FROM pagamentos WHERE leitura_id = :id ORDER BY data_pagamento ASC"), {'id': leitura_id}).fetchall()]
    
    consumo_m3 = int(safe_float(leitura_data.get('consumo_m3')))
    data_leitura_anterior_obj = leitura_data.get('data_leitura_anterior')
    
    dias_no_periodo = 0
    if data_leitura_anterior_obj and leitura_data.get('data_leitura_atual'):
        dias_no_periodo = (leitura_data['data_leitura_atual'] - data_leitura_anterior_obj).days

    media_diaria_consumo = (consumo_m3 / dias_no_periodo) if dias_no_periodo > 0 else 0.0

    detalhamento_fatura = []
    if leitura_data.get('valor_original') is not None:
        taxa_valor_usada = safe_float(leitura_data.get('taxa_minima_valor_usada'))
        taxa_franquia_usada = safe_float(leitura_data.get('taxa_minima_franquia_usada'))
        valor_m3_usado = safe_float(leitura_data.get('valor_m3_usado'))

        if consumo_m3 > 0 and valor_m3_usado == 0 and taxa_valor_usada == 0:
            config_fallback = get_current_config()
            taxa_valor_usada = safe_float(config_fallback.get('taxa_minima_consumo'))
            taxa_franquia_usada = safe_float(config_fallback.get('taxa_minima_franquia_m3'))
            valor_m3_usado = safe_float(config_fallback.get('valor_m3'))
            
        if consumo_m3 <= taxa_franquia_usada:
            detalhamento_fatura.append({'descricao': f"Taxa Mínima (Franquia de até {taxa_franquia_usada:.0f} m³)", 'valor': taxa_valor_usada})
        else:
            consumo_excedente = consumo_m3 - taxa_franquia_usada
            valor_excedente = consumo_excedente * valor_m3_usado
            detalhamento_fatura.append({'descricao': f"Taxa Mínima (Franquia de {taxa_franquia_usada:.0f} m³)", 'valor': taxa_valor_usada})
            detalhamento_fatura.append({'descricao': f"Consumo Excedente ({consumo_excedente} m³ x R$ {valor_m3_usado:.2f})".replace('.',','), 'valor': valor_excedente})

    valor_original_fatura = safe_float(leitura_data.get('valor_original'))
    total_pago_acumulado = sum(safe_float(p.get('valor_pago')) for p in pagamentos_feitos)
    total_multa_paga = sum(safe_float(p.get('valor_multa')) for p in pagamentos_feitos)
    total_juros_pago = sum(safe_float(p.get('valor_juros')) for p in pagamentos_feitos)
    total_juros_multa_pago_calculado = total_multa_paga + total_juros_pago
    saldo_devedor_base = max(0, valor_original_fatura + total_multa_paga + total_juros_pago - total_pago_acumulado)
    
    multa_hoje, juros_hoje, dias_atraso = 0.0, 0.0, 0
    if saldo_devedor_base > 0 and leitura_data.get('vencimento'):
        hoje_str = date.today().strftime('%Y-%m-%d')
        config = get_current_config()
        multa_hoje, juros_hoje, dias_atraso = calcular_penalidades(
            valor_original_fatura, saldo_devedor_base, leitura_data.get('vencimento'),
            hoje_str, config['multa_percentual'], config['juros_diario_percentual']
        )
    
    multa_a_cobrar = multa_hoje if total_multa_paga == 0 and dias_atraso > 0 else 0.0
    valor_total_atualizado = saldo_devedor_base + multa_a_cobrar + juros_hoje

    situacao_da_fatura_texto = ""
    if leitura_data.get('valor_original') is None:
        situacao_da_fatura_texto = "Leitura Informativa"
    elif valor_total_atualizado <= 0.01:
        situacao_da_fatura_texto = "Fatura Quitada"
    elif leitura_data.get('vencimento') and date.today() > leitura_data.get('vencimento'):
        situacao_da_fatura_texto = f"Vencida há {dias_atraso} dias"
    else:
        situacao_da_fatura_texto = "Pendente"

    data_leitura_anterior_formatada = data_leitura_anterior_obj.strftime('%d/%m/%Y') if data_leitura_anterior_obj else 'Início'
    
    # --- CONSULTA DO HISTÓRICO ATUALIZADA ---
    # Agora ela busca todas as leituras de todas as unidades daquele cliente
    historico_bruto_rows = db.execute(text('''
        SELECT TO_CHAR(data_leitura_atual, 'MM/YYYY') AS mes_ano, SUM(consumo_m3) AS consumo_total
        FROM leituras WHERE unidade_id IN (SELECT id FROM unidades_consumidoras WHERE cliente_id = :cid)
        GROUP BY TO_CHAR(data_leitura_atual, 'YYYY-MM'), TO_CHAR(data_leitura_atual, 'MM/YYYY')
        ORDER BY TO_CHAR(data_leitura_atual, 'YYYY-MM') DESC LIMIT 6
    '''), {'cid': leitura_data['cliente_id']}).fetchall()
    
    historico_dicts = [row._asdict() for row in historico_bruto_rows]
    historico_dicts.reverse()
    
    vencimento_obj = leitura_data.get('vencimento')

    # Monta o dicionário de contexto final que será enviado para o template HTML
    contexto = {
        'leitura': leitura_data, 
        'pagamentos_feitos': pagamentos_feitos, 
        'detalhamento_fatura': detalhamento_fatura,
        'historico_consumo': { 'labels': [item['mes_ano'] for item in historico_dicts], 'data': [float(item['consumo_total']) for item in historico_dicts] },
        'consumo_m3': consumo_m3,
        'dias_atraso': dias_atraso, 
        'multa_atual': multa_a_cobrar,
        'juros_atual': juros_hoje,
        'valor_total_devido': valor_total_atualizado,
        'total_pago_acumulado': total_pago_acumulado,
        'total_juros_multa_pago': total_juros_multa_pago_calculado,
        'situacao_da_fatura_texto': situacao_da_fatura_texto,
        'periodo_consumo': f"{data_leitura_anterior_formatada} a {leitura_data['data_leitura_atual'].strftime('%d/%m/%Y')}",
        'data_leitura_atual_formatada': leitura_data['data_leitura_atual'].strftime('%d/%m/%Y'), 
        'vencimento_formatado': vencimento_obj.strftime('%d/%m/%Y') if vencimento_obj else 'N/A',
        'data_emissao': date.today().strftime('%d/%m/%Y'),
        'saldo_final': valor_total_atualizado,
        'dias_no_periodo': dias_no_periodo,
        'media_diaria_consumo': media_diaria_consumo
    }
    return contexto
    
# -------Função Safe_float-----------
def safe_float(value, default=0.0):
    """Converte um valor para float de forma segura, tratando None e outros erros."""
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


# --- Rota para gerar a página com o botão de PDF (Leitura de consumo) ---
@app.route('/gerar-comprovante-pdf/<int:leitura_id>')
@login_required
def gerar_comprovante_pdf(leitura_id):
    contexto = _get_fatura_contexto(leitura_id)
    if contexto is None:
        flash('Fatura não encontrada.', 'danger')
        return redirect(url_for('listar_pagamentos'))
    
    # --- LÓGICA DO WHATSAPP ---
    pdf_url = url_for('download_comprovante_pdf', leitura_id=leitura_id, _external=True)
    texto_whatsapp = f"Olá! Segue o extrato da sua fatura Águas de Santa Maria (Ref. #{leitura_id}). Para visualizar ou baixar o PDF, acesse: {pdf_url}"
    
    whatsapp_phone = contexto['leitura'].get('telefone')
    
    if whatsapp_phone:
        whatsapp_phone_cleaned = ''.join(filter(str.isdigit, str(whatsapp_phone)))
        if len(whatsapp_phone_cleaned) >= 10 and not whatsapp_phone_cleaned.startswith('55'):
            whatsapp_phone_cleaned = f"55{whatsapp_phone_cleaned}"
    else:
        whatsapp_phone_cleaned = ''

    contexto['whatsapp_message'] = quote(texto_whatsapp)
    contexto['whatsapp_phone_number'] = whatsapp_phone_cleaned
        
    return render_template('detalhes_pagamento.html', **contexto)


# ---download do PDF do Comprovante de Leitura---
@app.route('/download-comprovante-pdf/<int:leitura_id>')
# @login_required <-- REMOVIDO também para consistência
def download_comprovante_pdf(leitura_id):
    contexto = _get_fatura_contexto(leitura_id)
    if not contexto:
        flash("Fatura não encontrada para gerar o comprovante.", "danger")
        return redirect(url_for('listar_pagamentos'))

    # Aplicando a mesma lógica de imagem embutida aqui
    contexto['leitura']['foto_hidrometro_base64'] = get_image_base64_string(contexto['leitura'].get('foto_hidrometro'))

    html_content = render_template('detalhes_pagamento.html', **contexto)

    try:
        pdf = HTML(string=html_content).write_pdf()
        response = make_response(pdf)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'inline; filename=comprovante_pagamento_{leitura_id}.pdf'
        return response
    except Exception as e:
        app.logger.error(f"Erro ao gerar PDF para leitura {leitura_id}: {e}", exc_info=True)
        flash('Erro ao gerar o PDF. Tente novamente mais tarde.', 'danger')
        return redirect(url_for('detalhes_pagamento', leitura_id=leitura_id))

#---------------Comprovante de Leiutura PDF----------------
@app.route('/comprovante_leitura/<int:leitura_id>')
@login_required
def comprovante_leitura(leitura_id):
    """
    Rota para o COMPROVANTE IMEDIATO após a leitura.
    Agora, ela reutiliza a função _get_fatura_contexto e prepara os dados para o WhatsApp.
    """
    # Esta parte do seu código foi mantida
    contexto = _get_fatura_contexto(leitura_id)
    
    if not contexto:
        flash('Leitura não encontrada.', 'danger')
        return redirect(url_for('listar_leituras'))
        
    # ======================================================================
    # INÍCIO DO BLOCO AJUSTADO - LÓGICA DO WHATSAPP
    # ======================================================================
    whatsapp_phone = contexto['leitura'].get('telefone')
    whatsapp_phone_cleaned = ''
    if whatsapp_phone:
        # Remove caracteres não numéricos do telefone (ex: '()', '-', ' ')
        whatsapp_phone_cleaned = ''.join(filter(str.isdigit, str(whatsapp_phone)))
        # Adiciona o código do Brasil (55) se não tiver
        if len(whatsapp_phone_cleaned) >= 10 and not whatsapp_phone_cleaned.startswith('55'):
            whatsapp_phone_cleaned = f"55{whatsapp_phone_cleaned}"

    # 1. Gera a URL completa e externa para o PDF
    pdf_url = url_for('download_leitura_pdf', leitura_id=leitura_id, _external=True)

    # 2. Mensagem personalizada agora inclui o link do PDF
    texto_mensagem = (f"Olá! Segue o comprovante de leitura da Águas de Santa Maria (Referência: #{leitura_id}).\n\n"
                      f"Para visualizar ou baixar o PDF, acesse o link:\n{pdf_url}")
    
    # O resto do bloco continua exatamente como estava
    whatsapp_message_encoded = quote(texto_mensagem)

    contexto['whatsapp_phone_number'] = whatsapp_phone_cleaned
    contexto['whatsapp_message'] = whatsapp_message_encoded
    # ======================================================================
    # FIM DO BLOCO AJUSTADO
    # ======================================================================
        
    # Esta parte do seu código também foi mantida
    return render_template('comprovante_leitura.html', **contexto)

#-----------------Funçao para mostrar imagem do hidrometro PDF whatsapp
def get_image_base64_string(foto_filename):
    """
    Busca uma imagem do S3, a baixa em memória e a converte para base64.
    """
    if not foto_filename:
        return None

    S3_BUCKET = os.environ.get('S3_BUCKET_NAME')
    AWS_REGION = os.environ.get('AWS_REGION')
    
    # Constrói a URL pública do objeto no S3
    url = f"https://{S3_BUCKET}.s3.{AWS_REGION}.amazonaws.com/{foto_filename}"

    try:
        # Faz o download da imagem a partir da URL
        response = requests.get(url, stream=True)
        response.raise_for_status() # Lança um erro se a imagem não for encontrada

        # Codifica a imagem para base64
        encoded_string = base64.b64encode(response.content).decode('utf-8')
        mime_type = response.headers.get('Content-Type', 'image/jpeg')
        
        return f"data:{mime_type};base64,{encoded_string}"

    except requests.exceptions.RequestException as e:
        app.logger.error(f"Erro ao baixar a imagem do S3 pela URL {url}: {e}")
        return None

#-------Visualizar e Baixar PDF da Leitura----------------------------
@app.route('/download-leitura-pdf/<int:leitura_id>')
# @login_required  <-- REMOVIDO para que o link funcione para o cliente
def download_leitura_pdf(leitura_id):
    contexto = _get_fatura_contexto(leitura_id)
    if not contexto:
        return "Leitura não encontrada.", 404

    contexto['leitura']['foto_hidrometro_base64'] = get_image_base64_string(contexto['leitura'].get('foto_hidrometro'))
    
    html_string = render_template('comprovante_leitura.html', **contexto)
    
    try:
        pdf = HTML(string=html_string).write_pdf()
        response = make_response(pdf)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'inline; filename=comprovante_leitura_{leitura_id}.pdf'
        return response
    except Exception as e:
        app.logger.error(f"Erro ao gerar PDF do comprovante de leitura {leitura_id}: {e}", exc_info=True)
        return "Erro ao gerar PDF.", 500

# --- Relatório de Unidades (VERSÃO FINAL REESTRUTURADA) ---
@app.route('/relatorio-unidades') # URL ATUALIZADA
@login_required
def relatorio_unidades():
    try:
        db = get_db()
        mes_filtro = request.args.get('mes')
        ano_filtro = request.args.get('ano')
        ano_atual = datetime.now().year

        if not mes_filtro and not ano_filtro:
            mes_filtro = datetime.now().strftime('%m')
            ano_filtro = str(ano_atual)
        
        if mes_filtro and mes_filtro.lower() == 'todos':
            mes_filtro = None

        # A consulta SQL foi refinada para ser mais robusta
        query = """
            WITH UltimaLeitura AS (
                SELECT 
                    l.unidade_id,
                    l.leitura_anterior,
                    l.leitura_atual,
                    l.data_leitura_atual,
                    l.foto_hidrometro,
                    CASE
                        WHEN l.valor_original IS NULL THEN 'Informativa'
                        WHEN (SELECT COALESCE(SUM(p.valor_pago), 0) FROM pagamentos p WHERE p.leitura_id = l.id) >= l.valor_original THEN 'Pago'
                        ELSE 'Pendente'
                    END as status_pagamento,
                    ROW_NUMBER() OVER(PARTITION BY l.unidade_id ORDER BY l.data_leitura_atual DESC, l.id DESC) as rn
                FROM leituras l
            )
            SELECT 
                c.nome, c.cpf, c.telefone,
                u.endereco, u.hidrometro_num,
                ul.leitura_anterior,
                ul.leitura_atual,
                ul.data_leitura_atual,
                ul.status_pagamento,
                ul.foto_hidrometro
            FROM clientes c
            JOIN unidades_consumidoras u ON c.id = u.cliente_id
            LEFT JOIN UltimaLeitura ul ON u.id = ul.unidade_id AND ul.rn = 1
        """

        conditions = []
        params = {}
        if mes_filtro:
            conditions.append("TO_CHAR(ul.data_leitura_atual, 'MM') = :mes_filtro")
            params['mes_filtro'] = mes_filtro.zfill(2)
        if ano_filtro:
            conditions.append("TO_CHAR(ul.data_leitura_atual, 'YYYY') = :ano_filtro")
            params['ano_filtro'] = ano_filtro
        
        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY c.nome, u.endereco"

        unidades_brutas = db.execute(text(query), params).fetchall()
        unidades = [u._asdict() for u in unidades_brutas]

        # Cálculos para os cards de estatísticas
        total_unidades_geral = db.execute(text("SELECT COUNT(id) FROM unidades_consumidoras WHERE status = 'Ativo'")).fetchone()[0]
        unidades_com_leituras_no_periodo = len([u for u in unidades if u['data_leitura_atual'] is not None])

        return render_template(
            'relatorio_unidades.html',
            unidades=unidades,
            mes_filtro=mes_filtro if mes_filtro else 'todos',
            ano_filtro=ano_filtro,
            ano_atual=ano_atual,
            total_unidades=total_unidades_geral,
            unidades_com_leituras=unidades_com_leituras_no_periodo,
            # AJUSTE: Passando as variáveis do S3 para o template
            S3_BUCKET_NAME=os.environ.get('S3_BUCKET_NAME'),
            AWS_REGION=os.environ.get('AWS_REGION')
        )

    except Exception as e:
        app.logger.error(f"Erro no relatório de unidades: {str(e)}", exc_info=True)
        flash("Ocorreu um erro ao gerar o relatório de unidades.", "danger")
        return redirect(url_for('dashboard'))    
#----------------------Lançamentos de Leituras em Planilha (VERSÃO REESTRUTURADA)---------------
@app.route('/lancamento_leituras', methods=['GET', 'POST'])
@login_required
def lancamento_leituras():
    db = get_db()
    hoje = datetime.now()

    if request.method == 'POST':
        form_data = request.form
        mes_competencia = form_data.get('mes_competencia')
        ano_competencia = form_data.get('ano_competencia')
        leituras_salvas = 0
        erros_de_validacao = []
        
        try:
            with db.begin():
                unidades_para_processar = db.execute(text("SELECT id FROM unidades_consumidoras")).fetchall()

                query_ultimas_leituras = text("""
                    WITH RankedLeituras AS (
                        SELECT l.*, ROW_NUMBER() OVER(PARTITION BY unidade_id ORDER BY data_leitura_atual DESC, id DESC) as rn
                        FROM leituras l
                    ) SELECT * FROM RankedLeituras WHERE rn = 1;
                """)
                ultimas_leituras_raw = db.execute(query_ultimas_leituras).fetchall()
                ultimas_leituras_map = {l.unidade_id: l for l in ultimas_leituras_raw}

                config = get_current_config()
                taxa_minima_valor = float(config.get('taxa_minima_valor', 15.0))
                taxa_minima_franquia = float(config.get('taxa_minima_franquia_m3', 10.0))
                valor_m3_configurado = float(config.get('valor_m3', 0.0))
                dias_uteis = int(config.get('dias_uteis_para_vencimento', 5))

                for unidade in unidades_para_processar:
                    unidade_id = unidade.id
                    leitura_atual_str = form_data.get(f'leitura_atual_{unidade_id}')
                    data_leitura_str = form_data.get(f'data_leitura_{unidade_id}')

                    if leitura_atual_str and data_leitura_str:
                        leitura_atual = int(leitura_atual_str)
                        data_leitura_obj = datetime.strptime(data_leitura_str, '%Y-%m-%d').date()
                        
                        ultima_leitura_real = ultimas_leituras_map.get(unidade_id)
                        leitura_anterior_real = ultima_leitura_real.leitura_atual if ultima_leitura_real else 0
                        data_anterior_real = ultima_leitura_real.data_leitura_atual if ultima_leitura_real else None
                        
                        if data_anterior_real and data_leitura_obj <= data_anterior_real:
                            erros_de_validacao.append(f"Erro na unidade {unidade_id}: A data da nova leitura deve ser posterior à última data registrada.")
                            continue
                        if leitura_atual < leitura_anterior_real:
                            erros_de_validacao.append(f"Erro na unidade {unidade_id}: A nova leitura não pode ser menor que a anterior.")
                            continue

                        consumo_m3 = leitura_atual - leitura_anterior_real
                        
                        consumo_m3_final = consumo_m3
                        if leitura_anterior_real < 500 and leitura_atual > 500:
                            consumo_m3_final = 0

                        valor_original = 0.0
                        if leitura_anterior_real > 0:
                            valor_original = taxa_minima_valor
                            if consumo_m3 > taxa_minima_franquia:
                                consumo_excedente = consumo_m3 - taxa_minima_franquia
                                valor_excedente = consumo_excedente * valor_m3_configurado
                                valor_original = taxa_minima_valor + valor_excedente
                        
                        data_vencimento = adicionar_dias_uteis(data_leitura_obj, dias_uteis)

                        db.execute(text("""
                            INSERT INTO leituras (unidade_id, leitura_anterior, data_leitura_anterior, leitura_atual, data_leitura_atual, consumo_m3, valor_original, vencimento, mes_competencia, ano_competencia, valor_m3_usado, taxa_minima_valor_usada, taxa_minima_franquia_usada)
                            VALUES (:unidade_id, :l_ant, :d_ant, :l_atu, :d_atu, :consumo, :val_orig, :venc, :mes_comp, :ano_comp, :v_m3, :t_min_val, :t_min_fran)
                        """), {
                            'unidade_id': unidade_id, 'l_ant': leitura_anterior_real, 'd_ant': data_anterior_real,
                            'l_atu': leitura_atual, 'd_atu': data_leitura_obj, 'consumo': consumo_m3_final,
                            'val_orig': valor_original, 'venc': data_vencimento,
                            'mes_comp': int(mes_competencia), 'ano_comp': int(ano_competencia),
                            'v_m3': valor_m3_configurado, 't_min_val': taxa_minima_valor, 't_min_fran': taxa_minima_franquia
                        })
                        leituras_salvas += 1
            
            if leituras_salvas > 0: flash(f"{leituras_salvas} leitura(s) foram salvas com sucesso!", "success")
            if erros_de_validacao:
                for erro in erros_de_validacao: flash(erro, "danger")
            elif leituras_salvas == 0 and not erros_de_validacao: flash("Nenhuma nova leitura foi preenchida para salvar.", "info")

            return redirect(url_for('lancamento_leituras', mes=mes_competencia, ano=ano_competencia))
        except Exception as e:
            app.logger.error(f"Erro ao salvar leituras em massa: {e}", exc_info=True)
            flash("Ocorreu um erro inesperado ao tentar salvar as leituras. A operação foi cancelada.", "danger")
            return redirect(url_for('lancamento_leituras', mes=request.form.get('mes_competencia'), ano=request.form.get('ano_competencia')))

    else: # Lógica GET
        try:
            mes_competencia = request.args.get('mes', hoje.strftime('%m'))
            ano_competencia = request.args.get('ano', hoje.strftime('%Y'))
            
            todas_unidades = db.execute(text("""
                SELECT u.id, u.endereco, u.hidrometro_num, c.nome as cliente_nome
                FROM unidades_consumidoras u
                JOIN clientes c ON u.cliente_id = c.id
                ORDER BY c.nome, u.endereco
            """)).fetchall()
            
            query_ultimas_leituras = text("""
                WITH RankedLeituras AS (
                    SELECT l.*, ROW_NUMBER() OVER(PARTITION BY unidade_id ORDER BY data_leitura_atual DESC, id DESC) as rn FROM leituras l
                ) SELECT * FROM RankedLeituras WHERE rn = 1;
            """)
            ultimas_leituras_raw = db.execute(query_ultimas_leituras).fetchall()
            ultimas_leituras_map = {l.unidade_id: l for l in ultimas_leituras_raw}

            query_leituras_feitas = text("SELECT * FROM leituras WHERE mes_competencia = :mes AND ano_competencia = :ano")
            leituras_feitas_raw = db.execute(query_leituras_feitas, {'mes': int(mes_competencia), 'ano': int(ano_competencia)}).fetchall()
            leituras_feitas_map_mes_corrente = {l.unidade_id: l for l in leituras_feitas_raw}
            
            dados_para_planilha = []
            for unidade in todas_unidades:
                unidade_id = unidade.id
                ultima_leitura_geral = ultimas_leituras_map.get(unidade_id)
                
                dados_da_unidade = {
                    'unidade_info': unidade._asdict(),
                    'leitura_anterior': ultima_leitura_geral.leitura_atual if ultima_leitura_geral else 0,
                    'data_leitura_anterior': ultima_leitura_geral.data_leitura_atual.strftime('%d/%m/%Y') if ultima_leitura_geral and ultima_leitura_geral.data_leitura_atual else 'N/A',
                    'ultima_leitura_data_iso': ultima_leitura_geral.data_leitura_atual.isoformat() if ultima_leitura_geral and ultima_leitura_geral.data_leitura_atual else None,
                    'leitura_do_mes': leituras_feitas_map_mes_corrente.get(unidade_id)
                }
                dados_para_planilha.append(dados_da_unidade)
            
            return render_template('lancamento_leituras.html',
                dados_planilha=dados_para_planilha, mes_selecionado=mes_competencia,
                ano_selecionado=ano_competencia, ano_atual=hoje.year,
                today_date=hoje.strftime('%Y-%m-%d'))
        except Exception as e:
            app.logger.error(f"Erro ao carregar a página de lançamento de leituras: {e}", exc_info=True)
            flash("Ocorreu um erro ao carregar a planilha de leituras.", "danger")
            return redirect(url_for('dashboard'))
        
        
# --- Listar Leituras (VERSÃO FINAL E CORRIGIDA PARA POSTGRESQL) ---
# Em app.py, substitua a função listar_leituras por esta:

@app.route('/leituras')
@login_required
def listar_leituras():
    try:
        db = get_db()
        page = request.args.get('page', 1, type=int)
        mes_filtro = request.args.get('mes', '')
        ano_filtro = request.args.get('ano', '')
        
        PER_PAGE = 20
        offset = (page - 1) * PER_PAGE
        
        # --- LÓGICA DA CONSULTA ATUALIZADA ---
        # A base da query agora junta as 3 tabelas
        base_query = """
            FROM leituras l
            JOIN unidades_consumidoras u ON l.unidade_id = u.id
            JOIN clientes c ON u.cliente_id = c.id
        """
        
        conditions = []
        params = {}
        
        if mes_filtro:
            conditions.append("TO_CHAR(l.data_leitura_atual, 'MM') = :mes")
            params['mes'] = mes_filtro.zfill(2)
        if ano_filtro:
            conditions.append("TO_CHAR(l.data_leitura_atual, 'YYYY') = :ano")
            params['ano'] = ano_filtro
        
        where_clause = ""
        if conditions:
            where_clause = " WHERE " + " AND ".join(conditions)
        
        # Query para contar o total de itens para a paginação
        count_query_str = f"SELECT COUNT(l.id) {base_query} {where_clause}"
        total_items_params = {k: v for k, v in params.items()}
        total_items = db.execute(text(count_query_str), total_items_params).fetchone()[0]

        # Query para buscar os dados da página atual
        data_query_str = f"""
            SELECT 
                l.*, 
                c.nome as cliente_nome, 
                u.endereco,
                u.hidrometro_num,
                (SELECT COUNT(p.id) FROM pagamentos p WHERE p.leitura_id = l.id) as num_pagamentos
            {base_query}
            {where_clause}
            ORDER BY l.data_leitura_atual DESC, l.id DESC 
            LIMIT :limit OFFSET :offset
        """
        params['limit'] = PER_PAGE
        params['offset'] = offset
        
        leituras_brutas = db.execute(text(data_query_str), params).fetchall()
        leituras_formatadas = [l_bruto._asdict() for l_bruto in leituras_brutas]
        
        total_pages = math.ceil(total_items / PER_PAGE) if total_items > 0 else 1
        
        pagination = {
            "page": page, "total_pages": total_pages,
            "has_prev": page > 1, "has_next": page < total_pages
        }

        return render_template(
            'listar_leituras.html', 
            leituras=leituras_formatadas,
            pagination=pagination,
            mes_filtro=mes_filtro,
            ano_filtro=ano_filtro,
            ano_atual=datetime.now().year
        )
    except Exception as e:
        app.logger.error(f"Erro ao listar leituras: {e}", exc_info=True)
        flash("Ocorreu um erro ao carregar o relatório de leituras.", "danger")
        return redirect(url_for('dashboard'))

# --- Relatório Geral (VERSÃO FINAL E CORRIGIDA) ---
# --- Relatório Geral (VERSÃO REESTRUTURADA FINAL) ---
@app.route('/relatorio-geral')
@login_required
def relatorio_geral():
    """
    Busca e calcula todos os indicadores consolidados para o Relatório Geral.
    """
    try:
        db = get_db()
        hoje = datetime.now()
        mes_atual = hoje.strftime('%m')
        ano_atual = hoje.strftime('%Y')

        # 1. Receitas no Mês
        total_receitas_mes = db.execute(text("""
            SELECT COALESCE(SUM(valor_pago), 0) FROM pagamentos 
            WHERE TO_CHAR(data_pagamento, 'MM') = :mes AND TO_CHAR(data_pagamento, 'YYYY') = :ano
        """), {'mes': mes_atual, 'ano': ano_atual}).fetchone()[0]

        # 2. Despesas no Mês
        total_despesas_mes = db.execute(text("""
            SELECT COALESCE(SUM(valor), 0) FROM despesas 
            WHERE TO_CHAR(data_despesa, 'MM') = :mes AND TO_CHAR(data_despesa, 'YYYY') = :ano
        """), {'mes': mes_atual, 'ano': ano_atual}).fetchone()[0]

        # 3. Saldo do Mês
        saldo_mes = total_receitas_mes - total_despesas_mes

        # 4. Total de Unidades Consumidoras Ativas (AQUI ESTÁ A CORREÇÃO)
        total_unidades_ativas = db.execute(text("SELECT COUNT(id) FROM unidades_consumidoras WHERE status = 'Ativo'")).fetchone()[0]

        # 5. Total de Faturas Pendentes (Esta consulta já estava correta)
        faturas_pendentes = db.execute(text('''
            WITH PagamentosAgregados AS (
                SELECT leitura_id, SUM(valor_pago) as total_pago, SUM(valor_multa) as total_multa, SUM(valor_juros) as total_juros
                FROM pagamentos GROUP BY leitura_id
            )
            SELECT COUNT(l.id)
            FROM leituras l
            LEFT JOIN PagamentosAgregados p ON l.id = p.leitura_id
            WHERE (l.valor_original + COALESCE(p.total_multa, 0) + COALESCE(p.total_juros, 0)) > (COALESCE(p.total_pago, 0) + 0.001)
        ''')).fetchone()[0]

        # 6. Consumo Total de Água no Mês (Esta consulta já estava correta)
        consumo_total_mes = db.execute(text("""
            SELECT COALESCE(SUM(consumo_m3), 0) FROM leituras 
            WHERE TO_CHAR(data_leitura_atual, 'MM') = :mes AND TO_CHAR(data_leitura_atual, 'YYYY') = :ano
        """), {'mes': mes_atual, 'ano': ano_atual}).fetchone()[0]

        # 7. Pagamentos Realizados Hoje
        pagamentos_hoje = db.execute(text("SELECT COUNT(id) FROM pagamentos WHERE data_pagamento = :hoje"), {'hoje': hoje.strftime('%Y-%m-%d')}).fetchone()[0]

        # Monta o dicionário completo para enviar ao template
        resumo = {
            'total_receitas_mes': total_receitas_mes,
            'total_despesas_mes': total_despesas_mes,
            'saldo_mes': saldo_mes,
            'total_consumidores': total_unidades_ativas, # Passando o novo valor com o nome antigo para não quebrar o HTML
            'faturas_pendentes': faturas_pendentes,
            'consumo_total_mes': consumo_total_mes,
            'pagamentos_hoje': pagamentos_hoje
        }

        return render_template('relatorio_geral.html', resumo=resumo)
    
    except Exception as e:
        app.logger.error(f"Erro ao gerar Relatório Geral: {e}", exc_info=True)
        flash("Ocorreu um erro ao carregar os dados do Relatório Geral.", "danger")
        return redirect(url_for('dashboard'))
    
# --- Selecionar Comprovante (VERSÃO FINAL - CORRIGIDA PARA POSTGRESQL) ---
@app.route('/selecionar-comprovante')
@login_required
def selecionar_comprovante():
    db = get_db()
    try:
        # ATUALIZADO: A consulta agora usa a nova estrutura de tabelas
        leituras_brutas = db.execute(text('''
            SELECT DISTINCT l.id, l.data_leitura_atual, l.valor_original, c.nome AS cliente_nome
            FROM leituras l
            JOIN pagamentos p ON l.id = p.leitura_id
            JOIN unidades_consumidoras u ON l.unidade_id = u.id
            JOIN clientes c ON u.cliente_id = c.id
            ORDER BY l.data_leitura_atual DESC
        ''')).fetchall()
        
        leituras_pagas = [row._asdict() for row in leituras_brutas]
        
        return render_template('selecionar_comprovante.html', leituras_pagas=leituras_pagas)

    except Exception as e:
        app.logger.error(f"Erro ao carregar a lista de comprovantes: {e}", exc_info=True)
        flash("Ocorreu um erro ao carregar a lista de comprovantes.", "danger")
        return redirect(url_for('dashboard'))


# --- Relatórios no Card ---
@app.route('/relatorios')
@login_required
def relatorios():
    return render_template('relatorios.html')

@app.route('/backup-db')
@admin_required
def baixar_db():
    try:
        # Apenas permite download se o arquivo existir
        if os.path.exists(DATABASE):
            return send_file(DATABASE, as_attachment=True)
        else:
            flash("Arquivo de banco de dados não encontrado.", "error")
            return redirect(url_for('dashboard'))
    except Exception as e:
        app.logger.error(f"Erro ao baixar DB: {e}", exc_info=True)
        flash("Erro ao tentar baixar o banco de dados.", "error")
        return redirect(url_for('dashboard'))


# --- Relatório de Inadimplência (VERSÃO REESTRUTURADA) ---
@app.route('/relatorio-inadimplencia')
@login_required
def relatorio_inadimplencia():
    try:
        db = get_db()
        config = get_current_config() 
        hoje_str = date.today().strftime('%Y-%m-%d')
        hoje_obj = date.today()

        faturas_raw = db.execute(text('''
            SELECT 
                l.id AS leitura_id,
                c.nome AS cliente_nome,
                u.endereco,
                c.telefone,
                l.data_leitura_atual,
                l.vencimento,
                l.valor_original,
                COALESCE((SELECT SUM(p.valor_pago) FROM pagamentos p WHERE p.leitura_id = l.id), 0) AS total_pago_acumulado,
                COALESCE((SELECT SUM(p.valor_multa) FROM pagamentos p WHERE p.leitura_id = l.id), 0) AS total_multa_acumulada,
                COALESCE((SELECT SUM(p.valor_juros) FROM pagamentos p WHERE p.leitura_id = l.id), 0) AS total_juros_acumulados
            FROM leituras l
            JOIN unidades_consumidoras u ON l.unidade_id = u.id
            JOIN clientes c ON u.cliente_id = c.id
            WHERE l.valor_original IS NOT NULL
            ORDER BY l.vencimento ASC
        ''')).fetchall()
        
        pendencias_calculadas = []
        total_pendente_geral = 0.0
        total_atualizado_geral = 0.0

        for p_bruto in faturas_raw:
            p_raw = p_bruto._asdict()
            try:
                valor_original_da_fatura = safe_float(p_raw.get('valor_original'))
                total_pago_acumulado = safe_float(p_raw.get('total_pago_acumulado'))
                total_multa_acumulada = safe_float(p_raw.get('total_multa_acumulada'))
                total_juros_acumulados = safe_float(p_raw.get('total_juros_acumulados'))

                valor_pendente_base = (valor_original_da_fatura + total_multa_acumulada + total_juros_acumulados) - total_pago_acumulado

                if valor_pendente_base > 0.01:
                    vencimento_data = p_raw.get('vencimento')
                    if not vencimento_data: continue

                    # --- Início da correção pontual no formato da data de vencimento ---
                    # Garantir que vencimento_data é um objeto de data/datetime antes de formatar
                    if isinstance(vencimento_data, datetime):
                        vencimento_data_obj = vencimento_data.date()
                    elif isinstance(vencimento_data, date):
                        vencimento_data_obj = vencimento_data
                    else:
                        # Se não for um objeto de data, tentar parsear de string (formato YYYY-MM-DD)
                        try:
                            vencimento_data_obj = datetime.strptime(str(vencimento_data), '%Y-%m-%d').date()
                        except ValueError:
                            # Se não conseguir parsear, pular esta entrada ou definir como 'N/A'
                            app.logger.warning(f"Data de vencimento inválida para formatação: {vencimento_data}. Pulando entrada.")
                            continue 
                    
                    # Formatar a data usando f-string para maior controle e clareza
                    vencimento_formatado = f"{vencimento_data_obj.day:02d}/{vencimento_data_obj.month:02d}/{vencimento_data_obj.year}"
                    # --- Fim da correção pontual ---

                    multa_calculada_potencial, juros_calc, dias_atraso = calcular_penalidades(
                        valor_original_da_fatura, valor_pendente_base, vencimento_data_obj, # Usar vencimento_data_obj corrigido aqui
                        hoje_str, config['multa_percentual'], config['juros_diario_percentual']
                    )
                    
                    multa_para_exibir_agora = 0.0
                    if dias_atraso > 0 and total_multa_acumulada == 0:
                        multa_para_exibir_agora = multa_calculada_potencial

                    valor_atualizado = round(valor_pendente_base + multa_para_exibir_agora + juros_calc, 2)
                    
                    if valor_atualizado > 0.01:
                        is_vencido = vencimento_data_obj < hoje_obj # Usar vencimento_data_obj corrigido aqui
                        pendencias_calculadas.append({
                            'consumidor': p_raw.get('cliente_nome'),
                            'endereco': p_raw.get('endereco'),
                            'telefone': p_raw.get('telefone'),
                            'data_leitura_atual': p_raw.get('data_leitura_atual').strftime('%d/%m/%Y') if p_raw.get('data_leitura_atual') else 'N/A',
                            'vencimento': vencimento_formatado, # Usar a string formatada aqui
                            'valor_original': valor_original_da_fatura,
                            'total_pago': total_pago_acumulado,
                            'valor_pendente': valor_pendente_base, 
                            'valor_atualizado': valor_atualizado,
                            'is_vencido': is_vencido
                        })
                        total_pendente_geral += valor_pendente_base 
                        total_atualizado_geral += valor_atualizado
            except Exception as e_loop:
                app.logger.error(f"Erro ao processar inadimplência para leitura ID {p_raw.get('leitura_id')}: {e_loop}", exc_info=True)
                continue

        return render_template(
            'relatorio_inadimplencia.html',
            pendencias=pendencias_calculadas,
            total_pendente=round(total_pendente_geral, 2),
            total_atualizado=round(total_atualizado_geral, 2),
            data_hoje=datetime.now().strftime('%d/%m/%Y')
        )
    
    except Exception as e:
        app.logger.error(f"Erro crítico no relatório de inadimplência: {str(e)}", exc_info=True)
        flash("Ocorreu um erro ao gerar o relatório de inadimplência.", "danger")
        return redirect(url_for('dashboard'))
    
# --- Rotas de Gerenciamento de Despesas (VERSÃO CORRIGIDA) ---
@app.route('/cadastrar-despesa', methods=['GET', 'POST'])
@login_required
def cadastrar_despesa():
    if request.method == 'POST':
        descricao = request.form['descricao'].strip()
        valor_str = request.form['valor']
        data_despesa_str = request.form.get('data_despesa') or date.today().strftime('%Y-%m-%d')
        categoria = request.form.get('categoria', '').strip()
        observacoes = request.form.get('observacoes', '').strip()

        if not descricao or not valor_str:
            flash("Descrição e Valor são campos obrigatórios.", "danger")
            return render_template('cadastrar_despesa.html', today_date=data_despesa_str)

        try:
            valor = parse_number_from_br_form(valor_str)
            if valor <= 0:
                flash("O valor da despesa deve ser maior que R$ 0,00.", "danger")
                return render_template('cadastrar_despesa.html', today_date=data_despesa_str)

            db = get_db()
            with db.begin():
                db.execute(
                    text("""
                        INSERT INTO despesas (data_despesa, descricao, valor, categoria, observacoes)
                        VALUES (:data, :desc, :val, :cat, :obs)
                    """), {
                        'data': data_despesa_str, 'desc': descricao, 'val': valor, 
                        'cat': categoria, 'obs': observacoes
                    }
                )
            
            flash("Despesa cadastrada com sucesso!", "success")
            return redirect(url_for('listar_despesas'))
        except Exception as e:
            app.logger.error(f"Erro ao cadastrar despesa: {str(e)}", exc_info=True)
            flash(f"Erro ao cadastrar despesa: {str(e)}", "danger")
            return render_template('cadastrar_despesa.html', today_date=data_despesa_str)

    else: # Método GET
        today_date = date.today().strftime('%Y-%m-%d')
        return render_template('cadastrar_despesa.html', today_date=today_date)

# --- Listar Despesas (VERSÃO CORRIGIDA PARA POSTGRESQL) ---
@app.route('/listar-despesas')
@login_required
def listar_despesas():
    db = get_db()
    page = request.args.get('page', 1, type=int)
    mes_filtro = request.args.get('mes', '')
    ano_filtro = request.args.get('ano', '')
    categoria_filtro = request.args.get('categoria', '')

    # Bloco de validação de datas (pode ser mantido como está)
    MAX_FUTURE_YEARS = 20
    try:
        if ano_filtro:
            ano_int = int(ano_filtro)
            if not (1900 <= ano_int <= datetime.now().year + MAX_FUTURE_YEARS):
                flash(f"Ano inválido ou fora do intervalo permitido (1900 - {datetime.now().year + MAX_FUTURE_YEARS}).", "warning")
                ano_filtro = ''
        if mes_filtro:
            if not (1 <= int(mes_filtro) <= 12):
                flash("Mês inválido.", "warning")
                mes_filtro = ''
    except ValueError:
        flash("Filtro de data inválido. Limpando filtros de data.", "warning")
        mes_filtro = ''
        ano_filtro = ''

    PER_PAGE = 15
    offset = (page - 1) * PER_PAGE

    base_query = "FROM despesas"
    conditions = []
    params = {}

    # --- CORREÇÃO DO DIALETO SQL ---
    # Substituindo strftime por TO_CHAR
    if mes_filtro:
        conditions.append("TO_CHAR(data_despesa, 'MM') = :mes")
        params['mes'] = mes_filtro.zfill(2)
    
    if ano_filtro:
        conditions.append("TO_CHAR(data_despesa, 'YYYY') = :ano")
        params['ano'] = ano_filtro
    
    if categoria_filtro:
        conditions.append("categoria = :categoria")
        params['categoria'] = categoria_filtro

    where_clause = ""
    if conditions:
        where_clause = " WHERE " + " AND ".join(conditions)

    # O resto da função já usa a sintaxe correta do SQLAlchemy (text())
    count_query = f"SELECT COUNT(id) {base_query} {where_clause}"
    params_summary = {k: v for k, v in params.items() if k not in ['limit', 'offset']}
    total_items = db.execute(text(count_query), params_summary).fetchone()[0]

    data_query = f"SELECT * {base_query} {where_clause} ORDER BY data_despesa DESC, id DESC LIMIT :limit OFFSET :offset"
    params['limit'] = PER_PAGE
    params['offset'] = offset
    despesas = db.execute(text(data_query), params).fetchall()

    total_pages = math.ceil(total_items / PER_PAGE) if total_items > 0 else 1
    pagination = {
        "page": page, "total_pages": total_pages,
        "has_prev": page > 1, "has_next": page < total_pages
    }
    
    categorias = db.execute(text("SELECT DISTINCT categoria FROM despesas WHERE categoria IS NOT NULL AND categoria != '' ORDER BY categoria")).fetchall()
    
    total_despesas_periodo = db.execute(text(f"SELECT COALESCE(SUM(valor), 0) {base_query} {where_clause}"), params_summary).fetchone()[0]

    return render_template('listar_despesas.html',
                           despesas=despesas,
                           pagination=pagination,
                           mes_filtro=mes_filtro,
                           ano_filtro=ano_filtro,
                           categoria_filtro=categoria_filtro,
                           categorias=categorias,
                           ano_atual=datetime.now().year,
                           total_despesas_periodo=total_despesas_periodo)

# --- Editar Despesa (VERSÃO CORRIGIDA PARA POSTGRESQL) ---
@app.route('/editar-despesa/<int:id>', methods=['GET', 'POST'])
@login_required
def editar_despesa(id):
    db = get_db()
    
    # --- Lógica para POST (SALVAR as alterações) ---
    if request.method == 'POST':
        descricao = request.form['descricao'].strip()
        valor_str = request.form['valor']
        data_despesa_str = request.form['data_despesa']
        categoria = request.form.get('categoria', '').strip()
        observacoes = request.form.get('observacoes', '').strip()

        # Validação dos dados de entrada
        if not descricao or not valor_str or not data_despesa_str:
            flash("Descrição, Valor e Data da Despesa são campos obrigatórios.", "danger")
            # Em caso de erro, busca os dados novamente para exibir a página
            resultado_bruto = db.execute(text("SELECT * FROM despesas WHERE id = :id"), {'id': id}).fetchone()
            despesa = resultado_bruto._asdict() if resultado_bruto else None
            return render_template('editar_despesa.html', despesa=despesa)

        try:
            # Tenta converter os valores
            valor = parse_number_from_br_form(valor_str)
            if valor <= 0:
                raise ValueError("O valor da despesa deve ser maior que R$ 0,00.")
            datetime.strptime(data_despesa_str, '%Y-%m-%d')
        except ValueError as e:
            flash(str(e), "danger")
            resultado_bruto = db.execute(text("SELECT * FROM despesas WHERE id = :id"), {'id': id}).fetchone()
            despesa = resultado_bruto._asdict() if resultado_bruto else None
            return render_template('editar_despesa.html', despesa=despesa)

        # Tenta atualizar o banco de dados
        try:
            with db.begin():
                db.execute(
                    text("""
                        UPDATE despesas
                        SET data_despesa = :data, descricao = :desc, valor = :val, categoria = :cat, observacoes = :obs
                        WHERE id = :id
                    """),
                    {
                        'data': data_despesa_str, 'desc': descricao, 'val': valor, 
                        'cat': categoria, 'obs': observacoes, 'id': id
                    }
                )
            
            flash("Despesa atualizada com sucesso!", "success")
            return redirect(url_for('listar_despesas'))
        except Exception as e:
            app.logger.error(f"Erro ao atualizar despesa: {str(e)}", exc_info=True)
            flash(f"Erro ao atualizar despesa: {str(e)}", "danger")
            resultado_bruto = db.execute(text("SELECT * FROM despesas WHERE id = :id"), {'id': id}).fetchone()
            despesa = resultado_bruto._asdict() if resultado_bruto else None
            return render_template('editar_despesa.html', despesa=despesa)
    
    # --- Lógica para GET (CARREGAR a página de edição) ---
    else:
        resultado_bruto = db.execute(text("SELECT * FROM despesas WHERE id = :id"), {'id': id}).fetchone()

        if not resultado_bruto:
            flash("Despesa não encontrada.", "danger")
            return redirect(url_for('listar_despesas'))
        
        # Converte o resultado para dicionário antes de enviar para o template
        despesa = resultado_bruto._asdict()
        return render_template('editar_despesa.html', despesa=despesa)


@app.route('/excluir-despesa/<int:id>', methods=['POST']) # <-- A CORREÇÃO ESTÁ AQUI
@login_required
def excluir_despesa(id):
    db = get_db()
    try:
        # Usa o bloco 'with' para transação segura e automática
        with db.begin():
            # Usa o parâmetro nomeado ':id', que é o correto para SQLAlchemy
            db.execute(text("DELETE FROM despesas WHERE id = :id"), {'id': id})
        
        flash("Despesa excluída com sucesso!", "success")

    except Exception as e:
        app.logger.error(f"Erro ao excluir despesa: {str(e)}", exc_info=True)
        flash("Erro ao excluir a despesa.", "danger")

    return redirect(url_for('listar_despesas'))

# --- Relatório Financeiro (VERSÃO CORRIGIDA PARA POSTGRESQL) ---
@app.route('/relatorio-financeiro')
@login_required
def relatorio_financeiro():
    db = get_db()
    
    mes_filtro = request.args.get('mes', '')
    ano_filtro = request.args.get('ano', str(datetime.now().year))

    # Bloco de validação de datas (mantido)
    MAX_FUTURE_YEARS = 20
    try:
        if ano_filtro:
            ano_int = int(ano_filtro)
            if not (1900 <= ano_int <= datetime.now().year + MAX_FUTURE_YEARS):
                flash(f"Ano inválido ou fora do intervalo permitido.", "warning")
                ano_filtro = str(datetime.now().year)
        if mes_filtro:
            if not (1 <= int(mes_filtro) <= 12):
                flash("Mês inválido.", "warning")
                mes_filtro = ''
    except ValueError:
        flash("Filtro de data inválido. Resetando para o ano atual.", "warning")
        mes_filtro = ''
        ano_filtro = str(datetime.now().year)

    # --- CORREÇÃO DO DIALETO SQL ---
    # As condições agora usam TO_CHAR, que é o padrão do PostgreSQL
    receitas_conditions = []
    despesas_conditions = []
    params = {}

    if mes_filtro:
        receitas_conditions.append("TO_CHAR(data_pagamento, 'MM') = :mes")
        despesas_conditions.append("TO_CHAR(data_despesa, 'MM') = :mes")
        params['mes'] = mes_filtro.zfill(2)
        
    if ano_filtro:
        receitas_conditions.append("TO_CHAR(data_pagamento, 'YYYY') = :ano")
        despesas_conditions.append("TO_CHAR(data_despesa, 'YYYY') = :ano")
        params['ano'] = ano_filtro

    receitas_where_clause = " WHERE " + " AND ".join(receitas_conditions) if receitas_conditions else ""
    despesas_where_clause = " WHERE " + " AND ".join(despesas_conditions) if despesas_conditions else ""

    receitas_query = f"SELECT COALESCE(SUM(valor_pago), 0) FROM pagamentos {receitas_where_clause}"
    total_receitas = db.execute(text(receitas_query), params).fetchone()[0]

    despesas_query = f"SELECT COALESCE(SUM(valor), 0) FROM despesas {despesas_where_clause}"
    total_despesas = db.execute(text(despesas_query), params).fetchone()[0]

    saldo = total_receitas - total_despesas

    return render_template('relatorio_financeiro.html',
                           total_receitas=total_receitas,
                           total_despesas=total_despesas,
                           saldo=saldo,
                           mes_filtro=mes_filtro,
                           ano_filtro=ano_filtro,
                           ano_atual=datetime.now().year)

# --- Gerar PDF do Relatório Financeiro (VERSÃO CORRIGIDA) ---
@app.route('/gerar-pdf/relatorio-financeiro')
@login_required
def gerar_pdf_relatorio_financeiro():
    db = get_db()
    mes_filtro = request.args.get('mes', '')
    ano_filtro = request.args.get('ano', str(datetime.now().year))

    # Reutiliza a mesma lógica de cálculo e filtro da rota principal
    receitas_conditions = []
    despesas_conditions = []
    params = {}

    if mes_filtro:
        receitas_conditions.append("TO_CHAR(data_pagamento, 'MM') = :mes")
        despesas_conditions.append("TO_CHAR(data_despesa, 'MM') = :mes")
        params['mes'] = mes_filtro.zfill(2)
    
    if ano_filtro:
        receitas_conditions.append("TO_CHAR(data_pagamento, 'YYYY') = :ano")
        despesas_conditions.append("TO_CHAR(data_despesa, 'YYYY') = :ano")
        params['ano'] = ano_filtro

    receitas_where_clause = " WHERE " + " AND ".join(receitas_conditions) if receitas_conditions else ""
    despesas_where_clause = " WHERE " + " AND ".join(despesas_conditions) if despesas_conditions else ""

    receitas_query = f"SELECT COALESCE(SUM(valor_pago), 0) FROM pagamentos {receitas_where_clause}"
    total_receitas = db.execute(text(receitas_query), params).fetchone()[0]

    despesas_query = f"SELECT COALESCE(SUM(valor), 0) FROM despesas {despesas_where_clause}"
    total_despesas = db.execute(text(despesas_query), params).fetchone()[0]

    saldo = total_receitas - total_despesas
    
    html_string = render_template(
        'relatorio_financeiro.html',
        total_receitas=total_receitas,
        total_despesas=total_despesas,
        saldo=saldo,
        mes_filtro=mes_filtro,
        ano_filtro=ano_filtro,
        ano_atual=datetime.now().year,
        is_pdf=True
    )
    
    pdf = HTML(string=html_string).write_pdf()
    
    return Response(
        pdf,
        mimetype='application/pdf',
        headers={'Content-Disposition': 'inline; filename=relatorio_financeiro.pdf'}
    )

#---------------------- Central de Fechamento Mensal (VERSÃO FINAL) ----------------------
@app.route('/fechamento-mensal', methods=['GET', 'POST'])
@login_required
def fechamento_mensal():
    db = get_db()
    resultado = None
    
    # --- Lógica POST: Quando um NOVO fechamento é criado ---
    if request.method == 'POST':
        try:
            leitura_anterior_master = float(request.form.get('leitura_anterior_master_criar', 0))
            leitura_atual_master = float(request.form.get('leitura_atual_master_criar'))
            mes_competencia_criar = int(request.form.get('mes_competencia_criar'))
            ano_competencia_criar = int(request.form.get('ano_competencia_criar'))

            if leitura_atual_master <= leitura_anterior_master:
                flash("A leitura atual do medidor principal não pode ser menor ou igual à anterior.", "danger")
                return redirect(url_for('fechamento_mensal'))

            with db.begin():
                consumo_master = leitura_atual_master - leitura_anterior_master
                soma_consumidores_bruto = db.execute(text("""
                    SELECT COALESCE(SUM(consumo_m3), 0) FROM leituras
                    WHERE mes_competencia = :mes AND ano_competencia = :ano
                """), {'mes': mes_competencia_criar, 'ano': ano_competencia_criar}).fetchone()
                soma_consumidores = float(soma_consumidores_bruto[0])
                perda_m3 = consumo_master - soma_consumidores
                perda_percentual = (perda_m3 / consumo_master * 100) if consumo_master > 0 else 0

                db.execute(text("""
                    INSERT INTO fechamentos (
                        mes_competencia, ano_competencia, leitura_anterior_master, leitura_atual_master,
                        consumo_master_calculado, soma_consumidores_calculado, perda_calculada_m3, perda_percentual
                    ) VALUES (:mes, :ano, :l_ant, :l_atu, :c_master, :s_consum, :p_m3, :p_perc)
                """), {
                    'mes': mes_competencia_criar, 'ano': ano_competencia_criar, 'l_ant': leitura_anterior_master,
                    'l_atu': leitura_atual_master, 'c_master': consumo_master, 's_consum': soma_consumidores,
                    'p_m3': perda_m3, 'p_perc': perda_percentual
                })
            
            flash("Novo fechamento salvo com sucesso! O resultado está exibido abaixo.", "success")
            return redirect(url_for('fechamento_mensal', mes=mes_competencia_criar, ano=ano_competencia_criar))

        except IntegrityError:
            flash(f"Já existe um fechamento registrado para a competência {mes_competencia_criar:02d}/{ano_competencia_criar}.", "warning")
            return redirect(url_for('fechamento_mensal'))
        except Exception as e:
            flash(f"Ocorreu um erro ao criar o fechamento: {e}", "danger")
            app.logger.error(f"Erro no POST de fechamento mensal: {e}", exc_info=True)
            return redirect(url_for('fechamento_mensal'))

    # --- Lógica GET: Carrega a página e exibe consultas do histórico ---
    else:
        mes_consulta = request.args.get('mes', type=int)
        ano_consulta = request.args.get('ano', type=int)

        if mes_consulta and ano_consulta:
            resultado_bruto = db.execute(text("""
                SELECT * FROM fechamentos WHERE mes_competencia = :mes AND ano_competencia = :ano
            """), {'mes': mes_consulta, 'ano': ano_consulta}).fetchone()
            if resultado_bruto:
                resultado = resultado_bruto._asdict()
            else:
                flash(f"Nenhum fechamento encontrado para a competência {mes_consulta:02d}/{ano_consulta}.", "info")

        ultima_leitura_registrada = db.execute(text("""
            SELECT leitura_atual_master FROM fechamentos ORDER BY ano_competencia DESC, mes_competencia DESC LIMIT 1
        """)).fetchone()
        
        is_primeiro_fechamento = ultima_leitura_registrada is None
        leitura_anterior_para_form = float(ultima_leitura_registrada[0]) if not is_primeiro_fechamento else 0

        # No final da função fechamento_mensal, substitua o 'return' por este:

    return render_template(
    'fechamento_mensal.html',
    leitura_anterior_criar=leitura_anterior_para_form,
    is_primeiro_fechamento=is_primeiro_fechamento,
    resultado=resultado,
    ano_atual=datetime.now().year,
    mes_atual=datetime.now().month,
    # --- LINHAS ADICIONADAS/CORRIGIDAS ---
    mes_consulta_selecionado=mes_consulta,
    ano_consulta_selecionado=(ano_consulta or datetime.now().year)
)

# --- NOVO: COMANDO PARA INICIAR O BANCO DE DADOS (VERSÃO CORRIGIDA) ---
@app.cli.command("init-admin")
def init_admin_command():
    """Cria o primeiro usuário administrador se não existir."""
    try:
        db = get_db()
        print("--- Verificando a existência de um usuário admin...")
        
        # Fazendo tudo dentro de uma única "conversa" (transação) com o banco
        with db.begin(): 
            admin_exists = db.execute(text("SELECT id FROM usuarios_admin WHERE papel = :papel"), {'papel': 'admin'}).fetchone()
    
            if not admin_exists:
                print("--- Nenhum admin encontrado. Criando o primeiro usuário...")
                # --- Personalize seus dados aqui ---
                primeiro_user = 'admin' 
                primeira_senha = 'admin' 
                primeiro_email = 'vivendamirassol@gmail.com'
                # ------------------------------------
                
                senha_hash = generate_password_hash(primeira_senha)
                
                db.execute(text("""
                    INSERT INTO usuarios_admin (username, senha_hash, email, papel) 
                    VALUES (:username, :senha_hash, :email, :papel)
                """), {
                    'username': primeiro_user, 
                    'senha_hash': senha_hash, 
                    'email': primeiro_email, 
                    'papel': 'admin'
                })
                
                print(">>> SUCESSO: Primeiro usuário admin criado!")
            else:
                print("--- Usuário admin já existe. Nenhuma ação necessária.")
    except Exception as e:
        print(f"Ocorreu um erro: {e}")
    finally:
        # Garante que a conexão com o banco seja fechada
        close_db(None)

        # --- NOVO: COMANDO PARA LIMPAR DADOS DE TESTE ---
@app.cli.command("clear-data")
def clear_data_command():
    """Apaga todos os dados de consumidores, leituras, pagamentos, etc., mas MANTÉM os usuários."""
    print("--- ATENÇÃO: Esta operação é IRREVERSÍVEL. ---")
    # Pede uma confirmação dupla para evitar acidentes
    confirmacao = input(">>> Você tem certeza que deseja apagar TODOS os dados (exceto usuários)? (s/n): ")
    
    if confirmacao.lower() != 's':
        print("Operação cancelada.")
        return

    try:
        db = get_db()
        # O comando TRUNCATE é a forma mais eficiente de limpar tabelas no PostgreSQL.
        # RESTART IDENTITY reinicia os contadores de ID.
        # CASCADE remove registros em tabelas relacionadas que dependem destes dados.
        query = text("""
            TRUNCATE TABLE 
                configuracoes, 
                consumidores, 
                despesas, 
                leituras, 
                pagamentos
            RESTART IDENTITY CASCADE;
        """)

        with db.begin(): # Garante que a operação seja executada com segurança
            print(">>> Limpando tabelas: configuracoes, consumidores, despesas, leituras, pagamentos...")
            db.execute(query)
            print(">>> SUCESSO: Todos os dados de teste foram removidos.")
            print(">>> A tabela 'usuarios_admin' não foi alterada.")

    except Exception as e:
        print(f"\nOcorreu um erro ao tentar limpar o banco de dados: {e}")
    finally:
        # Garante que a conexão com o banco seja fechada
        close_db(None)

# --- Inicialização da Aplicação ---
if __name__ == '__main__':
    # Cria a pasta de uploads se não existir
    if not os.path.exists(app.config['UPLOAD_FOLDER']):
        os.makedirs(app.config['UPLOAD_FOLDER'])

    #-----init_db()---descomentar apenas se for recriar o banco de dados----

     # Rodar a aplicação em modo debug para desenvolvimento
    app.run(debug=True)    
   