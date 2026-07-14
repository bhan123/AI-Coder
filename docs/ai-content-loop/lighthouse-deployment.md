# AI Content Loop Lighthouse Deployment

Target server:

- Tencent Cloud Lighthouse
- Ubuntu
- 4 cores / 8 GB RAM

## Resource rules

- Do not run local LLMs on this server.
- Prefer API and RSS sources.
- Keep daily raw items at or below 200.
- Keep deep research candidates at or below 10.
- Generate 1-2 publish queue items per day.
- Treat browser automation as out of scope for the first 30 days.

## Suggested layout

```text
/opt/ai-content-loop/
  repo/
  venv/
  data/
    ai_content_loop.sqlite3
  out/
    drafts/
    final/
    failures/
    weekly-summary.json
  logs/
```

## Runtime setup

Install the managed Python environment and Chinese font package:

```bash
sudo apt-get update
sudo apt-get install -y python3-venv fonts-noto-cjk
if [ ! -x /opt/ai-content-loop/venv/bin/python ]; then
  sudo python3 -m venv /opt/ai-content-loop/venv
fi
sudo /opt/ai-content-loop/venv/bin/python -m pip install --upgrade pip
sudo /opt/ai-content-loop/venv/bin/python -m pip install \
  -r /opt/ai-content-loop/repo/requirements-review.txt
test -f /usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc
```

The existence check reuses an installed virtual environment instead of
recreating it during every deployment.

## Production configuration

Keep runtime data outside the checked-out source tree:

```toml
database_path = "/opt/ai-content-loop/data/ai_content_loop.sqlite3"
output_dir = "/opt/ai-content-loop/out"
hermes_command = "/home/agentuser/.local/bin/hermes"
generation_timeout_seconds = 600
generation_retries = 1
visual_font_path = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
visual_render_concurrency = 1

[source_limits]
hackernews = 30
```

Keep `visual_font_path` and `visual_render_concurrency` above
`[source_limits]` so they remain top-level TOML settings.

The production source limit for Hacker News can be reduced to `10` when
Tencent Cloud connectivity makes its per-item API slow.

## Manual commands

```bash
cd /opt/ai-content-loop/repo
/opt/ai-content-loop/venv/bin/python -m ai_content_loop.cli --config /opt/ai-content-loop/config.toml init
/opt/ai-content-loop/venv/bin/python -m ai_content_loop.cli --config /opt/ai-content-loop/config.toml ingest
/opt/ai-content-loop/venv/bin/python -m ai_content_loop.cli --config /opt/ai-content-loop/config.toml score
/opt/ai-content-loop/venv/bin/python -m ai_content_loop.cli --config /opt/ai-content-loop/config.toml build-queue
/opt/ai-content-loop/venv/bin/python -m ai_content_loop.cli --config /opt/ai-content-loop/config.toml generate-drafts
```

Run the complete daily chain manually:

```bash
/opt/ai-content-loop/venv/bin/python -m ai_content_loop.cli \
  --config /opt/ai-content-loop/config.toml \
  daily
```

## Daily systemd timer

Install the versioned unit files:

```bash
test -x /opt/ai-content-loop/venv/bin/python
sudo install -o root -g root -m 0644 \
  /opt/ai-content-loop/repo/deploy/systemd/ai-content-loop.service \
  /etc/systemd/system/ai-content-loop.service
sudo install -o root -g root -m 0644 \
  /opt/ai-content-loop/repo/deploy/systemd/ai-content-loop.timer \
  /etc/systemd/system/ai-content-loop.timer
sudo systemd-analyze verify /etc/systemd/system/ai-content-loop.service
sudo systemd-analyze verify /etc/systemd/system/ai-content-loop.timer
sudo systemctl daemon-reload
sudo systemctl enable --now ai-content-loop.timer
systemctl list-timers ai-content-loop.timer --no-pager
```

The timer runs at 08:00 Asia/Shanghai. It is persistent, so a missed run fires
after the server starts.

Run and inspect it on demand:

```bash
sudo systemctl start ai-content-loop.service
sudo systemctl status ai-content-loop.service --no-pager
sudo journalctl -u ai-content-loop.service -n 100 --no-pager
```

## Weekly command

```bash
cd /opt/ai-content-loop/repo
/opt/ai-content-loop/venv/bin/python -m ai_content_loop.cli --config /opt/ai-content-loop/config.toml weekly-summary --since 2026-06-24
```

## Human review boundary

Hermes input briefs remain in `out/drafts/`. Validated complete articles are
written to `out/final/`; terminal generation failures are written to
`out/failures/`. A human must review final articles before publishing to
WeChat, Xiaohongshu, Toutiao, or Zhihu.

Hermes is invoked with no tools for article generation. The service runs as
`agentuser`, never as root, and does not use `--yolo`.
