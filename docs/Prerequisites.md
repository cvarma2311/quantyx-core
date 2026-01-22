# quantyx-core-services Ops Intelligence — Prerequisites & Setup

This document lists **all prerequisites** required to develop, run, and contribute to
the quantyx-core-services Ops Intelligence MVP.

It assumes:
- A fresh GitHub repository
- Local development first (no cloud dependency)
- Postgres as the data store
- dbt + Python-based AI services

---

## 1. System Requirements

### Supported OS
- macOS (Intel / Apple Silicon)
- Linux (Ubuntu 20.04+ recommended)
- Windows (via WSL2 recommended)

---

## 2. Required Software

### 2.1 Git
**Purpose:** Source control

Check your version:
```bash
git --version
```

If not installed:
- **macOS:** `brew install git`
- **Ubuntu:** `sudo apt install git`
- **Windows:** Install via [Git SCM](https://git-scm.com/download/win) or use WSL.

### 2.2 Python (REQUIRED)
**Version:** Python 3.10 or 3.11
(Do NOT use 3.12 yet — dbt compatibility may vary.)

Check your version:
```bash
python3 --version
```

If missing:
- **macOS:** `brew install python@3.11`
- **Ubuntu:** `sudo apt install python3.11 python3.11-venv`
- **Windows:** Use Python via WSL.

### 2.3 Virtual Environment (MANDATORY)
Always use a virtual environment to isolate project dependencies.

Create and activate the environment:
```bash
python3 -m venv .venv
source .venv/bin/activate
```

Confirm you are using the correct Python interpreter:
```bash
which python
# Should point to the .venv directory
```

### 2.4 PostgreSQL
**Version:** PostgreSQL 13+

This will be used for:
- Source operational data
- dbt analytics marts
- Storing results from forecasts or anomaly detection

Check your version:
```bash
psql --version
```
If not installed:
- **macOS:** `brew install postgresql@14`
- **Ubuntu:** `sudo apt install postgresql postgresql-contrib`
- **Docker:** (Recommended) See Section 6 for a Docker-based setup.

### 2.5 dbt Core (REQUIRED)
**Adapter:** `dbt-postgres`

Install inside your activated virtual environment:
```bash
pip install dbt-postgres
```
Verify the installation:
```bash
dbt --version
```

### 2.6 Node.js (OPTIONAL)
Only required if you are building or running a React-based UI.

Check your version:
```bash
node --version
```
Recommended: **Node 18+**

---

## 3. Python Dependencies (MVP)
Create a `requirements.txt` file in the root of the repository:

```text
# requirements.txt
fastapi
uvicorn
psycopg2-binary
sqlalchemy
pandas
numpy
scipy
statsmodels
pydantic
python-dotenv
```

Install all dependencies:
```bash
pip install -r requirements.txt
```

---

## 4. dbt Project Setup

### 4.1 Initialize dbt Project
From the repository root:
```bash
dbt init quantyx_core_services
```

### 4.2 Configure dbt Profile
Your `~/.dbt/profiles.yml` file connects dbt to your database.
**DO NOT COMMIT THIS FILE.**

Example configuration:
```yaml
# ~/.dbt/profiles.yml
quantyx_core_services:
  target: dev
  outputs:
    dev:
      type: postgres
      host: localhost
      user: quantyx_user
      password: your_password # Use environment variables in production
      port: 5432
      dbname: quantyx_db
      schema: analytics
      threads: 4
```

---

## 5. Environment Variables
Create a `.env` file in the repository root for local development.
**DO NOT COMMIT THIS FILE.**

```env
# .env
DB_HOST=localhost
DB_PORT=5432
DB_NAME=quantyx_db
DB_USER=quantyx_user
DB_PASSWORD=your_secret_password
DB_SCHEMA=analytics
APP_ENV=local
LOG_LEVEL=INFO
```
These variables can be loaded into your Python application using the `python-dotenv` library.

---

## 6. Docker (OPTIONAL but Recommended)
Using Docker provides a consistent, reproducible local development stack.

### 6.1 Check Installation
```bash
docker --version
docker compose version
```
### 6.2 Example Services
You can define services for:
- Postgres Database
- pgAdmin (for database management)
- Python API Service

Docker-related files should be organized under the `infra/docker/` directory.

---

## 7. Git Conventions

### 7.1 Branching Strategy
- **`main`**: Stable, production-ready code.
- **`develop`**: Active development branch. All feature branches are merged here.
- **`feature/<name>`**: Individual feature branches (e.g., `feature/add-sales-forecast`).

### 7.2 Commit Message Style
Follow the [Conventional Commits](https://www.conventionalcommits.org/) specification.
```text
feat: add new sales fact model for HPCL
fix: correct filtering logic in a staging model
docs: update prerequisites and setup guide
```

---

## 8. Required Repository Files (MVP)
The repository must include, at a minimum:
- `README.md`
- `docs/PREREQUISITES.md`
- `docs/MVP_HPCL_SALES_AND_INDUSTRY.md`
- `docs/POST_MVP_ROADMAP_NO_MINDSDB.md`
- `.gitignore`

---

## 9. Local Verification Checklist
Before pushing code, always ensure the following:
- [ ] Virtual environment is active (`source .venv/bin/activate`)
- [ ] `dbt debug` passes successfully
- [ ] `dbt run` completes without errors
- [ ] `dbt test` passes all tests
- [ ] API service starts locally (e.g., `uvicorn main:app --reload`)
- [ ] No secrets or environment-specific files are committed (`git status`)

---

## 10. Guiding Rule
> If it cannot be run locally from scratch following this guide, it is not ready for production or collaboration.

---

## 11. Troubleshooting Notes
- Always activate the virtual environment (`.venv`) before running `dbt` or `python` commands.
- AI services should **never** query raw data tables directly. All queries should target dbt marts (`fact_*`, `dim_*`).

---

## 12. Next Setup Steps
After completing these prerequisites, proceed with:
1. Implement the dbt staging models.
2. Build the core MVP fact and dimension tables.
3. Define the initial metric catalog.
4. Develop the AI Q&A endpoint.
5. Create the first set of dashboards.

---

## `.gitignore` (Repo Root)

```gitignore
# Python
.venv/
__pycache__/
*.pyc
*.pyo
*.pyd
*.egg-info/
dist/
build/

# Environment & Secrets
.env
.env.*
*.key
*.pem

# dbt
target/
dbt_packages/
logs/
*.log

# IDE
.vscode/
.idea/
*.swp
.DS_Store

# OS
Thumbs.db

# Node (if UI exists)
node_modules/
npm-debug.log*
yarn-error.log*

# Docker
*.tar
docker-compose.override.yml

# Data artifacts
*.csv
*.parquet
*.avro
*.jsonl
```
