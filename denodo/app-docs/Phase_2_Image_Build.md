# Phase 2: Docker Image Build via Ansible

## Goals
- Build Denodo image from installer zip using idempotent Ansible tasks.

## Build flow
1. Copy installer zip into Ansible/files (or reference absolute path).
2. Template Dockerfile with required dependencies.
3. Build Docker image with `community.docker.docker_image`.
4. Tag image (example): `denodo-express:9-local`.

## Implemented now
- Build role auto-detects install script from zip (`*/install.sh`) when:
  - `denodo_auto_detect_installer_script: true`
- For your zip this resolves to:
  - `denodo-install-9/install.sh`
- Installer execution during build is controlled by:
  - `denodo_run_installer_during_build` (default `false`)

## Suggested role variables
- `denodo_image_name: denodo-express`
- `denodo_image_tag: 9-local`
- `denodo_zip_src: files/denodo-express-install-9-linux64.zip`
- `denodo_build_context: /tmp/denodo-build`

## Dockerfile expectations
- Base OS + JRE dependencies expected by installer
- Unzip installer
- Non-interactive install strategy (if supported)
- Expose required ports
- Define startup command/entrypoint

## Validation
- `docker images | grep denodo-express`
- `docker run --rm denodo-express:9-local <version-check-cmd>`

## Deliverables
- Reproducible local image build from Ansible
