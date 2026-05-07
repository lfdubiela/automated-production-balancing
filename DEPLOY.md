# Deploy — Fly.io

Guia passo-a-passo pra publicar o BalancePro em produção.

## Pré-requisitos

- Conta Fly.io (https://fly.io/app/sign-up)
- Cartão de crédito (verificação — não é cobrado dentro do free tier)
- `flyctl` CLI instalado

## 1. Instalar flyctl

```bash
# macOS
brew install flyctl

# Linux
curl -L https://fly.io/install.sh | sh

# Windows (PowerShell)
iwr https://fly.io/install.ps1 -useb | iex
```

## 2. Autenticar

```bash
fly auth signup    # primeira vez
# OU
fly auth login     # já tem conta
```

## 3. Setup inicial (uma vez por app)

```bash
cd /caminho/balanceamento

# Cria app na Fly (não faz deploy ainda)
fly launch --no-deploy --copy-config --name balancepro --region gru
# Aceita config existente (fly.toml já está no repo)

# Cria volume persistente para SQLite (1GB grátis)
fly volumes create balancepro_data --region gru --size 1
```

> **Nota**: `app = "balancepro"` no `fly.toml` precisa ser único globalmente. Se o nome estiver tomado, edite pra algo único (ex: `balancepro-acme`).

## 4. Deploy

```bash
fly deploy
```

Primeiro deploy demora ~3-5 min (build da imagem + push). Subsequentes ~1 min.

## 5. Acessar app

```bash
fly open                # abre URL no browser
fly status              # status das máquinas
fly logs                # logs em tempo real
```

URL padrão: `https://balancepro.fly.dev`

## 6. Domínio custom (opcional)

```bash
fly certs add balanceamento.exemplo.com.br
# Adiciona CNAME no DNS apontando pra balancepro.fly.dev
fly certs check balanceamento.exemplo.com.br
```

## 7. Backups SQLite

```bash
# Download do DB pra máquina local
fly ssh sftp shell
> get /data/balanceamento.db backup-$(date +%F).db

# Ou via comando único
fly ssh console -C "cat /data/balanceamento.db" > backup.db
```

Sugestão: cron local diário rodando o comando acima.

## 8. Restore SQLite

```bash
# Sobe DB local pro volume
fly ssh sftp shell
> put backup.db /data/balanceamento.db

# Reinicia pra garantir
fly machines restart
```

## 9. Auto-deploy via GitHub Actions (via tag)

Workflow em `.github/workflows/fly-deploy.yml` dispara deploy ao **criar tag `v*.*.*`** (semver). Push em `main` NÃO faz deploy automático — só tags.

### Setup (uma vez)

```bash
# Gera token de deploy
fly tokens create deploy -x 8760h    # 1 ano

# Adiciona como secret no GitHub
gh secret set FLY_API_TOKEN
# Cole o token quando pedir
```

### Release fluxo

```bash
# 1. Faz mudanças no código + push pra main (não deploya)
git push origin main

# 2. Cria tag semver pra release (deploya)
git tag -a v1.0.0 -m "Primeira release produção"
git push origin v1.0.0

# 3. Acompanha deploy
gh run list --workflow=fly-deploy.yml
gh run watch
```

### Deploy manual via UI

GitHub → Actions → "Deploy to Fly.io" → Run workflow → escolhe ref (tag ou branch)

### Listar tags / desfazer

```bash
git tag -l "v*"                 # lista
git tag -d v1.0.0               # apaga local
git push origin --delete v1.0.0 # apaga remoto
```

### Convenção de tags sugerida

- `v1.0.0` major.minor.patch
- Major = breaking change schema/API
- Minor = nova feature
- Patch = bugfix

## 10. Monitoramento

```bash
fly logs                    # stream
fly status                  # status atual
fly machines list           # lista VMs
fly metrics                 # CPU/RAM/req
```

## Custos

- Free tier (a partir de 2024): pago via Pay-As-You-Go com $5 USD de crédito mensal pra apps pequenos
- Este app cabe no free com `auto_stop_machines = "stop"` (dorme quando ocioso)
- Volume 1GB grátis (até 3GB)
- Estimativa real: **$0/mês** se uso é esporádico

## Troubleshooting

**"App não inicia"**
```bash
fly logs --instance-id <id>
```

**"DB não persistiu após restart"**
- Verifica volume: `fly volumes list`
- Confirma mount em `fly.toml` (`destination = "/data"`)
- Confirma `DB_PATH=/data/balanceamento.db` no env

**"502 Bad Gateway"**
- App falhou em iniciar dentro do `grace_period`
- Aumenta em `fly.toml` se demora a subir
- Roda `fly logs` pra ver stacktrace

**"Permission denied no /data"**
- Volume foi criado em região diferente da app
- Recriar: `fly volumes destroy <id>` + `fly volumes create ... --region gru`

## Variáveis de ambiente

Setadas em `fly.toml` (`[env]`):
- `FLASK_DEBUG=0` — produção (sem hot reload)
- `DB_PATH=/data/balanceamento.db` — DB no volume persistente
- `PORT=8080` — porta interna do gunicorn

Para secrets (futuras adições, ex: SECRET_KEY):
```bash
fly secrets set FLASK_SECRET_KEY=$(openssl rand -hex 32)
fly secrets list
```

## Rollback

```bash
fly releases                       # lista releases
fly releases rollback <version>    # volta pra versão anterior
```

## Local Docker test

Antes de fazer deploy, validar imagem local:

```bash
docker build -t balancepro .
docker run -p 8080:8080 -v $(pwd)/data:/data balancepro
# Acessar http://localhost:8080
```
