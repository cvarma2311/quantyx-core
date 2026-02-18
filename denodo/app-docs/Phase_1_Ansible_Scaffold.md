# Phase 1: Ansible Scaffold

## Goals
- Create a clean, repeatable Ansible layout for local Denodo deployment.

## Target structure
```text
denodo/
  ansible/
    ansible.cfg
    inventory/
      local.ini
    group_vars/
      all.yml
    playbooks/
      site.yml
      build_image.yml
      run_container.yml
      verify.yml
    roles/
      denodo_image/
        tasks/main.yml
        templates/Dockerfile.j2
      denodo_runtime/
        tasks/main.yml
      denodo_verify/
        tasks/main.yml
    files/
      denodo-express-install-9-linux64.zip
```

## Steps
1. Initialize `ansible` root with inventory + config.
2. Add `group_vars/all.yml` for image/tag/ports/volumes.
3. Add role skeletons (`denodo_image`, `denodo_runtime`, `denodo_verify`).
4. Add playbooks to orchestrate roles in sequence.

## Deliverables
- Runnable `ansible-playbook` structure
- Local inventory targeting `localhost`
