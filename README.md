# BalancePro — Sistema de Balanceamento de Produção

Sistema web para balanceamento de linha de produção (confecção), desenvolvido em Python com Flask. Permite cadastrar operações e seus tempos, sequenciar operações, montar balanceamentos por ciclo e distribuir cargas entre colaboradores.

---

## O que o sistema faz

### Dashboard
Painel com indicadores gerais: total de operações no banco, tempo padrão acumulado, quantidade de operadores, equipamentos, sequências e balanceamentos cadastrados. Exibe distribuição de carga por equipamento.

### Banco de Tempos
Cadastro de operações com:
- Nome da operação, equipamento utilizado, nome da operadora
- Tempo cronometrado (minutos e segundos) e percentual de eficiência
- Cálculo automático do **Tempo Padrão** pela fórmula: `TP = (tempo_min / 10) / eficiência`
- Importação em lote via arquivo CSV ou ODS
- Exportação do banco completo como CSV

### Sequência Operacional
Agrupa operações do banco em sequências nomeadas, definindo a ordem em que serão executadas na linha. Calcula automaticamente o tempo padrão total da sequência.

### Balanceamento
Interface interativa (arrastar e soltar) para montar o balanceamento:
- Define o **ciclo** de produção: 5, 10, 15, 20, 25, 30, 45 ou 60 minutos
- Distribui as operações da sequência entre os times/postos
- Exibe a carga de cada time e o saldo em relação ao ciclo
- Auto-balanceamento automático por algoritmo **greedy** (maior operação primeiro, aloca no time menos carregado)
- Exportação do balanceamento como CSV

### Divisão de Times
Associa operadores cadastrados aos times definidos no balanceamento, com visualização da carga por colaborador.

### Operadores
Cadastro completo de colaboradores:
- Nome completo, CPF, telefone
- Endereço (logradouro, bairro, cidade, estado, CEP)
- Função e status (Ativo/Inativo)

### Equipamentos
Cadastro de máquinas e equipamentos:
- Código, nome, tipo, marca, modelo
- Número de patrimônio, status e observações

---

## O que o sistema **não** faz

- Não calcula cronoanálise — os tempos são inseridos manualmente a partir de cronometragem prévia
- Não tem controle de apontamento de produção (ordens de serviço, produção realizada)
- Não integra diretamente com planilhas Excel — a importação é via CSV/ODS exportado manualmente
- Não possui autenticação de usuários ou controle de acesso
- Não envia notificações ou e-mails
- Não tem backup automático do banco de dados

---

## Módulos / Arquivos

| Arquivo | Descrição |
|---|---|
| `iniciar.py` | Launcher: instala Flask se ausente, abre o browser e inicia o servidor |
| `app.py` | Backend Flask com todas as rotas da API e inicialização do banco SQLite |
| `templates/index.html` | Frontend completo — SPA em HTML + CSS + JavaScript puro, sem frameworks |
| `balanceamento.db` | Banco de dados SQLite (criado automaticamente na primeira execução) |

---

## Tecnologias

- **Backend:** Python 3 + Flask
- **Banco de dados:** SQLite (arquivo local `balanceamento.db`)
- **Frontend:** HTML5, CSS3 e JavaScript puro (sem frameworks, sem build step)
- **Dependência externa:** apenas `flask` (instalada automaticamente pelo `iniciar.py`)

---

## Como executar

```bash
python iniciar.py
```

O sistema abrirá automaticamente no navegador em `http://localhost:5000`.

Para encerrar: `Ctrl+C` no terminal.

> Na primeira execução, o Flask será instalado automaticamente se não estiver presente no ambiente.

---

## Fórmula do Tempo Padrão

```
TP = (tempo_cronometrado_em_minutos / 10) / eficiência
```

Exemplo: operação de 1min30s com eficiência de 85%:
```
TP = (1.5 / 10) / 0.85 = 0.176471
```

O ciclo do balanceamento representa a capacidade máxima de carga por time. A soma dos tempos padrão das operações alocadas em cada time não deve ultrapassar o ciclo definido.
