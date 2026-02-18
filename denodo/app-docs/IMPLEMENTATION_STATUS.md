# Denodo Phase Implementation Status

## Completed now
- Phase 1: Ansible scaffold created under `denodo/ansible/`
- Phase 2: Docker image build automation role created
- Phase 3: Runtime deployment role created
- Phase 4: Verification role created
- Phase 5: Operations playbooks and bootstrap scripts added

## Created artifacts
- `denodo/ansible/ansible.cfg`
- `denodo/ansible/inventory/local.ini`
- `denodo/ansible/group_vars/all.yml`
- `denodo/ansible/requirements.yml`
- `denodo/ansible/playbooks/site.yml`
- `denodo/ansible/playbooks/build_image.yml`
- `denodo/ansible/playbooks/run_container.yml`
- `denodo/ansible/playbooks/verify.yml`
- `denodo/ansible/playbooks/rebuild.yml`
- `denodo/ansible/playbooks/restart.yml`
- `denodo/ansible/playbooks/destroy.yml`
- `denodo/ansible/playbooks/discovery.yml`
- `denodo/ansible/playbooks/generate_response.yml`
- `denodo/ansible/roles/denodo_image/tasks/main.yml`
- `denodo/ansible/roles/denodo_image/templates/Dockerfile.j2`
- `denodo/ansible/roles/denodo_runtime/tasks/main.yml`
- `denodo/ansible/roles/denodo_verify/tasks/main.yml`
- `denodo/ansible/scripts/detect_installer.sh`
- `denodo/ansible/scripts/bootstrap_and_run.sh`
- `denodo/ansible/scripts/discover_installer.sh`
- `denodo/ansible/scripts/generate_response_file.sh`

## Auto-detection status
- Installer zip was inspected and contains:
  - `denodo-install-9/install.sh`
- Build role now auto-detects `install.sh` when `denodo_auto_detect_installer_script=true`.

## Important note
- Denodo unattended installer is now enabled by default using generated response XML.
- Variables:
  - `denodo_run_installer_during_build`
  - `denodo_installer_script`
  - `denodo_installer_flags`
  - `denodo_install_root`
  - `denodo_response_file_path`

## Run sequence
```bash
cd denodo/ansible
ansible-galaxy collection install -r requirements.yml
ansible-playbook playbooks/build_image.yml
ansible-playbook playbooks/run_container.yml
ansible-playbook playbooks/verify.yml
```

## One-command bootstrap
```bash
cd denodo/ansible
./scripts/bootstrap_and_run.sh site
```

## Installer discovery
```bash
cd denodo/ansible
./scripts/bootstrap_and_run.sh discovery
```
Outputs:
- `denodo/runtime/discovery/INSTALLER_DISCOVERY_REPORT.md`
- `denodo/runtime/discovery/install.sh`
- `denodo/runtime/discovery/dat_strings_filtered.txt`

## Generate response XML (interactive helper)
```bash
cd denodo/ansible
./scripts/bootstrap_and_run.sh generate-response
```
Note:
- This path runs the helper script directly (not via Ansible task) to preserve interactive TTY behavior.
- On Apple Silicon, helper forces `--platform linux/amd64` because Denodo bundled JRE is x86_64.
Output:
- `denodo/installable/response_file_9_0.xml`

## Operational commands
```bash
./scripts/bootstrap_and_run.sh rebuild
./scripts/bootstrap_and_run.sh restart
./scripts/bootstrap_and_run.sh destroy -e denodo_remove_runtime_on_destroy=true
```

## Helper command to print detected installer values
```bash
./scripts/detect_installer.sh ../../denodo/installable/denodo-express-install-9-linux64.zip
```

## Remaining work
- Determine correct silent installation flags for `install.sh`/`denodo-install-9.dat`.
- Set `DENODO_START_CMD` to actual Denodo startup command after installation layout is known.
