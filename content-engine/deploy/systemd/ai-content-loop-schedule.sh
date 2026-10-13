#!/bin/bash
# Root-only scheduler entrypoint.  It mirrors systemd's EnvironmentFile before
# dropping privileges to the application account.
set -euo pipefail

environment_file=/opt/ai-content-loop/image.env
if [[ -r "$environment_file" ]]; then
  set -a
  # shellcheck disable=SC1090
  . "$environment_file"
  set +a
fi

exec /usr/sbin/runuser --preserve-environment -u agentuser -- \
  /usr/bin/env HOME=/home/agentuser PYTHONUNBUFFERED=1 \
  /usr/local/bin/ai-content-loop-run.sh
