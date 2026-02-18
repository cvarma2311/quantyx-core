# Phase 4: Local Access and Smoke Tests

## Goals
- Confirm Denodo is reachable from your local machine.

## Access checks
1. `docker ps` shows running container.
2. Browser access to configured local UI port.
3. Port checks via:
   - `curl http://localhost:<port>`
   - `nc -zv localhost <port>`
4. Logs review:
   - `docker logs denodo-express-local --tail 200`

## Ansible verification playbook
- Add `verify.yml` that:
  - waits for ports
  - asserts container state = running
  - optionally hits health endpoint/page

## Deliverables
- Verified local connectivity
- Repeatable smoke test playbook
