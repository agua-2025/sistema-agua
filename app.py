from flask import Flask, render_template, request, redirect, url_for, session, g, jsonify, flash, make_response, send_file, Response # Adicionado Response
import sqlite3
from werkzeug.security import check_password_hash, generate_password_hash
import os
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta, date # date e datetime importados
import secrets
import smtplib
from email.mime.text import MIMEText
from email.utils import formataddr
from functools import wraps
from urllib.parse import quote
import math
from weasyprint import HTML # Importado para gerar PDFs
import click
from flask.cli import with_appcontext

# --- Configurações da Aplicação ---
app = Flask(__name__)

# --- Adicionar filtro de data para Jinja2 ---
@app.template_filter('date_format')
def _jinja2_filter_date_format(value, fmt='%d/%m/%Y'):
    if not value: # Lida com valores nulos ou vazios
        return ""
    # Tenta converter de objeto datetime.date ou datetime.datetime
    if isinstance(value, (datetime, date)):
        return value.strftime(fmt)
    
    # Tenta parsear string do formato AAAA-MM-DD (comum de banco de dados)
    try:
        return datetime.strptime(str(value), '%Y-%m-%d').strftime(fmt)
    except ValueError:
        pass # Se não for AAAA-MM-DD, tenta outros formatos ou deixa passar

    # Se 'value' já for uma string no formato desejado ou não puder ser parseado, retorna como está.
    return str(value)

# Chave secreta deve ser lida de variável de ambiente em produção
app.secret_key = os.environ.get('SECRET_KEY', 'sua-chave-super-secreta-para-desenvolvimento')

DATABASE = 'a_g_santa_maria.db'

UPLOAD_FOLDER = 'static/fotos_hidrometros'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# --- Funções Auxiliares ---

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db

@click.command('init-db')
@with_appcontext
def init_db_command():
    """Limpa os dados existentes e cria novas tabelas."""
    init_db()
    click.echo('Banco de dados inicializado.')

# Esta linha registra o comando no Flask
app.cli.add_command(init_db_command)

@app.teardown_appcontext
def close_db(error):
    if 'db' in g:
        g.db.close()

# Função para inicializar o banco de dados (criar tabelas)
def init_db():
    with app.app_context():
        db = get_db()
        # Abre o arquivo schema.sql e executa os comandos SQL
        with app.open_resource('schema.sql', mode='r') as f:
            db.cursor().executescript(f.read())
        db.commit()
    print("Database initialized successfully from schema.sql.")

# Decorador para verificar se o usuário está logado
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'usuario' not in session:
            flash('Você precisa estar logado para acessar esta página.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Função auxiliar para obter as configurações mais recentes
def get_current_config():
    db = get_db()
    # Primeiro, tenta buscar a última configuração do banco de dados
    config = db.execute('''
        SELECT COALESCE(multa_percentual, 2.0) AS multa_percentual,
               COALESCE(juros_diario_percentual, 0.033) AS juros_diario_percentual,
               COALESCE(valor_litro, 0.0) AS valor_litro,
               COALESCE(taxa_minima_consumo, 0.0) AS taxa_minima_consumo,
               COALESCE(dias_uteis_para_vencimento, 5) AS dias_uteis_para_vencimento,
               COALESCE(hidr_geral_anterior, 0) AS hidr_geral_anterior,
               COALESCE(hidr_geral_atual, 0) AS hidr_geral_atual,
               COALESCE(data_ultima_config, DATE('now')) AS data_ultima_config, -- Usar data atual se não houver
               COALESCE(consumo_geral, 0) AS consumo_geral
        FROM configuracoes
        ORDER BY id DESC
        LIMIT 1
    ''').fetchone()
    
    # Se uma configuração foi encontrada no banco, converte para dicionário e retorna
    if config:
        return dict(config) 
    else:
        # Se NENHUMA configuração foi encontrada, retorna um dicionário com valores padrão
        return {
            'multa_percentual': 2.0,
            'juros_diario_percentual': 0.033,
            'valor_litro': 0.0,
            'taxa_minima_consumo': 0.0,
            'dias_uteis_para_vencimento': 5,
            'hidr_geral_anterior': 0,
            'hidr_geral_atual': 0,
            'data_ultima_config': date.today().strftime('%Y-%m-%d'), # Data de hoje formatada
            'consumo_geral': 0
        }

# Função auxiliar para calcular multa e juros
def calcular_penalidades(valor_original_fatura, valor_base_para_juros, vencimento_str, data_referencia_str, config_multa_percentual, config_juros_diario_percentual):
    multa = 0.0
    juros = 0.0
    dias_atraso = 0

    try:
        vencimento = datetime.strptime(vencimento_str, '%Y-%m-%d').date()
        data_referencia_dt = datetime.strptime(data_referencia_str, '%Y-%m-%d').date()
        dias_atraso = max((data_referencia_dt - vencimento).days, 0)
    except (ValueError, TypeError) as e:
        app.logger.warning(f"Erro ao parsear datas para cálculo de penalidades: {e}")
        dias_atraso = 0 

    if dias_atraso > 0:
        # Multa: Calculada UMA VEZ sobre o valor ORIGINAL da fatura.
        # Esta multa será sempre o valor X% do valor original da fatura se a mesma estiver em atraso.
        # Não se acumula em pagamentos parciais ou sobre juros/outras multas.
        # AQUI, calculamos o valor máximo da multa. Se ela já foi aplicada, veremos na rota.
        multa = round(valor_original_fatura * (config_multa_percentual / 100), 2)
        
        # Juros: sobre o valor_base_para_juros (que é o saldo atual para cálculo de penalidades,
        # podendo incluir a multa fixa e juros anteriores não pagos).
        juros = round(valor_base_para_juros * (config_juros_diario_percentual / 100) * dias_atraso, 2)
    
    return multa, juros, dias_atraso

# NOVA FUNÇÃO DE PARSE SEGURA - Substitui a antiga currency_to_float e outras
def parse_number_from_br_form(value_str):
    if not value_str:
        return 0.0
    
    # 1. Converte para string e remove espaços em branco no início/fim
    s_value = str(value_str).strip()
    
    # 2. Remove símbolos de moeda (Ex: R$) e espaços extras
    s_value = s_value.replace('R$', '').replace(' ', '')
    
    # 3. Lida com separadores de milhar (ponto) e decimal (vírgula) no formato BR.
    if ',' in s_value: # Se a string contém vírgula, ela é o separador decimal.
        s_value = s_value.replace('.', '') # Remove TODOS os pontos (são separadores de milhar)
        s_value = s_value.replace(',', '.') # Troca a vírgula pelo ponto decimal (agora só tem 1 ponto)
    # Se não tem vírgula, e tem ponto, assume que o ponto já é o decimal (Ex: "0.033")
    # ou que é um número inteiro (Ex: "1500"). Nada a fazer aqui.

    try:
        return float(s_value)
    except ValueError:
        app.logger.warning(f"Falha ao converter '{value_str}' (limpo para '{s_value}') para float. Retornando 0.0.")
        return 0.0

# As funções adicionar_dias_uteis e enviar_email permanecem inalteradas
def adicionar_dias_uteis(data_inicial, dias_uteis):
    dias_adicionados = 0
    data_final = data_inicial
    while dias_adicionados < dias_uteis:
        data_final += timedelta(days=1)
        if data_final.weekday() < 5:  # segunda a sexta (0=segunda, 4=sexta)
            dias_adicionados += 1
    return data_final

def enviar_email(destino, assunto, corpo):
    msg = MIMEText(corpo, 'plain', 'utf-8')
    msg['Subject'] = assunto
    msg['From'] = formataddr(('Águas de Santa Maria', os.environ.get('EMAIL_USER', 'seu-email@gmail.com')))
    msg['To'] = destino

    try:
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
        user = db.execute('SELECT * FROM usuarios_admin WHERE username = ?', (username,)).fetchone()
        if user and check_password_hash(user['senha_hash'], senha):
            session['usuario'] = username
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
        total_consumidores = db.execute('SELECT COUNT(id) FROM consumidores').fetchone()[0]
        
        # 2. Total de Usuários
        try:
            total_usuarios = db.execute('SELECT COUNT(id) FROM usuarios_admin').fetchone()[0]
        except sqlite3.OperationalError:
            app.logger.error("A tabela 'usuarios_admin' não foi encontrada. Verifique se o nome está correto.")
            total_usuarios = 'Erro' # Indica um erro no card
        
        # 3. Pagamentos feitos hoje
        hoje = date.today().strftime('%Y-%m-%d')
        pagamentos_hoje = db.execute('SELECT COUNT(id) FROM pagamentos WHERE data_pagamento = ?', (hoje,)).fetchone()[0]
        
        # 4. Total de Faturas Pendentes (Inadimplência) - LÓGICA REFINADA
        # Esta query é otimizada para contar precisamente as faturas com saldo devedor.
        faturas_pendentes = db.execute('''
            SELECT COUNT(*) 
            FROM (
                SELECT 
                    l.id
                FROM 
                    leituras l
                LEFT JOIN 
                    (
                        SELECT 
                            leitura_id, 
                            SUM(valor_pago) as total_pago,
                            SUM(valor_multa) as total_multa,
                            SUM(valor_juros) as total_juros
                        FROM 
                            pagamentos
                        GROUP BY 
                            leitura_id
                    ) p ON l.id = p.leitura_id
                GROUP BY 
                    l.id 
                HAVING 
                    (l.valor_original + COALESCE(p.total_multa, 0) + COALESCE(p.total_juros, 0)) > (COALESCE(p.total_pago, 0) + 0.001)
            )
        ''').fetchone()[0]

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

# --- Configurações do Sistema ---
@app.route('/configuracoes', methods=['GET', 'POST'])
@login_required
def configuracoes():
    db = get_db()
    mensagem = None
    if request.method == 'POST':
        form = request.form
        try:
            hidr_geral_anterior = int(form['hidr_geral_anterior'])
            hidr_geral_atual = int(form['hidr_geral_atual'])
            
            # Usar currency_to_float para todos os campos que podem ter decimais/formatação de moeda
            valor_litro = parse_number_from_br_form(form.get('valor_litro', ''))
            taxa_minima_consumo = parse_number_from_br_form(form.get('taxa_minima_consumo', ''))
            multa_percentual = parse_number_from_br_form(form.get('multa_percentual', ''))
            juros_diario_percentual = parse_number_from_br_form(form.get('juros_diario_percentual', ''))
            
            data_ultima_config = form['data_ultima_config']
            dias_uteis_para_vencimento = int(form['dias_uteis_para_vencimento'])
            
            consumo_geral = hidr_geral_atual - hidr_geral_anterior
            
            db.execute("""
                INSERT INTO configuracoes (
                    hidr_geral_anterior, hidr_geral_atual, consumo_geral,
                    valor_litro, taxa_minima_consumo, data_ultima_config,
                    dias_uteis_para_vencimento, multa_percentual, juros_diario_percentual
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                hidr_geral_anterior, hidr_geral_atual, consumo_geral,
                valor_litro, taxa_minima_consumo, data_ultima_config,
                dias_uteis_para_vencimento, multa_percentual, juros_diario_percentual
            ))
            db.commit()
            flash("Configuração salva com sucesso!", 'success')
        except Exception as e:
            db.rollback()
            app.logger.error(f"Erro ao salvar configuração: {str(e)}", exc_info=True) # Adicionado log de erro
            flash(f"Erro ao salvar configuração: {str(e)}", 'danger')

    config = get_current_config() # Usando a função auxiliar
    return render_template('configuracoes.html', config=config, mensagem=mensagem)

# --- API para Configurações (Juros e Multa) ---
@app.route('/api/configuracoes')
def api_configuracoes():
    config = get_current_config() # Usando a função auxiliar
    return jsonify({
        'multa_percentual': config['multa_percentual'],
        'juros_diario_percentual': config['juros_diario_percentual']
    })

# --- CRUD Consumidores ---
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
        db = get_db()
        try:
            db.execute("""
                INSERT INTO consumidores (nome, cpf, rg, endereco, telefone, hidrometro_num)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (nome, cpf, rg, endereco, telefone, hidrometro_num))
            db.commit()
            flash('Consumidor cadastrado com sucesso!', 'success')
            return redirect(url_for('listar_consumidores')) # Redirecionado para listar
        except sqlite3.IntegrityError:
            error = "CPF ou número do hidrômetro já cadastrado. Verifique os dados e tente novamente."
            flash(error, 'danger')
        except Exception as e:
            db.rollback()
            error = f"Erro ao cadastrar consumidor: {str(e)}"
            flash(error, 'danger')
    return render_template('cadastrar_consumidor.html', error=error)

# (Certifique-se de que tem estes imports no topo do seu app.py)
from datetime import date
from flask import render_template, flash, redirect, url_for
# ... e outros imports que você usa

# (Certifique-se que 'date', 'flash', 'redirect', 'url_for' etc. estão importados)

# --- Listar Pagamentos (Versão com Lógica de Filtro Refinada) ---
@app.route('/listar-pagamentos')
@login_required
def listar_pagamentos():
    """
    Busca e exibe os pagamentos registrados com filtro por período, paginação e um resumo financeiro.
    """
    try:
        db = get_db()
        
        page = request.args.get('page', 1, type=int)
        mes_filtro = request.args.get('mes', '')
        ano_filtro = request.args.get('ano', '')
        
        PER_PAGE = 20
        offset = (page - 1) * PER_PAGE
        
        # Monta a base da query e dos parâmetros
        base_query = "FROM pagamentos p JOIN consumidores c ON p.consumidor_id = c.id"
        conditions = []
        params = {}
        
        if mes_filtro:
            conditions.append("strftime('%m', p.data_pagamento) = :mes")
            params['mes'] = mes_filtro.zfill(2)
        if ano_filtro:
            conditions.append("strftime('%Y', p.data_pagamento) = :ano")
            params['ano'] = ano_filtro
        
        # Adiciona parâmetros de paginação ao dicionário principal
        params['limit'] = PER_PAGE
        params['offset'] = offset
        
        where_clause = ""
        if conditions:
            where_clause = " WHERE " + " AND ".join(conditions)
        
        # Query para o resumo (sem paginação)
        summary_query = f"SELECT COUNT(p.id), COALESCE(SUM(p.valor_pago), 0) {base_query} {where_clause}"
        # Cria uma cópia dos parâmetros sem os dados de paginação para a query de resumo
        params_summary = {k: v for k, v in params.items() if k not in ['limit', 'offset']}
        total_pagamentos_periodo, valor_arrecadado_periodo = db.execute(summary_query, params_summary).fetchone()

        # Query para os dados da tabela (com paginação)
        data_query = f"SELECT p.*, c.nome {base_query} {where_clause} ORDER BY p.data_pagamento DESC, p.id DESC LIMIT :limit OFFSET :offset"
        # Usa o dicionário de parâmetros completo (com limit/offset) para a query de dados
        pagamentos = db.execute(data_query, params).fetchall()

        # Lógica de Paginação
        total_items = total_pagamentos_periodo
        total_pages = math.ceil(total_items / PER_PAGE) if total_items > 0 else 1
        pagination = {
            "page": page, "total_pages": total_pages,
            "has_prev": page > 1, "has_next": page < total_pages
        }

        return render_template(
            'listar_pagamentos.html', 
            pagamentos=pagamentos,
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
    consumidores = db.execute("SELECT * FROM consumidores").fetchall()
    return render_template('consumidores.html', consumidores=consumidores)

# ---------- Cadastro de Leitura ----------
@app.route('/cadastrar-leitura', methods=['GET', 'POST'])
@login_required
def cadastrar_leitura():
    db = get_db()
    
    if request.method == 'POST':
        try:
            consumidor_id = request.form['consumidor_id']
            
            # Usar parse_number_from_br_form para todas as entradas numéricas do formulário
            leitura_anterior = parse_number_from_br_form(request.form.get('leitura_anterior'))
            leitura_atual = parse_number_from_br_form(request.form['leitura_atual']) 
            
            data_leitura_anterior = request.form.get('data_leitura_anterior') or None
            data_leitura_atual = request.form['data_leitura_atual']
            
            # qtd_dias_utilizados é int, não precisa de parse_number_from_br_form
            qtd_dias_utilizados = int(request.form['qtd_dias_utilizados']) if request.form.get('qtd_dias_utilizados') else None
            
            litros_consumidos = parse_number_from_br_form(request.form.get('litros_consumidos'))
            media_por_dia = parse_number_from_br_form(request.form.get('media_por_dia'))
            
            valor_original = parse_number_from_br_form(request.form.get('valor_original'))
            
            taxa_minima_aplicada = request.form['taxa_minima_aplicada']
            valor_taxa_minima = parse_number_from_br_form(request.form.get('valor_taxa_minima'))
            
            vencimento = request.form.get('vencimento')

            nome_arquivo = None
            if 'foto_hidrometro' in request.files:
                foto_hidrometro = request.files['foto_hidrometro']
                if foto_hidrometro and allowed_file(foto_hidrometro.filename): 
                    filename = secure_filename(foto_hidrometro.filename)
                    caminho_foto = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    foto_hidrometro.save(caminho_foto)
                    nome_arquivo = filename

            db.execute('''
                INSERT INTO leituras (
                    consumidor_id, leitura_anterior, leitura_atual,
                    data_leitura_anterior, data_leitura_atual,
                    qtd_dias_utilizados, litros_consumidos, media_por_dia,
                    valor_original, taxa_minima_aplicada, valor_taxa_minima,
                    vencimento, foto_hidrometro
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                consumidor_id, leitura_anterior, leitura_atual,
                data_leitura_anterior, data_leitura_atual,
                qtd_dias_utilizados, litros_consumidos, media_por_dia,
                valor_original, taxa_minima_aplicada, valor_taxa_minima,
                vencimento, nome_arquivo
            ))
            db.commit()
            flash('Leitura cadastrada com sucesso!', 'success')
            return redirect(url_for('listar_leituras')) # Redirecionado para listar leituras

        except Exception as e:
            db.rollback()
            app.logger.error(f'Erro ao salvar leitura: {e}', exc_info=True)
            flash(f'Erro ao cadastrar leitura: {str(e)}', 'danger')
            return redirect(url_for('cadastrar_leitura'))

    else: # Método GET
        consumidor_id = request.args.get('consumidor_id')
        consumidores = db.execute('SELECT id, nome FROM consumidores ORDER BY nome').fetchall()

        leitura_anterior = ''
        data_leitura_anterior_formatted = '' 

        if consumidor_id:
            ultima_leitura = db.execute('''
                SELECT leitura_atual, data_leitura_atual
                FROM leituras
                WHERE consumidor_id = ?
                ORDER BY date(data_leitura_atual) DESC, id DESC
                LIMIT 1
            ''', (consumidor_id,)).fetchone()

            if ultima_leitura:
                leitura_anterior = str(ultima_leitura['leitura_atual']) if ultima_leitura['leitura_atual'] else ''
                data_l_anterior_do_banco = ultima_leitura['data_leitura_atual']
                if data_l_anterior_do_banco:
                    try:
                        date_obj = datetime.strptime(data_l_anterior_do_banco, '%Y-%m-%d').date()
                        data_leitura_anterior_formatted = date_obj.strftime('%d/%m/%Y')
                    except ValueError:
                        data_leitura_anterior_formatted = ''
                else:
                    data_leitura_anterior_formatted = ''

        return render_template('cadastrar_leitura.html',
                               consumidores=consumidores,
                               consumidor_selecionado=int(consumidor_id) if consumidor_id else '',
                               leitura_anterior=leitura_anterior,
                               data_leitura_anterior=data_leitura_anterior_formatted,
                               qtd_dias_utilizados='',
                               litros_consumidos='',
                               media_por_dia='',
                               vencimento='')    
# --- API para Dias Úteis Após Vencimento ---
@app.route('/api/dias_uteis')
def api_dias_uteis():
    config = get_current_config() # Usando a função auxiliar
    dias = config['dias_uteis_para_vencimento']
    return jsonify({'dias_uteis': dias})

# (Certifique-se que 'date', 'flash', 'redirect', 'url_for' etc. estão importados)
# --- Registrar Pagamento ---@app.route('/registrar-pagamento', methods=['GET', 'POST'])
@app.route('/registrar-pagamento', methods=['GET', 'POST'])
@login_required
def registrar_pagamento():
    db = get_db()
    consumidores = db.execute('SELECT id, nome FROM consumidores').fetchall()
    
    # --- Lógica para GET (carregar o formulário) ---
    if request.method == 'GET':
        # Esta parte do código busca e prepara os dados para exibir no formulário.
        # Mantive sua lógica original para não alterar o que já funciona no carregamento.
        leituras_ativas_query = '''
            SELECT 
                l.id, l.valor_original, l.vencimento, l.data_leitura_atual,
                l.data_leitura_anterior, c.nome AS consumidor_nome
            FROM leituras l
            JOIN consumidores c ON l.consumidor_id = c.id
        '''
        leituras_ativas_db = db.execute(leituras_ativas_query).fetchall()

        leituras_para_pagamento = []
        config = get_current_config()
        data_referencia_para_calculo = request.args.get('data_pagamento_ref', date.today().strftime('%Y-%m-%d'))

        for leitura_data in leituras_ativas_db:
            leitura_id = leitura_data['id']
            valor_original_da_fatura = float(leitura_data['valor_original'])
            
            total_pago_acumulado_db = db.execute("SELECT COALESCE(SUM(valor_pago), 0) FROM pagamentos WHERE leitura_id = ?", (leitura_id,)).fetchone()[0]
            total_multa_acumulada_db = db.execute("SELECT COALESCE(SUM(valor_multa), 0) FROM pagamentos WHERE leitura_id = ?", (leitura_id,)).fetchone()[0]
            total_juros_acumulados_db = db.execute("SELECT COALESCE(SUM(valor_juros), 0) FROM pagamentos WHERE leitura_id = ?", (leitura_id,)).fetchone()[0]

            valor_base_para_penalidades = max(valor_original_da_fatura + total_multa_acumulada_db + total_juros_acumulados_db - total_pago_acumulado_db, 0)

            multa_calc, juros_calc, dias_atraso = calcular_penalidades(
                valor_original_da_fatura, valor_base_para_penalidades, leitura_data['vencimento'],
                data_referencia_para_calculo, config['multa_percentual'], config['juros_diario_percentual']
            )
            
            multa_para_exibir_na_lista = 0.0
            if dias_atraso > 0 and total_multa_acumulada_db == 0: 
                multa_para_exibir_na_lista = multa_calc
            
            valor_total_devido_lista = round(valor_base_para_penalidades + multa_para_exibir_na_lista + juros_calc, 2)
            
            # Filtro para não mostrar faturas já quitadas
            saldo_real_da_divida = valor_original_da_fatura + total_multa_acumulada_db + total_juros_acumulados_db - total_pago_acumulado_db
            if saldo_real_da_divida < 0.001:
                continue
            
            leituras_para_pagamento.append({
                'id': leitura_data['id'],
                'consumidor_nome': leitura_data['consumidor_nome'],
                'data_leitura_atual': leitura_data['data_leitura_atual'], 
                'vencimento': leitura_data['vencimento'],
                'valor_original': valor_original_da_fatura,
                'saldo_pendente': valor_total_devido_lista, 
                'multa_hoje': round(multa_para_exibir_na_lista, 2),
                'juros_hoje': round(juros_calc, 2)
            })
        
        return render_template('registrar_pagamento.html', consumidores=consumidores, leituras=leituras_para_pagamento)

    # --- Lógica para POST (salvar o pagamento) ---
    if request.method == 'POST':
        try:
            consumidor_id = request.form['consumidor_id']
            leitura_id = request.form['leitura_id']
            
            # --- AJUSTE DE SEGURANÇA APLICADO AQUI ---
            # A data do pagamento é sempre a data atual do servidor, não a do formulário.
            data_pagamento_str = date.today().strftime('%Y-%m-%d')
            
            forma_pagamento = request.form['forma_pagamento']
            valor_pago_str = request.form.get('valor_pago', '0')
            
            # Validação para não permitir pagamento zerado
            valor_pago = float(valor_pago_str.replace('R$', '').replace('.', '').replace(',', '.'))
            if valor_pago <= 0:
                flash('O valor do pagamento deve ser maior que R$ 0,00.', 'warning')
                return redirect(url_for('registrar_pagamento'))

            # Recalcula todos os valores no momento do POST para garantir consistência
            leitura_selecionada = db.execute('SELECT valor_original, vencimento FROM leituras WHERE id = ?', (leitura_id,)).fetchone()
            config = get_current_config()

            valor_original_fatura = float(leitura_selecionada['valor_original'])
            data_vencimento = leitura_selecionada['vencimento']

            total_pago_acumulado_antes = db.execute("SELECT COALESCE(SUM(valor_pago), 0) FROM pagamentos WHERE leitura_id = ?", (leitura_id,)).fetchone()[0]
            total_multa_acumulada_antes = db.execute("SELECT COALESCE(SUM(valor_multa), 0) FROM pagamentos WHERE leitura_id = ?", (leitura_id,)).fetchone()[0]
            total_juros_acumulados_antes = db.execute("SELECT COALESCE(SUM(valor_juros), 0) FROM pagamentos WHERE leitura_id = ?", (leitura_id,)).fetchone()[0]
            
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

            # Inserção no banco de dados
            db.execute('''
                INSERT INTO pagamentos (
                    leitura_id, consumidor_id, data_pagamento, forma_pagamento, valor_pago, 
                    dias_atraso, valor_multa, valor_juros, total_corrigido, saldo_devedor, saldo_credor
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                leitura_id, consumidor_id, data_pagamento_str, forma_pagamento, valor_pago, 
                dias_atraso, multa_a_ser_paga, juros_devido, total_corrigido, saldo_devedor, saldo_credor
            ))

            # Commit para salvar permanentemente a transação
            db.commit()
            
            flash('Pagamento registrado com sucesso!', 'success')
            return redirect(url_for('listar_pagamentos'))

        except Exception as e:
            db.rollback() # Desfaz a transação em caso de erro
            app.logger.error(f"Erro ao registrar pagamento: {e}", exc_info=True)
            flash(f'Erro ao registrar pagamento. Verifique os dados e tente novamente.', 'danger')
            return redirect(url_for('registrar_pagamento'))

# --- API para obter detalhes da leitura para o formulário de pagamento ---
# Esta API será chamada pelo JavaScript quando uma leitura for selecionada
@app.route('/get-leitura-details/<int:leitura_id>')
@login_required
def get_leitura_details(leitura_id):
    db = get_db()
    leitura = db.execute('SELECT valor_original, vencimento FROM leituras WHERE id = ?', (leitura_id,)).fetchone()
    
    if not leitura:
        return jsonify({'error': 'Leitura não encontrada'}), 404

    valor_original = float(leitura['valor_original'])
    data_vencimento = leitura['vencimento']
    
    config = get_current_config()
    
    # Pega a data de referência para cálculo dos juros/multa da URL (passada pelo JS)
    # OU usa a data atual se não for passada
    data_referencia_calculo_str = request.args.get('data_pagamento_ref', date.today().strftime('%Y-%m-%d'))


    # Calcular o total pago acumulado para esta leitura
    total_pago_acumulado_db = db.execute("SELECT COALESCE(SUM(valor_pago), 0) FROM pagamentos WHERE leitura_id = ?", (leitura_id,)).fetchone()[0]
    total_multa_acumulada_db = db.execute("SELECT COALESCE(SUM(valor_multa), 0) FROM pagamentos WHERE leitura_id = ?", (leitura_id,)).fetchone()[0]
    total_juros_acumulados_db = db.execute("SELECT COALESCE(SUM(valor_juros), 0) FROM pagamentos WHERE leitura_id = ?", (leitura_id,)).fetchone()[0]

    # Base para cálculo de penalidades: (Original + Multas Acumuladas + Juros Acumulados) - Pagamentos Acumulados
    valor_base_para_penalidades = max(
        valor_original + total_multa_acumulada_db + total_juros_acumulados_db - total_pago_acumulado_db,
        0
    )

    multa_calc, juros_calc, dias_atraso = calcular_penalidades(
        valor_original, # Passa o valor original como base para a multa
        valor_base_para_penalidades, # Passa o saldo remanescente para o cálculo de juros diários
        data_vencimento,
        data_referencia_calculo_str, # Usa a data de referência para o cálculo na API
        config['multa_percentual'],
        config['juros_diario_percentual']
    )
    
    # Lógica para multa única na API: só retorna multa se ela ainda não foi aplicada/registrada
    multa_para_exibir_na_api = 0.0
    if dias_atraso > 0 and total_multa_acumulada_db == 0: 
        multa_para_exibir_na_api = multa_calc

    # O valor a pagar inicial é o saldo pendente + multa + juros
    valor_a_pagar = round(valor_base_para_penalidades + multa_para_exibir_na_api + juros_calc, 2)

    return jsonify({
        'valor_original_fatura': round(valor_original, 2), 
        'data_vencimento': data_vencimento, 
        'multa': round(multa_para_exibir_na_api, 2), 
        'juros': round(juros_calc, 2),
        'dias_atraso': dias_atraso, 
        'total_corrigido': valor_a_pagar,
        'valor_base_para_novas_penalidades': round(valor_base_para_penalidades, 2) 
    })

# (Certifique-se que 'date' da biblioteca 'datetime' está importado no topo do seu arquivo)
# from datetime import date

# --- API para retornar leituras pendentes de um consumidor ---
@app.route('/api/leituras/<int:consumidor_id>')
def api_leituras(consumidor_id):
    if 'usuario' not in session:
        return jsonify({'erro': 'Não autorizado'}), 401

    db = get_db()
    
    config = get_current_config() # Usando a função auxiliar
    if not config:
        app.logger.error("Configurações de cálculo não foram encontradas.")
        return jsonify({'erro': 'Erro de configuração interna.'}), 500

    try:
        # A ÚNICA MUDANÇA ESTÁ NA CLÁUSULA "HAVING" NO FINAL DESTA QUERY.
        leituras = db.execute('''
            SELECT
                l.id,
                l.data_leitura_atual,
                l.vencimento,
                l.valor_original,
                l.data_leitura_anterior,
                COALESCE(SUM(p.valor_pago), 0) AS total_pago_acumulado,
                COALESCE(SUM(p.valor_multa), 0) AS total_multa_acumulada,
                COALESCE(SUM(p.valor_juros), 0) AS total_juros_acumulados
            FROM leituras l
            LEFT JOIN pagamentos p ON p.leitura_id = l.id
            WHERE l.consumidor_id = ?
            GROUP BY l.id
            /* * AJUSTE DE SEGURANÇA:
             * Em vez de verificar se o saldo é > 0, verificamos se é > 0.001.
             * Isso corrige o problema de arredondamento de centavos sem afetar
             * faturas com saldos reais.
             */
            HAVING (l.valor_original + COALESCE(SUM(p.valor_multa), 0) + COALESCE(SUM(p.valor_juros), 0) - COALESCE(SUM(p.valor_pago), 0)) > 0.001
            ORDER BY l.data_leitura_atual DESC
        ''', (consumidor_id,)).fetchall()

        hoje = date.today().strftime('%Y-%m-%d')
        resultado = []

        for l in leituras:
            try:
                valor_original_da_fatura = float(l['valor_original'])
                total_pago_acumulado = float(l['total_pago_acumulado'])
                total_multa_acumulada = float(l['total_multa_acumulada'])
                total_juros_acumulados = float(l['total_juros_acumulados'])

                valor_base_para_novas_penalidades = max(
                    valor_original_da_fatura + total_multa_acumulada + total_juros_acumulados - total_pago_acumulado,
                    0
                )
                
                multa_calculada_potencial, juros_calculado_agora, dias_atraso = calcular_penalidades(
                    valor_original_da_fatura,
                    valor_base_para_novas_penalidades,
                    l['vencimento'],
                    hoje,
                    config['multa_percentual'],
                    config['juros_diario_percentual']
                )

                multa_para_exibir_agora = 0.0
                if dias_atraso > 0 and total_multa_acumulada == 0:
                    multa_para_exibir_agora = multa_calculada_potencial
                
                valor_corrigido_total_para_proximo_pagamento = round(valor_base_para_novas_penalidades + multa_para_exibir_agora + juros_calculado_agora, 2)

                resultado.append({
                    'id': l['id'],
                    'data_leitura_atual': l['data_leitura_atual'],
                    'vencimento': l['vencimento'],
                    'valor_original_da_fatura': round(valor_original_da_fatura, 2),
                    'total_pago_acumulado': round(total_pago_acumulado, 2),
                    'valor_base_para_novas_penalidades': round(valor_base_para_novas_penalidades, 2),
                    'valor_corrigido_total_para_proximo_pagamento': valor_corrigido_total_para_proximo_pagamento,
                    'dias_atraso': dias_atraso,
                    'multa_calculada_agora': round(multa_para_exibir_agora, 2),
                    'juros_calculado_agora': round(juros_calculado_agora, 2),
                    'data_leitura_anterior': l['data_leitura_anterior']
                })
            except Exception as e:
                app.logger.warning(f"Erro processando leitura {l.get('id', 'N/A')}: {str(e)}")
                continue

        return jsonify(resultado)

    except Exception as e:
        app.logger.error(f"Erro ao buscar leituras via API: {str(e)}", exc_info=True)
        return jsonify({'erro': 'Erro interno no servidor'}), 500

# --- API para retornar o valor do litro atual ---
@app.route('/api/valor_litro')
def api_valor_litro():
    config = get_current_config() # Usando a função auxiliar
    return jsonify({'valor_litro': config['valor_litro']})

# --- Detalhes do Pagamento ---
@app.route('/detalhes-pagamento')
@login_required
def detalhes_pagamento():
    leitura_id = request.args.get('leitura_id')
    if not leitura_id:
        flash('Nenhum pagamento selecionado', 'error')
        return redirect(url_for('listar_pagamentos'))

    db = get_db()
    
    leitura_data = db.execute('''
        SELECT 
            l.*, 
            c.nome AS consumidor_nome,
            c.endereco AS consumidor_endereco,
            c.hidrometro_num AS hidrometro
        FROM leituras l
        JOIN consumidores c ON l.consumidor_id = c.id
        WHERE l.id = ?
    ''', (leitura_id,)).fetchone()

    if not leitura_data:
        flash('Leitura não encontrada', 'error')
        return redirect(url_for('listar_pagamentos'))

    pagamentos_feitos = db.execute('''
        SELECT 
            p.*
        FROM pagamentos p
        WHERE p.leitura_id = ?
        ORDER BY p.data_pagamento ASC
    ''', (leitura_id,)).fetchall()

    valor_original_da_fatura = float(leitura_data['valor_original'])
    
    total_pago_acumulado_db = db.execute("SELECT COALESCE(SUM(valor_pago), 0) FROM pagamentos WHERE leitura_id = ?", (leitura_id,)).fetchone()[0]
    total_multa_acumulada_db = db.execute("SELECT COALESCE(SUM(valor_multa), 0) FROM pagamentos WHERE leitura_id = ?", (leitura_id,)).fetchone()[0]
    total_juros_acumulados_db = db.execute("SELECT COALESCE(SUM(valor_juros), 0) FROM pagamentos WHERE leitura_id = ?", (leitura_id,)).fetchone()[0]

    valor_base_para_penalidades = max(
        valor_original_da_fatura + total_multa_acumulada_db + total_juros_acumulados_db - total_pago_acumulado_db,
        0
    )

    config = get_current_config()
    hoje = date.today().strftime('%Y-%m-%d')

    multa_calc, juros_calc, dias_atraso = calcular_penalidades(
        valor_original_da_fatura, 
        valor_base_para_penalidades,
        leitura_data['vencimento'],
        hoje, 
        config['multa_percentual'],
        config['juros_diario_percentual']
    )
    
    # valor_total_devido_hoje: O que é devido ATUALMENTE, considerando atraso atÉ HOJE
    valor_total_devido_hoje = round(valor_base_para_penalidades + multa_calc + juros_calc, 2)
    
    # --- NOVA LÓGICA PARA STATUS FINAL DA FATURA ---
    # Calcular o valor total histórico da dívida (Original + todas as multas e juros que já foram cobrados)
    total_historico_da_divida = round(valor_original_da_fatura + total_multa_acumulada_db + total_juros_acumulados_db, 2)

    # Margem de tolerância para comparação de floats (arredondamento)
    EPSILON = 0.01 

    # Determinar o status final
    situacao_da_fatura_texto = "Fatura Aberta"
    saldo_devedor_final_display = 0.0
    saldo_credor_final_display = 0.0

    if abs(total_pago_acumulado_db - total_historico_da_divida) < EPSILON:
        # Se o total pago é IGUAL ao total histórico da dívida (com pequena tolerância)
        situacao_da_fatura_texto = "Fatura Quitada."
    elif total_pago_acumulado_db < total_historico_da_divida:
        # Se o total pago é MENOR que o total histórico da dívida
        situacao_da_fatura_texto = "SALDO DEVEDOR"
        saldo_devedor_final_display = round(total_historico_da_divida - total_pago_acumulado_db, 2)
    else: # total_pago_acumulado_db > total_historico_da_divida
        # Se o total pago é MAIOR que o total histórico da dívida (verdadeiro saldo credor)
        situacao_da_fatura_texto = "SALDO CREDOR"
        saldo_credor_final_display = round(total_pago_acumulado_db - total_historico_da_divida, 2)
    # --- FIM DA NOVA LÓGICA ---


    litros_consumidos = 0
    periodo_consumo = None

    try:
        leitura_anterior = float(leitura_data['leitura_anterior']) if leitura_data['leitura_anterior'] else 0
        leitura_atual = float(leitura_data['leitura_atual']) if leitura_data['leitura_atual'] else 0
        litros_consumidos = abs(leitura_atual - leitura_anterior)

        data_leitura_atual_formatada = ""
        if leitura_data['data_leitura_atual']:
            try:
                data_leitura_atual_formatada = datetime.strptime(leitura_data['data_leitura_atual'], '%Y-%m-%d').strftime('%d/%m/%Y')
            except ValueError:
                data_leitura_atual_formatada = "Data inválida"

        vencimento_formatado = ""
        if leitura_data['vencimento']:
            try:
                vencimento_formatado = datetime.strptime(leitura_data['vencimento'], '%Y-%m-%d').strftime('%d/%m/%Y')
            except ValueError:
                vencimento_formatado = "Data inválida"

        if leitura_data['data_leitura_anterior'] and leitura_data['data_leitura_atual']:
            try:
                inicio = datetime.strptime(leitura_data['data_leitura_anterior'], '%Y-%m-%d').strftime('%d/%m/%Y')
                fim = datetime.strptime(leitura_data['data_leitura_atual'], '%Y-%m-%d').strftime('%d/%m/%Y')
                periodo_consumo = f"{inicio} a {fim}"
            except ValueError:
                periodo_consumo = "N/A (formato de data inválido)"

    except Exception as e:
        app.logger.warning(f"Erro ao calcular dados adicionais para detalhes de pagamento (período consumo): {str(e)}")
        periodo_consumo = "N/A (erro de cálculo)" 


    return render_template(
        'detalhes_pagamento.html',
        leitura=leitura_data, 
        pagamentos_feitos=pagamentos_feitos, 
        litros_consumidos=litros_consumidos,
        dias_atraso=dias_atraso,
        multa_atual=round(multa_calc, 2), # Multa calculada HOJE
        juros_atual=round(juros_calc, 2), # Juros calculados HOJE
        valor_total_devido=valor_total_devido_hoje, # O que é devido HOJE
        total_pago_acumulado=round(total_pago_acumulado_db, 2),
        # NOVO: Variáveis para a situação final da fatura
        situacao_da_fatura_texto=situacao_da_fatura_texto,
        saldo_devedor_final_display=saldo_devedor_final_display,
        saldo_credor_final_display=saldo_credor_final_display,
        
        periodo_consumo=periodo_consumo,
        data_leitura_atual_formatada=data_leitura_atual_formatada,
        vencimento_formatado=vencimento_formatado,
        # Mantido por compatibilidade com HTML, mas o ideal é usar 'leitura'
        pagamento=leitura_data 
    )
# --- Recuperação de Senha ---
@app.route('/recuperar-senha', methods=['POST'])
def recuperar_senha():
    email = request.form.get('email', '').strip().lower()
    app.logger.info(f"Tentativa de recuperação de senha para: {email}")

    db = get_db()
    try:
        user = db.execute(
            'SELECT id FROM usuarios_admin WHERE email = ?', 
            (email,)
        ).fetchone()

        if not user:
            flash("E-mail não cadastrado.", "error")
            return redirect(url_for('login'))

        token = secrets.token_urlsafe(50)
        expires_at = datetime.now() + timedelta(hours=1)
        expires_at_str = expires_at.strftime('%Y-%m-%d %H:%M:%S')

        db.execute("""
            UPDATE usuarios_admin 
            SET reset_token = ?, reset_expira_em = ? 
            WHERE id = ?
        """, (token, expires_at_str, user['id']))
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
    user = db.execute("""
        SELECT id FROM usuarios_admin 
        WHERE reset_token = ? AND reset_expira_em > ?
    """, (token, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))).fetchone()
    
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
        user = db.execute("""
            SELECT id FROM usuarios_admin 
            WHERE reset_token = ? AND reset_expira_em > ?
        """, (token, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))).fetchone()

        if user:
            db.execute("""
                UPDATE usuarios_admin 
                SET senha_hash = ?, reset_token = NULL, reset_expira_em = NULL 
                WHERE id = ?
            """, (generate_password_hash(nova_senha), user['id']))
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

# --- Cadastrar Usuário ---
@app.route('/cadastrar-usuario', methods=['GET', 'POST'])
@login_required
def cadastrar_usuario():
    db = get_db()
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        email = request.form.get('email')

        if not username or not password or not email:
            flash("Preencha todos os campos.", "error")
            return redirect(url_for('cadastrar_usuario'))

        if len(password) < 6:
            flash("A senha deve ter pelo menos 6 caracteres.", "error")
            return redirect(url_for('cadastrar_usuario'))

        try:
            usuario_existente = db.execute(
                "SELECT id FROM usuarios_admin WHERE username = ?", 
                (username,)
            ).fetchone()

            email_existente = db.execute(
                "SELECT id FROM usuarios_admin WHERE email = ?", 
                (email,)
            ).fetchone()

            if usuario_existente:
                flash("Este nome de usuário já está em uso.", "error")
                return redirect(url_for('cadastrar_usuario'))
            if email_existente:
                flash("Este e-mail já está cadastrado.", "error")
                return redirect(url_for('cadastrar_usuario'))

            db.execute("""
                INSERT INTO usuarios_admin (username, senha_hash, email)
                VALUES (?, ?, ?)
            """, (username, generate_password_hash(password), email))
            db.commit()
            flash("Usuário cadastrado com sucesso!", "success")
            return redirect(url_for('dashboard'))

        except Exception as e:
            db.rollback()
            app.logger.error(f"Erro ao cadastrar usuário: {str(e)}", exc_info=True)
            flash("Ocorreu um erro ao cadastrar o usuário.", "error")
            return redirect(url_for('cadastrar_usuario'))

    return render_template('cadastrar_usuario.html')

# --- Editar Consumidor ---
@app.route('/editar-consumidor/<int:id>', methods=['GET', 'POST'])
@login_required
def editar_consumidor(id):
    db = get_db()
    consumidor = db.execute("SELECT * FROM consumidores WHERE id = ?", (id,)).fetchone()
    
    if not consumidor:
        flash("Consumidor não encontrado.", "error")
        return redirect(url_for('listar_consumidores'))

    if request.method == 'POST':
        nome = request.form['nome']
        cpf = request.form['cpf']
        rg = request.form['rg']
        endereco = request.form['endereco']
        telefone = request.form['telefone']
        hidrometro_num = request.form['hidrometro']

        try:
            db.execute("""
                UPDATE consumidores 
                SET nome = ?, cpf = ?, rg = ?, endereco = ?, telefone = ?, hidrometro_num = ? 
                WHERE id = ?
            """, (nome, cpf, rg, endereco, telefone, hidrometro_num, id))
            db.commit()
            flash("Dados atualizados com sucesso!", "success")
            return redirect(url_for('listar_consumidores'))
        except sqlite3.IntegrityError as e:
            flash("CPF ou número do hidrômetro já cadastrado.", "error")
        except Exception as e:
            db.rollback()
            app.logger.error(f"Erro ao editar consumidor: {str(e)}", exc_info=True)
            flash(f"Erro ao editar o consumidor: {str(e)}", "error")

    return render_template('editar_consumidor.html', consumidor=consumidor)

# --- Excluir Consumidor ---
@app.route('/excluir-consumidor/<int:id>')
@login_required
def excluir_consumidor(id):
    db = get_db()
    try:
        db.execute("DELETE FROM consumidores WHERE id = ?", (id,))
        db.commit()
        flash("Consumidor excluído com sucesso!", "success")
    except sqlite3.IntegrityError: # Pode ocorrer se houver leituras ou pagamentos vinculados
        db.rollback()
        flash("Não foi possível excluir o consumidor. Existem leituras ou pagamentos associados a ele.", "error")
    except Exception as e:
        db.rollback()
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

def _get_fatura_contexto(leitura_id):
    """
    Função auxiliar que busca e calcula todos os dados para uma fatura.
    Isso evita repetição de código entre a página HTML e o gerador de PDF.
    """
    db = get_db()
    config = get_current_config()

    # A query agora busca 'c.telefone'
    leitura_data = db.execute('''
        SELECT 
            l.*, 
            c.nome AS consumidor_nome, 
            c.endereco AS consumidor_endereco, 
            c.hidrometro_num AS hidrometro,
            c.telefone 
        FROM leituras l JOIN consumidores c ON l.consumidor_id = c.id
        WHERE l.id = ?
    ''', (leitura_id,)).fetchone()

    if not leitura_data:
        return None

    pagamentos_feitos = db.execute("SELECT * FROM pagamentos WHERE leitura_id = ? ORDER BY data_pagamento ASC", (leitura_id,)).fetchall()
    
    total_pago_acumulado_db = sum(p['valor_pago'] for p in pagamentos_feitos)
    total_multa_acumulada_db = sum(p['valor_multa'] for p in pagamentos_feitos)
    total_juros_acumulados_db = sum(p['valor_juros'] for p in pagamentos_feitos)
    valor_original_da_fatura = float(leitura_data['valor_original'])
    valor_base_para_penalidades = max(valor_original_da_fatura + total_multa_acumulada_db + total_juros_acumulados_db - total_pago_acumulado_db, 0)
    hoje = date.today().strftime('%Y-%m-%d')
    multa_potencial, juros_hoje, dias_atraso = calcular_penalidades(
        valor_original_da_fatura, valor_base_para_penalidades, leitura_data['vencimento'],
        hoje, config['multa_percentual'], config['juros_diario_percentual']
    )
    multa_a_aplicar_hoje = 0.0
    if dias_atraso > 0 and total_multa_acumulada_db == 0:
        multa_a_aplicar_hoje = multa_potencial
    valor_total_devido_hoje = round(valor_base_para_penalidades + multa_a_aplicar_hoje + juros_hoje, 2)
    saldo_devedor_final_display = 0.0
    saldo_credor_final_display = 0.0
    situacao_da_fatura_texto = "Fatura Quitada."
    if valor_total_devido_hoje > 0.001:
        situacao_da_fatura_texto = "SALDO DEVEDOR"
        saldo_devedor_final_display = valor_total_devido_hoje
    elif valor_total_devido_hoje < -0.001:
        situacao_da_fatura_texto = "SALDO CREDOR"
        saldo_credor_final_display = abs(valor_total_devido_hoje)

    # --- LÓGICA DE FORMATAÇÃO DE DATA CORRIGIDA E ROBUSTA ---
    litros_consumidos, periodo_consumo, vencimento_formatado, data_leitura_atual_formatada = 0, "Não disponível", "Não informado", "Não informada"
    try:
        litros_consumidos = abs(float(leitura_data['leitura_atual'] or 0) - float(leitura_data['leitura_anterior'] or 0))
        
        def format_date_safely(date_string):
            if not date_string:
                return None
            try:
                # Tenta o formato padrão AAAA-MM-DD
                return datetime.strptime(date_string, '%Y-%m-%d').strftime('%d/%m/%Y')
            except ValueError:
                # Se falhar, retorna a string original, pois ela já pode estar no formato DD/MM/AAAA
                return date_string

        data_ant_str = format_date_safely(leitura_data['data_leitura_anterior'])
        data_atu_str = format_date_safely(leitura_data['data_leitura_atual'])
        vencimento_formatado = format_date_safely(leitura_data['vencimento']) or "Não informado"
        data_leitura_atual_formatada = data_atu_str or "Não informada"

        if data_ant_str and data_atu_str:
            periodo_consumo = f"{data_ant_str} a {data_atu_str}"

    except (TypeError, KeyError) as e:
        app.logger.warning(f"Erro de tipo ou chave não encontrada para leitura ID {leitura_id}: {e}")
        
    return {
        'leitura': leitura_data, 'pagamentos_feitos': pagamentos_feitos, 'litros_consumidos': litros_consumidos,
        'dias_atraso': dias_atraso, 'multa_atual': round(multa_a_aplicar_hoje, 2), 'juros_atual': round(juros_hoje, 2),
        'valor_total_devido': valor_total_devido_hoje, 'total_pago_acumulado': round(total_pago_acumulado_db, 2),
        'situacao_da_fatura_texto': situacao_da_fatura_texto, 'saldo_devedor_final_display': saldo_devedor_final_display,
        'saldo_credor_final_display': saldo_credor_final_display, 'periodo_consumo': periodo_consumo,
        'data_leitura_atual_formatada': data_leitura_atual_formatada, 'vencimento_formatado': vencimento_formatado
    }

@app.route('/gerar-comprovante-pdf/<int:leitura_id>')
@login_required
def gerar_comprovante_pdf(leitura_id):
    contexto = _get_fatura_contexto(leitura_id)
    if contexto is None:
        flash('Fatura não encontrada.', 'danger')
        return redirect(url_for('listar_pagamentos'))
    
    pdf_url = url_for('download_comprovante_pdf', leitura_id=leitura_id, _external=True)
    texto_whatsapp = f"Olá! Segue o extrato da sua fatura Águas de Santa Maria (Ref. #{leitura_id}). Para visualizar ou baixar o PDF, acesse: {pdf_url}"
    
    # Usa a coluna 'telefone' que já existe
    whatsapp_phone = contexto['leitura']['telefone']
    
    if whatsapp_phone:
        whatsapp_phone_cleaned = ''.join(filter(str.isdigit, whatsapp_phone))
        if not whatsapp_phone_cleaned.startswith('55'):
            whatsapp_phone_cleaned = f"55{whatsapp_phone_cleaned}"
    else:
        whatsapp_phone_cleaned = ''

    contexto['whatsapp_message'] = quote(texto_whatsapp)
    contexto['whatsapp_phone_number'] = whatsapp_phone_cleaned
    
    return render_template('detalhes_pagamento.html', **contexto)

@app.route('/download-comprovante-pdf/<int:leitura_id>')
@login_required
def download_comprovante_pdf(leitura_id):
    contexto = _get_fatura_contexto(leitura_id)
    if contexto is None:
        return "Fatura não encontrada", 404
        
    contexto['is_pdf_render'] = True
    html_string = render_template('detalhes_pagamento.html', **contexto)
    pdf = HTML(string=html_string).write_pdf()
    
    return Response(pdf, mimetype='application/pdf', headers={'Content-Disposition': f'inline; filename=fatura_{leitura_id}.pdf'})


# Garanta que estes imports estão no topo do seu arquivo app.py
from flask import render_template, flash, redirect, url_for, request, session
from datetime import datetime
# Seus outros imports...
# from .db import get_db
# from .auth import login_required

# --- Relatório de Consumidores (Versão Corrigida e Integrada) ---
@app.route('/relatorio-consumidores')
@login_required
def relatorio_consumidores():
    try:
        db = get_db()
        mes_filtro = request.args.get('mes')
        ano_filtro = request.args.get('ano')
        ano_atual = datetime.now().year

        # Se a página carregar sem filtros, define o mês e ano atuais como padrão.
        if not mes_filtro and not ano_filtro:
            mes_filtro = datetime.now().strftime('%m')
            ano_filtro = str(ano_atual)

        if mes_filtro and mes_filtro.lower() == 'todos':
            mes_filtro = None

        # Validação do ano para evitar erros
        if ano_filtro:
            try:
                if int(ano_filtro) > ano_atual:
                    flash("Não é possível filtrar por anos futuros.", "warning")
                    ano_filtro = str(ano_atual)
            except ValueError:
                flash("Ano inválido.", "warning")
                ano_filtro = str(ano_atual)
        
        params = {}
        condicoes_leitura = []

        if mes_filtro:
            condicoes_leitura.append("strftime('%m', data_leitura_atual) = :mes_filtro")
            params['mes_filtro'] = mes_filtro.zfill(2)
        
        if ano_filtro:
            condicoes_leitura.append("strftime('%Y', data_leitura_atual) = :ano_filtro")
            params['ano_filtro'] = ano_filtro
            
        condicoes_sql = " AND ".join(condicoes_leitura) if condicoes_leitura else "1=1"

        # --- QUERY CORRIGIDA ---
        # A lógica do status agora compara o total pago com o valor original + multas + juros
        query = f"""
            WITH UltimaLeitura AS (
                -- Pega o ID da última leitura de cada consumidor no período filtrado
                SELECT consumidor_id, MAX(id) as ultima_leitura_id
                FROM leituras
                WHERE {condicoes_sql}
                GROUP BY consumidor_id
            ),
            PagamentosAgregados AS (
                -- Calcula os totais pagos para cada fatura (incluindo multas e juros)
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
            ORDER BY c.nome
        """
        consumidores = db.execute(query, params).fetchall()

        total_consumidores = db.execute("SELECT COUNT(id) FROM consumidores").fetchone()[0]
        consumidores_com_leituras = sum(1 for c in consumidores if c['data_leitura_atual'] is not None)

        return render_template(
            'relatorio_consumidores.html',
            consumidores=consumidores,
            mes_filtro=mes_filtro if mes_filtro else 'Todos',
            ano_filtro=ano_filtro,
            ano_atual=ano_atual,
            total_consumidores=total_consumidores,
            consumidores_com_leituras=consumidores_com_leituras
        )

    except Exception as e:
        app.logger.error(f"Erro no relatório de consumidores: {str(e)}", exc_info=True)
        flash("Ocorreu um erro ao gerar o relatório de consumidores.", "danger")
        return redirect(url_for('dashboard'))

# --- Listar Leituras (Versão com Filtro e Paginação) ---
@app.route('/leituras')
@login_required
def listar_leituras():
    """
    Busca e exibe as leituras registradas com filtro por período e paginação.
    """
    try:
        db = get_db()
        
        # --- Lógica de Filtro e Paginação ---
        page = request.args.get('page', 1, type=int)
        mes_filtro = request.args.get('mes', '')
        ano_filtro = request.args.get('ano', '')
        
        PER_PAGE = 20 # Leituras por página
        offset = (page - 1) * PER_PAGE
        
        # Monta a query de forma dinâmica
        # AJUSTE: A query agora calcula os campos 'litros_consumidos' e 'media_por_dia'
        base_query = """
            FROM leituras l 
            JOIN consumidores c ON l.consumidor_id = c.id
        """
        count_query = "SELECT COUNT(l.id) " + base_query
        data_query = """
            SELECT 
                l.*, 
                c.nome as nome_consumidor,
                (l.leitura_atual - l.leitura_anterior) AS litros_consumidos,
                CASE
                    WHEN (JULIANDAY(l.data_leitura_atual) - JULIANDAY(l.data_leitura_anterior)) > 0
                    THEN CAST(l.leitura_atual - l.leitura_anterior AS REAL) / (JULIANDAY(l.data_leitura_atual) - JULIANDAY(l.data_leitura_anterior))
                    ELSE 0
                END AS media_por_dia
        """ + base_query

        conditions = []
        params = {}
        
        if mes_filtro:
            conditions.append("strftime('%m', l.data_leitura_atual) = :mes")
            params['mes'] = mes_filtro.zfill(2)
            
        if ano_filtro:
            conditions.append("strftime('%Y', l.data_leitura_atual) = :ano")
            params['ano'] = ano_filtro
        
        if conditions:
            where_clause = " WHERE " + " AND ".join(conditions)
            count_query += where_clause
            data_query += where_clause
            
        data_query += " ORDER BY l.data_leitura_atual DESC, l.id DESC LIMIT :limit OFFSET :offset"
        params['limit'] = PER_PAGE
        params['offset'] = offset
        
        # Executa as queries
        total_items = db.execute(count_query, {k: v for k, v in params.items() if k not in ['limit', 'offset']}).fetchone()[0]
        leituras = db.execute(data_query, params).fetchall()
        
        total_pages = math.ceil(total_items / PER_PAGE) if total_items > 0 else 1
        
        # Cria um objeto de paginação simples para o template
        pagination = {
            "page": page,
            "total_pages": total_pages,
            "has_prev": page > 1,
            "has_next": page < total_pages
        }

        return render_template(
            'listar_leituras.html', 
            leituras=leituras,
            pagination=pagination,
            mes_filtro=mes_filtro,
            ano_filtro=ano_filtro,
            ano_atual=datetime.now().year
        )
    except Exception as e:
        app.logger.error(f"Erro ao listar leituras: {e}", exc_info=True)
        flash("Ocorreu um erro ao carregar o relatório de leituras.", "danger")
        return redirect(url_for('dashboard'))

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

        # --- Cálculos para o Mês Atual ---
        # 1. Receitas no Mês
        total_receitas_mes = db.execute("""
            SELECT COALESCE(SUM(valor_pago), 0) FROM pagamentos 
            WHERE strftime('%m', data_pagamento) = ? AND strftime('%Y', data_pagamento) = ?
        """, (mes_atual, ano_atual)).fetchone()[0]

        # 2. Despesas no Mês
        total_despesas_mes = db.execute("""
            SELECT COALESCE(SUM(valor), 0) FROM despesas 
            WHERE strftime('%m', data_despesa) = ? AND strftime('%Y', data_despesa) = ?
        """, (mes_atual, ano_atual)).fetchone()[0]

        # 3. Saldo do Mês
        saldo_mes = total_receitas_mes - total_despesas_mes

        # --- Indicadores Gerais ---
        # 4. Total de Consumidores
        total_consumidores = db.execute("SELECT COUNT(id) FROM consumidores").fetchone()[0]

        # 5. Total de Faturas Pendentes (lógica de inadimplência)
        faturas_pendentes = db.execute("""
            SELECT COUNT(*) FROM (
                SELECT l.id FROM leituras l 
                LEFT JOIN pagamentos p ON l.id = p.leitura_id 
                GROUP BY l.id 
                HAVING (l.valor_original + COALESCE(SUM(p.valor_multa),0) + COALESCE(SUM(p.valor_juros),0)) > (COALESCE(SUM(p.valor_pago),0) + 0.001)
            )
        """).fetchone()[0]

        # 6. Consumo Total de Água no Mês
        consumo_total_mes = db.execute("""
            SELECT COALESCE(SUM(litros_consumidos), 0) FROM leituras 
            WHERE strftime('%m', data_leitura_atual) = ? AND strftime('%Y', data_leitura_atual) = ?
        """, (mes_atual, ano_atual)).fetchone()[0]

        # 7. Pagamentos Realizados Hoje
        pagamentos_hoje = db.execute("SELECT COUNT(id) FROM pagamentos WHERE data_pagamento = ?", (hoje.strftime('%Y-%m-%d'),)).fetchone()[0]

        # Monta o dicionário para enviar ao template
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

# --- Selecionar Comprovante ---
@app.route('/selecionar-comprovante')
@login_required
def selecionar_comprovante():
    db = get_db()
    # Listar leituras que tiveram pagamentos (não necessariamente quitadas)
    leituras_pagas = db.execute('''
        SELECT DISTINCT l.id, l.data_leitura_atual, l.valor_original, c.nome AS consumidor_nome
        FROM leituras l
        JOIN pagamentos p ON l.id = p.leitura_id
        JOIN consumidores c ON l.consumidor_id = c.id
        ORDER BY l.data_leitura_atual DESC
    ''').fetchall()
    return render_template('selecionar_comprovante.html', leituras_pagas=leituras_pagas)

# --- Relatórios no Card ---
@app.route('/relatorios')
@login_required
def relatorios():
    return render_template('relatorios.html')

@app.route('/backup-db')
@login_required
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


# --- Relatório de Inadimplência (Versão mais robusta) ---
@app.route('/relatorio-inadimplencia')
@login_required
def relatorio_inadimplencia():
    try:
        db = get_db()
        config = get_current_config() 
        hoje = date.today().strftime('%Y-%m-%d')
        hoje_obj = date.today()

        # Query para buscar todas as faturas que ainda podem ter pendências
        faturas_raw = db.execute('''
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
        ''').fetchall()
        
        pendencias_calculadas = []
        total_pendente_geral = 0.0
        total_atualizado_geral = 0.0

        for p_raw in faturas_raw:
            try:
                valor_original_da_fatura = float(p_raw['valor_original'])
                total_pago_acumulado = float(p_raw['total_pago_acumulado'])
                total_multa_acumulada = float(p_raw['total_multa_acumulada'])
                total_juros_acumulados = float(p_raw['total_juros_acumulados'])

                # Saldo pendente histórico
                valor_pendente = (valor_original_da_fatura + total_multa_acumulada + total_juros_acumulados) - total_pago_acumulado

                # Se o saldo pendente for maior que um centavo, processe
                if valor_pendente > 0.01:
                    # AJUSTE DE SEGURANÇA: Verifica se a data de vencimento existe antes de calcular
                    if not p_raw['vencimento']:
                        continue # Pula para a próxima fatura se não houver data de vencimento

                    multa_calculada_potencial, juros_calc, dias_atraso = calcular_penalidades(
                        valor_original_da_fatura,
                        valor_pendente, # Base para juros é o saldo pendente
                        p_raw['vencimento'],
                        hoje,
                        config['multa_percentual'],
                        config['juros_diario_percentual']
                    )
                    
                    multa_para_exibir_agora = 0.0
                    if dias_atraso > 0 and total_multa_acumulada == 0:
                        multa_para_exibir_agora = multa_calculada_potencial

                    valor_atualizado = round(valor_pendente + multa_para_exibir_agora + juros_calc, 2)
                    
                    is_vencido = datetime.strptime(p_raw['vencimento'], '%Y-%m-%d').date() < hoje_obj

                    pendencias_calculadas.append({
                        'consumidor': p_raw['consumidor'],
                        'endereco': p_raw['endereco'],
                        'telefone': p_raw['telefone'],
                        'data_leitura_atual': p_raw['data_leitura_atual'],
                        'vencimento': p_raw['vencimento'],
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
   
    
# --- Rotas de Gerenciamento de Despesas ---
@app.route('/cadastrar-despesa', methods=['GET', 'POST'])
@login_required
def cadastrar_despesa():
    if request.method == 'POST':
        descricao = request.form['descricao'].strip()
        valor_str = request.form['valor']
        data_despesa_str = request.form['data_despesa']
        categoria = request.form.get('categoria', '').strip()
        observacoes = request.form.get('observacoes', '').strip()

        if not descricao or not valor_str or not data_despesa_str:
            flash("Descrição, Valor e Data da Despesa são campos obrigatórios.", "danger")
            today_date = date.today().strftime('%Y-%m-%d') # Adicionado para re-renderizar em caso de erro
            return render_template('cadastrar_despesa.html', today_date=today_date)

        try:
            valor = parse_number_from_br_form(valor_str)
            if valor <= 0:
                flash("O valor da despesa deve ser maior que R$ 0,00.", "danger")
                today_date = date.today().strftime('%Y-%m-%d') # Adicionado para re-renderizar em caso de erro
                return render_template('cadastrar_despesa.html', today_date=today_date)
            
            # Valida o formato da data
            datetime.strptime(data_despesa_str, '%Y-%m-%d')
            
        except ValueError:
            flash("Formato de valor ou data inválido. Use o formato BCE-MM-DD para a data.", "danger")
            today_date = date.today().strftime('%Y-%m-%d') # Adicionado para re-renderizar em caso de erro
            return render_template('cadastrar_despesa.html', today_date=today_date)

        db = get_db()
        try:
            db.execute(
                """
                INSERT INTO despesas (data_despesa, descricao, valor, categoria, observacoes)
                VALUES (?, ?, ?, ?, ?)
                """,
                (data_despesa_str, descricao, valor, categoria, observacoes)
            )
            db.commit()
            flash("Despesa cadastrada com sucesso!", "success")
            return redirect(url_for('listar_despesas'))
        except Exception as e:
            db.rollback()
            app.logger.error(f"Erro ao cadastrar despesa: {str(e)}", exc_info=True)
            flash(f"Erro ao cadastrar despesa: {str(e)}", "danger")
            today_date = date.today().strftime('%Y-%m-%d') # Adicionado para re-renderizar em caso de erro
            return render_template('cadastrar_despesa.html', today_date=today_date)

    else: # Método GET
        today_date = date.today().strftime('%Y-%m-%d') # Obtenha a data atual para o campo de data
        return render_template('cadastrar_despesa.html', today_date=today_date)

@app.route('/listar-despesas')
@login_required
def listar_despesas():
    db = get_db()
    page = request.args.get('page', 1, type=int)
    mes_filtro = request.args.get('mes', '')
    ano_filtro = request.args.get('ano', '') # Pega o ano, vazio se não fornecido
    categoria_filtro = request.args.get('categoria', '')

    # Limite superior para anos futuros na validação
    MAX_FUTURE_YEARS = 20 # Permite anos até 20 anos no futuro (2025 + 20 = 2045)

    try:
        # Validação do ano: permite vazio (para todos os anos) ou um ano válido
        if ano_filtro:
            ano_int = int(ano_filtro)
            if not (1900 <= ano_int <= datetime.now().year + MAX_FUTURE_YEARS):
                flash(f"Ano inválido ou fora do intervalo permitido (1900 - {datetime.now().year + MAX_FUTURE_YEARS}).", "warning")
                ano_filtro = '' # Limpa o filtro de ano em caso de erro
        # Se ano_filtro for vazio, ele será tratado como "todos" implicitamente pela ausência da condição WHERE.

        # Validação do mês (se houver)
        if mes_filtro:
            if not (1 <= int(mes_filtro) <= 12):
                flash("Mês inválido.", "warning")
                mes_filtro = '' # Volta para "Todos os meses" se o mês for inválido

    except ValueError:
        flash("Filtro de data inválido. Limpando filtros de data.", "warning")
        mes_filtro = ''
        ano_filtro = '' # Limpa ambos em caso de erro de conversão

    PER_PAGE = 15
    offset = (page - 1) * PER_PAGE

    base_query = "FROM despesas"
    conditions = []
    params = {}

    if mes_filtro:
        conditions.append("strftime('%m', data_despesa) = :mes")
        params['mes'] = mes_filtro.zfill(2)
    
    if ano_filtro: # Adiciona condição de ano APENAS se um ano válido for fornecido
        conditions.append("strftime('%Y', data_despesa) = :ano")
        params['ano'] = ano_filtro
    
    if categoria_filtro:
        conditions.append("categoria = :categoria")
        params['categoria'] = categoria_filtro

    where_clause = ""
    if conditions:
        where_clause = " WHERE " + " AND ".join(conditions)

    # Query para contagem total
    count_query = f"SELECT COUNT(id) {base_query} {where_clause}"
    total_items = db.execute(count_query, params).fetchone()[0]

    # Query para dados com paginação
    data_query = f"SELECT * {base_query} {where_clause} ORDER BY data_despesa DESC, id DESC LIMIT :limit OFFSET :offset"
    params['limit'] = PER_PAGE
    params['offset'] = offset
    
    despesas = db.execute(data_query, params).fetchall()

    total_pages = math.ceil(total_items / PER_PAGE) if total_items > 0 else 1
    pagination = {
        "page": page, "total_pages": total_pages,
        "has_prev": page > 1, "has_next": page < total_pages
    }
    
    # Obter categorias únicas para o filtro
    categorias = db.execute("SELECT DISTINCT categoria FROM despesas WHERE categoria IS NOT NULL AND categoria != '' ORDER BY categoria").fetchall()
    
    # Calcular o total de despesas para o período filtrado
    total_despesas_periodo = db.execute(f"SELECT COALESCE(SUM(valor), 0) {base_query} {where_clause}", {k: v for k, v in params.items() if k not in ['limit', 'offset']}).fetchone()[0]

    return render_template('listar_despesas.html',
                           despesas=despesas,
                           pagination=pagination,
                           mes_filtro=mes_filtro,
                           ano_filtro=ano_filtro,
                           categoria_filtro=categoria_filtro,
                           categorias=categorias,
                           ano_atual=datetime.now().year, # Continua passando para o placeholder/max no HTML
                           total_despesas_periodo=total_despesas_periodo)

@app.route('/editar-despesa/<int:id>', methods=['GET', 'POST'])
@login_required
def editar_despesa(id):
    db = get_db()
    despesa = db.execute("SELECT * FROM despesas WHERE id = ?", (id,)).fetchone()

    if not despesa:
        flash("Despesa não encontrada.", "danger")
        return redirect(url_for('listar_despesas'))

    if request.method == 'POST':
        descricao = request.form['descricao'].strip()
        valor_str = request.form['valor']
        data_despesa_str = request.form['data_despesa']
        categoria = request.form.get('categoria', '').strip()
        observacoes = request.form.get('observacoes', '').strip()

        if not descricao or not valor_str or not data_despesa_str:
            flash("Descrição, Valor e Data da Despesa são campos obrigatórios.", "danger")
            # Recarrega a despesa original para passar de volta ao template
            return render_template('editar_despesa.html', despesa=despesa)

        try:
            valor = parse_number_from_br_form(valor_str)
            if valor <= 0:
                flash("O valor da despesa deve ser maior que R$ 0,00.", "danger")
                return render_template('editar_despesa.html', despesa=despesa)
            datetime.strptime(data_despesa_str, '%Y-%m-%d')
        except ValueError:
            flash("Formato de valor ou data inválido. Use o formato AAAA-MM-DD para a data.", "danger")
            return render_template('editar_despesa.html', despesa=despesa)

        try:
            db.execute(
                """
                UPDATE despesas
                SET data_despesa = ?, descricao = ?, valor = ?, categoria = ?, observacoes = ?
                WHERE id = ?
                """,
                (data_despesa_str, descricao, valor, categoria, observacoes, id)
            )
            db.commit()
            flash("Despesa atualizada com sucesso!", "success")
            return redirect(url_for('listar_despesas'))
        except Exception as e:
            db.rollback()
            app.logger.error(f"Erro ao atualizar despesa: {str(e)}", exc_info=True)
            flash(f"Erro ao atualizar despesa: {str(e)}", "danger")
            return render_template('editar_despesa.html', despesa=despesa)

    return render_template('editar_despesa.html', despesa=despesa)

@app.route('/excluir-despesa/<int:id>')
@login_required
def excluir_despesa(id):
    db = get_db()
    try:
        db.execute("DELETE FROM despesas WHERE id = ?", (id,))
        db.commit()
        flash("Despesa excluída com sucesso!", "success")
    except Exception as e:
        db.rollback()
        app.logger.error(f"Erro ao excluir despesa: {str(e)}", exc_info=True)
        flash("Erro ao excluir a despesa.", "danger")
    return redirect(url_for('listar_despesas'))

@app.route('/relatorio-financeiro')
@login_required
def relatorio_financeiro():
    db = get_db()
    
    # Pega os filtros do request. Se não houver, assume o ano atual como padrão e nenhum mês.
    mes_filtro = request.args.get('mes', '') # Agora vazio por padrão para "Todos os meses"
    ano_filtro = request.args.get('ano', str(datetime.now().year)) # Padrão é o ano atual

    MAX_FUTURE_YEARS = 20 # Limite superior para anos futuros

    try:
        # Validação do ano
        if ano_filtro:
            ano_int = int(ano_filtro)
            if not (1900 <= ano_int <= datetime.now().year + MAX_FUTURE_YEARS):
                flash(f"Ano inválido ou fora do intervalo permitido (1900 - {datetime.now().year + MAX_FUTURE_YEARS}).", "warning")
                ano_filtro = str(datetime.now().year) # Volta para o ano atual em caso de erro
        else: # Se o ano não for fornecido ou for vazio, use o ano atual como padrão para a query
            ano_filtro = str(datetime.now().year)

        # Validação do mês (se houver)
        if mes_filtro:
            if not (1 <= int(mes_filtro) <= 12):
                flash("Mês inválido.", "warning")
                mes_filtro = '' # Volta para "Todos os meses" se o mês for inválido

    except ValueError:
        flash("Filtro de data inválido. Resetando para o ano atual.", "warning")
        mes_filtro = ''
        ano_filtro = str(datetime.now().year)

    # Condições para as queries
    receitas_conditions = []
    despesas_conditions = []
    params = {}

    if mes_filtro:
        receitas_conditions.append("strftime('%m', data_pagamento) = :mes")
        despesas_conditions.append("strftime('%m', data_despesa) = :mes")
        params['mes'] = mes_filtro.zfill(2) # Garante que o mês tenha 2 dígitos (ex: '01', '02')
        
    if ano_filtro:
        receitas_conditions.append("strftime('%Y', data_pagamento) = :ano")
        despesas_conditions.append("strftime('%Y', data_despesa) = :ano")
        params['ano'] = ano_filtro

    # Monta a cláusula WHERE
    receitas_where_clause = " WHERE " + " AND ".join(receitas_conditions) if receitas_conditions else ""
    despesas_where_clause = " WHERE " + " AND ".join(despesas_conditions) if despesas_conditions else ""

    # Query para total de receitas (pagamentos)
    receitas_query = f"""
        SELECT COALESCE(SUM(valor_pago), 0)
        FROM pagamentos
        {receitas_where_clause}
    """
    total_receitas = db.execute(receitas_query, params).fetchone()[0]

    # Query para total de despesas
    despesas_query = f"""
        SELECT COALESCE(SUM(valor), 0)
        FROM despesas
        {despesas_where_clause}
    """
    total_despesas = db.execute(despesas_query, params).fetchone()[0]

    saldo = total_receitas - total_despesas

    return render_template('relatorio_financeiro.html',
                           total_receitas=total_receitas,
                           total_despesas=total_despesas,
                           saldo=saldo,
                           mes_filtro=mes_filtro, # Retorna o valor do filtro para manter no select
                           ano_filtro=ano_filtro, # Retorna o valor do filtro para manter no input
                           ano_atual=datetime.now().year) # Para usar no placeholder/max do input de ano

@app.route('/gerar-pdf/relatorio-financeiro')
@login_required
def gerar_pdf_relatorio_financeiro():
    """
    Gera um PDF do relatório financeiro com base nos filtros aplicados.
    """
    db = get_db()
    mes_filtro = request.args.get('mes', '')
    ano_filtro = request.args.get('ano', str(datetime.now().year))

    # Reutiliza a mesma lógica de cálculo da rota 'relatorio_financeiro'
    receitas_conditions = []
    despesas_conditions = []
    params = {}

    if mes_filtro:
        receitas_conditions.append("strftime('%m', data_pagamento) = :mes")
        despesas_conditions.append("strftime('%m', data_despesa) = :mes")
        params['mes'] = mes_filtro.zfill(2)
    
    if ano_filtro:
        receitas_conditions.append("strftime('%Y', data_pagamento) = :ano")
        despesas_conditions.append("strftime('%Y', data_despesa) = :ano")
        params['ano'] = ano_filtro

    receitas_where_clause = " WHERE " + " AND ".join(receitas_conditions) if receitas_conditions else ""
    despesas_where_clause = " WHERE " + " AND ".join(despesas_conditions) if despesas_conditions else ""

    receitas_query = f"SELECT COALESCE(SUM(valor_pago), 0) FROM pagamentos {receitas_where_clause}"
    total_receitas = db.execute(receitas_query, params).fetchone()[0]

    despesas_query = f"SELECT COALESCE(SUM(valor), 0) FROM despesas {despesas_where_clause}"
    total_despesas = db.execute(despesas_query, params).fetchone()[0]

    saldo = total_receitas - total_despesas
    
    # Renderiza o mesmo template, mas com uma flag para o PDF
    html_string = render_template(
        'relatorio_financeiro.html',
        total_receitas=total_receitas,
        total_despesas=total_despesas,
        saldo=saldo,
        mes_filtro=mes_filtro,
        ano_filtro=ano_filtro,
        ano_atual=datetime.now().year,
        is_pdf=True  # Flag para o template saber que é uma renderização para PDF
    )
    
    pdf = HTML(string=html_string).write_pdf()
    
    return Response(
        pdf,
        mimetype='application/pdf',
        headers={'Content-Disposition': 'inline; filename=relatorio_financeiro.pdf'}
    )

# --- Inicialização da Aplicação ---
if __name__ == '__main__':
    # Cria a pasta de uploads se não existir
    if not os.path.exists(app.config['UPLOAD_FOLDER']):
        os.makedirs(app.config['UPLOAD_FOLDER'])
        
    # No seu app.py, substitua sua função init_db por esta:

def init_db():
    with app.app_context():
        db = get_db()
        # Abre o arquivo schema.sql e executa os comandos para criar as tabelas
        with app.open_resource('schema.sql', mode='r') as f:
            db.cursor().executescript(f.read().decode('utf8'))
        
        # AGORA, INSERE O USUÁRIO ADMIN DIRETAMENTE AQUI NO CÓDIGO
        try:
            db.execute(
                """INSERT INTO usuarios_admin (username, senha_hash, email) VALUES (?, ?, ?)""",
                (
                    'admin',
                    generate_password_hash('admin123'), # Gera o hash na hora
                    'admin@example.com'
                )
            )
            print("Usuário 'admin' padrão inserido com sucesso pelo app.py.")
        except sqlite3.IntegrityError:
            # Isso evita um erro caso a função seja rodada mais de uma vez
            print("Usuário 'admin' já existia.")

        db.commit()
    print("Database initialized successfully.")
    
    # Rodar a aplicação em modo debug para desenvolvimento
    app.run(debug=True)