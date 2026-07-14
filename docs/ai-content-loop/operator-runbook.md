# AI Content Loop Operator Runbook

## Daily review

1. Open the newest JSON files under `/opt/ai-content-loop/out/final/`.
2. Check `master_title`, the source URL, and the selected platform body.
3. Select the matching field under `platform_markdown`:
   - `wechat`
   - `xiaohongshu`
   - `toutiao`
   - `zhihu`
4. Reject content with unsupported claims, title/body mismatch, risky advice,
   or an incorrect source link.
5. Copy the reviewed platform body into the target platform editor.
6. Record platform metrics manually in a CSV with this header:

```csv
dedupe_key,platform,metric_date,views,likes,collects,comments,shares,follows,notes
```

## Metrics import

```bash
python -m ai_content_loop.cli --config /opt/ai-content-loop/config.toml import-metrics /opt/ai-content-loop/metrics.csv
```

## Generation failures

Inspect `/opt/ai-content-loop/out/failures/` when the queue status is
`generation_failed`. Failure artifacts contain generic machine-readable
codes, not raw model output or credentials.

Do not publish a `generation_failed` item. Fix the input/configuration, reset
the queue row to `needs_generation`, and rerun:

```bash
cd /opt/ai-content-loop/repo
python3 -m ai_content_loop.cli \
  --config /opt/ai-content-loop/config.toml \
  generate-drafts
```

Rows left in `generating` after a process crash are protected by a one-hour
lease and are reclaimed automatically by the next run. Claim tokens prevent
an expired worker from overwriting a newer worker's state.

## Service checks

```bash
systemctl is-enabled ai-content-loop.timer
systemctl is-active ai-content-loop.timer
systemctl list-timers ai-content-loop.timer --no-pager
sudo journalctl -u ai-content-loop.service -n 100 --no-pager
```

## Stop conditions

Stop publishing and inspect manually when any of these happen:

- platform login abnormality;
- captcha or account risk prompt;
- source item has no first-party URL;
- title and body do not describe the same thing;
- draft includes medical, legal, or financial advice;
- draft claims guaranteed income.
- the item exists only under `out/drafts/` or `out/failures/`, not
  `out/final/`.

## Weekly review

Use `out/weekly-summary.json` plus Hermes weekly recap prompt to decide:

- source weights to increase;
- source weights to decrease;
- title patterns to reuse;
- columns to expand;
- topics to avoid.
