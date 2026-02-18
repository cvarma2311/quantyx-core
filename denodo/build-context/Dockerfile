FROM ubuntu:22.04

ARG DEBIAN_FRONTEND=noninteractive
ARG DENODO_INSTALLER_SCRIPT=""
ARG DENODO_INSTALLER_FLAGS=""
ARG DENODO_INSTALL_ROOT=""
ARG DENODO_RUN_INSTALLER_DURING_BUILD="false"

RUN apt-get update \
  && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    unzip \
    bash \
    tini \
    openjdk-17-jre-headless \
  && rm -rf /var/lib/apt/lists/*

RUN cat > /usr/local/bin/start-denodo-auto <<'SH' && chmod +x /usr/local/bin/start-denodo-auto
#!/usr/bin/env bash
set -euo pipefail

for candidate in \
  /opt/denodo/bin/denodo_platform \
  /root/denodo/bin/denodo_platform \
  /usr/local/denodo/bin/denodo_platform \
  /denodo/bin/denodo_platform; do
  if [[ -x "$candidate" ]]; then
    echo "Starting Denodo using: $candidate"
    "$candidate" start || true
    exec tail -f /dev/null
  fi
done

echo "Could not locate denodo_platform startup script in common paths."
echo "Set DENODO_START_CMD to the correct startup command after confirming install path."
exec sleep infinity
SH

WORKDIR /tmp/denodo-installer
COPY denodo-express-install-9-linux64.zip /tmp/denodo-express-install-9-linux64.zip
RUN unzip -q /tmp/denodo-express-install-9-linux64.zip -d /tmp/denodo-installer

# If DENODO_INSTALLER_SCRIPT is set (for example install_denodo.sh), run it.
# The exact script name/flags depend on Denodo's installer package.
RUN if [ "${DENODO_RUN_INSTALLER_DURING_BUILD}" = "true" ] && [ -n "${DENODO_INSTALLER_SCRIPT}" ]; then \
      if [ -n "${DENODO_INSTALL_ROOT}" ]; then cd "/tmp/denodo-installer/${DENODO_INSTALL_ROOT}"; fi && \
      chmod +x "/tmp/denodo-installer/${DENODO_INSTALLER_SCRIPT}" && \
      /bin/bash "/tmp/denodo-installer/${DENODO_INSTALLER_SCRIPT}" ${DENODO_INSTALLER_FLAGS}; \
    else \
      echo "Installer execution skipped in image build"; \
    fi

EXPOSE 9090 9999
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/bin/bash", "-lc", "if [ -n \"$DENODO_START_CMD\" ]; then echo \"Running DENODO_START_CMD: $DENODO_START_CMD\"; eval \"$DENODO_START_CMD\"; rc=$?; echo \"DENODO_START_CMD exited with code $rc\"; else echo 'Set DENODO_START_CMD to launch Denodo.'; fi; echo 'Container will stay alive for troubleshooting.'; exec tail -f /dev/null"]
