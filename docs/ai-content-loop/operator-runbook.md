# AI Content Loop Operator Runbook

## Daily review

1. Open the newest article in the authenticated review desk. Final JSON lives
   under `/opt/ai-content-loop/out/final/`, but do not modify it directly.
2. Check `master_title`, the source URL, source note, and the selected
   platform body.
3. Open the **rich preview** and check the reader-facing order: hero, lead,
   key judgment, sections, callouts, and source note. `article_layout` is a
   constrained semantic plan; it is not editable HTML. Older articles without
   it use the safe Markdown fallback and remain reviewable.
4. Select the matching field under `platform_markdown`:
   - `wechat`
   - `xiaohongshu`
   - `toutiao`
   - `zhihu`
5. Reject content with unsupported claims, title/body mismatch, risky advice,
   or an incorrect source link.
6. Confirm the generated cover and one body visual are relevant and readable.
   Approval is intentionally blocked when a required visual asset or its
   canonical WeChat body marker is missing.
7. Save any corrections through the desk. A save, history restore, or visual
   rerender automatically revokes prior approval and the current web-edition
   record; review the changed version again.
8. When the item is approved, use **Export web edition** only when a portable
   shareable HTML file is needed. The service writes the current approved
   version atomically to
   `/opt/ai-content-loop/out/web/<article-id>.html`; use the returned view or
   download link rather than guessing a filesystem path.
9. Copy the reviewed platform body into the target platform editor. The web
   edition is a reading and sharing artifact, not an automatic publisher.
10. Record platform metrics manually in a CSV with this header:

```csv
dedupe_key,platform,metric_date,views,likes,collects,comments,shares,follows,notes
```

## Review and export safety boundary

- Never paste model-generated HTML, CSS, JavaScript, embed code, or external
  asset URLs into `article_layout`; the renderer owns markup, theme, escaping,
  and asset paths.
- Rich previews and exported editions keep source URLs as readable text rather
  than outbound navigation. Verify the source before publishing through any
  target platform.
- The review desk requires login and CSRF protection. Its CSP allows only
  same-origin review assets. A web edition is served only while its approval
  and content-version record remain current; its CSP disallows scripts and
  network connections and permits only inline renderer CSS plus embedded
  `data:` images.
- Do not publish directly from `out/web/`, expose `out/` through a static web
  server, or reuse an exported file after any article or visual change. The
  record is revoked on change even if an old HTML file remains on disk.

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
