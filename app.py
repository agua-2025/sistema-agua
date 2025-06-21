print("--- EXECUTANDO A VERSÃO MAIS RECENTE DO APP.PY ---")
from flask import Flask, render_template, request, redirect, url_for, session, g, jsonify, flash, make_response, send_file
#import sqlite3
from werkzeug.security import check_password_hash, generate_password_hash
import os
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta, date # Garante que date e datetime estão aqui
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
    try:
        dt_obj = datetime.strptime(str(value), '%Y-%m-%d %H:%M:%S.%f')
    except ValueError:
        try:
            dt_obj = datetime.strptime(str(value), '%Y-%m-%d')
        except ValueError:
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
        
        # 1. Total de Consumidores
        total_consumidores = db.execute(text('SELECT COUNT(id) FROM consumidores')).fetchone()[0]
        
        # 2. Total de Usuários
        try:
            total_usuarios = db.execute(text('SELECT COUNT(id) FROM usuarios_admin')).fetchone()[0]
        except sqlite3.OperationalError:
            app.logger.error("A tabela 'usuarios_admin' não foi encontrada. Verifique se o nome está correto.")
            total_usuarios = 'Erro' # Indica um erro no card
        
        # 3. Pagamentos feitos hoje
        hoje = date.today().strftime('%Y-%m-%d')
        pagamentos_hoje = db.execute(text('SELECT COUNT(id) FROM pagamentos WHERE data_pagamento = :data'), {'data': hoje}).fetchone()[0]
        
        # 4. Total de Faturas Pendentes (Inadimplência) - LÓGICA REFINADA
        # Esta query é otimizada para contar precisamente as faturas com saldo devedor.
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
            total_consumidores=total_consumidores,
            total_usuarios=total_usuarios,
            pagamentos_hoje=pagamentos_hoje,
            faturas_pendentes=faturas_pendentes
        )
    except Exception as e:
        app.logger.error(f"Erro ao carregar o dashboard: {e}", exc_info=True)
        flash("Ocorreu um erro ao carregar os dados do painel. Tente novamente.", "danger")
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
@login_required 
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

# --- CRUD Consumidores (VERSÃO CORRIGIDA) ---
@app.route('/cadastrar-consumidor', methods=['GET', 'POST'])
@login_required
def cadastrar_consumidor():
    error = None
    if request.method == 'POST':
        nome = request.form['nome']
        cpf = request.form['cpf']
        rg = request.form['rg']
        endereco = request.form['endereco']
        telefone = request.form['telefone']
        hidrometro_num = request.form['hidrometro']
        
        try:
            db = get_db()
            with db.begin():  # Garante que a operação seja salva ou desfeita com segurança
                db.execute(text("""
                    INSERT INTO consumidores (nome, cpf, rg, endereco, telefone, hidrometro_num)
                    VALUES (:nome, :cpf, :rg, :endereco, :telefone, :hidrometro_num)
                """), {
                    'nome': nome, 'cpf': cpf, 'rg': rg, 'endereco': endereco, 
                    'telefone': telefone, 'hidrometro_num': hidrometro_num
                })
            
            flash('Consumidor cadastrado com sucesso!', 'success')
            return redirect(url_for('listar_consumidores'))

        except IntegrityError:  # Usando o novo tipo de erro que importamos
            error = "CPF ou número do hidrômetro já cadastrado. Verifique os dados e tente novamente."
            flash(error, 'danger')
            
        except Exception as e:
            error = f"Erro ao cadastrar consumidor: {str(e)}"
            flash(error, 'danger')
            
    return render_template('cadastrar_consumidor.html', error=error)

# (Certifique-se de que tem estes imports no topo do seu app.py)
from datetime import date
from flask import render_template, flash, redirect, url_for
# ... e outros imports que você usa

# (Certifique-se que 'date', 'flash', 'redirect', 'url_for' etc. estão importados)

# --- Listar Pagamentos (VERSÃO FINAL E CORRIGIDA) ---
@app.route('/listar-pagamentos')
@login_required
def listar_pagamentos():
    try:
        db = get_db()
        
        page = request.args.get('page', 1, type=int)
        mes_filtro = request.args.get('mes', '')
        ano_filtro = request.args.get('ano', '')
        
        PER_PAGE = 20
        offset = (page - 1) * PER_PAGE
        
        base_query = "FROM pagamentos p JOIN consumidores c ON p.consumidor_id = c.id"
        conditions = []
        params = {}
        
        # CORREÇÃO: Usando TO_CHAR para ser compatível com PostgreSQL
        if mes_filtro:
            conditions.append("TO_CHAR(p.data_pagamento, 'MM') = :mes")
            params['mes'] = mes_filtro.zfill(2)
        if ano_filtro:
            conditions.append("TO_CHAR(p.data_pagamento, 'YYYY') = :ano")
            params['ano'] = ano_filtro
        
        where_clause = ""
        if conditions:
            where_clause = " WHERE " + " AND ".join(conditions)
        
        # Busca o total de itens para a paginação
        summary_query = f"SELECT COUNT(p.id), COALESCE(SUM(p.valor_pago), 0) {base_query} {where_clause}"
        params_summary = {k: v for k, v in params.items() if k not in ['limit', 'offset']}
        total_pagamentos_periodo, valor_arrecadado_periodo = db.execute(text(summary_query), params_summary).fetchone()

        # Busca os dados da página atual
        data_query = f"SELECT p.*, c.nome {base_query} {where_clause} ORDER BY p.data_pagamento DESC, p.id DESC LIMIT :limit OFFSET :offset"
        params['limit'] = PER_PAGE
        params['offset'] = offset
        pagamentos_brutos = db.execute(text(data_query), params).fetchall()

        # --- CORREÇÃO IMPORTANTE AQUI ---
        # Converte os resultados para uma lista de dicionários
        # e garante que a data seja uma string para o template não quebrar
        pagamentos_formatados = []
        for p_bruto in pagamentos_brutos:
            p_dict = p_bruto._asdict()
            # Converte o objeto de data em texto no formato 'AAAA-MM-DD'
            if isinstance(p_dict.get('data_pagamento'), date):
                p_dict['data_pagamento'] = p_dict['data_pagamento'].strftime('%Y-%m-%d')
            pagamentos_formatados.append(p_dict)

        # Configura a paginação
        total_pages = math.ceil(total_pagamentos_periodo / PER_PAGE) if total_pagamentos_periodo > 0 else 1
        pagination = {
            "page": page, "total_pages": total_pages,
            "has_prev": page > 1, "has_next": page < total_pages
        }

        # Envia os dados corrigidos para a página
        return render_template(
            'listar_pagamentos.html', 
            pagamentos=pagamentos_formatados, # Passando a lista formatada
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


@app.route('/listar-consumidores')
@login_required
def listar_consumidores():
    db = get_db()
    consumidores = db.execute(text("SELECT * FROM consumidores")).fetchall()
    return render_template('consumidores.html', consumidores=consumidores)


# ------------------Cadastrar Leitura----------------:
# Em app.py, substitua a função cadastrar_leitura por esta:

@app.route('/cadastrar-leitura', methods=['GET', 'POST'])
@login_required
def cadastrar_leitura():
    db = get_db()
    if request.method == 'POST':
        # A lógica de POST (salvamento) continua a mesma que corrigimos antes
        try:
            consumidor_id = int(request.form.get('consumidor_id'))
            leitura_atual = int(parse_number_from_br_form(request.form.get('leitura_atual')))
            data_leitura_obj = datetime.strptime(request.form.get('data_leitura_atual'), '%Y-%m-%d').date()
            foto_salva = None
            if 'foto_hidrometro' in request.files:
                foto = request.files['foto_hidrometro']
                if foto and foto.filename != '' and allowed_file(foto.filename):
                    filename = secure_filename(foto.filename)
                    novo_nome = str(int(datetime.now().timestamp())) + "_" + filename
                    caminho_salvo = os.path.join(app.config['UPLOAD_FOLDER'], novo_nome)
                    foto.save(caminho_salvo)
                    foto_salva = novo_nome
            with db.begin():
                leitura_anterior_db = db.execute(text("SELECT id, leitura_atual, data_leitura_atual FROM leituras WHERE consumidor_id = :cid ORDER BY data_leitura_atual DESC, id DESC LIMIT 1"), {'cid': consumidor_id}).fetchone()
                config = get_current_config()
                consumo_m3 = 0
                valor_original = None
                data_vencimento = None
                leitura_anterior_valor = 0
                data_leitura_anterior_obj = None
                if not leitura_anterior_db:
                    pass
                else:
                    leitura_anterior_valor = int(leitura_anterior_db.leitura_atual)
                    data_leitura_anterior_obj = leitura_anterior_db.data_leitura_atual
                    if leitura_atual < leitura_anterior_valor:
                        raise ValueError('Leitura atual não pode ser menor que a anterior.')
                    consumo_m3 = leitura_atual - leitura_anterior_valor
                    valor_original = 0.0
                    taxa_minima_valor = float(config.get('taxa_minima_consumo', 0.0))
                    taxa_minima_franquia = float(config.get('taxa_minima_franquia_m3', 10.0))
                    valor_m3_configurado = float(config.get('valor_m3', 0.0))
                    if consumo_m3 <= taxa_minima_franquia:
                        valor_original = taxa_minima_valor
                    else:
                        consumo_excedente = consumo_m3 - taxa_minima_franquia
                        valor_excedente = consumo_excedente * valor_m3_configurado
                        valor_original = taxa_minima_valor + valor_excedente
                    dias_para_vencimento = int(config.get('dias_uteis_para_vencimento', 5))
                    data_vencimento = adicionar_dias_uteis(data_leitura_obj, dias_para_vencimento)
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
                    'val_orig': valor_original, 'venc': data_vencimento, 'foto': foto_salva,
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
    
    else: # Lógica GET (carregar a página)
        consumidores = db.execute(text('SELECT id, nome FROM consumidores ORDER BY nome')).fetchall()
        consumidor_selecionado = request.args.get('consumidor_id', type=int)
        leitura_anterior_valor = '0'
        data_leitura_anterior_str = 'N/A'
        data_leitura_anterior_iso = None # <-- Inicia como None

        if consumidor_selecionado:
            ultima_leitura = db.execute(text("SELECT leitura_atual, data_leitura_atual FROM leituras WHERE consumidor_id = :cid ORDER BY data_leitura_atual DESC, id DESC LIMIT 1"), {'cid': consumidor_selecionado}).fetchone()
            if ultima_leitura:
                leitura_anterior_valor = str(int(ultima_leitura.leitura_atual))
                data_leitura_anterior_str = ultima_leitura.data_leitura_atual.strftime('%d/%m/%Y')
                data_leitura_anterior_iso = ultima_leitura.data_leitura_atual.isoformat() # <-- Define o valor se existir

        return render_template('cadastrar_leitura.html', 
                               consumidores=consumidores, 
                               consumidor_selecionado=consumidor_selecionado,
                               leitura_anterior=leitura_anterior_valor,
                               data_leitura_anterior=data_leitura_anterior_str,
                               data_leitura_anterior_iso=data_leitura_anterior_iso, # <-- Variável enviada
                               today_date=date.today().isoformat())
    
# --- Registrar Pagamento (AGORA COM A LÓGICA WHATSAPP EMBUTIDA) ---
@app.route('/registrar-pagamento', methods=['GET', 'POST'])
@login_required
def registrar_pagamento():
    db = get_db()
    
    # --- Lógica para POST (salvar o pagamento) ---
    if request.method == 'POST':
        try:
            # Coleta de dados do formulário
            consumidor_id = request.form['consumidor_id']
            leitura_id = request.form['leitura_id']
            data_pagamento_str = date.today().strftime('%Y-%m-%d')
            forma_pagamento = request.form['forma_pagamento']
            valor_pago = parse_number_from_br_form(request.form.get('valor_pago', '0'))

            if valor_pago <= 0:
                flash('O valor do pagamento deve ser maior que R$ 0,00.', 'warning')
                return redirect(url_for('registrar_pagamento'))

            # ABRIMOS A TRANSAÇÃO AQUI PARA ENVOLVER TODAS AS OPERAÇÕES
            with db.begin():
                resultado_bruto = db.execute(text('SELECT valor_original, vencimento FROM leituras WHERE id = :leitura_id'), {'leitura_id': leitura_id}).fetchone()
                leitura_selecionada = resultado_bruto._asdict() if resultado_bruto else None
                
                if not leitura_selecionada:
                    flash('Leitura selecionada é inválida.', 'error')
                    # Retornar aqui não causa problema, pois o 'with' gerencia o rollback
                    return redirect(url_for('registrar_pagamento'))

                config = get_current_config() # Esta função já usa get_db()
                valor_original_fatura = float(leitura_selecionada['valor_original'])
                data_vencimento = leitura_selecionada['vencimento']

                total_pago_acumulado_antes = db.execute(text("SELECT COALESCE(SUM(valor_pago), 0) FROM pagamentos WHERE leitura_id = :leitura_id"), {'leitura_id': leitura_id}).fetchone()[0]
                total_multa_acumulada_antes = db.execute(text("SELECT COALESCE(SUM(valor_multa), 0) FROM pagamentos WHERE leitura_id = :leitura_id"), {'leitura_id': leitura_id}).fetchone()[0]
                total_juros_acumulados_antes = db.execute(text("SELECT COALESCE(SUM(valor_juros), 0) FROM pagamentos WHERE leitura_id = :leitura_id"), {'leitura_id': leitura_id}).fetchone()[0]
                
                valor_base_antes = max(valor_original_fatura + total_multa_acumulada_antes + total_juros_acumulados_antes - total_pago_acumulado_antes, 0)

                multa_devida, juros_devido, dias_atraso = calcular_penalidades(
                    valor_original_fatura, valor_base_antes, data_vencimento,
                    data_pagamento_str, config['multa_percentual'], config['juros_diario_percentual']
                )

                multa_a_ser_paga = 0.0
                if dias_atraso > 0 and total_multa_acumulada_antes == 0:
                    multa_a_ser_paga = multa_devida

                total_corrigido = round(valor_base_antes + multa_a_ser_paga + juros_devido, 2)
                saldo_devedor = max(0, total_corrigido - valor_pago)
                saldo_credor = max(0, valor_pago - total_corrigido)

                db.execute(text('''
                    INSERT INTO pagamentos (
                        leitura_id, consumidor_id, data_pagamento, forma_pagamento, valor_pago, 
                        dias_atraso, valor_multa, valor_juros, total_corrigido, saldo_devedor, saldo_credor
                    ) VALUES (:leitura_id, :consumidor_id, :data_pagamento, :forma_pagamento, :valor_pago, :dias_atraso, :valor_multa, :valor_juros, :total_corrigido, :saldo_devedor, :saldo_credor)
                '''), {
                    'leitura_id': int(leitura_id), 'consumidor_id': int(consumidor_id), 'data_pagamento': data_pagamento_str, 
                    'forma_pagamento': forma_pagamento, 'valor_pago': valor_pago, 'dias_atraso': dias_atraso, 
                    'valor_multa': multa_a_ser_paga, 'valor_juros': juros_devido, 'total_corrigido': total_corrigido, 
                    'saldo_devedor': saldo_devedor, 'saldo_credor': saldo_credor
                })
            
            flash('Pagamento registrado com sucesso!', 'success')
            return redirect(url_for('listar_pagamentos'))

        except Exception as e:
            app.logger.error(f"Erro ao registrar pagamento: {e}", exc_info=True)
            flash('Erro ao registrar pagamento. Verifique os dados e tente novamente.', 'danger')
            return redirect(url_for('registrar_pagamento'))

    # --- Lógica para GET (carregar o formulário) ---
    else:
        consumidores = db.execute(text('SELECT id, nome FROM consumidores ORDER BY nome')).fetchall()
        return render_template('registrar_pagamento.html', consumidores=consumidores, leituras=[])


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

# Em app.py, substitua a função editar_leitura inteira por esta:

@app.route('/leitura/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def editar_leitura(id):
    db = get_db()
    
    try:
        # A TRANSAÇÃO COMEÇA AQUI, ENVOLVENDO TODAS AS OPERAÇÕES
        with db.begin():
            # TRAVA DE SEGURANÇA: Verifica se existe pagamento
            pagamento_existente = db.execute(
                text("SELECT id FROM pagamentos WHERE leitura_id = :id LIMIT 1"), {'id': id}
            ).fetchone()

            if pagamento_existente:
                flash("Não é possível editar esta leitura, pois já existem pagamentos registrados para ela.", "warning")
                # Importante: Como estamos dentro de uma transação, um simples return não vai funcionar.
                # Redirecionamos fora do bloco `try...except`
                # Para sair da função aqui, podemos levantar uma exceção customizada ou usar uma flag.
                # A forma mais simples é deixar a verificação e redirecionar depois.
                # No entanto, vamos reestruturar para ficar mais claro.
                pass # Deixa a verificação para depois do POST para não complicar o fluxo da transação.

            # LÓGICA PARA POST (SALVAR)
            if request.method == 'POST':
                if pagamento_existente: # Verifica de novo, agora dentro do contexto do POST
                    flash("Ação bloqueada: esta leitura já possui pagamentos.", "warning")
                    # Para forçar a saída da transação, levantamos um erro que será pego pelo except.
                    raise ValueError("Tentativa de editar leitura com pagamento.")

                nova_leitura_atual = parse_number_from_br_form(request.form['leitura_atual'])
                nova_data_leitura = request.form['data_leitura_atual']

                leitura_atual_db = db.execute(text("SELECT * FROM leituras WHERE id = :id"), {'id': id}).fetchone()
                if not leitura_atual_db:
                    flash('Leitura não encontrada.', 'danger')
                    raise ValueError("Leitura não encontrada para edição.")

                leitura_anterior_valor = float(leitura_atual_db.leitura_anterior)
                if nova_leitura_atual < leitura_anterior_valor:
                    flash('Erro: A nova leitura atual não pode ser menor que a leitura anterior.', 'danger')
                    raise ValueError("Leitura atual menor que a anterior.")

                # Lógica de recálculo (mantida)
                consumo_m3 = nova_leitura_atual - leitura_anterior_valor
                config = get_current_config()
                taxa_minima_valor_usada = float(leitura_atual_db.taxa_minima_valor_usada or config.get('taxa_minima_consumo'))
                taxa_minima_franquia_usada = float(leitura_atual_db.taxa_minima_franquia_usada or config.get('taxa_minima_franquia_m3'))
                valor_m3_usado = float(leitura_atual_db.valor_m3_usado or config.get('valor_m3'))
                
                valor_original_recalculado = 0.0
                # A primeira leitura informativa não tem valor, então não precisa de recálculo de valor.
                # Verificamos se a leitura original tinha um valor para recalcular.
                if leitura_atual_db.valor_original is not None:
                    if consumo_m3 <= taxa_minima_franquia_usada:
                        valor_original_recalculado = taxa_minima_valor_usada
                    else:
                        consumo_excedente = consumo_m3 - taxa_minima_franquia_usada
                        valor_excedente = consumo_excedente * valor_m3_usado
                        valor_original_recalculado = taxa_minima_valor_usada + valor_excedente
                else: # Se era uma leitura informativa, o valor continua nulo
                    valor_original_recalculado = None

                db.execute(text("""
                    UPDATE leituras
                    SET leitura_atual = :l_atu, data_leitura_atual = :d_atu,
                        consumo_m3 = :consumo, valor_original = :val_orig
                    WHERE id = :id
                """), {
                    'l_atu': nova_leitura_atual, 'd_atu': nova_data_leitura,
                    'consumo': consumo_m3, 'val_orig': valor_original_recalculado if valor_original_recalculado is not None else None,
                    'id': id
                })
                
                flash('Leitura atualizada com sucesso!', 'success')
                # O commit é feito automaticamente ao sair do bloco 'with' sem erros.
                return redirect(url_for('listar_leituras'))

            # LÓGICA PARA GET (CARREGAR A PÁGINA)
            else: 
                resultado_bruto = db.execute(text("""
                    SELECT l.*, c.nome as nome_consumidor
                    FROM leituras l JOIN consumidores c ON l.consumidor_id = c.id
                    WHERE l.id = :id
                """), {'id': id}).fetchone()
                
                if not resultado_bruto:
                    flash("Leitura não encontrada.", "danger")
                    return redirect(url_for('listar_leituras'))

                # Se a leitura tiver pagamento, exibe a mensagem de bloqueio na tela de edição
                if pagamento_existente:
                     flash("Esta leitura não pode ser editada pois já possui pagamentos associados.", "warning")

                return render_template('editar_leitura.html', leitura=resultado_bruto._asdict(), bloqueado=bool(pagamento_existente))

    except ValueError as e:
        # Erros "controlados" (como validações) redirecionam para a lista de leituras
        app.logger.warning(f"Erro de validação ao editar leitura ID {id}: {e}")
        return redirect(url_for('listar_leituras'))

    except Exception as e:
        # Erros inesperados do banco de dados
        flash('Ocorreu um erro inesperado ao processar sua solicitação.', 'danger')
        app.logger.error(f"Erro crítico ao editar leitura ID {id}: {e}", exc_info=True)
        return redirect(url_for('listar_leituras'))
    
#------------------------Excluir Leitura----------------------------    
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

# --- API para retornar leituras pendentes (VERSÃO COM TRADUÇÃO MANUAL) ---
@app.route('/api/leituras/<int:consumidor_id>')
@login_required
def api_leituras(consumidor_id):
    if 'usuario' not in session:
        return jsonify({'erro': 'Não autorizado'}), 401

    db = get_db()
    config = get_current_config()
    if not config:
        app.logger.error("Configurações de cálculo não foram encontradas.")
        return jsonify({'erro': 'Erro de configuração interna.'}), 500

    try:
        leituras_brutas = db.execute(text('''
            SELECT
                l.id, l.data_leitura_atual, l.vencimento, l.valor_original,
                l.data_leitura_anterior,
                COALESCE(SUM(p.valor_pago), 0) AS total_pago_acumulado,
                COALESCE(SUM(p.valor_multa), 0) AS total_multa_acumulada,
                COALESCE(SUM(p.valor_juros), 0) AS total_juros_acumulados
            FROM leituras l
            LEFT JOIN pagamentos p ON p.leitura_id = l.id
            WHERE l.consumidor_id = :cid
            GROUP BY l.id
            HAVING (l.valor_original + COALESCE(SUM(p.valor_multa), 0) + COALESCE(SUM(p.valor_juros), 0) - COALESCE(SUM(p.valor_pago), 0)) > 0.001
            ORDER BY l.data_leitura_atual DESC
        '''), {'cid': consumidor_id}).fetchall()

        hoje = date.today().strftime('%Y-%m-%d')
        resultado_final = []

        for l_bruto in leituras_brutas:
            l = l_bruto._asdict()
            try:
                valor_original_da_fatura = float(l['valor_original'])
                total_pago_acumulado = float(l['total_pago_acumulado'])
                total_multa_acumulada = float(l['total_multa_acumulada'])
                total_juros_acumulados = float(l['total_juros_acumulados'])

                valor_base_para_novas_penalidades = max(
                    valor_original_da_fatura + total_multa_acumulada + total_juros_acumulados - total_pago_acumulado, 0
                )
                
                multa_calculada_potencial, juros_calculado_agora, dias_atraso = calcular_penalidades(
                    valor_original_da_fatura, valor_base_para_novas_penalidades, l['vencimento'],
                    hoje, config['multa_percentual'], config['juros_diario_percentual']
                )

                multa_para_exibir_agora = 0.0
                if dias_atraso > 0 and total_multa_acumulada == 0:
                    multa_para_exibir_agora = multa_calculada_potencial
                
                valor_corrigido_total = round(valor_base_para_novas_penalidades + multa_para_exibir_agora + juros_calculado_agora, 2)

                dados_da_leitura = {
                    'id': l['id'], 
                    'data_leitura_atual': l['data_leitura_atual'],
                    'vencimento': l['vencimento'], 
                    'valor_original_da_fatura': round(valor_original_da_fatura, 2),
                    'total_pago_acumulado': round(total_pago_acumulado, 2),
                    'valor_base_para_novas_penalidades': round(valor_base_para_novas_penalidades, 2),
                    'valor_corrigido_total_para_proximo_pagamento': valor_corrigido_total,
                    'dias_atraso': dias_atraso, 
                    'multa_calculada_agora': round(multa_para_exibir_agora, 2),
                    'juros_calculado_agora': round(juros_calculado_agora, 2),
                    'data_leitura_anterior': l['data_leitura_anterior']
                }

                # Tradução manual das datas para um formato que o JavaScript entende
                if isinstance(dados_da_leitura['data_leitura_atual'], date):
                    dados_da_leitura['data_leitura_atual'] = dados_da_leitura['data_leitura_atual'].isoformat()
                if isinstance(dados_da_leitura['vencimento'], date):
                    dados_da_leitura['vencimento'] = dados_da_leitura['vencimento'].isoformat()
                
                resultado_final.append(dados_da_leitura)

            except Exception as e_loop:
                app.logger.warning(f"Erro processando leitura {l.get('id', 'N/A')}: {str(e_loop)}")
                continue

        return jsonify(resultado_final)

    except Exception as e:
        app.logger.error(f"Erro ao buscar leituras via API: {str(e)}", exc_info=True)
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

# --- Editar Consumidor (VERSÃO CORRIGIDA) ---
@app.route('/editar-consumidor/<int:id>', methods=['GET', 'POST'])
@login_required
def editar_consumidor(id):
    db = get_db()
    
    if request.method == 'POST':
        nome = request.form['nome']
        cpf = request.form['cpf']
        rg = request.form['rg']
        endereco = request.form['endereco']
        telefone = request.form['telefone']
        hidrometro_num = request.form['hidrometro']

        try:
            with db.begin(): # Garante a transação segura
                db.execute(text("""
                    UPDATE consumidores 
                    SET nome = :nome, cpf = :cpf, rg = :rg, endereco = :endereco, telefone = :telefone, hidrometro_num = :hidrometro_num 
                    WHERE id = :id
                """), {
                    'nome': nome, 'cpf': cpf, 'rg': rg, 'endereco': endereco, 
                    'telefone': telefone, 'hidrometro_num': hidrometro_num, 'id': id
                })
            
            flash("Dados atualizados com sucesso!", "success")
            return redirect(url_for('listar_consumidores'))
        except IntegrityError:
            flash("CPF ou número do hidrômetro já cadastrado para outro consumidor.", "danger")
        except Exception as e:
            app.logger.error(f"Erro ao editar consumidor: {str(e)}", exc_info=True)
            flash(f"Erro ao editar o consumidor: {str(e)}", "danger")
        
        # Em caso de erro, recarrega os dados para exibir o formulário novamente
        resultado_bruto = db.execute(text("SELECT * FROM consumidores WHERE id = :id"), {'id': id}).fetchone()
        consumidor = resultado_bruto._asdict() if resultado_bruto else None
        return render_template('editar_consumidor.html', consumidor=consumidor)

    # --- Lógica para GET (carregar a página de edição) ---
    else:
        resultado_bruto = db.execute(text("SELECT * FROM consumidores WHERE id = :id"), {'id': id}).fetchone()
        
        if not resultado_bruto:
            flash("Consumidor não encontrado.", "error")
            return redirect(url_for('listar_consumidores'))

        # Converte o resultado para dicionário antes de enviar para o template
        consumidor = resultado_bruto._asdict()
        return render_template('editar_consumidor.html', consumidor=consumidor)


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

# Adicione estes imports no topo do seu arquivo app.py
from flask import Response
from weasyprint import HTML
from urllib.parse import quote
# Garanta que estes também estão presentes
from datetime import date, datetime
# Seus outros imports...


#----------------- Get_Fatura_Contexto------------
# Em app.py, substitua a função _get_fatura_contexto inteira por esta versão final:

def _get_fatura_contexto(leitura_id):
    """
    Busca e calcula todos os dados para um extrato de fatura/comprovante.
    VERSÃO FINAL: Robusta para lidar com leituras informativas (valores nulos).
    """
    db = get_db()
    
    resultado_bruto = db.execute(text('''
        SELECT l.*, c.nome AS consumidor_nome, c.endereco AS consumidor_endereco, c.hidrometro_num AS hidrometro, c.telefone 
        FROM leituras l JOIN consumidores c ON l.consumidor_id = c.id
        WHERE l.id = :id
    '''), {'id': leitura_id}).fetchone()

    if not resultado_bruto: return None
    leitura_data = resultado_bruto._asdict()

    pagamentos_feitos = [p._asdict() for p in db.execute(text("SELECT * FROM pagamentos WHERE leitura_id = :id ORDER BY data_pagamento ASC"), {'id': leitura_id}).fetchall()]
    
    consumo_m3 = int(safe_float(leitura_data.get('consumo_m3')))
    data_leitura_anterior_obj = leitura_data.get('data_leitura_anterior')
    
    dias_no_periodo = 0
    if data_leitura_anterior_obj and leitura_data.get('data_leitura_atual'):
        dias_no_periodo = (leitura_data['data_leitura_atual'] - data_leitura_anterior_obj).days

    media_diaria_consumo = (consumo_m3 / dias_no_periodo) if dias_no_periodo > 0 else 0.0

    detalhamento_fatura = []
    # Apenas tenta detalhar a fatura se ela tiver um valor original
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
    
    historico_bruto_rows = db.execute(text('''
        SELECT TO_CHAR(data_leitura_atual, 'MM/YYYY') AS mes_ano, SUM(consumo_m3) AS consumo_total
        FROM leituras WHERE consumidor_id = :cid
        GROUP BY TO_CHAR(data_leitura_atual, 'YYYY-MM'), TO_CHAR(data_leitura_atual, 'MM/YYYY')
        ORDER BY TO_CHAR(data_leitura_atual, 'YYYY-MM') DESC LIMIT 6
    '''), {'cid': leitura_data['consumidor_id']}).fetchall()
    
    historico_dicts = [row._asdict() for row in historico_bruto_rows]
    historico_dicts.reverse()
    
    # AQUI ESTÁ A CORREÇÃO PRINCIPAL:
    vencimento_obj = leitura_data.get('vencimento')

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
        'vencimento_formatado': vencimento_obj.strftime('%d/%m/%Y') if vencimento_obj else 'N/A', # <-- LÓGICA CORRIGIDA
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
    if not foto_filename:
        return None
    foto_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'fotos_hidrometros', foto_filename)
    if os.path.exists(foto_path):
        with open(foto_path, "rb") as image_file:
            encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
            mime_type = guess_type(foto_path)[0] or 'image/jpeg'
            return f"data:{mime_type};base64,{encoded_string}"
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

# --- Relatório de Consumidores (VERSÃO CORRIGIDA PARA POSTGRESQL) ---
@app.route('/relatorio-consumidores')
@login_required
def relatorio_consumidores():
    try:
        db = get_db()
        mes_filtro = request.args.get('mes')
        ano_filtro = request.args.get('ano')
        ano_atual = datetime.now().year

        # Define o período atual como padrão se nenhum filtro for aplicado
        if not mes_filtro and not ano_filtro:
            mes_filtro = datetime.now().strftime('%m')
            ano_filtro = str(ano_atual)

        # Permite que o usuário selecione "Todos" os meses
        if mes_filtro and mes_filtro.lower() == 'todos':
            mes_filtro = None

        # --- NOVA LÓGICA DA CONSULTA ---
        # 1. Encontra a última leitura de CADA consumidor, sem filtro de data inicial.
        # 2. Junta os dados de pagamento para essa última leitura.
        # 3. Aplica o filtro de Mês/Ano no resultado final.
        query = """
            WITH UltimaLeitura AS (
                SELECT consumidor_id, MAX(id) as ultima_leitura_id
                FROM leituras
                GROUP BY consumidor_id
            ),
            PagamentosAgregados AS (
                SELECT 
                    leitura_id, 
                    SUM(valor_pago) as total_pago,
                    SUM(valor_multa) as total_multa,
                    SUM(valor_juros) as total_juros
                FROM pagamentos
                GROUP BY leitura_id
            )
            SELECT 
                c.id AS consumidor_id, c.nome, c.cpf, c.endereco, c.telefone, c.hidrometro_num,
                l.leitura_anterior, l.leitura_atual, l.data_leitura_atual, l.foto_hidrometro,
                CASE
                    WHEN l.id IS NULL THEN 'Sem Leitura'
                    WHEN COALESCE(pa.total_pago, 0) >= (l.valor_original + COALESCE(pa.total_multa, 0) + COALESCE(pa.total_juros, 0)) THEN 'Pago'
                    ELSE 'Pendente'
                END as status_pagamento
            FROM consumidores c
            LEFT JOIN UltimaLeitura ul ON c.id = ul.consumidor_id
            LEFT JOIN leituras l ON ul.ultima_leitura_id = l.id
            LEFT JOIN PagamentosAgregados pa ON l.id = pa.leitura_id
        """

        conditions = []
        params = {}
        # Adiciona filtros se eles existirem
        if mes_filtro:
            conditions.append("TO_CHAR(l.data_leitura_atual, 'MM') = :mes_filtro")
            params['mes_filtro'] = mes_filtro.zfill(2)
        if ano_filtro:
            conditions.append("TO_CHAR(l.data_leitura_atual, 'YYYY') = :ano_filtro")
            params['ano_filtro'] = ano_filtro
        
        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY c.nome"

        consumidores_brutos = db.execute(text(query), params).fetchall()
        consumidores = [c._asdict() for c in consumidores_brutos]

        total_consumidores_geral = db.execute(text("SELECT COUNT(id) FROM consumidores")).fetchone()[0]
        consumidores_com_leituras = sum(1 for c in consumidores if c['data_leitura_atual'] is not None)

        return render_template(
            'relatorio_consumidores.html',
            consumidores=consumidores,
            mes_filtro=mes_filtro if mes_filtro else 'Todos',
            ano_filtro=ano_filtro,
            ano_atual=ano_atual,
            total_consumidores=total_consumidores_geral,
            consumidores_com_leituras=consumidores_com_leituras
        )

    except Exception as e:
        app.logger.error(f"Erro no relatório de consumidores: {str(e)}", exc_info=True)
        flash("Ocorreu um erro ao gerar o relatório de consumidores.", "danger")
        return redirect(url_for('dashboard'))


# --- Listar Leituras (VERSÃO FINAL E CORRIGIDA PARA POSTGRESQL) ---
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
        
        # CONSULTA ATUALIZADA: Agora ela conta quantos pagamentos cada leitura tem (COUNT(p.id))
        data_query = """
            SELECT 
                l.*, 
                c.nome as nome_consumidor,
                (l.leitura_atual - l.leitura_anterior) AS litros_consumidos,
                CASE
                    WHEN (l.data_leitura_atual::date - l.data_leitura_anterior::date) > 0
                    THEN CAST((l.leitura_atual - l.leitura_anterior) AS REAL) / (l.data_leitura_atual::date - l.data_leitura_anterior::date)
                    ELSE 0
                END AS media_por_dia,
                COUNT(p.id) as num_pagamentos
            FROM leituras l
            JOIN consumidores c ON l.consumidor_id = c.id
            LEFT JOIN pagamentos p ON l.id = p.leitura_id
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
        
        # Adiciona o agrupamento necessário por causa da contagem (COUNT)
        group_by_clause = " GROUP BY l.id, c.id"

        count_query = "SELECT COUNT(DISTINCT l.id) FROM leituras l " + where_clause
        data_query += where_clause + group_by_clause + " ORDER BY l.data_leitura_atual DESC, l.id DESC LIMIT :limit OFFSET :offset"
        
        params['limit'] = PER_PAGE
        params['offset'] = offset
        
        total_items_params = {k: v for k, v in params.items() if k not in ['limit', 'offset']}
        
        total_items = db.execute(text(count_query), total_items_params).fetchone()[0]
        leituras_brutas = db.execute(text(data_query), params).fetchall()
        
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

# --- Relatório Geral (VERSÃO COMPLETA E CORRIGIDA) ---
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

        # 4. Total de Consumidores
        total_consumidores = db.execute(text("SELECT COUNT(id) FROM consumidores")).fetchone()[0]

        # 5. Total de Faturas Pendentes
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

        # 6. Consumo Total de Água no Mês (AQUI ESTÁ A CORREÇÃO PRINCIPAL)
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
            'total_consumidores': total_consumidores,
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
        # Esta consulta busca todos os comprovantes que tiveram ao menos um pagamento
        leituras_brutas = db.execute(text('''
            SELECT DISTINCT l.id, l.data_leitura_atual, l.valor_original, c.nome AS consumidor_nome
            FROM leituras l
            JOIN pagamentos p ON l.id = p.leitura_id
            JOIN consumidores c ON l.consumidor_id = c.id
            ORDER BY l.data_leitura_atual DESC
        ''')).fetchall()
        
        # Converte cada linha do resultado em um dicionário que o template HTML entende
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


# --- Relatório de Inadimplência (VERSÃO FINAL E CORRIGIDA) ---
@app.route('/relatorio-inadimplencia')
@login_required
def relatorio_inadimplencia():
    try:
        db = get_db()
        config = get_current_config() 
        hoje = date.today().strftime('%Y-%m-%d')
        hoje_obj = date.today()

        faturas_raw = db.execute(text('''
            SELECT 
                l.id AS leitura_id,
                c.nome AS consumidor,
                c.endereco,
                c.telefone,
                l.data_leitura_atual,
                l.vencimento,
                l.valor_original,
                COALESCE((SELECT SUM(p.valor_pago) FROM pagamentos p WHERE p.leitura_id = l.id), 0) AS total_pago_acumulado,
                COALESCE((SELECT SUM(p.valor_multa) FROM pagamentos p WHERE p.leitura_id = l.id), 0) AS total_multa_acumulada,
                COALESCE((SELECT SUM(p.valor_juros) FROM pagamentos p WHERE p.leitura_id = l.id), 0) AS total_juros_acumulados
            FROM leituras l
            JOIN consumidores c ON l.consumidor_id = c.id
            ORDER BY l.vencimento ASC
        ''')).fetchall()
        
        pendencias_calculadas = []
        total_pendente_geral = 0.0
        total_atualizado_geral = 0.0

        for p_bruto in faturas_raw:
            p_raw = p_bruto._asdict()
            try:
                valor_original_da_fatura = float(p_raw['valor_original'])
                total_pago_acumulado = float(p_raw['total_pago_acumulado'])
                total_multa_acumulada = float(p_raw['total_multa_acumulada'])
                total_juros_acumulados = float(p_raw['total_juros_acumulados'])

                valor_pendente = (valor_original_da_fatura + total_multa_acumulada + total_juros_acumulados) - total_pago_acumulado

                if valor_pendente > 0.01:
                    vencimento_data = p_raw['vencimento']
                    if not vencimento_data:
                        continue

                    multa_calculada_potencial, juros_calc, dias_atraso = calcular_penalidades(
                        valor_original_da_fatura,
                        valor_pendente,
                        vencimento_data,
                        hoje,
                        config['multa_percentual'],
                        config['juros_diario_percentual']
                    )
                    
                    multa_para_exibir_agora = 0.0
                    if dias_atraso > 0 and total_multa_acumulada == 0:
                        multa_para_exibir_agora = multa_calculada_potencial

                    valor_atualizado = round(valor_pendente + multa_para_exibir_agora + juros_calc, 2)
                    
                    is_vencido = vencimento_data < hoje_obj

                    # --- CORREÇÃO APLICADA AQUI ---
                    # Convertendo as datas para texto ANTES de enviar para o template
                    pendencias_calculadas.append({
                        'consumidor': p_raw['consumidor'],
                        'endereco': p_raw['endereco'],
                        'telefone': p_raw['telefone'],
                        'data_leitura_atual': p_raw['data_leitura_atual'].strftime('%Y-%m-%d') if p_raw['data_leitura_atual'] else 'N/A',
                        'vencimento': vencimento_data.strftime('%Y-%m-%d') if vencimento_data else 'N/A',
                        'valor_original': valor_original_da_fatura,
                        'total_pago': total_pago_acumulado,
                        'valor_pendente': valor_pendente, 
                        'valor_atualizado': valor_atualizado,
                        'is_vencido': is_vencido
                    })
                    
                    total_pendente_geral += valor_pendente 
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


@app.route('/excluir-despesa/<int:id>')
@login_required
def excluir_despesa(id):
    db = get_db()
    try:
        db.execute(text("DELETE FROM despesas WHERE id = ?"), (id,))
        db.commit()
        flash("Despesa excluída com sucesso!", "success")
    except Exception as e:
        db.rollback()
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
   