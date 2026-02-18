# Phase 6: Installer Discovery (Silent Flags + Startup Command)

## Goal
Discover the correct Denodo silent-install parameters and startup command for fully automated builds.

## What is implemented
- Ansible playbook: `denodo/ansible/playbooks/discovery.yml`
- Discovery script: `denodo/ansible/scripts/discover_installer.sh`
- Response generation playbook: `denodo/ansible/playbooks/generate_response.yml`
- Interactive helper script: `denodo/ansible/scripts/generate_response_file.sh`
- Bootstrap command:
  - `./scripts/bootstrap_and_run.sh discovery`
  - `./scripts/bootstrap_and_run.sh generate-response`

## Output artifacts
Generated under `denodo/runtime/discovery/`:
- `INSTALLER_DISCOVERY_REPORT.md`
- `zip_listing.txt`
- `install.sh`
- `start_script_candidates.txt`
- `dat_strings_filtered.txt`

## Workflow
1. Run discovery.
2. Inspect `install.sh` and filtered `.dat` strings for silent/response options.
3. Use Denodo CLI installer mode (from Denodo docs):
   - `./scripts/bootstrap_and_run.sh generate-response`
   - `installer_cli.sh install --autoinstaller response_file_9_0.xml`
4. Set confirmed values in `denodo/ansible/group_vars/all.yml`:
   - `denodo_run_installer_during_build: true`
   - `denodo_installer_script`
   - `denodo_install_root`
   - `denodo_installer_flags`
   - `denodo_env.DENODO_START_CMD`
5. Run rebuild:
   - `./scripts/bootstrap_and_run.sh rebuild`

## Acceptance
- Automated build executes installer without manual prompts.
- Container starts Denodo services automatically.
- Local access works from macOS on configured ports.
