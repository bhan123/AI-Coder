#!/bin/bash
# All manual and scheduled pipeline runs share this blocking lock.  A later
# hourly trigger waits for the current run instead of being discarded.
set -euo pipefail

cd /opt/ai-content-loop/repo

exec /usr/bin/flock /opt/ai-content-loop/data/ai-content-loop.lock \
  /opt/ai-content-loop/venv/bin/python \
  -m engine.cli \
  --config /opt/ai-content-loop/config.toml \
  daily
