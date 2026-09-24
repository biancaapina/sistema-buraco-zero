from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import sqlite3
import os
import re
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY')

UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

def init_db():
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    
    # Tabela de Denúncias / Ocorrências
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS denuncias (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            cpf TEXT NOT NULL,
            localizacao TEXT NOT NULL,
            bairro TEXT NOT NULL,
            descricao TEXT NOT NULL,
            foto_path TEXT,
            status TEXT DEFAULT 'Pendente',
            latitude REAL,
            longitude REAL,
            acao_mapa TEXT DEFAULT 'padrao'
        )
    ''')
    
    # Tabela de Reparos (Com a coluna cep incluída)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reparos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT,
            cpf TEXT,
            cep TEXT,
            localizacao TEXT NOT NULL,
            bairro TEXT NOT NULL,
            descricao TEXT NOT NULL,
            foto_path TEXT,
            status TEXT DEFAULT 'Aguardando Validação'
        )
    ''')

    # Ajustes de colunas caso as tabelas sejam antigas
    for tabela in ['denuncias', 'reparos']:
        try:
            cursor.execute(f'ALTER TABLE {tabela} ADD COLUMN latitude REAL')
        except sqlite3.OperationalError:
            pass
            
        try:
            cursor.execute(f'ALTER TABLE {tabela} ADD COLUMN longitude REAL')
        except sqlite3.OperationalError:
            pass

    try:
        cursor.execute('ALTER TABLE denuncias ADD COLUMN acao_mapa TEXT DEFAULT "padrao"')
    except sqlite3.OperationalError:
        pass

    # Garante colunas adicionais em bases de reparos antigas
    try:
        cursor.execute('ALTER TABLE reparos ADD COLUMN nome TEXT')
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute('ALTER TABLE reparos ADD COLUMN cpf TEXT')
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute('ALTER TABLE reparos ADD COLUMN cep TEXT')
    except sqlite3.OperationalError:
        pass

    # Vincula o reparo à denúncia de origem (para saber de qual denúncia ele veio)
    try:
        cursor.execute('ALTER TABLE reparos ADD COLUMN denuncia_id INTEGER')
    except sqlite3.OperationalError:
        pass

    # Passa a guardar o CEP também na denúncia, para permitir buscar por CEP na hora do reparo
    try:
        cursor.execute('ALTER TABLE denuncias ADD COLUMN cep TEXT')
    except sqlite3.OperationalError:
        pass

    conn.commit()
    conn.close()

init_db()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/denuncia', methods=['GET', 'POST'])
def denuncia():
    if request.method == 'POST':
        nome = request.form.get('nome')
        cpf = request.form.get('cpf')
        localizacao = request.form.get('localizacao')
        cep = request.form.get('cep')
        bairro = request.form.get('bairro')
        descricao = request.form.get('descricao')
        latitude = request.form.get('latitude')
        longitude = request.form.get('longitude')
        
        lat = float(latitude) if latitude else None
        lon = float(longitude) if longitude else None
        
        foto = request.files.get('foto')
        foto_path = None
        if foto and foto.filename != '':
            foto_path = os.path.join(app.config['UPLOAD_FOLDER'], foto.filename)
            foto.save(foto_path)

        conn = sqlite3.connect('database.db')
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO denuncias (nome, cpf, localizacao, cep, bairro, descricao, foto_path, latitude, longitude)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (nome, cpf, localizacao, cep, bairro, descricao, foto_path, lat, lon))
        conn.commit()
        conn.close()

        # CORRIGIDO: Redireciona para o index público em vez do painel público antigo
        return redirect(url_for('index'))

    return render_template('denuncia.html')

@app.route('/reparo', methods=['GET', 'POST'])
def reparo():
    if request.method == 'POST':
        nome = request.form.get('nome')
        cpf = request.form.get('cpf')
        cep = request.form.get('cep')
        localizacao = request.form.get('localizacao')
        bairro = request.form.get('bairro')
        descricao = request.form.get('descricao')
        denuncia_id = request.form.get('denuncia_id') or None

        foto = request.files.get('foto')
        foto_path = None
        if foto and foto.filename != '':
            foto_path = os.path.join(app.config['UPLOAD_FOLDER'], 'reparo_' + foto.filename)
            foto.save(foto_path)

        conn = sqlite3.connect('database.db')
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO reparos (nome, cpf, cep, localizacao, bairro, descricao, foto_path, denuncia_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (nome, cpf, cep, localizacao, bairro, descricao, foto_path, denuncia_id))

        # Atualiza o status da denúncia original, já que ela foi reparada
        if denuncia_id:
            cursor.execute(
                "UPDATE denuncias SET status = ? WHERE id = ?",
                ('Concluído', denuncia_id)
            )

        conn.commit()
        conn.close()

        # CORRIGIDO: Redireciona para o index público
        return redirect(url_for('index'))

    # Se veio de uma busca (denuncia_id na URL), carrega os dados da denúncia
    # para pré-preencher o formulário
    denuncia = None
    denuncia_id = request.args.get('denuncia_id')
    if denuncia_id:
        conn = sqlite3.connect('database.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM denuncias WHERE id = ?', (denuncia_id,))
        denuncia = cursor.fetchone()
        conn.close()

        # Trava extra: não permite relatar reparo de uma denúncia já concluída
        if denuncia and denuncia['status'] == 'Concluído':
            return redirect(url_for('buscar_reparo', erro='ja_concluida'))

    return render_template('reparo.html', denuncia=denuncia)


@app.route('/reparo/buscar')
def buscar_reparo():
    cep = request.args.get('cep', '').strip()
    cpf = request.args.get('cpf', '').strip()
    erro = request.args.get('erro')
    resultados = []
    buscou = False

    if cep or cpf:
        buscou = True
        conn = sqlite3.connect('database.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        if cep:
            # remove pontuação para comparar só os números
            cep_limpo = re.sub(r'\D', '', cep)
            cursor.execute('''
                SELECT * FROM denuncias
                WHERE REPLACE(REPLACE(COALESCE(cep, ''), '-', ''), '.', '') LIKE ?
                ORDER BY id DESC
            ''', (f'%{cep_limpo}%',))
        else:
            cpf_limpo = re.sub(r'\D', '', cpf)
            cursor.execute('''
                SELECT * FROM denuncias
                WHERE REPLACE(REPLACE(REPLACE(COALESCE(cpf, ''), '.', ''), '-', ''), ' ', '') LIKE ?
                ORDER BY id DESC
            ''', (f'%{cpf_limpo}%',))

        resultados = cursor.fetchall()
        conn.close()

    return render_template('buscar_reparo.html', resultados=resultados, buscou=buscou, cep=cep, cpf=cpf, erro=erro)

@app.route('/painel')
def painel():
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute('SELECT bairro, COUNT(*) as total FROM denuncias GROUP BY bairro ORDER BY total DESC')
    ranking_bairros = cursor.fetchall()
    
    cursor.execute('SELECT id, localizacao, bairro, descricao, foto_path, status, latitude, longitude FROM denuncias ORDER BY id DESC')
    denuncias = cursor.fetchall()
    
    conn.close()
    return render_template('painel.html', denuncias=denuncias, ranking_bairros=ranking_bairros)

@app.route('/login', methods=['GET', 'POST'])
def login():
    erro = None
    if request.method == 'POST':
        senha_digitada = request.form.get('senha')
        senha_correta = os.getenv('ADMIN_SENHA')
        
        if senha_digitada == senha_correta:
            session['admin_logado'] = True
            return redirect(url_for('admin_ocorrencias'))
        else:
            erro = 'Senha incorreta. Tente novamente.'
    return render_template('login.html', erro=erro)

@app.route('/logout')
def logout():
    session.pop('admin_logado', None)
    return redirect(url_for('login'))

@app.route('/admin')
@app.route('/admin/ocorrencias')
def admin_ocorrencias():
    if not session.get('admin_logado'):
        return redirect(url_for('login'))

    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('SELECT id, nome, cpf, localizacao, bairro, descricao, foto_path, status, latitude, longitude, acao_mapa FROM denuncias ORDER BY id DESC')
    denuncias = cursor.fetchall()
    conn.close()
    return render_template('admin_ocorrencias.html', ocorrencias=denuncias)

@app.route('/admin/painel')
def admin_painel():
    if not session.get('admin_logado'):
        return redirect(url_for('login'))

    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) as total FROM denuncias')
    total_denuncias = cursor.fetchone()['total']
    cursor.execute('SELECT COUNT(*) as total FROM reparos')
    total_reparos = cursor.fetchone()['total']
    conn.close()

    return render_template('admin_painel.html', total_denuncias=total_denuncias, total_reparos=total_reparos)

@app.route('/admin/reparos')
def admin_reparos():
    if not session.get('admin_logado'):
        return redirect(url_for('login'))

    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('SELECT id, nome, cpf, cep, localizacao, bairro, descricao, foto_path, status FROM reparos ORDER BY id DESC')
    reparos = cursor.fetchall()
    conn.close()
    return render_template('admin_reparos.html', reparos=reparos)

@app.route('/admin/atualizar/<int:id>', methods=['POST'])
def atualizar_status(id):
    if not session.get('admin_logado'):
        return "Acesso negado", 403
        
    novo_status = request.form.get('status')
    acao_mapa = request.form.get('acao_mapa')
    
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE denuncias SET status = ?, acao_mapa = ? WHERE id = ?", (novo_status, acao_mapa, id))
    conn.commit()
    conn.close()
    
    return redirect(url_for('admin_ocorrencias'))

@app.route('/admin/atualizar_reparo/<int:id>', methods=['POST'])
def atualizar_reparo(id):
    if not session.get('admin_logado'):
        return "Acesso negado", 403
        
    novo_status = request.form.get('status')
    
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE reparos SET status = ? WHERE id = ?", (novo_status, id))
    conn.commit()
    conn.close()
    
    return redirect(url_for('admin_reparos'))

@app.route('/admin/deletar_ocorrencia/<int:id>', methods=['POST'])
def deletar_ocorrencia(id):
    if not session.get('admin_logado'):
        return "Acesso negado", 403
        
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute("DELETE FROM denuncias WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    
    return redirect(url_for('admin_ocorrencias'))

@app.route('/admin/deletar_reparo/<int:id>', methods=['POST'])
def deletar_reparo(id):
    if not session.get('admin_logado'):
        return "Acesso negado", 403
        
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute("DELETE FROM reparos WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    
    return redirect(url_for('admin_reparos'))

@app.route('/api/denuncias', methods=['GET'])
def api_denuncias():
    try:
        conn = sqlite3.connect('database.db')
        cursor = conn.cursor()
        cursor.execute('SELECT id, nome, localizacao, bairro, descricao, status, latitude, longitude, acao_mapa FROM denuncias')
        registros = cursor.fetchall()
        conn.close()

        lista_denuncias = []
        for reg in registros:
            lista_denuncias.append({
                "id": reg[0],
                "nome": reg[1],
                "localizacao": reg[2],
                "bairro": reg[3],
                "descricao": reg[4],
                "status": reg[5],
                "latitude": reg[6],
                "longitude": reg[7],
                "acao_mapa": reg[8] if reg[8] else "padrao"
            })

        return jsonify(lista_denuncias), 200
    except Exception as e:
        return jsonify({"erro": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)