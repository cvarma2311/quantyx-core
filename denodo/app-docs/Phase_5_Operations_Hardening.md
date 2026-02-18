# Phase 5: Operations and Hardening

## Goals
- Make local automation reliable and maintainable.

## Hardening checklist
- Idempotency checks for all roles and playbooks
- `--check` mode compatibility where possible
- Sensitives moved to Ansible Vault
- Structured logs and failure diagnostics
- Clean rollback/redeploy workflow

## Operational playbooks
- `site.yml` (build + run + verify)
- `rebuild.yml` (force rebuild image)
- `restart.yml` (container restart only)
- `destroy.yml` (stop/remove container; optional volume cleanup)

## Implemented now
- Playbooks added under `denodo/ansible/playbooks/`:
  - `rebuild.yml`
  - `restart.yml`
  - `destroy.yml`
- Scripts added under `denodo/ansible/scripts/`:
  - `bootstrap_and_run.sh` (install deps + run selected playbook)
  - `detect_installer.sh` (print detected installer settings from zip)

## CI optional follow-up
- Lint playbooks (`ansible-lint`)
- Syntax check in CI
- Optional local Molecule tests

## Deliverables
- Stable local Denodo automation lifecycle
