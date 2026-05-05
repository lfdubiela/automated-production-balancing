from flask import Flask, render_template, request, jsonify, send_file
import sqlite3, json, os
from datetime import datetime
import io

app = Flask(__name__)
DB = 'balanceamento.db'

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.executescript('''
        CREATE TABLE IF NOT EXISTS equipamentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo TEXT UNIQUE NOT NULL,
            nome TEXT NOT NULL,
            tipo TEXT,
            marca TEXT,
            modelo TEXT,
            patrimonio TEXT,
            status TEXT DEFAULT 'Ativo',
            observacoes TEXT,
            criado_em TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS operadores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            cpf TEXT UNIQUE,
            telefone TEXT,
            endereco TEXT,
            bairro TEXT,
            cidade TEXT,
            estado TEXT,
            cep TEXT,
            funcao TEXT,
            status TEXT DEFAULT 'Ativo',
            criado_em TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS banco_tempos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            seq INTEGER,
            operacao TEXT NOT NULL,
            equipamento_id INTEGER,
            equipamento_nome TEXT,
            minutos INTEGER DEFAULT 0,
            segundos INTEGER DEFAULT 0,
            percentual REAL DEFAULT 0.85,
            tempo_padrao REAL,
            operadora TEXT,
            data_inclusao TEXT,
            referencia TEXT,
            observacoes TEXT,
            criado_em TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS sequencia_operacional (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            descricao TEXT,
            criado_em TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS sequencia_itens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sequencia_id INTEGER,
            banco_tempo_id INTEGER,
            ordem INTEGER,
            FOREIGN KEY(sequencia_id) REFERENCES sequencia_operacional(id),
            FOREIGN KEY(banco_tempo_id) REFERENCES banco_tempos(id)
        );
        CREATE TABLE IF NOT EXISTS balanceamentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            produto TEXT,
            ciclo_minutos REAL,
            meta_dia INTEGER,
            eficiencia REAL DEFAULT 1.0,
            sequencia_id INTEGER,
            criado_em TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS balanceamento_times (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            balanceamento_id INTEGER,
            numero_time INTEGER,
            operador_id INTEGER,
            operador_nome TEXT,
            operacoes TEXT,
            carga_total REAL,
            saldo REAL,
            FOREIGN KEY(balanceamento_id) REFERENCES balanceamentos(id)
        );
        CREATE TABLE IF NOT EXISTS operacoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo TEXT UNIQUE NOT NULL,
            nome TEXT NOT NULL,
            criado_em TEXT DEFAULT CURRENT_TIMESTAMP
        );
    ''')
    conn.commit()
    # Migração: renomeia coluna legada nome_sequencia → nome (SQLite 3.25+)
    try:
        cols = [r[1] for r in c.execute('PRAGMA table_info(sequencia_operacional)').fetchall()]
        if 'nome_sequencia' in cols and 'nome' not in cols:
            c.execute('ALTER TABLE sequencia_operacional RENAME COLUMN nome_sequencia TO nome')
            conn.commit()
    except Exception:
        pass
    # Migração: popula tabela operacoes a partir do banco_tempos e vincula operacao_id
    try:
        op_cols = [r[1] for r in c.execute('PRAGMA table_info(operacoes)').fetchall()]
        bt_cols = [r[1] for r in c.execute('PRAGMA table_info(banco_tempos)').fetchall()]
        # Popula operacoes com nomes distintos do banco_tempos
        existing = {r[0] for r in c.execute('SELECT nome FROM operacoes').fetchall()}
        distintos = c.execute('SELECT DISTINCT operacao FROM banco_tempos ORDER BY operacao').fetchall()
        counter = c.execute('SELECT COUNT(*) FROM operacoes').fetchone()[0]
        for (nome,) in distintos:
            if nome not in existing:
                counter += 1
                codigo = 'OP-{:03d}'.format(counter)
                c.execute('INSERT OR IGNORE INTO operacoes(codigo, nome) VALUES(?,?)', (codigo, nome))
                existing.add(nome)
        # Adiciona coluna operacao_id em banco_tempos se não existir
        if 'operacao_id' not in bt_cols:
            c.execute('ALTER TABLE banco_tempos ADD COLUMN operacao_id INTEGER')
        # Vincula banco_tempos.operacao_id com base no nome
        c.execute('''UPDATE banco_tempos SET operacao_id = (
            SELECT o.id FROM operacoes o WHERE o.nome = banco_tempos.operacao LIMIT 1
        ) WHERE operacao_id IS NULL''')
        conn.commit()
    except Exception:
        pass
    # Migração: adiciona colunas em operadores
    try:
        cols = [r[1] for r in c.execute('PRAGMA table_info(operadores)').fetchall()]
        if 'equipamentos_ids' not in cols:
            c.execute("ALTER TABLE operadores ADD COLUMN equipamentos_ids TEXT DEFAULT '[]'")
        if 'operacoes' not in cols:
            c.execute("ALTER TABLE operadores ADD COLUMN operacoes TEXT DEFAULT ''")
        conn.commit()
    except Exception:
        pass
    conn.close()

init_db()

# ─── ROTAS PRINCIPAIS ───────────────────────────────────────────────
@app.route('/')
def index():
    return render_template('index.html')

# ─── OPERAÇÕES (CATÁLOGO) ───────────────────────────────────────────
@app.route('/api/operacoes', methods=['GET'])
def list_operacoes():
    conn = get_db()
    rows = conn.execute('SELECT * FROM operacoes ORDER BY codigo').fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/operacoes', methods=['POST'])
def save_operacao():
    d = request.json
    conn = get_db()
    try:
        if d.get('id'):
            conn.execute('UPDATE operacoes SET codigo=?,nome=? WHERE id=?',
                         (d['codigo'].upper(), d['nome'].upper(), d['id']))
        else:
            conn.execute('INSERT INTO operacoes(codigo,nome) VALUES(?,?)',
                         (d['codigo'].upper(), d['nome'].upper()))
        conn.commit()
    except Exception as e:
        conn.close()
        return jsonify({'error': str(e)}), 400
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/operacoes/<int:oid>', methods=['DELETE'])
def del_operacao(oid):
    conn = get_db()
    em_uso = conn.execute('SELECT COUNT(*) FROM banco_tempos WHERE operacao_id=?', (oid,)).fetchone()[0]
    if em_uso:
        conn.close()
        return jsonify({'error': f'Operação em uso em {em_uso} registro(s) do banco de tempos.'}), 400
    conn.execute('DELETE FROM operacoes WHERE id=?', (oid,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

# ─── EQUIPAMENTOS ───────────────────────────────────────────────────
@app.route('/api/equipamentos', methods=['GET'])
def list_equipamentos():
    conn = get_db()
    rows = conn.execute('SELECT * FROM equipamentos ORDER BY nome').fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/equipamentos', methods=['POST'])
def save_equipamento():
    d = request.json
    conn = get_db()
    if d.get('id'):
        conn.execute('''UPDATE equipamentos SET codigo=?,nome=?,tipo=?,marca=?,modelo=?,
            patrimonio=?,status=?,observacoes=? WHERE id=?''',
            (d['codigo'],d['nome'],d.get('tipo',''),d.get('marca',''),d.get('modelo',''),
             d.get('patrimonio',''),d.get('status','Ativo'),d.get('observacoes',''),d['id']))
    else:
        conn.execute('''INSERT INTO equipamentos(codigo,nome,tipo,marca,modelo,patrimonio,status,observacoes)
            VALUES(?,?,?,?,?,?,?,?)''',
            (d['codigo'],d['nome'],d.get('tipo',''),d.get('marca',''),d.get('modelo',''),
             d.get('patrimonio',''),d.get('status','Ativo'),d.get('observacoes','')))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/equipamentos/<int:eid>', methods=['DELETE'])
def del_equipamento(eid):
    conn = get_db()
    conn.execute('DELETE FROM equipamentos WHERE id=?', (eid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

# ─── OPERADORES ─────────────────────────────────────────────────────
@app.route('/api/operadores', methods=['GET'])
def list_operadores():
    conn = get_db()
    rows = conn.execute('SELECT * FROM operadores ORDER BY nome').fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/operadores', methods=['POST'])
def save_operador():
    d = request.json
    conn = get_db()
    eqs_ids = json.dumps(d.get('equipamentos_ids', []))
    if d.get('id'):
        conn.execute('''UPDATE operadores SET nome=?,cpf=?,telefone=?,endereco=?,bairro=?,
            cidade=?,estado=?,cep=?,funcao=?,status=?,equipamentos_ids=?,operacoes=? WHERE id=?''',
            (d['nome'],d.get('cpf',''),d.get('telefone',''),d.get('endereco',''),
             d.get('bairro',''),d.get('cidade',''),d.get('estado',''),d.get('cep',''),
             d.get('funcao',''),d.get('status','Ativo'),eqs_ids,d.get('operacoes',''),d['id']))
    else:
        conn.execute('''INSERT INTO operadores(nome,cpf,telefone,endereco,bairro,cidade,estado,cep,funcao,status,equipamentos_ids,operacoes)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
            (d['nome'],d.get('cpf',''),d.get('telefone',''),d.get('endereco',''),
             d.get('bairro',''),d.get('cidade',''),d.get('estado',''),d.get('cep',''),
             d.get('funcao',''),d.get('status','Ativo'),eqs_ids,d.get('operacoes','')))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/operadores/<int:oid>', methods=['DELETE'])
def del_operador(oid):
    conn = get_db()
    conn.execute('DELETE FROM operadores WHERE id=?', (oid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

# ─── BANCO DE TEMPOS ────────────────────────────────────────────────
@app.route('/api/banco', methods=['GET'])
def list_banco():
    conn = get_db()
    rows = conn.execute('SELECT * FROM banco_tempos ORDER BY seq, id').fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/banco', methods=['POST'])
def save_banco():
    d = request.json
    mins = int(d.get('minutos', 0))
    secs = int(d.get('segundos', 0))
    pct = float(d.get('percentual', 0.85))
    total_seg = mins * 60 + secs
    total_min = total_seg / 60
    tp = (total_min / 10) / pct if pct > 0 else 0
    conn = get_db()
    operacao_id = d.get('operacao_id') or None
    # Resolve nome da operação a partir do catálogo
    operacao_nome = d.get('operacao', '')
    if operacao_id:
        row = conn.execute('SELECT nome FROM operacoes WHERE id=?', (operacao_id,)).fetchone()
        if row:
            operacao_nome = row[0]
    if d.get('id'):
        conn.execute('''UPDATE banco_tempos SET seq=?,operacao=?,operacao_id=?,equipamento_nome=?,minutos=?,segundos=?,
            percentual=?,tempo_padrao=?,operadora=?,data_inclusao=?,referencia=?,observacoes=? WHERE id=?''',
            (d.get('seq'),operacao_nome,operacao_id,d.get('equipamento_nome',''),mins,secs,pct,tp,
             d.get('operadora',''),d.get('data_inclusao',''),d.get('referencia',''),
             d.get('observacoes',''),d['id']))
    else:
        seq = conn.execute('SELECT COALESCE(MAX(seq),0)+1 FROM banco_tempos').fetchone()[0]
        conn.execute('''INSERT INTO banco_tempos(seq,operacao,operacao_id,equipamento_nome,minutos,segundos,
            percentual,tempo_padrao,operadora,data_inclusao,referencia,observacoes)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
            (d.get('seq', seq),operacao_nome,operacao_id,d.get('equipamento_nome',''),mins,secs,pct,tp,
             d.get('operadora',''),d.get('data_inclusao', datetime.now().strftime('%Y-%m-%d')),
             d.get('referencia',''),d.get('observacoes','')))
    conn.commit(); conn.close()
    return jsonify({'ok': True, 'tempo_padrao': round(tp, 6)})

@app.route('/api/banco/<int:bid>', methods=['DELETE'])
def del_banco(bid):
    conn = get_db()
    conn.execute('DELETE FROM banco_tempos WHERE id=?', (bid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

# ─── SEQUÊNCIA OPERACIONAL ──────────────────────────────────────────
@app.route('/api/sequencias', methods=['GET'])
def list_sequencias():
    conn = get_db()
    seqs = conn.execute('SELECT * FROM sequencia_operacional ORDER BY id DESC').fetchall()
    result = []
    for s in seqs:
        itens = conn.execute('''
            SELECT si.ordem, bt.*
            FROM sequencia_itens si
            JOIN banco_tempos bt ON bt.id = si.banco_tempo_id
            WHERE si.sequencia_id=? ORDER BY si.ordem
        ''', (s['id'],)).fetchall()
        d = dict(s)
        d['itens'] = [dict(i) for i in itens]
        d['total_tp'] = sum(i['tempo_padrao'] or 0 for i in itens)
        result.append(d)
    conn.close()
    return jsonify(result)

@app.route('/api/sequencias', methods=['POST'])
def save_sequencia():
    d = request.json
    conn = get_db()
    if d.get('id'):
        conn.execute('UPDATE sequencia_operacional SET nome=?,descricao=? WHERE id=?',
                     (d['nome'], d.get('descricao',''), d['id']))
        conn.execute('DELETE FROM sequencia_itens WHERE sequencia_id=?', (d['id'],))
        sid = d['id']
    else:
        cur = conn.execute('INSERT INTO sequencia_operacional(nome,descricao) VALUES(?,?)',
                           (d['nome'], d.get('descricao','')))
        sid = cur.lastrowid
    for i, item in enumerate(d.get('itens', [])):
        conn.execute('INSERT INTO sequencia_itens(sequencia_id,banco_tempo_id,ordem) VALUES(?,?,?)',
                     (sid, item['id'], i+1))
    conn.commit(); conn.close()
    return jsonify({'ok': True, 'id': sid})

@app.route('/api/sequencias/<int:sid>', methods=['DELETE'])
def del_sequencia(sid):
    conn = get_db()
    conn.execute('DELETE FROM sequencia_itens WHERE sequencia_id=?', (sid,))
    conn.execute('DELETE FROM sequencia_operacional WHERE id=?', (sid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

# ─── BALANCEAMENTO ──────────────────────────────────────────────────
@app.route('/api/balanceamentos', methods=['GET'])
def list_balanceamentos():
    conn = get_db()
    bals = conn.execute('SELECT * FROM balanceamentos ORDER BY id DESC').fetchall()
    result = []
    for b in bals:
        times = conn.execute('SELECT * FROM balanceamento_times WHERE balanceamento_id=? ORDER BY numero_time',
                             (b['id'],)).fetchall()
        d = dict(b)
        d['times'] = [dict(t) for t in times]
        result.append(d)
    conn.close()
    return jsonify(result)

@app.route('/api/balanceamentos', methods=['POST'])
def save_balanceamento():
    d = request.json
    conn = get_db()
    if d.get('id'):
        conn.execute('''UPDATE balanceamentos SET nome=?,produto=?,ciclo_minutos=?,meta_dia=?,
            eficiencia=?,sequencia_id=? WHERE id=?''',
            (d['nome'],d.get('produto',''),d.get('ciclo_minutos',30),d.get('meta_dia',0),
             d.get('eficiencia',1.0),d.get('sequencia_id'),d['id']))
        conn.execute('DELETE FROM balanceamento_times WHERE balanceamento_id=?', (d['id'],))
        bid = d['id']
    else:
        cur = conn.execute('''INSERT INTO balanceamentos(nome,produto,ciclo_minutos,meta_dia,eficiencia,sequencia_id)
            VALUES(?,?,?,?,?,?)''',
            (d['nome'],d.get('produto',''),d.get('ciclo_minutos',30),d.get('meta_dia',0),
             d.get('eficiencia',1.0),d.get('sequencia_id')))
        bid = cur.lastrowid
    for t in d.get('times', []):
        conn.execute('''INSERT INTO balanceamento_times(balanceamento_id,numero_time,operador_id,
            operador_nome,operacoes,carga_total,saldo) VALUES(?,?,?,?,?,?,?)''',
            (bid,t['numero_time'],t.get('operador_id'),t.get('operador_nome',''),
             json.dumps(t.get('operacoes',[])),t.get('carga_total',0),t.get('saldo',0)))
    conn.commit(); conn.close()
    return jsonify({'ok': True, 'id': bid})

@app.route('/api/balanceamentos/<int:bid>', methods=['DELETE'])
def del_balanceamento(bid):
    conn = get_db()
    conn.execute('DELETE FROM balanceamento_times WHERE balanceamento_id=?', (bid,))
    conn.execute('DELETE FROM balanceamentos WHERE id=?', (bid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

if __name__ == '__main__':
    print("\n" + "="*55)
    print("  SISTEMA DE BALANCEAMENTO DE PRODUÇÃO")
    print("  Acesse: http://localhost:5000")
    print("="*55 + "\n")
    app.run(debug=False, port=5000)

# ─── RELATÓRIOS E EXPORTAÇÃO ────────────────────────────────────────
from io import BytesIO

@app.route('/api/relatorio/banco')
def relatorio_banco():
    """Exporta banco de tempos como CSV"""
    conn = get_db()
    rows = conn.execute('SELECT seq, operacao, equipamento_nome, minutos, segundos, percentual, tempo_padrao, operadora, data_inclusao, referencia, observacoes FROM banco_tempos ORDER BY seq, id').fetchall()
    conn.close()
    lines = ['Seq;Operação;Equipamento;Minutos;Segundos;Eficiência%;T.Padrão;Operadora;Data;Referência;Observações']
    for r in rows:
        pct = round((r['percentual'] or 0.85)*100, 0)
        lines.append(f"{r['seq'] or ''};{r['operacao']};{r['equipamento_nome'] or ''};{r['minutos'] or 0};{r['segundos'] or 0};{pct};{r['tempo_padrao'] or 0:.6f};{r['operadora'] or ''};{r['data_inclusao'] or ''};{r['referencia'] or ''};{r['observacoes'] or ''}")
    csv = '\n'.join(lines)
    return app.response_class(csv.encode('utf-8-sig'), mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=banco_tempos.csv'})

@app.route('/api/relatorio/balanceamento/<int:bid>')
def relatorio_balanceamento(bid):
    conn = get_db()
    b = conn.execute('SELECT * FROM balanceamentos WHERE id=?', (bid,)).fetchone()
    times = conn.execute('SELECT * FROM balanceamento_times WHERE balanceamento_id=? ORDER BY numero_time', (bid,)).fetchall()
    conn.close()
    if not b:
        return jsonify({'error': 'Não encontrado'}), 404
    lines = [f'BALANCEAMENTO: {b["nome"]}', f'Produto: {b["produto"] or ""}', f'Ciclo: {b["ciclo_minutos"]} min', f'Meta/dia: {b["meta_dia"] or ""}', '']
    lines.append('TIME;OPERAÇÃO;EQUIPAMENTO;T.PADRÃO;CARGA_TIME;SALDO;OPERADOR')
    for t in times:
        ops = json.loads(t['operacoes'] or '[]')
        carga = sum(o.get('tempo_padrao',0) for o in ops)
        saldo = (b['ciclo_minutos'] or 0) - carga
        for o in ops:
            lines.append(f"TIME {t['numero_time']};{o['operacao']};{o.get('equipamento_nome','')};{o.get('tempo_padrao',0):.6f};{carga:.4f};{saldo:.4f};{t['operador_nome'] or ''}")
    csv = '\n'.join(lines)
    return app.response_class(csv.encode('utf-8-sig'), mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename=balanceamento_{bid}.csv'})

@app.route('/api/stats')
def get_stats():
    conn = get_db()
    banco_count = conn.execute('SELECT COUNT(*) FROM banco_tempos').fetchone()[0]
    total_tp = conn.execute('SELECT SUM(tempo_padrao) FROM banco_tempos').fetchone()[0] or 0
    ops_count = conn.execute('SELECT COUNT(*) FROM operadores').fetchone()[0]
    eqs_count = conn.execute('SELECT COUNT(*) FROM equipamentos').fetchone()[0]
    bals_count = conn.execute('SELECT COUNT(*) FROM balanceamentos').fetchone()[0]
    seqs_count = conn.execute('SELECT COUNT(*) FROM sequencia_operacional').fetchone()[0]
    # equip distribution
    equip_dist = conn.execute('''SELECT equipamento_nome, COUNT(*) as cnt, SUM(tempo_padrao) as total
        FROM banco_tempos WHERE equipamento_nome != '' GROUP BY equipamento_nome ORDER BY cnt DESC''').fetchall()
    conn.close()
    return jsonify({
        'banco_count': banco_count, 'total_tp': round(total_tp, 4),
        'ops_count': ops_count, 'eqs_count': eqs_count,
        'bals_count': bals_count, 'seqs_count': seqs_count,
        'equip_dist': [dict(r) for r in equip_dist]
    })

@app.route('/api/balanceamentos/auto', methods=['POST'])
def auto_balance():
    """Auto-distribuição de operações nos times com algoritmo greedy"""
    d = request.json
    ops = d.get('ops', [])  # lista de {id, operacao, tempo_padrao, equipamento_nome}
    ciclo = float(d.get('ciclo', 30))
    n_times = int(d.get('n_times', 5))
    
    times = [{'num': i+1, 'ops': [], 'carga': 0} for i in range(n_times)]
    
    # Greedy: aloca cada operação no time com menor carga que ainda cabe
    for op in sorted(ops, key=lambda x: x.get('tempo_padrao', 0), reverse=True):
        tp = op.get('tempo_padrao', 0)
        # Encontra time com menor carga
        best = min(times, key=lambda t: t['carga'])
        best['ops'].append(op['id'])
        best['carga'] += tp
    
    return jsonify({'times': [{'num': t['num'], 'ops': t['ops'], 'carga': round(t['carga'], 6)} for t in times]})

@app.route('/api/operadores/busca')
def busca_operadores():
    q = request.args.get('q', '').lower()
    conn = get_db()
    rows = conn.execute("SELECT id, nome, funcao, status FROM operadores WHERE LOWER(nome) LIKE ? AND status='Ativo' LIMIT 10", ('%'+q+'%',)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

# Importação em lote do ODS/CSV
@app.route('/api/banco/importar', methods=['POST'])
def importar_banco():
    data = request.json.get('operacoes', [])
    conn = get_db()
    inserted = 0
    for item in data:
        try:
            mins = int(item.get('minutos', 0))
            secs = int(item.get('segundos', 0))
            pct = float(item.get('percentual', 0.85))
            total = (mins*60+secs)/60
            tp = (total/10)/pct if pct > 0 else 0
            conn.execute('''INSERT INTO banco_tempos(seq,operacao,equipamento_nome,minutos,segundos,percentual,tempo_padrao,data_inclusao)
                VALUES(?,?,?,?,?,?,?,?)''',
                (item.get('seq'), item['operacao'].upper(), item.get('equipamento_nome',''),
                 mins, secs, pct, tp, item.get('data_inclusao','')))
            inserted += 1
        except Exception as e:
            continue
    conn.commit(); conn.close()
    return jsonify({'ok': True, 'inserted': inserted})
