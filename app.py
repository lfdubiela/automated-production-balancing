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
        CREATE TABLE IF NOT EXISTS balanceamento_atribuicoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            balanceamento_id INTEGER NOT NULL,
            operacao_idx INTEGER NOT NULL,
            operador_id INTEGER NOT NULL,
            UNIQUE(balanceamento_id, operacao_idx, operador_id),
            FOREIGN KEY(balanceamento_id) REFERENCES balanceamentos(id),
            FOREIGN KEY(operador_id) REFERENCES operadores(id)
        );
        CREATE INDEX IF NOT EXISTS idx_atrib_bal ON balanceamento_atribuicoes(balanceamento_id);
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
    # Migração: adiciona coluna status em balanceamentos
    try:
        cols = [r[1] for r in c.execute('PRAGMA table_info(balanceamentos)').fetchall()]
        if 'status' not in cols:
            c.execute("ALTER TABLE balanceamentos ADD COLUMN status TEXT DEFAULT 'finalizado'")
        conn.commit()
    except Exception:
        pass
    # Migração: adiciona coluna operadores (JSON list) em balanceamento_times
    try:
        cols = [r[1] for r in c.execute('PRAGMA table_info(balanceamento_times)').fetchall()]
        if 'operadores' not in cols:
            c.execute("ALTER TABLE balanceamento_times ADD COLUMN operadores TEXT DEFAULT '[]'")
        conn.commit()
    except Exception:
        pass
    # Migração: adiciona coluna depende_de em sequencia_itens (JSON list de banco_tempo_ids)
    try:
        cols = [r[1] for r in c.execute('PRAGMA table_info(sequencia_itens)').fetchall()]
        if 'depende_de' not in cols:
            c.execute("ALTER TABLE sequencia_itens ADD COLUMN depende_de TEXT DEFAULT '[]'")
        conn.commit()
    except Exception:
        pass
    # Migração: adiciona minutos_trabalhados em balanceamentos
    try:
        cols = [r[1] for r in c.execute('PRAGMA table_info(balanceamentos)').fetchall()]
        if 'minutos_trabalhados' not in cols:
            c.execute("ALTER TABLE balanceamentos ADD COLUMN minutos_trabalhados INTEGER DEFAULT 540")
        if 'n_operadoras' not in cols:
            c.execute("ALTER TABLE balanceamentos ADD COLUMN n_operadoras INTEGER DEFAULT 0")
        if 'pcs_pacote' not in cols:
            c.execute("ALTER TABLE balanceamentos ADD COLUMN pcs_pacote INTEGER DEFAULT 0")
        if 'ativo' not in cols:
            c.execute("ALTER TABLE balanceamentos ADD COLUMN ativo INTEGER DEFAULT 1")
        if 'deleted_at' not in cols:
            c.execute("ALTER TABLE balanceamentos ADD COLUMN deleted_at TEXT")
        if 'estado' not in cols:
            c.execute("ALTER TABLE balanceamentos ADD COLUMN estado TEXT DEFAULT 'created'")
        conn.commit()
    except Exception:
        pass
    # Migração: adiciona tempo_min + qualificado em balanceamento_atribuicoes
    try:
        cols = [r[1] for r in c.execute('PRAGMA table_info(balanceamento_atribuicoes)').fetchall()]
        if 'tempo_min' not in cols:
            c.execute("ALTER TABLE balanceamento_atribuicoes ADD COLUMN tempo_min REAL DEFAULT 0")
        if 'qualificado' not in cols:
            c.execute("ALTER TABLE balanceamento_atribuicoes ADD COLUMN qualificado INTEGER DEFAULT 1")
        if 'numero_time' not in cols:
            c.execute("ALTER TABLE balanceamento_atribuicoes ADD COLUMN numero_time INTEGER")
        conn.commit()
    except Exception:
        pass
    # Tabelas novas: remanejos (entidade independente) + remanejo_atribuicoes
    c.execute('''CREATE TABLE IF NOT EXISTS remanejos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL,
        sequencia_id INTEGER NOT NULL,
        criado_em TEXT DEFAULT CURRENT_TIMESTAMP,
        ativo INTEGER DEFAULT 1,
        deleted_at TEXT,
        FOREIGN KEY (sequencia_id) REFERENCES sequencia_operacional(id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS remanejo_atribuicoes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        remanejo_id INTEGER NOT NULL,
        operacao_idx INTEGER NOT NULL,
        operador_id INTEGER NOT NULL,
        UNIQUE(remanejo_id, operacao_idx, operador_id),
        FOREIGN KEY (remanejo_id) REFERENCES remanejos(id)
    )''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_rematrib_rem ON remanejo_atribuicoes(remanejo_id)')
    # Migração: adiciona bal.remanejo_id
    try:
        cols = [r[1] for r in c.execute('PRAGMA table_info(balanceamentos)').fetchall()]
        if 'remanejo_id' not in cols:
            c.execute("ALTER TABLE balanceamentos ADD COLUMN remanejo_id INTEGER")
        conn.commit()
    except Exception:
        pass
    # Migração one-shot: copia bals status='remanejo' pra nova tabela remanejos
    try:
        n_existing = c.execute('SELECT COUNT(*) FROM remanejos').fetchone()[0]
        if n_existing == 0:
            old = c.execute(
                "SELECT id, nome, sequencia_id, criado_em, COALESCE(ativo,1), deleted_at FROM balanceamentos WHERE status='remanejo'"
            ).fetchall()
            for r in old:
                c.execute(
                    'INSERT INTO remanejos(id, nome, sequencia_id, criado_em, ativo, deleted_at) VALUES(?,?,?,?,?,?)',
                    (r[0], r[1], r[2], r[3], r[4], r[5])
                )
                atribs = c.execute(
                    'SELECT DISTINCT operacao_idx, operador_id FROM balanceamento_atribuicoes WHERE balanceamento_id=?',
                    (r[0],)
                ).fetchall()
                for a in atribs:
                    c.execute(
                        'INSERT OR IGNORE INTO remanejo_atribuicoes(remanejo_id, operacao_idx, operador_id) VALUES(?,?,?)',
                        (r[0], a[0], a[1])
                    )
                c.execute('DELETE FROM balanceamento_atribuicoes WHERE balanceamento_id=?', (r[0],))
            c.execute("DELETE FROM balanceamentos WHERE status='remanejo'")
            conn.commit()
    except Exception:
        pass
    # Migração: adiciona coluna cor em equipamentos
    try:
        cols = [r[1] for r in c.execute('PRAGMA table_info(equipamentos)').fetchall()]
        if 'cor' not in cols:
            c.execute("ALTER TABLE equipamentos ADD COLUMN cor TEXT DEFAULT '#94a3b8'")
        conn.commit()
    except Exception:
        pass
    # Tabela de configurações system-wide
    c.execute('''CREATE TABLE IF NOT EXISTS app_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )''')
    defaults = {
        'gordura_pct': '15',
        'arred_pacote': 'down',
        'ciclo_curto_default': '15',
        'min_dia_default': '540',
        'tolerancia_ceil_pct': '15',
        'ocupacao_min_pct': '95',
    }
    for k, v in defaults.items():
        c.execute('INSERT OR IGNORE INTO app_settings(key,value) VALUES(?,?)', (k, v))
    conn.commit()
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
    cor = d.get('cor') or '#94a3b8'
    if d.get('id'):
        conn.execute('''UPDATE equipamentos SET codigo=?,nome=?,tipo=?,marca=?,modelo=?,
            patrimonio=?,status=?,observacoes=?,cor=? WHERE id=?''',
            (d['codigo'],d['nome'],d.get('tipo',''),d.get('marca',''),d.get('modelo',''),
             d.get('patrimonio',''),d.get('status','Ativo'),d.get('observacoes',''),cor,d['id']))
    else:
        conn.execute('''INSERT INTO equipamentos(codigo,nome,tipo,marca,modelo,patrimonio,status,observacoes,cor)
            VALUES(?,?,?,?,?,?,?,?,?)''',
            (d['codigo'],d['nome'],d.get('tipo',''),d.get('marca',''),d.get('modelo',''),
             d.get('patrimonio',''),d.get('status','Ativo'),d.get('observacoes',''),cor))
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
            SELECT si.ordem, si.depende_de, bt.*
            FROM sequencia_itens si
            JOIN banco_tempos bt ON bt.id = si.banco_tempo_id
            WHERE si.sequencia_id=? ORDER BY si.ordem
        ''', (s['id'],)).fetchall()
        d = dict(s)
        items_out = []
        for i in itens:
            di = dict(i)
            try:
                di['depende_de'] = json.loads(i['depende_de'] or '[]')
            except Exception:
                di['depende_de'] = []
            items_out.append(di)
        d['itens'] = items_out
        d['total_tp'] = sum(i['tempo_padrao'] or 0 for i in itens)
        result.append(d)
    conn.close()
    return jsonify(result)

@app.route('/api/sequencias', methods=['POST'])
def save_sequencia():
    d = request.json
    itens = d.get('itens', [])
    # Validação: deps referenciam banco_tempo_ids dentro da sequência e formam DAG
    item_ids = [int(it['id']) for it in itens]
    item_ids_set = set(item_ids)
    pos_of = {bid: idx for idx, bid in enumerate(item_ids)}
    deps_per_item = {}
    for it in itens:
        raw = it.get('depende_de') or []
        if not isinstance(raw, list):
            raw = []
        try:
            ids = [int(x) for x in raw if x is not None]
        except (TypeError, ValueError):
            return jsonify({'error': 'depende_de inválido em algum item.'}), 400
        cur_id = int(it['id'])
        for p in ids:
            if p == cur_id:
                return jsonify({'error': 'Item não pode depender de si mesmo.'}), 400
            if p not in item_ids_set:
                return jsonify({'error': f'Predecessor inválido (id={p}) — deve estar na própria sequência.'}), 400
            if pos_of[p] >= pos_of[cur_id]:
                return jsonify({'error': 'Predecessor deve aparecer antes na sequência.'}), 400
        deps_per_item[cur_id] = ids
    # Detecção de ciclo (DFS)
    visiting = set(); visited = set()
    def has_cycle(node):
        if node in visiting: return True
        if node in visited: return False
        visiting.add(node)
        for nxt in deps_per_item.get(node, []):
            if has_cycle(nxt): return True
        visiting.discard(node); visited.add(node)
        return False
    for nid in deps_per_item:
        if has_cycle(nid):
            return jsonify({'error': 'Dependências formam ciclo.'}), 400
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
    for i, item in enumerate(itens):
        deps_json = json.dumps(deps_per_item.get(int(item['id']), []))
        conn.execute('INSERT INTO sequencia_itens(sequencia_id,banco_tempo_id,ordem,depende_de) VALUES(?,?,?,?)',
                     (sid, item['id'], i+1, deps_json))
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
    include_deleted = request.args.get('include_deleted') == '1'
    conn = get_db()
    if include_deleted:
        bals = conn.execute('SELECT * FROM balanceamentos ORDER BY id DESC').fetchall()
    else:
        bals = conn.execute('SELECT * FROM balanceamentos WHERE COALESCE(ativo,1)=1 ORDER BY id DESC').fetchall()
    seqs = {r['id']: r['nome'] for r in conn.execute('SELECT id, nome FROM sequencia_operacional').fetchall()}
    result = []
    for b in bals:
        times = conn.execute('SELECT * FROM balanceamento_times WHERE balanceamento_id=? ORDER BY numero_time',
                             (b['id'],)).fetchall()
        d = dict(b)
        d['times'] = [dict(t) for t in times]
        d['sequencia_nome'] = seqs.get(b['sequencia_id'], '—')
        d['pessoas_alocadas'] = conn.execute(
            'SELECT COUNT(DISTINCT operador_id) FROM balanceamento_atribuicoes WHERE balanceamento_id=?',
            (b['id'],)
        ).fetchone()[0]
        result.append(d)
    conn.close()
    return jsonify(result)

@app.route('/api/balanceamentos', methods=['POST'])
def save_balanceamento():
    d = request.json
    conn = get_db()
    mins = int(d.get('minutos_trabalhados') or 540)
    n_oper = int(d.get('n_operadoras') or 0)
    pcs_pac = int(d.get('pcs_pacote') or 0)
    rem_id = d.get('remanejo_id') or None
    if d.get('id'):
        conn.execute('''UPDATE balanceamentos SET nome=?,produto=?,ciclo_minutos=?,meta_dia=?,
            eficiencia=?,sequencia_id=?,minutos_trabalhados=?,n_operadoras=?,pcs_pacote=?,remanejo_id=? WHERE id=?''',
            (d['nome'],d.get('produto',''),d.get('ciclo_minutos',30),d.get('meta_dia',0),
             d.get('eficiencia',1.0),d.get('sequencia_id'),mins,n_oper,pcs_pac,rem_id,d['id']))
        conn.execute('DELETE FROM balanceamento_times WHERE balanceamento_id=?', (d['id'],))
        bid = d['id']
    else:
        cur = conn.execute('''INSERT INTO balanceamentos(nome,produto,ciclo_minutos,meta_dia,eficiencia,sequencia_id,minutos_trabalhados,n_operadoras,pcs_pacote,remanejo_id,status)
            VALUES(?,?,?,?,?,?,?,?,?,?,'finalizado')''',
            (d['nome'],d.get('produto',''),d.get('ciclo_minutos',30),d.get('meta_dia',0),
             d.get('eficiencia',1.0),d.get('sequencia_id'),mins,n_oper,pcs_pac,rem_id))
        bid = cur.lastrowid
    for t in d.get('times', []):
        operadores = t.get('operadores') or []
        first_op = operadores[0] if operadores else {}
        conn.execute('''INSERT INTO balanceamento_times(balanceamento_id,numero_time,operador_id,
            operador_nome,operacoes,carga_total,saldo,operadores) VALUES(?,?,?,?,?,?,?,?)''',
            (bid,t['numero_time'],t.get('operador_id') or first_op.get('id'),
             t.get('operador_nome') or first_op.get('nome',''),
             json.dumps(t.get('operacoes',[])),t.get('carga_total',0),t.get('saldo',0),
             json.dumps(operadores)))
    conn.commit(); conn.close()
    return jsonify({'ok': True, 'id': bid})

@app.route('/api/balanceamentos/<int:bid>', methods=['DELETE'])
def del_balanceamento(bid):
    """Soft delete: marca ativo=0 + deleted_at. Use ?hard=1 para deletar fisicamente."""
    hard = request.args.get('hard') == '1'
    conn = get_db()
    if hard:
        conn.execute('DELETE FROM balanceamento_times WHERE balanceamento_id=?', (bid,))
        conn.execute('DELETE FROM balanceamento_atribuicoes WHERE balanceamento_id=?', (bid,))
        conn.execute('DELETE FROM balanceamentos WHERE id=?', (bid,))
    else:
        conn.execute("UPDATE balanceamentos SET ativo=0, deleted_at=? WHERE id=?",
                     (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), bid))
    conn.commit(); conn.close()
    return jsonify({'ok': True, 'soft': not hard})

# ─── REMANEJOS (entidade independente, 1 remanejo : N balanceamentos) ──
@app.route('/api/remanejos', methods=['GET'])
def list_remanejos():
    """Lista remanejos. Filtros: sequencia_id, include_deleted=1."""
    sid = request.args.get('sequencia_id', type=int)
    include_deleted = request.args.get('include_deleted') == '1'
    conn = get_db()
    where = ['1=1']
    params = []
    if not include_deleted:
        where.append('COALESCE(r.ativo,1)=1')
    if sid:
        where.append('r.sequencia_id=?')
        params.append(sid)
    sql = f'''SELECT r.*, s.nome AS sequencia_nome,
                     (SELECT COUNT(DISTINCT operador_id) FROM remanejo_atribuicoes WHERE remanejo_id=r.id) AS total_operadores,
                     (SELECT COUNT(DISTINCT operacao_idx) FROM remanejo_atribuicoes WHERE remanejo_id=r.id) AS total_ops_cobertas,
                     (SELECT COUNT(*) FROM balanceamentos b WHERE b.remanejo_id=r.id AND COALESCE(b.ativo,1)=1) AS bals_usando
              FROM remanejos r
              LEFT JOIN sequencia_operacional s ON s.id=r.sequencia_id
              WHERE {' AND '.join(where)}
              ORDER BY r.id DESC'''
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/remanejos', methods=['POST'])
def save_remanejo():
    """Cria ou atualiza remanejo. Reusa id se passado, senão cria novo."""
    d = request.json or {}
    sequencia_id = d.get('sequencia_id')
    atribuicoes = d.get('atribuicoes') or {}
    nome_in = (d.get('nome') or '').strip()
    if not sequencia_id:
        return jsonify({'error': 'Sequência é obrigatória.'}), 400
    conn = get_db()
    seq = conn.execute('SELECT nome FROM sequencia_operacional WHERE id=?', (sequencia_id,)).fetchone()
    if not seq:
        conn.close()
        return jsonify({'error': 'Sequência não encontrada.'}), 404
    nome = nome_in or seq['nome']
    itens = conn.execute(
        '''SELECT si.ordem, bt.operacao
           FROM sequencia_itens si
           JOIN banco_tempos bt ON bt.id = si.banco_tempo_id
           WHERE si.sequencia_id=? ORDER BY si.ordem''',
        (sequencia_id,)
    ).fetchall()
    n = len(itens)
    if n == 0:
        conn.close()
        return jsonify({'error': 'Sequência não possui operações.'}), 400
    atrib_norm = {}
    for k, v in atribuicoes.items():
        try:
            ki = int(k)
        except (TypeError, ValueError):
            continue
        if isinstance(v, list) and v:
            ids = [int(x) for x in v if x is not None]
            if ids:
                atrib_norm[ki] = ids
    faltando = []
    for i in range(n):
        if not atrib_norm.get(i):
            faltando.append({'idx': i, 'operacao': itens[i]['operacao']})
    if faltando:
        conn.close()
        nomes = ', '.join(f["operacao"] for f in faltando)
        return jsonify({
            'error': f'Toda operação precisa de pelo menos um operador. Faltando: {nomes}',
            'faltando': faltando
        }), 400
    rid = d.get('id')
    if rid:
        row = conn.execute('SELECT id FROM remanejos WHERE id=?', (rid,)).fetchone()
        if not row:
            conn.close()
            return jsonify({'error': 'Remanejo não encontrado.'}), 404
        conn.execute('UPDATE remanejos SET nome=?, sequencia_id=? WHERE id=?', (nome, sequencia_id, rid))
        conn.execute('DELETE FROM remanejo_atribuicoes WHERE remanejo_id=?', (rid,))
    else:
        cur = conn.execute('INSERT INTO remanejos(nome, sequencia_id) VALUES(?,?)', (nome, sequencia_id))
        rid = cur.lastrowid
    operadores_unicos = set()
    for idx, ids in atrib_norm.items():
        for oid in ids:
            conn.execute(
                'INSERT OR IGNORE INTO remanejo_atribuicoes(remanejo_id, operacao_idx, operador_id) VALUES(?,?,?)',
                (rid, idx, oid)
            )
            operadores_unicos.add(oid)
    conn.commit(); conn.close()
    return jsonify({
        'ok': True, 'id': rid, 'nome': nome, 'sequencia_id': sequencia_id,
        'total_operacoes': n, 'total_operadores': len(operadores_unicos)
    })


@app.route('/api/remanejos/<int:rid>', methods=['DELETE'])
def del_remanejo(rid):
    """Soft delete remanejo (sempre). Use ?hard=1 pra delete físico."""
    hard = request.args.get('hard') == '1'
    conn = get_db()
    if hard:
        conn.execute('DELETE FROM remanejo_atribuicoes WHERE remanejo_id=?', (rid,))
        conn.execute('DELETE FROM remanejos WHERE id=?', (rid,))
    else:
        conn.execute('UPDATE remanejos SET ativo=0, deleted_at=? WHERE id=?',
                     (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), rid))
    conn.commit(); conn.close()
    return jsonify({'ok': True, 'soft': not hard})


@app.route('/api/remanejos/por-sequencia/<int:sid>', methods=['GET'])
def get_remanejo_por_sequencia(sid):
    """Retorna o último remanejo ATIVO da sequência. Compat com fluxo legado."""
    conn = get_db()
    row = conn.execute(
        'SELECT id FROM remanejos WHERE sequencia_id=? AND COALESCE(ativo,1)=1 ORDER BY id DESC LIMIT 1',
        (sid,)
    ).fetchone()
    conn.close()
    if not row:
        return jsonify({'found': False}), 200
    return get_remanejo(row['id'])


@app.route('/api/remanejos/<int:rid>', methods=['GET'])
def get_remanejo(rid):
    conn = get_db()
    b = conn.execute('SELECT id, nome, sequencia_id, ativo, deleted_at, criado_em FROM remanejos WHERE id=?', (rid,)).fetchone()
    if not b:
        conn.close()
        return jsonify({'error': 'Não encontrado'}), 404
    rows = conn.execute(
        'SELECT operacao_idx, operador_id FROM remanejo_atribuicoes WHERE remanejo_id=? ORDER BY operacao_idx',
        (rid,)
    ).fetchall()
    atribuicoes = {}
    operadores_unicos = []
    seen = set()
    for r in rows:
        atribuicoes.setdefault(str(r['operacao_idx']), []).append(r['operador_id'])
        if r['operador_id'] not in seen:
            seen.add(r['operador_id'])
            operadores_unicos.append(r['operador_id'])
    detalhe = []
    if operadores_unicos:
        placeholders = ','.join('?' for _ in operadores_unicos)
        ops = conn.execute(
            f'SELECT id, nome, funcao FROM operadores WHERE id IN ({placeholders})',
            operadores_unicos
        ).fetchall()
        det_map = {o['id']: dict(o) for o in ops}
        detalhe = [det_map[oid] for oid in operadores_unicos if oid in det_map]
    conn.close()
    return jsonify({
        'id': b['id'], 'nome': b['nome'], 'sequencia_id': b['sequencia_id'],
        'ativo': b['ativo'], 'deleted_at': b['deleted_at'], 'criado_em': b['criado_em'],
        'atribuicoes': atribuicoes,
        'operadores_unicos': operadores_unicos,
        'operadores_detalhe': detalhe
    })

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
    """Auto-balanceamento com regras (quando remanejo_id presente):
       1. Operações em ordem original (dependência sequencial).
       2. Cada time tem >=2 operadores extraídos do pool do remanejo.
       3. Cada operador no time cobre <=2 equipamentos distintos (best-effort, gera warning).
       4. Cada operação do time tem >=1 operador qualificado.
       5. Carga de cada time o mais próximo possível do ciclo, sem ultrapassar.
    """
    d = request.json or {}
    ops = d.get('ops', [])  # [{id, operacao, tempo_padrao, equipamento_nome, operacao_id?}]
    ciclo = float(d.get('ciclo', 30))
    n_times_req = int(d.get('n_times', 5))
    remanejo_id = d.get('remanejo_id')

    if not remanejo_id:
        # Modo legado: greedy sem ordem, sem operadores
        times = [{'num': i+1, 'ops': [], 'carga': 0} for i in range(n_times_req)]
        for op in sorted(ops, key=lambda x: x.get('tempo_padrao', 0), reverse=True):
            tp = op.get('tempo_padrao', 0)
            best = min(times, key=lambda t: t['carga'])
            best['ops'].append(op['id'])
            best['carga'] += tp
        return jsonify({'times': [{'num': t['num'], 'ops': t['ops'], 'carga': round(t['carga'], 6)} for t in times]})

    conn = get_db()
    rows = conn.execute(
        'SELECT DISTINCT operador_id FROM balanceamento_atribuicoes WHERE balanceamento_id=?',
        (remanejo_id,)
    ).fetchall()
    pool_ids = [r['operador_id'] for r in rows]
    if len(pool_ids) < 2:
        conn.close()
        return jsonify({'error': 'Pool de operadores insuficiente (mínimo 2 no remanejo).'}), 400
    placeholders = ','.join('?' for _ in pool_ids)
    op_rows = conn.execute(
        f'SELECT id, nome, operacoes FROM operadores WHERE id IN ({placeholders})',
        pool_ids
    ).fetchall()
    conn.close()

    pool = []
    for r in op_rows:
        try:
            qual = set(json.loads(r['operacoes'] or '[]'))
        except Exception:
            qual = set()
        pool.append({'id': r['id'], 'nome': r['nome'], 'qual': qual})

    n_times_max = max(1, len(pool) // 2)
    # Preserva ordem das operações conforme enviada
    ordered = list(ops)
    if ordered and n_times_max > len(ordered):
        n_times_max = len(ordered)
    n_times = n_times_max

    # Carrega DAG de dependências da sequência (banco_tempo_id -> [preds])
    sequencia_id = d.get('sequencia_id')
    deps_map = {}
    if sequencia_id:
        conn2 = get_db()
        scope_ids = set(int(o.get('id') or 0) for o in ordered)
        for r in conn2.execute(
            'SELECT banco_tempo_id, depende_de FROM sequencia_itens WHERE sequencia_id=?',
            (sequencia_id,)
        ).fetchall():
            try:
                lst = json.loads(r['depende_de'] or '[]')
            except Exception:
                lst = []
            deps_map[r['banco_tempo_id']] = [int(p) for p in lst if int(p) in scope_ids]
        conn2.close()

    # Carga efetiva com penalidade de equipamento escasso:
    # se 2+ ops do mesmo equipamento_nome num time, a soma de tps daquele grupo
    # conta dobrado (representa serialização forçada na máquina única).
    def carga_efetiva(team_ops):
        by_eq = {}
        for o in team_ops:
            eq = (o.get('equipamento_nome') or '').strip() or '_'
            by_eq.setdefault(eq, []).append(float(o.get('tempo_padrao') or 0))
        base = sum(float(o.get('tempo_padrao') or 0) for o in team_ops)
        extra = sum(sum(grp) for grp in by_eq.values() if len(grp) > 1)
        return base + extra

    n_ops = len(ordered)
    warnings = []
    chunks = []

    # Verifica se cada op respeita: pred deve aparecer antes na lista (sequência topológica).
    # save_sequencia já garante isso, mas defesa local.
    pos = {int(o.get('id') or 0): i for i, o in enumerate(ordered)}
    for op in ordered:
        bt_id = int(op.get('id') or 0)
        for p in deps_map.get(bt_id, []):
            if p in pos and pos[p] >= pos[bt_id]:
                warnings.append(f"Sequência fora de ordem topológica: '{op.get('operacao','?')}'.")

    # Pré-computa carga efetiva de chunks contíguos ordered[j:i].
    seg = [[0.0] * (n_ops + 1) for _ in range(n_ops + 1)]
    for j in range(n_ops):
        for i in range(j + 1, n_ops + 1):
            seg[j][i] = carga_efetiva(ordered[j:i])

    # DP: dp[i][k] = menor custo (Σ desvio²) particionando ordered[0:i] em k times contíguos.
    # Restrições: cada chunk não-vazio (mín 1 op por time), carga efetiva ≤ ciclo.
    pcs_ciclo = float(d.get('pcs_ciclo') or 0)
    total_tps = sum(float(o.get('tempo_padrao') or 0) for o in ordered)
    if pcs_ciclo > 0 and n_times > 0:
        # Target = K_avg × takt. Faz cargas convergirem pra valor que produz cap ≈ pcs_ciclo.
        k_avg = max(1, len(pool) / n_times)
        takt = ciclo / pcs_ciclo
        target_carga = k_avg * takt
    else:
        target_carga = (total_tps / n_times) if n_times else 0
    INF = float('inf')
    dp = [[INF] * (n_times + 1) for _ in range(n_ops + 1)]
    prev = [[None] * (n_times + 1) for _ in range(n_ops + 1)]
    dp[0][0] = 0.0
    for i in range(1, n_ops + 1):
        kmax = min(i, n_times)
        for k in range(1, kmax + 1):
            for j in range(k - 1, i):
                if dp[j][k - 1] == INF:
                    continue
                carga = seg[j][i]
                if carga > ciclo + 1e-9:
                    continue
                cost = dp[j][k - 1] + (carga - target_carga) ** 2
                if cost < dp[i][k]:
                    dp[i][k] = cost
                    prev[i][k] = j

    if n_ops == 0 or dp[n_ops][n_times] < INF:
        # Reconstrução
        cuts = []
        i, k = n_ops, n_times
        while k > 0:
            j = prev[i][k] if i else 0
            cuts.append((j, i))
            i, k = j, k - 1
        cuts.reverse()
        chunks = [ordered[j:i] for (j, i) in cuts]
    else:
        # Fallback: greedy com possível overflow (carga > ciclo) — emite warning.
        warnings.append('DP inviável (ciclo apertado p/ DAG); aplicando fallback greedy.')
        chunks = [[] for _ in range(n_times)]
        chunk_loads = [0.0] * n_times
        for op in ordered:
            tp = float(op.get('tempo_padrao') or 0)
            best_t = 0
            best_carga = INF
            for t in range(n_times):
                tentative = carga_efetiva(chunks[t] + [op])
                if tentative < best_carga:
                    best_carga = tentative
                    best_t = t
            chunks[best_t].append(op)
            chunk_loads[best_t] = carga_efetiva(chunks[best_t])
            if chunk_loads[best_t] > ciclo:
                warnings.append(f"Time {best_t+1}: carga {chunk_loads[best_t]:.3f} > ciclo {ciclo}.")

    # Detecta times vazios (não deveria acontecer com DP min-1-op, mas avisa)
    for i, ch in enumerate(chunks):
        if not ch:
            warnings.append(f"Time {i+1} vazio.")
    # Detecta dup-equipamento (informativo)
    for i, ch in enumerate(chunks):
        eqs = {}
        for o in ch:
            eq = (o.get('equipamento_nome') or '').strip() or '_'
            eqs[eq] = eqs.get(eq, 0) + 1
        dups = [eq for eq, c in eqs.items() if c > 1 and eq != '_']
        if dups:
            warnings.append(f"Time {i+1}: equipamento(s) repetido(s): {', '.join(dups)} (gargalo).")

    # Atribui operadores aos times via set-cover greedy + min 2 por time
    available = list(pool)
    times_chosen = []  # lista paralela aos chunks
    for i, chunk in enumerate(chunks):
        chunk_op_ids = set(int(o.get('operacao_id') or 0) for o in chunk if o.get('operacao_id'))
        chosen = []
        uncovered = set(chunk_op_ids)
        # Greedy set-cover (cobertura mínima)
        while available and (uncovered or len(chosen) < 2):
            best = None
            best_cov = -1
            for op in available:
                cov = len(uncovered & op['qual']) if uncovered else 0
                if best is None or cov > best_cov:
                    best = op; best_cov = cov
            if best is None:
                break
            if best_cov == 0 and len(chosen) >= 2:
                break
            chosen.append(best)
            uncovered -= best['qual']
            available.remove(best)
            if not uncovered and len(chosen) >= 2:
                break
        while len(chosen) < 2 and available:
            chosen.append(available.pop(0))
        if len(chosen) < 2:
            warnings.append(f"Time {i+1}: pool insuficiente para 2 operadores.")
        if uncovered:
            faltam = [o['operacao'] for o in chunk if int(o.get('operacao_id') or 0) in uncovered]
            warnings.append(f"Time {i+1}: operação(ões) sem operador qualificado: {', '.join(faltam)}")
        times_chosen.append(chosen)
    # Pass 2: distribui pool restante pra equilibrar capacidade (cap = K × ciclo / carga).
    # Atribui sobra ao time com MENOR cap (gargalo). Repete.
    def cap_of(chunk_ops, n_oper):
        cg = sum(float(o.get('tempo_padrao') or 0) for o in chunk_ops)
        return (n_oper * ciclo) / cg if cg > 0 else float('inf')
    while available:
        worst = min(range(len(chunks)), key=lambda i: cap_of(chunks[i], len(times_chosen[i])))
        chunk_op_ids = set(int(o.get('operacao_id') or 0) for o in chunks[worst] if o.get('operacao_id'))
        candidatos = sorted(available, key=lambda op: (-len(op['qual'] & chunk_op_ids), -len(op['qual'])))
        pick = candidatos[0]
        times_chosen[worst].append(pick)
        available.remove(pick)

    # Pass 3: local search — minimiza max-min cap movendo 1 operador por vez.
    # Restrição: cada time mantém >=2 ops e cobertura intacta.
    def all_caps():
        return [cap_of(chunks[i], len(times_chosen[i])) for i in range(len(chunks))]
    chunk_op_ids_list = [set(int(o.get('operacao_id') or 0) for o in chunks[i] if o.get('operacao_id'))
                         for i in range(len(chunks))]
    for _ in range(80):
        cs = all_caps()
        if not cs:
            break
        cur_gap = max(cs) - min(cs)
        if cur_gap < 1e-6:
            break
        best = None  # (gain, src, dst, op_idx_in_src)
        for src in range(len(chunks)):
            if len(times_chosen[src]) <= 2:
                continue
            src_chunk_ops = chunk_op_ids_list[src]
            for sidx, op in enumerate(times_chosen[src]):
                rest = times_chosen[src][:sidx] + times_chosen[src][sidx+1:]
                rest_qual = set().union(*(c['qual'] for c in rest)) if rest else set()
                if not src_chunk_ops.issubset(rest_qual):
                    continue
                for dst in range(len(chunks)):
                    if dst == src:
                        continue
                    new_src_K = len(times_chosen[src]) - 1
                    new_dst_K = len(times_chosen[dst]) + 1
                    new_cs = list(cs)
                    new_cs[src] = cap_of(chunks[src], new_src_K)
                    new_cs[dst] = cap_of(chunks[dst], new_dst_K)
                    new_gap = max(new_cs) - min(new_cs)
                    gain = cur_gap - new_gap
                    if gain > 1e-9 and (best is None or gain > best[0]):
                        best = (gain, src, dst, sidx)
        if best is None:
            break
        _, src, dst, sidx = best
        op = times_chosen[src].pop(sidx)
        times_chosen[dst].append(op)

    # Pass 4: merge de chunks adjacentes se reduz desvio quadrático da meta (pcs_ciclo).
    # Adjacentes preservam DAG (deps já estão em chunks anteriores ou no próprio).
    if pcs_ciclo > 0:
        def caps_of(chunks_list, chosen_list):
            out = []
            for i, ch in enumerate(chunks_list):
                cg = sum(float(o.get('tempo_padrao') or 0) for o in ch)
                K = len(chosen_list[i]) if chosen_list[i] else 1
                out.append((K * ciclo) / cg if cg > 0 else float('inf'))
            return out
        while len(chunks) > 1:
            cur_caps = caps_of(chunks, times_chosen)
            cur_cost = sum((c - pcs_ciclo) ** 2 for c in cur_caps)
            best_pair = None
            best_cost = cur_cost
            for i in range(len(chunks) - 1):
                merged_chunk = chunks[i] + chunks[i+1]
                merged_chosen = times_chosen[i] + times_chosen[i+1]
                cg = sum(float(o.get('tempo_padrao') or 0) for o in merged_chunk)
                K = len(merged_chosen)
                cap_m = (K * ciclo) / cg if cg > 0 else float('inf')
                cs2 = [cur_caps[j] for j in range(len(chunks)) if j != i and j != i+1] + [cap_m]
                cost2 = sum((c - pcs_ciclo) ** 2 for c in cs2)
                if cost2 < best_cost - 1e-9:
                    best_cost = cost2
                    best_pair = i
            if best_pair is None:
                break
            i = best_pair
            chunks[i] = chunks[i] + chunks[i+1]
            times_chosen[i] = times_chosen[i] + times_chosen[i+1]
            chunks.pop(i+1)
            times_chosen.pop(i+1)
        # Atualiza n_times pra refletir merges
        n_times = len(chunks)
    times_out = []
    for i, chunk in enumerate(chunks):
        chosen = times_chosen[i]
        # Distribui equipamentos por operador (best-effort): atribui cada op ao operador qualificado com menor count de equipamentos distintos
        eq_por_op = {o['id']: set() for o in chosen}
        op_assign = {}  # op.id -> operador.id
        for o in chunk:
            opid = int(o.get('operacao_id') or 0)
            eq = (o.get('equipamento_nome') or '').strip()
            qualif = [c for c in chosen if opid in c['qual']]
            if not qualif:
                qualif = chosen[:]
            qualif.sort(key=lambda c: (len(eq_por_op[c['id']] | ({eq} if eq else set())), len(eq_por_op[c['id']])))
            target_op = qualif[0] if qualif else None
            if target_op:
                op_assign[o['id']] = target_op['id']
                if eq:
                    eq_por_op[target_op['id']].add(eq)
        for c in chosen:
            if len(eq_por_op[c['id']]) > 2:
                warnings.append(f"Time {i+1}, operador {c['nome']}: {len(eq_por_op[c['id']])} equipamentos (máx 2).")
        carga = sum(float(o.get('tempo_padrao') or 0) for o in chunk)
        carga_eff = carga_efetiva(chunk)
        times_out.append({
            'num': i+1,
            'ops': [o['id'] for o in chunk],
            'operadores': [{'id': c['id'], 'nome': c['nome']} for c in chosen],
            'carga': round(carga, 6),
            'carga_efetiva': round(carga_eff, 6),
            'op_assign': op_assign,
        })
    return jsonify({
        'times': times_out,
        'warnings': warnings,
        'pool_size': len(pool),
        'n_times': n_times,
        'ciclo': ciclo,
    })

def _get_setting(conn, key, default=None):
    row = conn.execute('SELECT value FROM app_settings WHERE key=?', (key,)).fetchone()
    return row[0] if row else default

def _set_setting(conn, key, value):
    conn.execute('INSERT OR REPLACE INTO app_settings(key,value) VALUES(?,?)', (key, str(value)))

@app.route('/api/settings', methods=['GET'])
def list_settings():
    conn = get_db()
    rows = conn.execute('SELECT key, value FROM app_settings').fetchall()
    conn.close()
    return jsonify({r['key']: r['value'] for r in rows})

@app.route('/api/settings', methods=['POST'])
def save_settings():
    d = request.json or {}
    allowed = {'gordura_pct', 'arred_pacote', 'ciclo_curto_default', 'min_dia_default', 'tolerancia_ceil_pct', 'ocupacao_min_pct'}
    conn = get_db()
    for k, v in d.items():
        if k not in allowed:
            continue
        if k in ('gordura_pct', 'tolerancia_ceil_pct', 'ocupacao_min_pct'):
            try:
                f = float(v)
                if f < 0 or f > 100:
                    conn.close()
                    return jsonify({'error': f'{k} fora de [0,100]'}), 400
            except (TypeError, ValueError):
                conn.close()
                return jsonify({'error': f'{k} inválido'}), 400
        if k == 'arred_pacote' and v not in ('down', 'up', 'zero'):
            conn.close()
            return jsonify({'error': 'arred_pacote deve ser down/up/zero'}), 400
        _set_setting(conn, k, v)
    conn.commit()
    rows = conn.execute('SELECT key, value FROM app_settings').fetchall()
    conn.close()
    return jsonify({r['key']: r['value'] for r in rows})


@app.route('/api/balanceamentos/auto/takt', methods=['POST'])
def auto_balance_takt():
    """Balanceamento planilha-style (cronoanálise → pcs_pacote → pessoas/time + saldo/op).

    Calcula meta_dia a partir de operadoras+min_dia+eficiência+gordura(settings).
    Não considera operadores reais. Saldo é calculado por OPERAÇÃO.

    Payload:
      - ops: [{id, operacao, tempo_padrao, equipamento_nome, operacao_id?}]
      - min_dia: minutos/operadora/dia (default 540)
      - ciclo_curto: minutos do ciclo (default 15)
      - eficiencia_mostrada: 0..1 (default 1.0) — eficiência exibida
      - n_operadoras: nº operadoras disponíveis pra OP
      - n_times: opcional (default heurística)

    Settings consultadas: gordura_pct, arred_pacote.
    """
    import math
    d = request.json or {}
    ops = d.get('ops', [])
    min_dia = float(d.get('min_dia') or 540)
    ciclo_curto = float(d.get('ciclo_curto') or 15)
    efic_mostrada = float(d.get('eficiencia_mostrada') or 1.0)
    n_operadoras = int(d.get('n_operadoras') or 0)
    n_times_hint = d.get('n_times')

    if not ops:
        return jsonify({'error': 'ops vazio'}), 400
    if min_dia <= 0 or ciclo_curto <= 0:
        return jsonify({'error': 'min_dia/ciclo_curto inválidos'}), 400
    if n_operadoras <= 0:
        return jsonify({'error': 'n_operadoras deve ser > 0'}), 400

    conn = get_db()
    gordura_pct = float(_get_setting(conn, 'gordura_pct', '15') or 15)
    arred = _get_setting(conn, 'arred_pacote', 'down') or 'down'
    tolerancia_pct = float(_get_setting(conn, 'tolerancia_ceil_pct', str(gordura_pct)) or gordura_pct)
    conn.close()

    # Eficiência REAL (oculta). Aplica gordura sobre eficiência mostrada.
    efic_real = efic_mostrada * (1.0 - gordura_pct / 100.0)

    n_ops = len(ops)
    tps = [float(o.get('tempo_padrao') or 0) for o in ops]
    total_tp = sum(tps)
    if total_tp <= 0:
        return jsonify({'error': 'TP total = 0'}), 400

    ciclos_dia = min_dia / ciclo_curto
    # Pcs/Pacote (planilha H11): peças produzidas por ciclo curto, com gordura aplicada
    pcs_pacote_raw = (min_dia / total_tp) * n_operadoras * efic_real / ciclos_dia
    if arred == 'up':
        pcs_pacote = math.ceil(pcs_pacote_raw - 1e-9)
    elif arred == 'zero':
        pcs_pacote = 0
    else:  # down
        pcs_pacote = math.floor(pcs_pacote_raw + 1e-9)

    if pcs_pacote <= 0:
        return jsonify({
            'error': 'Pcs/Pacote calculou ≤ 0 — verifique entradas',
            'pcs_pacote_raw': round(pcs_pacote_raw, 4),
        }), 400

    meta_dia = pcs_pacote * ciclos_dia
    pcs_cab = meta_dia / n_operadoras if n_operadoras else 0
    takt = ciclo_curto / pcs_pacote

    total_pessoas = total_tp / takt

    if n_times_hint:
        n_times = max(1, min(int(n_times_hint), n_ops))
    else:
        n_times = max(1, min(n_ops, round(total_pessoas / 2.2)))

    # Prefix sums
    prefix = [0.0]
    for tp in tps:
        prefix.append(prefix[-1] + tp)

    # DP: minimiza Σ saldo_time² onde saldo_time = pessoas_round × ciclo − TP_time × pcs_pacote
    # Equivalente: ciclo × (pessoas_round − pessoas_dec). Penaliza tanto folga quanto déficit.
    INF = float('inf')
    dp = [[INF] * (n_times + 1) for _ in range(n_ops + 1)]
    prev = [[None] * (n_times + 1) for _ in range(n_ops + 1)]
    dp[0][0] = 0.0
    for i in range(1, n_ops + 1):
        kmax = min(i, n_times)
        for k in range(1, kmax + 1):
            for j in range(k - 1, i):
                if dp[j][k - 1] == INF:
                    continue
                chunk_tp = prefix[i] - prefix[j]
                chunk_pessoas_dec = chunk_tp / takt
                chunk_pessoas_round = max(1, round(chunk_pessoas_dec))
                chunk_demand = chunk_tp * pcs_pacote
                chunk_saldo = chunk_pessoas_round * ciclo_curto - chunk_demand
                cost = dp[j][k - 1] + chunk_saldo * chunk_saldo
                if cost < dp[i][k]:
                    dp[i][k] = cost
                    prev[i][k] = j

    if dp[n_ops][n_times] == INF:
        return jsonify({'error': 'Particionamento DP inviável.'}), 400

    cuts = []
    i, k = n_ops, n_times
    while k > 0:
        j = prev[i][k]
        cuts.append((j, i))
        i, k = j, k - 1
    cuts.reverse()

    tol_frac = tolerancia_pct / 100.0
    def op_metrics(tp):
        # pessoas_op_dec = TP × pcs_pacote / ciclo_curto
        pess_dec = (tp * pcs_pacote) / ciclo_curto if ciclo_curto > 0 else 0
        floor_p = math.floor(pess_dec + 1e-9)
        # Threshold: se pess_dec ≤ floor + tol, mantém floor (evita ceil desnecessário)
        # Só aplica quando floor_p ≥ 1 (abaixo de 1 sempre é forçado pra 1, sem trade-off)
        threshold = floor_p + tol_frac
        in_margin = (floor_p >= 1) and (pess_dec > floor_p + 1e-9) and (pess_dec <= threshold + 1e-9)
        if in_margin:
            pess_eff = floor_p
        else:
            pess_eff = max(1, math.ceil(pess_dec - 1e-9))
        carga = (tp * pcs_pacote) / pess_eff if pess_eff > 0 else 0
        saldo = ciclo_curto - carga
        return round(pess_dec, 4), pess_eff, round(carga, 4), round(saldo, 4), in_margin

    times_out = []
    total_pessoas_round = 0
    for idx, (j, i) in enumerate(cuts):
        chunk = ops[j:i]
        chunk_tps = tps[j:i]
        t_total = sum(chunk_tps)
        pessoas_dec = t_total / takt
        pessoas_round = max(1, round(pessoas_dec))
        total_pessoas_round += pessoas_round
        # Saldo time: capacidade (pessoas_round × ciclo) − demanda (TP × pcs_pacote)
        demand_time = t_total * pcs_pacote
        supply_time = pessoas_round * ciclo_curto
        saldo_time = supply_time - demand_time
        equipamentos = sorted({(o.get('equipamento_nome') or '').strip()
                               for o in chunk if o.get('equipamento_nome')})
        op_refs = []
        for o, tp in zip(chunk, chunk_tps):
            pdec, pceil, carga, saldo, gargalo = op_metrics(tp)
            op_refs.append({
                'id': o['id'],
                'operacao': o.get('operacao'),
                'equipamento_nome': o.get('equipamento_nome'),
                'tempo_padrao': tp,
                'pessoas_op': pdec,
                'pessoas_op_ceil': pceil,
                'carga_op': carga,
                'saldo_op': saldo,
                'gargalo_risco': gargalo,
            })
        times_out.append({
            'num': idx + 1,
            'ops': [o['id'] for o in chunk],
            'op_refs': op_refs,
            't_total': round(t_total, 6),
            'pessoas': round(pessoas_dec, 4),
            'pessoas_round': pessoas_round,
            'demand_time': round(demand_time, 4),
            'supply_time': round(supply_time, 4),
            'saldo_time': round(saldo_time, 4),
            'equipamentos': equipamentos,
        })

    total_gargalos = sum(1 for t in times_out for o in t['op_refs'] if o.get('gargalo_risco'))
    return jsonify({
        'mode': 'takt',
        'min_dia': min_dia,
        'ciclo_curto': ciclo_curto,
        'eficiencia_mostrada': efic_mostrada,
        'gordura_pct': gordura_pct,
        'tolerancia_ceil_pct': tolerancia_pct,
        'arred_pacote': arred,
        'n_operadoras': n_operadoras,
        'ciclos_dia': round(ciclos_dia, 4),
        'pcs_pacote': pcs_pacote,
        'pcs_pacote_raw': round(pcs_pacote_raw, 4),
        'meta_dia': round(meta_dia, 4),
        'pcs_cab': round(pcs_cab, 4),
        'takt': round(takt, 6),
        'total_tp': round(total_tp, 6),
        'total_pessoas_decimal': round(total_pessoas, 4),
        'total_pessoas_round': total_pessoas_round,
        'total_gargalos': total_gargalos,
        'n_times': n_times,
        'times': times_out,
    })


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

# ─── ATRIBUIÇÕES OPERADOR↔OP (BALANCEAMENTO RECRUTAMENTO) ──────────
def _compute_estado(conn, bid):
    """Calcula estado atual do bal: created/balanced/concluido."""
    b = conn.execute('SELECT id, sequencia_id FROM balanceamentos WHERE id=?', (bid,)).fetchone()
    if not b:
        return 'created'
    sid = b['sequencia_id']
    if not sid:
        return 'created'
    # Total ops da seq
    n_ops = conn.execute('SELECT COUNT(*) FROM sequencia_itens WHERE sequencia_id=?', (sid,)).fetchone()[0]
    if n_ops == 0:
        return 'created'
    # Ops alocadas em times salvos
    times = conn.execute(
        'SELECT operacoes FROM balanceamento_times WHERE balanceamento_id=?', (bid,)
    ).fetchall()
    alocadas = set()
    for t in times:
        try:
            for o in json.loads(t['operacoes'] or '[]'):
                if o.get('id'):
                    alocadas.add(o['id'])
        except Exception:
            pass
    # Total ops da seq (banco_tempo_ids)
    seq_op_ids = {r['banco_tempo_id'] for r in conn.execute(
        'SELECT banco_tempo_id FROM sequencia_itens WHERE sequencia_id=?', (sid,)
    ).fetchall()}
    if not seq_op_ids.issubset(alocadas):
        return 'created'
    # balanced: todas alocadas em times. Verifica se todas têm ≥1 operador atribuído
    atribs = conn.execute(
        'SELECT operacao_idx, operador_id FROM balanceamento_atribuicoes WHERE balanceamento_id=?', (bid,)
    ).fetchall()
    ops_com_operador = {r['operacao_idx'] for r in atribs}
    # operacao_idx aqui = banco_tempo_id (esquema reaproveitado)
    if seq_op_ids.issubset(ops_com_operador):
        return 'concluido'
    return 'balanced'


def _refresh_estado(conn, bid):
    estado = _compute_estado(conn, bid)
    conn.execute('UPDATE balanceamentos SET estado=? WHERE id=?', (estado, bid))
    return estado


@app.route('/api/balanceamentos/<int:bid>/relatorio', methods=['GET'])
def get_relatorio_balanceamento(bid):
    """Relatório enriquecido pra Divisão de Times: ops × colaboradores granular,
    indicadores de ocupação/gargalo/não-qualificação."""
    import math
    conn = get_db()
    bal = conn.execute('SELECT * FROM balanceamentos WHERE id=?', (bid,)).fetchone()
    if not bal:
        conn.close()
        return jsonify({'error': 'Não encontrado'}), 404
    seq_nome = '—'
    if bal['sequencia_id']:
        s = conn.execute('SELECT nome FROM sequencia_operacional WHERE id=?', (bal['sequencia_id'],)).fetchone()
        if s:
            seq_nome = s['nome']
    times = conn.execute(
        'SELECT * FROM balanceamento_times WHERE balanceamento_id=? ORDER BY numero_time', (bid,)
    ).fetchall()
    atribs_rows = conn.execute(
        '''SELECT a.operacao_idx AS op_id, a.operador_id, a.tempo_min, a.qualificado, a.numero_time,
                  o.nome AS operador_nome, o.funcao
           FROM balanceamento_atribuicoes a
           LEFT JOIN operadores o ON o.id=a.operador_id
           WHERE a.balanceamento_id=?''',
        (bid,)
    ).fetchall()
    # Settings
    gordura_pct = float(_get_setting(conn, 'gordura_pct', '15') or 15)
    tolerancia_pct = float(_get_setting(conn, 'tolerancia_ceil_pct', str(gordura_pct)) or gordura_pct)
    ocup_max_pct = float(_get_setting(conn, 'ocupacao_min_pct', '95') or 95)
    conn.close()
    ciclo = float(bal['ciclo_minutos'] or 15)
    pcs_pacote = bal['pcs_pacote'] or 0
    tol_frac = tolerancia_pct / 100.0
    # Aggrega atribs por op_id
    atribs_by_op = {}
    for r in atribs_rows:
        atribs_by_op.setdefault(r['op_id'], []).append({
            'operador_id': r['operador_id'],
            'operador_nome': r['operador_nome'] or f'#{r["operador_id"]}',
            'funcao': r['funcao'] or '',
            'tempo_min': r['tempo_min'] or 0,
            'qualificado': bool(r['qualificado']),
            'numero_time': r['numero_time'],
        })
    # Aggrega ocupação por operador (somando todos os times deste bal)
    ocup_by_oper = {}
    for r in atribs_rows:
        oid = r['operador_id']
        if oid not in ocup_by_oper:
            ocup_by_oper[oid] = {
                'operador_id': oid,
                'operador_nome': r['operador_nome'] or f'#{oid}',
                'funcao': r['funcao'] or '',
                'tempo_total': 0.0,
                'ops': [],
            }
        ocup_by_oper[oid]['tempo_total'] += r['tempo_min'] or 0
    for d in ocup_by_oper.values():
        d['ocupacao_pct'] = round((d['tempo_total'] / ciclo * 100) if ciclo > 0 else 0, 2)
        d['tempo_total'] = round(d['tempo_total'], 4)
    # Process times
    times_out = []
    for t in times:
        try:
            ops = json.loads(t['operacoes'] or '[]')
        except Exception:
            ops = []
        ops_out = []
        time_demanda = 0.0
        for o in ops:
            op_id = o['id']
            tp = float(o.get('tempo_padrao') or 0)
            demanda = tp * pcs_pacote
            time_demanda += demanda
            atribs = atribs_by_op.get(op_id, [])
            tempo_alocado = sum(a['tempo_min'] for a in atribs)
            # Métricas op (planilha-style com tolerância)
            pess_dec = (tp * pcs_pacote) / ciclo if ciclo > 0 else 0
            floor_p = math.floor(pess_dec + 1e-9)
            threshold = floor_p + tol_frac
            in_margin = (floor_p >= 1) and (pess_dec > floor_p + 1e-9) and (pess_dec <= threshold + 1e-9)
            pess_eff = floor_p if in_margin else max(1, math.ceil(pess_dec - 1e-9))
            # Adiciona %_alocado em cada atribuição (divisão da op)
            for a in atribs:
                a['pct_op'] = round((a['tempo_min'] / demanda * 100) if demanda > 0 else 0, 2)
                # Peças que esse operador faz (proporcional)
                a['pcs_alocadas'] = round((a['tempo_min'] / demanda * pcs_pacote) if demanda > 0 else 0, 2)
            ops_out.append({
                'id': op_id,
                'operacao': o.get('operacao'),
                'equipamento_nome': o.get('equipamento_nome'),
                'tempo_padrao': tp,
                'demanda_min': round(demanda, 4),
                'tempo_alocado': round(tempo_alocado, 4),
                'pessoas_op_dec': round(pess_dec, 4),
                'pessoas_op_ceil': pess_eff,
                'gargalo_risco': in_margin,
                'atribuicoes': atribs,
                'cobertura_pct': round((tempo_alocado / demanda * 100) if demanda > 0 else 0, 2),
            })
        # Pessoas time
        tp_time = sum(o.get('tempo_padrao', 0) for o in ops)
        takt = (ciclo / pcs_pacote) if pcs_pacote > 0 else 0
        pess_time_dec = (tp_time / takt) if takt > 0 else 0
        pess_time_round = max(1, round(pess_time_dec)) if pess_time_dec > 0 else 0
        supply_time = pess_time_round * ciclo
        saldo_time = supply_time - time_demanda
        # Operadores únicos no time
        opers_no_time = set()
        for o in ops_out:
            for a in o['atribuicoes']:
                opers_no_time.add(a['operador_id'])
        times_out.append({
            'numero_time': t['numero_time'],
            'ops': ops_out,
            'tp_total': round(tp_time, 6),
            'demanda_total': round(time_demanda, 4),
            'pessoas_dec': round(pess_time_dec, 4),
            'pessoas_round': pess_time_round,
            'supply_time': round(supply_time, 4),
            'saldo_time': round(saldo_time, 4),
            'operadores_unicos': sorted(opers_no_time),
        })
    return jsonify({
        'id': bal['id'],
        'nome': bal['nome'],
        'produto': bal['produto'],
        'sequencia_id': bal['sequencia_id'],
        'sequencia_nome': seq_nome,
        'estado': bal['estado'],
        'ciclo_minutos': ciclo,
        'meta_dia': bal['meta_dia'],
        'pcs_pacote': pcs_pacote,
        'minutos_trabalhados': bal['minutos_trabalhados'],
        'eficiencia': bal['eficiencia'],
        'gordura_pct': gordura_pct,
        'tolerancia_ceil_pct': tolerancia_pct,
        'ocupacao_min_pct': ocup_max_pct,
        'times': times_out,
        'operadores_ocupacao': sorted(ocup_by_oper.values(), key=lambda x: -x['ocupacao_pct']),
    })


@app.route('/api/balanceamentos/<int:bid>/atribuicoes', methods=['GET'])
def get_atribuicoes(bid):
    """Retorna atribuições + ocupação por operador."""
    conn = get_db()
    rows = conn.execute(
        '''SELECT a.operacao_idx, a.operador_id, a.tempo_min, a.qualificado, a.numero_time,
                  o.nome AS operador_nome, o.funcao, o.operacoes AS qualificacoes,
                  o.equipamentos_ids
           FROM balanceamento_atribuicoes a
           LEFT JOIN operadores o ON o.id=a.operador_id
           WHERE a.balanceamento_id=?''', (bid,)
    ).fetchall()
    bal = conn.execute('SELECT ciclo_minutos, sequencia_id, estado, remanejo_id FROM balanceamentos WHERE id=?', (bid,)).fetchone()
    ciclo = bal['ciclo_minutos'] if bal else 15
    # Pool vem do remanejo apontado pelo bal (bal.remanejo_id), fallback p/ último ativo da seq
    pool_ids = []
    rem_id = bal['remanejo_id'] if bal else None
    if not rem_id and bal and bal['sequencia_id']:
        rem = conn.execute(
            'SELECT id FROM remanejos WHERE sequencia_id=? AND COALESCE(ativo,1)=1 ORDER BY id DESC LIMIT 1',
            (bal['sequencia_id'],)
        ).fetchone()
        rem_id = rem['id'] if rem else None
    if rem_id:
        pool_ids = [r['operador_id'] for r in conn.execute(
            'SELECT DISTINCT operador_id FROM remanejo_atribuicoes WHERE remanejo_id=?', (rem_id,)
        ).fetchall()]
    pool = []
    if pool_ids:
        placeholders = ','.join('?' for _ in pool_ids)
        pool_rows = conn.execute(
            f'SELECT id, nome, funcao, operacoes, equipamentos_ids, status FROM operadores WHERE id IN ({placeholders})',
            pool_ids
        ).fetchall()
        # Tempo já alocado neste bal por operador
        ocup = {}
        for r in rows:
            ocup[r['operador_id']] = ocup.get(r['operador_id'], 0) + (r['tempo_min'] or 0)
        for o in pool_rows:
            tempo_aloc = ocup.get(o['id'], 0)
            ocup_pct = (tempo_aloc / ciclo * 100) if ciclo > 0 else 0
            pool.append({
                'id': o['id'], 'nome': o['nome'], 'funcao': o['funcao'],
                'operacoes': o['operacoes'] or '[]',
                'equipamentos_ids': o['equipamentos_ids'] or '[]',
                'status': o['status'],
                'tempo_alocado': round(tempo_aloc, 4),
                'ocupacao_pct': round(ocup_pct, 2),
            })
    atribs = []
    for r in rows:
        atribs.append({
            'op_id': r['operacao_idx'],
            'operador_id': r['operador_id'],
            'tempo_min': r['tempo_min'] or 0,
            'qualificado': r['qualificado'],
            'numero_time': r['numero_time'],
            'operador_nome': r['operador_nome'],
            'funcao': r['funcao'],
        })
    conn.close()
    return jsonify({'atribuicoes': atribs, 'pool': pool, 'ciclo_minutos': ciclo,
                    'estado': bal['estado'] if bal else 'created'})


@app.route('/api/balanceamentos/<int:bid>/atribuicoes', methods=['POST'])
def add_atribuicao(bid):
    """Adiciona/atualiza atribuição manual (drag-drop). Permite não-qualificado com flag."""
    d = request.json or {}
    op_id = int(d.get('op_id') or 0)
    operador_id = int(d.get('operador_id') or 0)
    tempo_min = float(d.get('tempo_min') or 0)
    numero_time = d.get('numero_time')
    if not op_id or not operador_id:
        return jsonify({'error': 'op_id e operador_id obrigatórios'}), 400
    conn = get_db()
    op_row = conn.execute('SELECT id, nome, operacoes FROM operadores WHERE id=?', (operador_id,)).fetchone()
    if not op_row:
        conn.close()
        return jsonify({'error': 'Operador não encontrado'}), 404
    try:
        qualificacoes = set(json.loads(op_row['operacoes'] or '[]'))
    except Exception:
        qualificacoes = set()
    # op_id é banco_tempo_id; precisa resolver pra operacao_id (catálogo)
    bt = conn.execute('SELECT operacao_id FROM banco_tempos WHERE id=?', (op_id,)).fetchone()
    cat_op_id = bt['operacao_id'] if bt else None
    qualificado = 1 if (cat_op_id and cat_op_id in qualificacoes) else 0
    # Upsert
    existing = conn.execute(
        'SELECT id FROM balanceamento_atribuicoes WHERE balanceamento_id=? AND operacao_idx=? AND operador_id=?',
        (bid, op_id, operador_id)
    ).fetchone()
    if existing:
        conn.execute(
            'UPDATE balanceamento_atribuicoes SET tempo_min=?, qualificado=?, numero_time=? WHERE id=?',
            (tempo_min, qualificado, numero_time, existing['id'])
        )
    else:
        conn.execute(
            '''INSERT INTO balanceamento_atribuicoes(balanceamento_id, operacao_idx, operador_id, tempo_min, qualificado, numero_time)
               VALUES(?,?,?,?,?,?)''',
            (bid, op_id, operador_id, tempo_min, qualificado, numero_time)
        )
    estado = _refresh_estado(conn, bid)
    conn.commit()
    conn.close()
    return jsonify({'ok': True, 'qualificado': qualificado, 'estado': estado})


@app.route('/api/balanceamentos/<int:bid>/atribuicoes', methods=['DELETE'])
def del_atribuicao(bid):
    op_id = request.args.get('op_id', type=int)
    operador_id = request.args.get('operador_id', type=int)
    if not op_id or not operador_id:
        return jsonify({'error': 'op_id e operador_id obrigatórios'}), 400
    conn = get_db()
    conn.execute(
        'DELETE FROM balanceamento_atribuicoes WHERE balanceamento_id=? AND operacao_idx=? AND operador_id=?',
        (bid, op_id, operador_id)
    )
    estado = _refresh_estado(conn, bid)
    conn.commit()
    conn.close()
    return jsonify({'ok': True, 'estado': estado})


@app.route('/api/balanceamentos/<int:bid>/alocar-operadores', methods=['POST'])
def alocar_operadores(bid):
    """Auto-distribui pool do remanejo nas ops do balanceamento.

    Algoritmo fair-share por op:
    1. Pra cada time T, lista ops + demanda (TP × pcs_pacote)
    2. Pra cada op O, lista candidatos qualificados (intersect pool com qualificados em O)
    3. Distribui demanda igualmente entre candidatos, respeitando ciclo curto e ocupacao_max
    4. Operadores com tempo livre podem cobrir múltiplos times (até ocupacao_min_pct)
    """
    import math
    conn = get_db()
    bal = conn.execute('SELECT * FROM balanceamentos WHERE id=?', (bid,)).fetchone()
    if not bal:
        conn.close()
        return jsonify({'error': 'Balanceamento não encontrado'}), 404
    sid = bal['sequencia_id']
    pcs_pacote = bal['pcs_pacote'] or 0
    ciclo = bal['ciclo_minutos'] or 15
    if not sid or pcs_pacote <= 0:
        conn.close()
        return jsonify({'error': 'Bal sem sequência ou pcs_pacote inválido'}), 400
    # Pool: usa bal.remanejo_id, fallback p/ último ativo da seq
    rem_id = bal['remanejo_id']
    if not rem_id:
        rem = conn.execute(
            'SELECT id FROM remanejos WHERE sequencia_id=? AND COALESCE(ativo,1)=1 ORDER BY id DESC LIMIT 1',
            (sid,)
        ).fetchone()
        rem_id = rem['id'] if rem else None
    if not rem_id:
        conn.close()
        return jsonify({'error': 'Nenhum remanejo vinculado. Crie/escolha um remanejo primeiro.'}), 400
    pool_ids = [r['operador_id'] for r in conn.execute(
        'SELECT DISTINCT operador_id FROM remanejo_atribuicoes WHERE remanejo_id=?', (rem_id,)
    ).fetchall()]
    if not pool_ids:
        conn.close()
        return jsonify({'error': 'Pool vazio. Adicione operadores ao remanejo.'}), 400
    placeholders = ','.join('?' for _ in pool_ids)
    pool = list(conn.execute(
        f'SELECT id, nome, operacoes FROM operadores WHERE id IN ({placeholders})', pool_ids
    ).fetchall())
    # Decode qualificações
    pool_qual = {}
    for o in pool:
        try:
            pool_qual[o['id']] = set(json.loads(o['operacoes'] or '[]'))
        except Exception:
            pool_qual[o['id']] = set()
    # Times do bal
    times = conn.execute(
        'SELECT * FROM balanceamento_times WHERE balanceamento_id=? ORDER BY numero_time', (bid,)
    ).fetchall()
    if not times:
        conn.close()
        return jsonify({'error': 'Bal não tem times. Faça balanceamento Takt primeiro.'}), 400
    # Settings
    ocup_max_pct = float(_get_setting(conn, 'ocupacao_min_pct', '95') or 95)
    cap_max_min = ciclo * (ocup_max_pct / 100.0)
    # Limpa atribuições antigas
    conn.execute('DELETE FROM balanceamento_atribuicoes WHERE balanceamento_id=?', (bid,))
    # Tempo já alocado por operador (acumulado)
    tempo_aloc = {oid: 0.0 for oid in pool_ids}
    warnings = []
    atribs_out = []
    for t in times:
        n_time = t['numero_time']
        try:
            ops = json.loads(t['operacoes'] or '[]')
        except Exception:
            ops = []
        for o in ops:
            op_id = o['id']  # banco_tempos.id
            tp = float(o.get('tempo_padrao') or 0)
            demanda = tp * pcs_pacote
            # Resolve operacao_id (catálogo) p/ checar qualificação
            bt = conn.execute('SELECT operacao_id FROM banco_tempos WHERE id=?', (op_id,)).fetchone()
            cat_op_id = bt['operacao_id'] if bt else None
            # Candidatos qualificados com tempo disponível
            candidatos = []
            for oid in pool_ids:
                if cat_op_id and cat_op_id in pool_qual.get(oid, set()):
                    livre = cap_max_min - tempo_aloc[oid]
                    if livre > 1e-6:
                        candidatos.append((oid, livre))
            if not candidatos:
                warnings.append(f"Time {n_time} op {o.get('operacao','?')} (id={op_id}): sem operador qualificado disponível.")
                continue
            # Fair share: distribuir demanda entre candidatos com mais capacidade primeiro
            candidatos.sort(key=lambda x: -x[1])
            resto = demanda
            for oid, livre in candidatos:
                if resto <= 1e-6:
                    break
                alloc = min(resto, livre, ciclo)  # nunca aloca mais que 1 ciclo por op
                if alloc <= 1e-6:
                    continue
                conn.execute(
                    '''INSERT INTO balanceamento_atribuicoes(balanceamento_id, operacao_idx, operador_id, tempo_min, qualificado, numero_time)
                       VALUES(?,?,?,?,1,?)''',
                    (bid, op_id, oid, round(alloc, 4), n_time)
                )
                tempo_aloc[oid] += alloc
                resto -= alloc
                atribs_out.append({'op_id': op_id, 'operador_id': oid, 'tempo_min': round(alloc, 4), 'numero_time': n_time})
            if resto > 0.5:
                warnings.append(f"Time {n_time} op {o.get('operacao','?')}: demanda {demanda:.2f}min, alocado {demanda-resto:.2f}min (déficit {resto:.2f}min).")
    estado = _refresh_estado(conn, bid)
    conn.commit()
    conn.close()
    return jsonify({
        'ok': True,
        'atribuicoes': atribs_out,
        'warnings': warnings,
        'estado': estado,
        'ocupacao_max_pct': ocup_max_pct,
    })


if __name__ == '__main__':
    import os
    debug = os.environ.get('FLASK_DEBUG', '1') != '0'
    print("\n" + "="*55)
    print("  SISTEMA DE BALANCEAMENTO DE PRODUÇÃO")
    print("  Acesse: http://localhost:5000")
    print(f"  Hot reload: {'ON' if debug else 'OFF'} (FLASK_DEBUG={'0' if not debug else '1'})")
    print("="*55 + "\n")
    # debug=True ativa Werkzeug reloader: monitora .py e recarrega no save
    app.run(debug=debug, port=5000, use_reloader=debug)
