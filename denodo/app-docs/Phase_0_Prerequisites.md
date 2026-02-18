# Phase 0: Prerequisites and Inputs

## Goals
- Validate all required tools and inputs before automation.
- Avoid blocked installs during Ansible execution.

## Required inputs
- Installer zip: `denodo-express-install-9-linux64.zip`
- Local working directory target: `denodo/`
- Chosen local ports (example):
  - `9090` for web/admin UI (example placeholder)
  - `9999` for VDP or service endpoint (example placeholder)

## Tooling checks
- `docker --version`
- `docker compose version` (optional)
- `ansible --version`
- `python3 --version`

## Decisions to finalize
- Base image for Docker build (`ubuntu`/`debian`/supported JRE base)
- Persistent storage locations:
  - Denodo data
  - logs
  - config/customizations
- Environment variable strategy:
  - local `.env`
  - Ansible vault for sensitive data

## Deliverables
- Confirmed toolchain
- Confirmed ports and volumes
- Confirmed legal usage model (Denodo Express flow does not require a license file)
