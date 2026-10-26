# Office Stock & Inventory Management System

A production-ready, server-rendered Django web application for multi-branch office inventory tracking, purchasing, dispatches, petty cash management, and audit logging.

Built with Python, Django, WhiteNoise, Docker, and Caddy with automatic SSL (Let's Encrypt).

---

## Table of Contents
1. [Core Features](#core-features)
2. [Local Development (Quick Start)](#local-development-quick-start)
3. [Sample Data & Testing](#sample-data--testing)
4. [Deploying on Oracle Cloud (Always Free)](#deploying-on-oracle-cloud-always-free)
5. [Connecting Your Custom Domain & SSL](#connecting-your-custom-domain--ssl)
6. [Data Backup & Recovery](#data-backup--recovery)
7. [Maintenance & Scheduled Tasks](#maintenance--scheduled-tasks)
8. [Configuration Reference](#configuration-reference)
9. [Project Structure](#project-structure)

---

## Core Features

- **Multi-Branch Inventory**: Main office warehouse and individual branch stock tracking.
- **Stock Ledger**: Immutable, append-only transaction ledger with row-level concurrency locking.
- **Purchasing & Issues**: Purchase order receiving (with partial receive support) and cancel-by-reversal office issues.
- **Branch Requests & Dispatches**: Requests raised by branches, reviewed by managers, dispatched with discrepancy/damage tracking.
- **Petty Cash Module**: Branch-specific petty cash request workflow, manager approvals, expense recording, and low-cash alerts.
- **Role-Based Access Control (RBAC)**: Fine-grained permissions per user and role (Super Admin, Stock Officer, Branch User, Viewer).
- **Audit Logging**: Append-only audit trail capturing user actions, IP addresses, and timestamps.
- **Reports**: Stock balance, purchase summaries, usage statistics, and dispatch reports with CSV export and print view.

---

## Local Development (Quick Start)

### Windows (PowerShell)

```powershell
# 1. Create and activate virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1    # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

# 2. Install dependencies
pip install -r requirements.txt

# 3. Create local environment file
Copy-Item .env.example .env

# 4. Run migrations and seed initial data
python manage.py migrate
python manage.py seed           # Creates main office, default roles, and first Super Admin

# 5. Start development server
python manage.py runserver
```

### macOS / Linux (Bash)

```bash
# 1. Create and activate virtual environment
python3 -m venv .venv && source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Create local environment file
cp .env.example .env

# 4. Run migrations and seed initial data
python manage.py migrate
python manage.py seed

# 5. Start development server
python manage.py runserver
```

Sign in at **http://127.0.0.1:8000/** using credentials configured in your `.env` (default: `admin@example.com` / `SEED_ADMIN_PASSWORD`).

---

## Sample Data & Testing

### Load Fictional Sample Data (Development Only)
Populates 5 sample records of every kind (branches, users, suppliers, items, purchases, issues, dispatches, petty cash):
```powershell
python manage.py seed_sample_data
# Or run helper script: .\scripts\load_sample_data.ps1
```
*Sample branch users sign in with `<name>@example.test` and password `HeritageDemo!2026`.*

### Reset / Clear Data
```powershell
python manage.py clear_all_data    # Resets everything except Super Admin & base roles
```

### Run Automated Tests
```powershell
python manage.py test              # Runs all 100+ unit and integration tests
```

---

## Deploying on Oracle Cloud (Always Free)

Oracle Cloud Infrastructure (OCI) provides an **Always Free Tier** with zero hosting expiration and high performance:

| Resource | Free Tier Allowance | Application Usage |
| :--- | :--- | :--- |
| **Hosting Duration** | **Forever (Always Free)** | Stays live 24/7/365 with no trial expiration. |
| **Database & Disk Storage** | **200 GB NVMe Storage** | Decades of inventory records and daily backups. |
| **Compute / RAM** | **Up to 4 OCPUs & 24 GB RAM** (Ampere ARM) | Fast, responsive server with zero lag. |
| **Bandwidth** | **10 TB / month** | More than enough for business operations. |

### 1. Launch a Free Compute Instance
1. In the Oracle Cloud Console, navigate to **Compute** &rarr; **Instances** &rarr; **Create Instance**.
2. **Image**: Choose **Ubuntu 22.04 LTS** or **24.04 LTS** (Always Free).
3. **Shape**: Choose **Ampere (VM.Standard.A1.Flex)** with 2 OCPUs and 8–12 GB RAM (or AMD Micro with 1 GB RAM).
4. **Networking**: Ensure **Assign a public IPv4 address** is checked.
5. **SSH Key**: Save the private key (`oracle_key.key`) to your computer.
6. Click **Create** and note the **Public IP Address** (e.g. `129.150.x.x`).

### 2. Open Web Ports (80 & 443) in Oracle Security List
1. In your Instance details, click the **Subnet** link under *Primary VNIC Information*.
2. Click **Default Security List** &rarr; **Add Ingress Rules**:
   - **Source CIDR**: `0.0.0.0/0`
   - **IP Protocol**: `TCP`
   - **Destination Port Range**: `80,443`
   - **Description**: `HTTP and HTTPS`
3. Click **Add Ingress Rules**.

---

## Connecting Your Custom Domain & SSL

### 1. Configure DNS A-Record
Log into your domain provider (Cloudflare, Namecheap, GoDaddy, etc.) and add an **A Record**:
- **Name**: `@` (for root domain `yourcompany.com`) or `inventory` (for `inventory.yourcompany.com`)
- **Type**: `A`
- **Value**: Your Oracle VM's **Public IP address**
- **TTL**: Auto (or 1 minute)

### 2. SSH into the Server & Install Docker
From PowerShell on your computer:
```powershell
ssh -i .\oracle_key.key ubuntu@<YOUR_ORACLE_PUBLIC_IP>
```

On the Ubuntu server:
```bash
# Update packages and configure firewall
sudo apt update && sudo apt upgrade -y
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save

# Install Docker & Docker Compose
sudo apt install -y docker.io docker-compose-v2
sudo usermod -aG docker ubuntu
newgrp docker
```

### 3. Clone Repository & Configure Environment
```bash
git clone https://github.com/<your-username>/<your-repo-name>.git inventory-system
cd inventory-system

# Create production environment file
cp .env.production.example .env
nano .env
```

Set your production values in `.env`:
```ini
DOMAIN_NAME=inventory.yourcompany.com
DJANGO_ALLOWED_HOSTS=inventory.yourcompany.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://inventory.yourcompany.com

DJANGO_SECRET_KEY=generate-a-strong-random-secret-key-at-least-50-chars-long
DJANGO_DEBUG=false

DB_ENGINE=sqlite
DB_PATH=/srv/app/data/db.sqlite3

SEED_ADMIN_NAME=Super Admin
SEED_ADMIN_EMAIL=admin@yourcompany.com
SEED_ADMIN_PASSWORD=ChooseAStrongPassword123!
SEED_COMPANY_NAME=Your Company Name
```

### 4. Start the Application
```bash
docker compose up -d --build
```

- Caddy automatically contacts Let's Encrypt to provision a valid, auto-renewing SSL certificate for your domain.
- The web container applies migrations, seeds the Super Admin, collects static files, and starts Gunicorn.
- Open `https://inventory.yourcompany.com` in your browser.

---

## Data Backup & Recovery

The system includes built-in commands for non-blocking, compressed, automated backups.

### 1. Manual Backup
Run backup on demand:
```bash
# Inside the container / on the server:
docker compose exec web python manage.py backup_db

# Or run the helper script:
./scripts/backup.sh
```
- Backups use SQLite's online safe backup API (zero data corruption during active use).
- Backups are automatically compressed (`.sqlite3.gz`) saving over 80% disk space.
- Files are saved in the `backups/` directory with a timestamp (e.g. `db_backup_20261026_103000.sqlite3.gz`).
- Backups older than 30 days are automatically rotated and deleted to keep storage clean.

### 2. Automatic Daily Backups (Cron)
On your Ubuntu server, set up an automatic daily backup at 2:00 AM:
```bash
crontab -e
```
Add the following line:
```cron
0 2 * * * /home/ubuntu/inventory-system/scripts/backup.sh >> /home/ubuntu/inventory-system/backups/backup.log 2>&1
```

### 3. Download Backups to Your Personal Computer
To download all backups from the server to your local machine:
```powershell
# Run from your local computer terminal:
scp -i .\oracle_key.key ubuntu@<YOUR_ORACLE_PUBLIC_IP>:~/inventory-system/backups/*.sqlite3.gz C:\MyBackups\
```

### 4. Restoring from a Backup
To restore a database backup:
```bash
docker compose exec -it web python manage.py restore_db --file /srv/app/backups/db_backup_YYYYMMDD_HHMMSS.sqlite3.gz
```

---

## Maintenance & Scheduled Tasks

### 30-Day Stock Ledger Retention
To keep the stock ledger lean and fast, transactions older than 30 days can be consolidated into single opening balances per item and location.

Trigger manually:
```bash
docker compose exec web python manage.py prune_stock_movements
```

Or trigger remotely via scheduled HTTP POST:
```http
POST https://inventory.yourcompany.com/maintenance/stock-ledger-retention/
Authorization: Bearer <CRON_SECRET>
```

---

## Configuration Reference

Key variables in `.env`:

| Variable | Description |
| :--- | :--- |
| `DOMAIN_NAME` | The domain used by Caddy for reverse proxy and SSL certificate generation. |
| `DJANGO_SECRET_KEY` | Cryptographic secret key (50+ random characters in production). |
| `DJANGO_DEBUG` | Must be `false` in production. |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated domain names allowed to serve requests. |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | Full HTTPS URLs (e.g. `https://inventory.yourcompany.com`). |
| `DB_ENGINE` | `sqlite` (default) or `postgres`. |
| `DB_PATH` | Path to the SQLite database (`/srv/app/data/db.sqlite3` in Docker). |
| `TIME_ZONE` | Timezone for business days and reporting (default: `Asia/Colombo`). |
| `CRON_SECRET` | Secret token used to authenticate maintenance requests. |
| `SEED_ADMIN_*` | Name, email, and password for initial Super Admin setup. |

---

## Project Structure

```
inventory-system/
├── accounts/                  # Users, custom authentication, roles, branches
├── branchops/                 # Branch requests, reviews, dispatches, receiving
├── catalog/                   # Items, categories, suppliers
├── config/                    # Django core configuration, URLs, WSGI/ASGI
├── core/                      # Shared models, business rules, dashboard, audit logs
│   └── management/commands/   # Custom management commands (backup_db, restore_db, seed)
├── docker/                    # Container startup scripts
├── inventory/                 # Stock balances, purchases, office issues, ledger
├── pettycash/                 # Branch petty cash requests, approvals, disbursements
├── reports/                   # Stock, purchase, usage, and dispatch reporting
├── scripts/                   # Backup and development utility scripts
├── static/                    # CSS, JavaScript, and static assets
├── templates/                 # Server-rendered HTML templates
├── backups/                   # Directory where compressed database backups are stored
├── Caddyfile                  # Caddy reverse proxy & automated HTTPS configuration
├── docker-compose.yml         # Container definitions (web & caddy services)
├── Dockerfile                 # Multi-stage production container build
├── README.md                  # Project documentation
└── requirements.txt           # Python dependencies
```

---

## License

Proprietary — Internal Business Use Only.
