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

def open_browser():
    time.sleep(1.5)
    webbrowser.open('http://localhost:5000')

threading.Thread(target=open_browser, daemon=True).start()
app.run(debug=False, port=5000, host='0.0.0.0')
