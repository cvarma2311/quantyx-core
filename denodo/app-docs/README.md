# Denodo Docker + Ansible Implementation Plan

This folder documents the end-to-end phases to:
1. Build a Docker image using `denodo-express-install-9-linux64.zip`
2. Automate everything with Ansible
3. Run and access Denodo locally

## Scope
- Create Ansible project structure under `denodo/ansible/`
- Build a local Docker image from Denodo installer zip
- Run container with persistent volumes and env vars
- Expose local ports for browser and admin access
- Add health checks, smoke tests, and restart workflows

## Assumptions
- You have legal rights to use the Denodo Express installer.
- Docker is installed and running locally.
- Ansible is installed locally.
- The installer zip exists locally as:
  - `denodo-express-install-9-linux64.zip`

## Phases
- Phase 0: Inputs and prerequisites
- Phase 1: Repository and Ansible project scaffolding
- Phase 2: Docker image build automation via Ansible
- Phase 3: Runtime/container orchestration via Ansible
- Phase 4: Local access, validation, and smoke tests
- Phase 5: Hardening, idempotency, and operations

Read in order:
1. `Phase_0_Prerequisites.md`
2. `Phase_1_Ansible_Scaffold.md`
3. `Phase_2_Image_Build.md`
4. `Phase_3_Runtime_Deploy.md`
5. `Phase_4_Local_Access_Testing.md`
6. `Phase_5_Operations_Hardening.md`
7. `Phase_6_Installer_Discovery.md`

## Quickstart (implemented)
```bash
cd denodo/ansible
./scripts/detect_installer.sh ../../denodo/installable/denodo-express-install-9-linux64.zip
./scripts/bootstrap_and_run.sh site
```

Operational commands:
```bash
./scripts/bootstrap_and_run.sh rebuild
./scripts/bootstrap_and_run.sh restart
./scripts/bootstrap_and_run.sh destroy -e denodo_remove_runtime_on_destroy=true
./scripts/bootstrap_and_run.sh discovery
./scripts/bootstrap_and_run.sh generate-response
```
