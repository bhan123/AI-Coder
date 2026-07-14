# Scrollable Review Workspace Design

## Problem

The review desk's `.workspace` container clips vertical overflow. At a short
viewport height, the fixed-height article metadata and controls can push the
action bar below the visible area, making the rich-reading preview button
unreachable.

## Decision

Keep the existing editor, preview panes, action bar, and JavaScript state
unchanged. Make `.workspace` the outer vertical scrolling boundary by setting
`min-height: 0`, `overflow-x: hidden`, and `overflow-y: auto`.

This is the smallest change that preserves the current inner article-preview
scrolling while allowing a reviewer to scroll the full workspace to its action
bar at any usable viewport height.

## Acceptance Criteria

- The rich-reading preview button remains reachable by vertical scrolling at a
  short desktop viewport.
- Horizontal overflow remains clipped at the workspace boundary.
- Existing editor, platform preview, rich preview, and action-bar behavior are
  unchanged.
- A regression test asserts the workspace's scroll boundary rather than relying
  on a fragile rendering implementation detail.
