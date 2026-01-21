# Ansible Playbook for quantyx-core-services

This Ansible playbook automates the setup of the development environment for the quantyx-core-services project.
It can be used to provision a new machine with all the necessary software and dependencies.

## Prerequisites

- Ansible installed on the control node.
- A target machine (local or remote) with SSH access.
- For macOS, [Homebrew](https://brew.sh/) must be installed.

## How to use

1.  **Install Ansible:**
    ```bash
    pip install ansible
    ```

2.  **Create an inventory file:**
    Create a file named `inventory` (or any other name) with the list of hosts you want to provision.
    For a local machine:
    ```ini
    localhost ansible_connection=local
    ```
    For a remote machine:
    ```ini
    my_server ansible_host=your_server_ip ansible_user=your_user
    ```

3.  **Run the playbook:**
    ```bash
    ansible-playbook -i inventory playbook.yml
    ```
    If your user on the remote machine needs a password for `sudo`, you can add the `--ask-become-pass` flag.

## What it does

The playbook will install the following software:
- Git
- Python 3.11 and venv
- PostgreSQL 14
- Node.js
- dbt-postgres (in a virtual environment)
- Python dependencies from `requirements.txt` (in a virtual environment)

The project will be set up in the `/opt/quantyx` directory. This can be changed by editing the `project_dir` variable in `playbook.yml`.
The Python virtual environment will be created at `/opt/quantyx/.venv`.
