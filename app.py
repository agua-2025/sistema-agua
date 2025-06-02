from flask import Flask, render_template, request, redirect, url_for, session, g, jsonify, flash
import sqlite3
from werkzeug.security import check_password_hash, generate_password_hash
import os
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
from datetime import datetime
import secrets
import smtplib
from flask import make_response
from email.mime.text import MIMEText
from email.utils import formataddr
from flask import send_file
def enviar_email(destino, assunto, corpo):
    msg = MIMEText(corpo, 'plain', 'utf-8')
    msg['Subject'] = assunto
    msg['From'] = formataddr(('Águas de Santa Maria', 'seu-email@gmail.com'))
    msg['To'] = destino

    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login('vivendamirassol@gmail.com', 'aaof orcx ogvk ensm')
            server.sendmail(msg['From'], [destino], msg.as_string())
        return True
    except Exception as e:
        print(f"❌ Erro ao enviar e-mail: {e}")
        return False

app = Flask(__name__)
app.secret_key = 'chave-super-secreta'
DATABASE = 'a_g_santa_maria.db'
import os
from werkzeug.utils import secure_filename

UPLOAD_FOLDER = 'static/fotos_hidrometros'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ---------- Conexão com o Banco ----------
def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(error):
    if 'db' in g:
        g.db.close()

def atualizar_leituras_quitadas():
    db = get_db()
    db.execute("""
        UPDATE leituras
        SET status_pagamento = 'Pago'
        WHERE id IN (
            SELECT l.id
            FROM leituras l
            LEFT JOIN (
                SELECT leitura_id, SUM(valor_pago) AS total_pago
                FROM pagamentos
                GROUP BY leitura_id
            ) pag ON pag.leitura_id = l.id
            WHERE pag.total_pago >= l.valor_original
              AND l.status_pagamento != 'Pago'
        )
    """)
    db.commit()


# ---------- Rotas de Autenticação ----------
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
            return redirect(url_for('dashboard'))
        else:
            error = 'Usuário ou senha inválidos.'
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.pop('usuario', None)
    return redirect(url_for('login'))

# ---------- Dashboard ----------
@app.route('/dashboard')
def dashboard():
    if 'usuario' in session:
        return render_template('dashboard.html', user=session['usuario'])
    return redirect(url_for('login'))

# ---------- Configurações do Sistema ----------
@app.route('/configuracoes', methods=['GET', 'POST'])
def configuracoes():
    if 'usuario' not in session:
        return redirect(url_for('login'))
    db = get_db()
    mensagem = None
    if request.method == 'POST':
        form = request.form
        hidr_geral_anterior = int(form['hidr_geral_anterior'])
        hidr_geral_atual = int(form['hidr_geral_atual'])
        valor_litro = float(form['valor_litro'])
        taxa_minima_consumo = float(form['taxa_minima_consumo'])
        data_ultima_config = form['data_ultima_config']
        dias_uteis_para_vencimento = int(form['dias_uteis_para_vencimento'])
        # Novos campos
        multa_percentual = float(form.get('multa_percentual', 0))
        juros_diario_percentual = float(form.get('juros_diario_percentual', 0))
        consumo_geral = hidr_geral_atual - hidr_geral_anterior
        db.execute("""
            INSERT INTO configuracoes (
                hidr_geral_anterior,
                hidr_geral_atual,
                consumo_geral,
                valor_litro,
                taxa_minima_consumo,
                data_ultima_config,
                dias_uteis_para_vencimento,
                multa_percentual,
                juros_diario_percentual
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            hidr_geral_anterior,
            hidr_geral_atual,
            consumo_geral,
            valor_litro,
            taxa_minima_consumo,
            data_ultima_config,
            dias_uteis_para_vencimento,
            multa_percentual,
            juros_diario_percentual
        ))
        db.commit()
        mensagem = "Configuração salva com sucesso!"
    # Buscar a última configuração salva
    config = db.execute("SELECT * FROM configuracoes ORDER BY id DESC LIMIT 1").fetchone()
    return render_template('configuracoes.html', config=config, mensagem=mensagem)

# ---------- CRUD Consumidores ----------
@app.route('/cadastrar-consumidor', methods=['GET', 'POST'])
def cadastrar_consumidor():
    if 'usuario' not in session:
        return redirect(url_for('login'))
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
            return redirect(url_for('dashboard'))
        except sqlite3.IntegrityError:
            error = "CPF ou número do hidrômetro já cadastrado. Verifique os dados e tente novamente."
    return render_template('cadastrar_consumidor.html', error=error)

@app.route('/listar-pagamentos')
def listar_pagamentos():
    if 'usuario' not in session:
        return redirect(url_for('login'))
    db = get_db()
    pagamentos = db.execute("""
        SELECT p.*, c.nome, l.valor_original, l.vencimento
        FROM pagamentos p
        JOIN leituras l ON l.id = p.leitura_id
        JOIN consumidores c ON c.id = l.consumidor_id
        ORDER BY p.data_pagamento DESC
    """).fetchall()
    return render_template('listar_pagamentos.html', pagamentos=pagamentos)

@app.route('/listar-consumidores')
def listar_consumidores():
    if 'usuario' not in session:
        return redirect(url_for('login'))
    db = get_db()
    consumidores = db.execute("SELECT * FROM consumidores").fetchall()
    return render_template('consumidores.html', consumidores=consumidores)

def adicionar_dias_uteis(data_inicial, dias_uteis):
    dias_adicionados = 0
    data_final = data_inicial
    while dias_adicionados < dias_uteis:
        data_final += timedelta(days=1)
        if data_final.weekday() < 5:  # segunda a sexta
            dias_adicionados += 1
    return data_final

# ---------- Cadastro de Leitura ----------
@app.route('/cadastrar-leitura', methods=['GET', 'POST'])
def cadastrar_leitura():
    if 'usuario' not in session:
        return redirect(url_for('login'))
    db = get_db()
    if request.method == 'POST':
        form = request.form
        consumidor_id = form['consumidor_id']
        leitura_anterior = int(form['leitura_anterior'])
        leitura_atual = int(form['leitura_atual'])
        data_leitura_anterior = form['data_leitura_anterior']
        data_leitura_atual = form['data_leitura_atual']
        qtd_dias_utilizados = int(form['qtd_dias_utilizados']) if form['qtd_dias_utilizados'] else 0
        litros_consumidos = int(form['litros_consumidos']) if form['litros_consumidos'] else 0
        media_por_dia = float(form['media_por_dia']) if form['media_por_dia'] else 0.0
        taxa_minima_aplicada = form['taxa_minima_aplicada']
        valor_taxa_minima = float(form['valor_taxa_minima']) if form['valor_taxa_minima'] else 0.0
        status_pagamento = form['status_pagamento']

        config = db.execute("SELECT valor_litro, dias_uteis_para_vencimento FROM configuracoes ORDER BY id DESC LIMIT 1").fetchone()
        valor_litro = float(config['valor_litro']) if config else 0.0
        dias_uteis_para_vencimento = int(config['dias_uteis_para_vencimento']) if config else 5

        valor_original = litros_consumidos * valor_litro
        data_leitura_dt = datetime.strptime(data_leitura_atual, '%Y-%m-%d')
        vencimento_dt = adicionar_dias_uteis(data_leitura_dt, dias_uteis_para_vencimento)
        vencimento = vencimento_dt.strftime('%Y-%m-%d')

        foto = request.files.get('foto_hidrometro')
        nome_arquivo = None

        if foto and foto.filename:
            if allowed_file(foto.filename):
                nome_arquivo = secure_filename(foto.filename)
                caminho_completo = os.path.join(app.config['UPLOAD_FOLDER'], nome_arquivo)
                foto.save(caminho_completo)
            else:
                flash("Tipo de arquivo inválido. Use imagens válidas.", "error")

        db.execute("""
            INSERT INTO leituras (
                consumidor_id, leitura_anterior, data_leitura_anterior,
                leitura_atual, data_leitura_atual, qtd_dias_utilizados,
                litros_consumidos, media_por_dia, foto_hidrometro,
                vencimento, valor_original, taxa_minima_aplicada,
                valor_taxa_minima, status_pagamento
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            consumidor_id, leitura_anterior, data_leitura_anterior,
            leitura_atual, data_leitura_atual, qtd_dias_utilizados,
            litros_consumidos, media_por_dia, nome_arquivo,
            vencimento, valor_original, taxa_minima_aplicada,
            valor_taxa_minima, status_pagamento
        ))
        db.commit()
        return redirect(url_for('dashboard'))

    # --- GET ---
    consumidores = db.execute("SELECT id, nome, hidrometro_num FROM consumidores").fetchall()
    consumidor_id = request.args.get('consumidor_id')
    leitura_anterior = 0
    data_leitura_anterior = ''
    qtd_dias_utilizados = 0
    litros_consumidos = 0
    media_por_dia = 0.0
    vencimento = ''

    if consumidor_id:
        ultima_leitura = db.execute("""
            SELECT leitura_atual, data_leitura_atual
            FROM leituras
            WHERE consumidor_id = ?
            ORDER BY id DESC
            LIMIT 1
        """, (consumidor_id,)).fetchone()
        if ultima_leitura:
            leitura_anterior = ultima_leitura['leitura_atual']
            data_leitura_anterior = ultima_leitura['data_leitura_atual']
            try:
                hoje = datetime.today().strftime('%Y-%m-%d')
                config = db.execute("SELECT dias_uteis_para_vencimento FROM configuracoes ORDER BY id DESC LIMIT 1").fetchone()
                dias_uteis = int(config['dias_uteis_para_vencimento']) if config else 5
                vencimento = adicionar_dias_uteis(hoje, dias_uteis)
            except:
                vencimento = ''
    
    return render_template(
        'cadastrar_leitura.html',
        consumidores=consumidores,
        consumidor_selecionado=int(consumidor_id) if consumidor_id else None,
        leitura_anterior=leitura_anterior,
        data_leitura_anterior=data_leitura_anterior,
        qtd_dias_utilizados=qtd_dias_utilizados,
        litros_consumidos=litros_consumidos,
        media_por_dia=media_por_dia,
        vencimento=vencimento
    )
#--------------------------------Dias Uteis Após Vencimento--------------------------------------------------------------
@app.route('/api/dias_uteis')
def api_dias_uteis():
    db = get_db()
    config = db.execute("SELECT dias_uteis_para_vencimento FROM configuracoes ORDER BY id DESC LIMIT 1").fetchone()
    dias = int(config['dias_uteis_para_vencimento']) if config else 5
    return jsonify({'dias_uteis': dias})

#------------------Registrar Pagamento-----------------------
@app.route('/registrar-pagamento', methods=['GET', 'POST'])
def registrar_pagamento():
    if 'usuario' not in session:
        return redirect(url_for('login'))
    db = get_db()
    if request.method == 'POST':
        try:
            # Validação dos dados de entrada
            campos_obrigatorios = ['consumidor_id', 'leitura_id', 'data_pagamento', 'forma_pagamento', 'valor_pago']
            if not all(campo in request.form for campo in campos_obrigatorios):
                flash('Dados incompletos no formulário', 'error')
                return redirect(url_for('registrar_pagamento'))
            # Obter e validar valores
            consumidor_id = request.form['consumidor_id']
            leitura_id = request.form['leitura_id']
            data_pagamento = request.form['data_pagamento']
            forma_pagamento = request.form['forma_pagamento']
            try:
                valor_pago = round(float(request.form['valor_pago']), 2)
                if valor_pago <= 0:
                    raise ValueError
            except ValueError:
                flash('Valor de pagamento inválido', 'error')
                return redirect(url_for('registrar_pagamento'))
            # Consulta da leitura
            leitura = db.execute('''
                SELECT l.id, l.valor_original, l.vencimento, l.status_pagamento,
                       COALESCE(SUM(p.valor_pago), 0) AS total_pago_anterior
                FROM leituras l
                LEFT JOIN pagamentos p ON p.leitura_id = l.id
                WHERE l.id = ?
                GROUP BY l.id
            ''', (leitura_id,)).fetchone()
            if not leitura:
                flash('Leitura não encontrada', 'error')
                return redirect(url_for('registrar_pagamento'))
            valor_original = round(float(leitura['valor_original']), 2)
            total_pago_anterior = round(float(leitura['total_pago_anterior']), 2)
            # Verificar se já foi pago
            if leitura['status_pagamento'] == 'Pago' or total_pago_anterior >= valor_original:
                flash(f'Esta leitura já foi quitada (Total pago: R$ {total_pago_anterior:.2f})', 'warning')
                return redirect(url_for('listar_pagamentos'))
            # Cálculo de dias em atraso
            try:
                vencimento = datetime.strptime(leitura['vencimento'], '%Y-%m-%d').date()
                data_pagamento_dt = datetime.strptime(data_pagamento, '%Y-%m-%d').date()
                dias_atraso = max((data_pagamento_dt - vencimento).days, 0)
            except (ValueError, TypeError):
                flash('Formato de data inválido', 'error')
                return redirect(url_for('registrar_pagamento'))
            # Obter configurações
            config = db.execute('''
                SELECT COALESCE(multa_percentual, 2.0) AS multa_percentual,
                       COALESCE(juros_diario_percentual, 0.1) AS juros_diario_percentual
                FROM configuracoes 
                ORDER BY id DESC 
                LIMIT 1
            ''').fetchone()
            # Cálculos financeiros
            multa = round(valor_original * config['multa_percentual'] / 100, 2) if dias_atraso > 0 else 0.0
            juros = round(valor_original * ((1 + config['juros_diario_percentual']/100) ** dias_atraso - 1), 2) if dias_atraso > 0 else 0.0
            total_corrigido = round(valor_original + multa + juros, 2)
            novo_total_pago = round(total_pago_anterior + valor_pago, 2)
            # Validação de valor
            if valor_pago > total_corrigido * 1.1:  # Permite até 10% a mais
                flash(f'Valor pago (R$ {valor_pago:.2f}) excede o valor devido (R$ {total_corrigido:.2f})', 'error')
                return redirect(url_for('registrar_pagamento'))
            # Registrar transação
            db.execute('''
                INSERT INTO pagamentos 
                (leitura_id, consumidor_id, data_pagamento, forma_pagamento, valor_pago)
                VALUES (?, ?, ?, ?, ?)
            ''', (leitura_id, consumidor_id, data_pagamento, forma_pagamento, valor_pago))
            # Atualizar status
            novo_status = 'Pago' if novo_total_pago >= valor_original else 'Pendente'
            db.execute('UPDATE leituras SET status_pagamento = ? WHERE id = ?', (novo_status, leitura_id))
            db.commit()
            flash(f'Pagamento de R$ {valor_pago:.2f} registrado com sucesso!', 'success')
            return redirect(url_for('detalhes_pagamento', leitura_id=leitura_id))
        except Exception as e:
            db.rollback()
            app.logger.error(f'Erro no pagamento: {str(e)}', exc_info=True)
            flash('Erro ao processar pagamento. Tente novamente.', 'error')
            return redirect(url_for('registrar_pagamento'))

    # Método GET
    try:
        consumidores = db.execute('SELECT id, nome FROM consumidores ORDER BY nome').fetchall()
        leituras = db.execute('''
            SELECT l.*, c.nome AS consumidor_nome,
                   COALESCE(SUM(p.valor_pago), 0) AS total_pago
            FROM leituras l
            JOIN consumidores c ON c.id = l.consumidor_id
            LEFT JOIN pagamentos p ON p.leitura_id = l.id
            WHERE l.status_pagamento = 'Pendente'
            GROUP BY l.id
            ORDER BY l.data_leitura_atual DESC
        ''').fetchall()
        return render_template('registrar_pagamento.html',
                             consumidores=consumidores,
                             leituras=leituras)
    except Exception as e:
        app.logger.error(f'Erro ao carregar formulário: {str(e)}', exc_info=True)
        flash('Erro ao carregar dados do formulário', 'error')
        return redirect(url_for('dashboard'))

# ---------- API para retornar leituras por consumidor ----------
@app.route('/api/leituras/<int:consumidor_id>')
def api_leituras(consumidor_id):
    if 'usuario' not in session:
        return jsonify({'erro': 'Não autorizado'}), 401

    db = get_db()

    try:
        # Consulta as leituras do consumidor
        leituras = db.execute("""
            SELECT 
                l.id, 
                l.data_leitura_atual, 
                l.valor_original, 
                l.vencimento, 
                l.status_pagamento,
                IFNULL(SUM(p.valor_pago), 0) AS total_pago
            FROM leituras l
            LEFT JOIN pagamentos p ON p.leitura_id = l.id
            WHERE l.consumidor_id = ?
            GROUP BY l.id
            HAVING l.status_pagamento = 'Pendente' OR total_pago < l.valor_original
            ORDER BY l.data_leitura_atual DESC
        """, (consumidor_id,)).fetchall()

        # Se não houver leituras, retorna lista vazia
        if not leituras:
            return jsonify([])

        # Monta o resultado com os dados formatados
        resultado = []
        for l in leituras:
            valor_original = float(l['valor_original']) if l['valor_original'] else 0.0
            total_pago = float(l['total_pago']) if l['total_pago'] else 0.0

            resultado.append({
                'id': l['id'],
                'data_leitura_atual': l['data_leitura_atual'],
                'valor_original': round(valor_original, 2),
                'vencimento': l['vencimento'],
                'status_pagamento': l['status_pagamento'],
                'faltando': round(max(valor_original - total_pago, 0), 2)
            })

        return jsonify(resultado)

    except Exception as e:
        app.logger.error(f"Erro ao buscar leituras via API: {str(e)}")
        return jsonify({'erro': 'Erro interno no servidor'}), 500

# ----------- API para Detalhes da Leitura (usado no JS de registrar_pagamento) -----------
@app.route('/api/leitura-detalhada/<int:leitura_id>')
def api_leitura_detalhada(leitura_id):
    if 'usuario' not in session:
        return jsonify({'erro': 'Não autorizado'}), 401
    db = get_db()
    try:
        leitura = db.execute('''
            SELECT 
                l.id,
                l.valor_original,
                l.vencimento,
                c.nome,
                IFNULL(SUM(p.valor_pago), 0) AS total_pago,
                (SELECT multa_percentual FROM configuracoes ORDER BY id DESC LIMIT 1) AS multa_percentual,
                (SELECT juros_diario_percentual FROM configuracoes ORDER BY id DESC LIMIT 1) AS juros_diario_percentual
            FROM leituras l
            JOIN consumidores c ON c.id = l.consumidor_id
            LEFT JOIN pagamentos p ON p.leitura_id = l.id
            WHERE l.id = ?
            GROUP BY l.id
        ''', (leitura_id,)).fetchone()
        if not leitura:
            return jsonify({'erro': 'Leitura não encontrada'}), 404
        # Calcula dias em atraso
        dias_atraso = 0
        if leitura['vencimento']:
            try:
                vencimento = datetime.strptime(leitura['vencimento'], '%Y-%m-%d').date()
                dias_atraso = max((datetime.now().date() - vencimento).days, 0)
            except:
                dias_atraso = 0
        response_data = {
            'id': leitura['id'],
            'nome': leitura['nome'],
            'valor_original': float(leitura['valor_original']),
            'vencimento': leitura['vencimento'],
            'total_pago': float(leitura['total_pago']),
            'multa_percentual': float(leitura['multa_percentual']),
            'juros_diario_percentual': float(leitura['juros_diario_percentual']),
            'dias_atraso': dias_atraso,
            'saldo_devedor': max(float(leitura['valor_original']) - float(leitura['total_pago']), 0)
        }
        return jsonify(response_data)
    except Exception as e:
        print(f"Erro na API leitura-detalhada: {str(e)}")
        return jsonify({'erro': 'Erro interno no servidor'}), 500

# ---------- API para retornar o valor do litro atual ----------
@app.route('/api/valor_litro')
def api_valor_litro():
    db = get_db()
    config = db.execute("SELECT valor_litro FROM configuracoes ORDER BY id DESC LIMIT 1").fetchone()
    return jsonify({'valor_litro': float(config['valor_litro']) if config else 0.0})


#-------------Detalhes do Pagamento-------------------
@app.route('/detalhes-pagamento')
def detalhes_pagamento():
    if 'usuario' not in session:
        return redirect(url_for('login'))

    leitura_id = request.args.get('leitura_id')
    if not leitura_id:
        flash('Nenhum pagamento selecionado', 'error')
        return redirect(url_for('listar_pagamentos'))

    db = get_db()
    pagamento = db.execute('''
        SELECT 
            p.*, 
            l.valor_original,
            l.vencimento,
            l.leitura_anterior,
            l.leitura_atual,
            l.data_leitura_anterior,
            l.data_leitura_atual,
            c.nome AS consumidor_nome,
            c.endereco AS consumidor_endereco,
            c.hidrometro_num AS hidrometro,
            (SELECT multa_percentual FROM configuracoes ORDER BY id DESC LIMIT 1) AS multa_percentual,
            (SELECT juros_diario_percentual FROM configuracoes ORDER BY id DESC LIMIT 1) AS juros_diario_percentual
        FROM pagamentos p
        JOIN leituras l ON p.leitura_id = l.id
        JOIN consumidores c ON l.consumidor_id = c.id
        WHERE p.leitura_id = ?
        ORDER BY p.data_pagamento DESC
        LIMIT 1
    ''', (leitura_id,)).fetchone()

    if not pagamento:
        flash('Pagamento não encontrado', 'error')
        return redirect(url_for('listar_pagamentos'))

    # Cálculos adicionais
    dias_atraso = 0
    juros = 0.0
    multa = 0.0
    litros_consumidos = 0
    periodo_consumo = None

    try:
        if pagamento['vencimento']:
            vencimento = datetime.strptime(pagamento['vencimento'], '%Y-%m-%d').date()
            data_pag = datetime.strptime(pagamento['data_pagamento'], '%Y-%m-%d').date()
            dias_atraso = max((data_pag - vencimento).days, 0)

        if dias_atraso > 0:
            juros_diario = pagamento['juros_diario_percentual'] / 100
            juros = round(pagamento['valor_original'] * ((1 + juros_diario) ** dias_atraso - 1), 2)
            multa = round(pagamento['valor_original'] * (pagamento['multa_percentual'] / 100), 2)

        leitura_anterior = float(pagamento['leitura_anterior']) if pagamento['leitura_anterior'] else 0
        leitura_atual = float(pagamento['leitura_atual']) if pagamento['leitura_atual'] else 0
        litros_consumidos = abs(leitura_atual - leitura_anterior)

        if pagamento['data_leitura_anterior'] and pagamento['data_leitura_atual']:
            inicio = datetime.strptime(pagamento['data_leitura_anterior'], '%Y-%m-%d').strftime('%d/%m/%Y')
            fim = datetime.strptime(pagamento['data_leitura_atual'], '%Y-%m-%d').strftime('%d/%m/%Y')
            periodo_consumo = f"{inicio} a {fim}"

    except Exception as e:
        app.logger.warning(f"Erro ao calcular dados adicionais: {str(e)}")

    return render_template(
        'detalhes_pagamento.html',
        pagamento=pagamento,
        litros_consumidos=litros_consumidos,
        dias_atraso=dias_atraso,
        multa=multa,
        juros=juros,
        periodo_consumo=periodo_consumo
    )

# ---------- Recuperação de Senha ----------
@app.route('/recuperar-senha', methods=['POST'])
def recuperar_senha():
    print("\n=== INÍCIO DA SOLICITAÇÃO ===")
    email = request.form.get('email', '').strip().lower()
    print(f"📧 Email recebido: '{email}'")

    db = get_db()
    try:
        user = db.execute(
            'SELECT id FROM usuarios_admin WHERE email = ?', 
            (email,)
        ).fetchone()

        if not user:
            print("❌ Nenhum usuário encontrado com este email!")
            flash("E-mail não cadastrado.", "error")
            return redirect(url_for('login'))

        token = secrets.token_urlsafe(50)
        expires_at = datetime.now() + timedelta(hours=1)
        expires_at_str = expires_at.strftime('%Y-%m-%d %H:%M:%S')

        # Atualiza o banco com token e expiração
        db.execute("""
            UPDATE usuarios_admin 
            SET reset_token = ?, reset_expira_em = ? 
            WHERE id = ?
        """, (token, expires_at_str, user['id']))
        db.commit()
        print(f"🔑 Token gerado: {token}")

        # Gera o link
        reset_link = url_for('redefinir_senha_form', token=token, _external=True)
        print(f"🔗 LINK PARA REDEFINIR:\n{reset_link}")

        # Envia o e-mail
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
            flash("Erro ao enviar e-mail. Verifique suas configurações.", "error")

        return redirect(url_for('login'))

    except Exception as e:
        app.logger.error(f"🔥 Erro ao processar recuperação de senha: {str(e)}")
        flash("Ocorreu um erro ao processar sua solicitação.", "error")
        return redirect(url_for('login'))

    except Exception as e:
        app.logger.error(f"🔥 Erro ao processar recuperação de senha: {str(e)}")
        return redirect(url_for('login', message='Erro no servidor'))

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
        return render_template('redefinir_senha.html',
                               token=token,
                               error="Senha deve ter pelo menos 6 caracteres.")

    if nova_senha != confirmar_senha:
        return render_template('redefinir_senha.html',
                               token=token,
                               error="As senhas não coincidem.")

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
            return render_template('redefinir_senha.html',
                                   token=token,
                                   error="Link inválido ou expirado.")
    except Exception as e:
        app.logger.error(f"🔥 Erro ao atualizar senha: {str(e)}")
        return render_template('redefinir_senha.html',
                               token=token,
                               error="Ocorreu um erro. Tente novamente mais tarde.")
from werkzeug.security import generate_password_hash

#---------------------------Cadastrar Usuário------------------------------------------
@app.route('/cadastrar-usuario', methods=['GET', 'POST'])
def cadastrar_usuario():
    if 'usuario' not in session:
        return redirect(url_for('login'))

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
            # Verifica se já existe esse usuário ou e-mail
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

            # Salva no banco com senha hash
            db.execute("""
                INSERT INTO usuarios_admin (username, senha_hash, email)
                VALUES (?, ?, ?)
            """, (username, generate_password_hash(password), email))
            db.commit()
            flash("Usuário cadastrado com sucesso!", "success")
            return redirect(url_for('dashboard'))

        except Exception as e:
            db.rollback()
            app.logger.error(f"Erro ao cadastrar usuário: {str(e)}")
            flash("Ocorreu um erro ao cadastrar o usuário.", "error")
            return redirect(url_for('cadastrar_usuario'))

    return render_template('cadastrar_usuario.html')

#----------------Editar Consumidor----------------------------
@app.route('/editar-consumidor/<int:id>', methods=['GET', 'POST'])
def editar_consumidor(id):
    if 'usuario' not in session:
        return redirect(url_for('login'))

    db = get_db()
    # Busca o consumidor pelo ID
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

    return render_template('editar_consumidor.html', consumidor=consumidor)

#-------------------------Excluir Consumidor---------------------------------
@app.route('/excluir-consumidor/<int:id>')
def excluir_consumidor(id):
    if 'usuario' not in session:
        return redirect(url_for('login'))

    db = get_db()
    try:
        db.execute("DELETE FROM consumidores WHERE id = ?", (id,))
        db.commit()
        flash("Consumidor excluído com sucesso!", "success")
    except Exception as e:
        db.rollback()
        app.logger.error(f"Erro ao excluir consumidor: {str(e)}")
        flash("Erro ao excluir o consumidor.", "error")

    return redirect(url_for('listar_consumidores'))

#--------------Comprovante PDF--------------
@app.route('/gerar-comprovante-pdf/<int:leitura_id>')
def gerar_comprovante_pdf(leitura_id):
    if 'usuario' not in session:
        return redirect(url_for('login'))

    db = get_db()
    pagamento = db.execute('''
        SELECT 
            p.*, 
            l.valor_original,
            l.vencimento,
            l.leitura_anterior,
            l.leitura_atual,
            l.data_leitura_anterior,
            l.data_leitura_atual,
            c.nome AS consumidor_nome,
            c.endereco AS consumidor_endereco,
            c.hidrometro_num AS hidrometro,
            (SELECT multa_percentual FROM configuracoes ORDER BY id DESC LIMIT 1) AS multa_percentual,
            (SELECT juros_diario_percentual FROM configuracoes ORDER BY id DESC LIMIT 1) AS juros_diario_percentual
        FROM pagamentos p
        JOIN leituras l ON p.leitura_id = l.id
        JOIN consumidores c ON l.consumidor_id = c.id
        WHERE p.leitura_id = ?
        ORDER BY p.data_pagamento DESC
        LIMIT 1
    ''', (leitura_id,)).fetchone()
    
    if not pagamento:
        return 'Comprovante não encontrado', 404

    # Cálculo de multa e juros
    dias_atraso = 0
    juros = 0.0
    multa = 0.0
    if pagamento['vencimento']:
        try:
            vencimento = datetime.strptime(pagamento['vencimento'], '%Y-%m-%d').date()
            data_pag = datetime.strptime(pagamento['data_pagamento'], '%Y-%m-%d').date()
            dias_atraso = max((data_pag - vencimento).days, 0)
            if dias_atraso > 0:
                juros_diario = pagamento['juros_diario_percentual'] / 100
                juros = round(pagamento['valor_original'] * ((1 + juros_diario) ** dias_atraso - 1), 2)
                multa = round(pagamento['valor_original'] * (pagamento['multa_percentual'] / 100), 2)
        except Exception as e:
            print("Erro ao calcular multa/juros:", e)

    # Calcular litros consumidos
    litros_consumidos = 0
    try:
        leitura_anterior = float(pagamento['leitura_anterior']) if pagamento['leitura_anterior'] else 0
        leitura_atual = float(pagamento['leitura_atual']) if pagamento['leitura_atual'] else 0
        litros_consumidos = abs(leitura_atual - leitura_anterior)
    except Exception as e:
        print("Erro ao calcular litros consumidos:", e)

    # Renderizar HTML para PDF
    try:
        rendered = render_template('detalhes_pagamento.html',
                                   pagamento=pagamento,
                                   dias_atraso=dias_atraso,
                                   juros=juros,
                                   multa=multa,
                                   litros_consumidos=litros_consumidos)

        import pdfkit
        config = pdfkit.configuration(wkhtmltopdf=r'C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe')

        pdf = pdfkit.from_string(rendered, False, configuration=config)

        response = make_response(pdf)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename=comprovante_{leitura_id}.pdf'
        return response

    except Exception as e:
        return f'Erro ao gerar PDF: {e}', 500


#--------------------Relatórios Consumidores------------------------
from flask import request, session, redirect, url_for, render_template
from datetime import datetime

@app.route('/relatorio-consumidores')
def relatorio_consumidores():
    if 'usuario' not in session:
        return redirect(url_for('login'))
    
    db = get_db()

    # Receber parâmetros de filtro
    mes_filtro = request.args.get('mes')
    ano_filtro = request.args.get('ano')

    # Validar ano futuro (opcional)
    try:
        if ano_filtro and int(ano_filtro) > datetime.now().year:
            return render_template(
                'relatorio_consumidores.html',
                consumidores=[],
                mes_filtro=mes_filtro,
                ano_filtro=ano_filtro,
                ano_atual=datetime.now().year,
                total_consumidores=0,
                consumidores_com_leituras=0,
                mensagem_erro="Não é possível filtrar por períodos futuros."
            )
    except ValueError:
        pass  # Ignora erro se o ano não for número

    # Montar condições de filtro
    filtro_subconsulta = ""
    filtro_principal = ""
    params_subconsulta = []
    params_principal = []

    if mes_filtro and ano_filtro:
        filtro_subconsulta += " AND strftime('%m', data_leitura_atual) = ?"
        filtro_subconsulta += " AND strftime('%Y', data_leitura_atual) = ?"
        params_subconsulta.extend([mes_filtro, ano_filtro])
        filtro_principal = filtro_subconsulta
        params_principal = params_subconsulta.copy()
    elif mes_filtro:
        filtro_subconsulta += " AND strftime('%m', data_leitura_atual) = ?"
        params_subconsulta.append(mes_filtro)
        filtro_principal = filtro_subconsulta
        params_principal = params_subconsulta.copy()
    elif ano_filtro:
        filtro_subconsulta += " AND strftime('%Y', data_leitura_atual) = ?"
        params_subconsulta.append(ano_filtro)
        filtro_principal = filtro_subconsulta
        params_principal = params_subconsulta.copy()

    # Consulta principal - traz consumidor + sua ÚLTIMA leitura no PERÍODO
    query = f"""
        SELECT 
            c.id AS consumidor_id,
            c.nome,
            c.cpf,
            c.endereco,
            c.telefone,
            c.hidrometro_num,
            l.leitura_anterior,
            l.leitura_atual,
            l.data_leitura_atual,
            l.foto_hidrometro,
            l.status_pagamento
        FROM consumidores c
        LEFT JOIN (
            SELECT *
            FROM leituras
            WHERE id IN (
                SELECT MAX(id)
                FROM leituras
                WHERE 1=1 {filtro_subconsulta}
                GROUP BY consumidor_id
            )
        ) l ON c.id = l.consumidor_id
        ORDER BY c.nome
    """

    consumidores = db.execute(query, params_principal).fetchall()

    # Contagem de consumidores totais
    total_consumidores = db.execute("SELECT COUNT(*) FROM consumidores").fetchone()[0]

    # Contagem de consumidores com leituras no período
    query_contagem = """
        SELECT COUNT(DISTINCT consumidor_id)
        FROM leituras
        WHERE 1=1
    """
    params_contagem = []
    if mes_filtro and ano_filtro:
        query_contagem += " AND strftime('%m', data_leitura_atual) = ? AND strftime('%Y', data_leitura_atual) = ?"
        params_contagem.extend([mes_filtro, ano_filtro])
    elif mes_filtro:
        query_contagem += " AND strftime('%m', data_leitura_atual) = ?"
        params_contagem.append(mes_filtro)
    elif ano_filtro:
        query_contagem += " AND strftime('%Y', data_leitura_atual) = ?"
        params_contagem.append(ano_filtro)

    consumidores_com_leituras = db.execute(query_contagem, params_contagem).fetchone()[0]

    # Dados adicionais
    ano_atual = datetime.now().year

    return render_template(
        'relatorio_consumidores.html',
        consumidores=consumidores,
        mes_filtro=mes_filtro,
        ano_filtro=ano_filtro,
        ano_atual=ano_atual,
        total_consumidores=total_consumidores,
        consumidores_com_leituras=consumidores_com_leituras
    )# Iniciar o servidor

#------------------------Listar Leituras---------------------------
@app.route('/leituras')
def listar_leituras():
    db = get_db()
    leituras = db.execute('''
        SELECT l.*, c.nome AS nome_consumidor
        FROM leituras l
        JOIN consumidores c ON l.consumidor_id = c.id
        ORDER BY l.data_leitura_atual DESC
    ''').fetchall()
    return render_template('listar_leituras.html', leituras=leituras)

#-----------------------Relatório Geral------------------------------
@app.route('/relatorio-geral')
def relatorio_geral():
    if 'usuario' not in session:
        return redirect(url_for('login'))
    return render_template('relatorio_geral.html')

#-------------------Selecionar Comprovante-----------------
@app.route('/selecionar-comprovante')
def selecionar_comprovante():
    if 'usuario' not in session:
        return redirect(url_for('login'))
    return render_template('selecionar_comprovante.html')

#---------------Relatórios no Card---------------
@app.route('/relatorios')
def relatorios():
    if 'usuario' not in session:
        return redirect(url_for('login'))
    return render_template('relatorios.html')

@app.route('/backup-db')
def baixar_db():
    return send_file(DATABASE, as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True)