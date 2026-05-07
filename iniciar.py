#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════╗
║   BALANCEPRO — Sistema de Balanceamento          ║
║   de Produção para Confecção                     ║
╠══════════════════════════════════════════════════╣
║  1. Execute: python3 iniciar.py                  ║
║  2. Abra no navegador: http://localhost:5000      ║
║  3. Para encerrar: Ctrl+C                        ║
╚══════════════════════════════════════════════════╝
"""
import subprocess, sys, os, webbrowser, time, threading

os.chdir(os.path.dirname(os.path.abspath(__file__)))

# Instalar Flask se necessário
try:
    import flask
except ImportError:
    print("Instalando Flask (apenas na primeira vez)...")
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'flask', '--quiet'])

print("""
╔══════════════════════════════════════════════════╗
║   ⚙️  BALANCEPRO — Balanceamento de Produção     ║
╠══════════════════════════════════════════════════╣
║  🌐  Acesse: http://localhost:5000               ║
║  📊  Dashboard com gráficos e indicadores        ║
║  ⏱️  Banco de Tempos completo                    ║
║  🎮  Balanceamento com arrastar e soltar          ║
║  👥  Divisão de times e colaboradores            ║
║  ⛔  Para encerrar: Ctrl+C                       ║
╚══════════════════════════════════════════════════╝
""")

from app import app, init_db
init_db()

debug = os.environ.get('FLASK_DEBUG', '1') != '0'

def open_browser():
    time.sleep(1.5)
    webbrowser.open('http://localhost:5000')

# Werkzeug reloader fork: só abre browser no processo principal (evita 2x)
if not debug or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
    threading.Thread(target=open_browser, daemon=True).start()

# Watch templates/ também (Werkzeug por default só monitora .py)
import glob
extra_files = glob.glob('templates/**/*.html', recursive=True) if debug else None

print(f"  Hot reload: {'ON' if debug else 'OFF'} (FLASK_DEBUG={'0' if not debug else '1'})")
if extra_files:
    print(f"  Watching: {len(extra_files)} arquivo(s) HTML em templates/\n")
else:
    print()
app.run(debug=debug, port=5000, host='0.0.0.0', use_reloader=debug, extra_files=extra_files)
