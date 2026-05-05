# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Application

```bash
python iniciar.py
```

This auto-installs Flask if missing, initializes the SQLite database, opens the browser at `http://localhost:5000`, and starts the Flask dev server.

To run the Flask app directly (without auto-browser open):

```bash
python app.py
```

## Architecture Overview

This is a **production balancing (balanceamento de produção)** web app with a Flask backend and a single-page frontend. The UI is entirely in Portuguese.

### Structure

- **`app.py`** — Flask backend with all 22 API routes and SQLite setup. Database initializes automatically on first run.
- **`iniciar.py`** — Launcher that installs Flask if absent, inits the DB, and opens the browser.
- **`templates/index.html`** — The entire frontend: a tab-based SPA in vanilla JS with no frameworks or build step.
- **`balanceamento.db`** — SQLite database (auto-created; do not commit).
- **`static/`** — Reserved for static assets (currently empty).

### Database Schema (8 tables)

| Table | Purpose |
|---|---|
| `equipamentos` | Equipment/machines |
| `operadores` | Workers with contact info |
| `banco_tempos` | Library of operations with standard times |
| `sequencia_operational` | Named groups of operations |
| `sequencia_itens` | Items in each sequence (join table) |
| `balanceamentos` | Production balancing configurations |
| `balanceamento_times` | Teams/assignments within a balancing |

### API Design

All endpoints are under `/api/`. Standard CRUD pattern: `GET` (list), `POST` (create/update), `DELETE`. Key specialized endpoints:

- `POST /api/balanceamentos/auto` — Greedy auto-balancing algorithm to distribute operations across teams
- `POST /api/banco/importar` — Bulk import operations from CSV/ODS
- `GET /api/relatorio/balanceamento/<id>` — Export balancing as CSV
- `GET /api/stats` — Dashboard statistics

### Frontend

`index.html` contains all HTML, CSS, and JavaScript inline. Navigation uses a tab system with seven sections: Dashboard, Banco, Sequência, Balanceamento, Divisão de Times, Operadores, Equipamentos. The balancing view includes drag-and-drop workload assignment.

## Dependencies

No `requirements.txt` exists. The only external dependency is:

- `flask` (auto-installed by `iniciar.py` if missing)

All other imports (`sqlite3`, `csv`, `datetime`, `os`, `json`) are Python stdlib.
