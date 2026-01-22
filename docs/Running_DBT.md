# Running dbt for quantyx-core-services

This document outlines the steps to initialize and configure your dbt project for the `quantyx-core-services` platform. It assumes you have already completed the prerequisites and installed dbt via the Ansible playbook.

---

## 1. Activate the dbt Virtual Environment

Before running any `dbt` commands, you must activate the dedicated Python virtual environment where `dbt-postgres` is installed.

```bash
source /opt/quantyx/.venv/bin/activate
```

You should see `(.venv)` or similar prefix in your terminal prompt, indicating the virtual environment is active.

---

## 2. Initialize the dbt Project

If you haven't already, initialize the dbt project. This command creates the basic dbt project structure.

```bash
dbt init quantyx_core_services
```

During this process, dbt will ask you a series of questions to configure your database connection profile. Use the following recommended values:

-   **Which database would you like to use?**
    -   Enter `1` (for `postgres`)
-   **host (hostname for the instance)**
    -   Enter `localhost`
-   **port**
    -   Enter `5432`
-   **user**
    -   Enter `quantyx_user`
-   **password**
    -   Enter a secure password of your choice (this should match the password configured for `quantyx_user` in your PostgreSQL setup).
-   **dbname**
    -   Enter `quantyx_db`
-   **schema**
    -   Enter `analytics`
-   **threads**
    -   Enter `4`

After successful initialization, dbt will create a new directory named `quantyx_core_services` within your current working directory. You should move this to `dbt` folder.

---

## 3. Verify Your dbt Setup

After initializing and configuring your profile, you can verify that dbt can connect to your database using the `dbt debug` command.

First, navigate into your dbt project directory:
```bash
cd dbt/quantyx_core_services
```

Then run:
```bash
dbt debug
```

A successful output will show `Connection test: OK` for your `dev` target. If there are issues, check your `~/.dbt/profiles.yml` file and your PostgreSQL server status.

---

## 4. Next Steps

Once dbt is successfully initialized and connected, you can proceed with defining your dbt sources, staging models, and analytics marts as outlined in the `artifacts/implementation_plan.md`.
