# Phase 3: Runtime Deployment via Ansible

## Goals
- Start Denodo container locally with persisted data and deterministic config.

## Runtime flow
1. Create local host directories for volumes.
2. Start container with `community.docker.docker_container`.
3. Map ports and mount volumes.
4. Set restart policy and required env vars.

## Suggested variables
- `denodo_container_name: denodo-express-local`
- `denodo_host_ports:`
  - `9090:9090`
  - `9999:9999`
- `denodo_volumes:`
  - `./runtime/data:/opt/denodo/data`
  - `./runtime/logs:/opt/denodo/logs`

## Ansible tasks
- `file` module: create volume dirs
- `docker_container` module: run/update container idempotently
- `docker_container_info`: post-start inspection

## Deliverables
- Running container managed by Ansible
- Persistent runtime state across restarts
