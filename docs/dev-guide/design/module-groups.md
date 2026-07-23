# Design: Module Groups

**Status**: Implemented

Optional install-time sub-groups of module context. Baseline always installs; `groups/` (sibling of `module/`) is opt-in via flags.

## Decisions

| Topic | Choice |
|-------|--------|
| Model | Hybrid: baseline ∪ selected groups |
| Layout | Convention `groups/<name>/{skills,commands,agents}/`; no `group.yaml` |
| Default | No `-g` / `--all-groups` → baseline only + print group names |
| CLI | `-g/--group` (repeatable), `--all-groups`, `lola mod groups` |
| Registry | Store expanded group name list (`[]` = baseline-only) |
| Conflicts | Hard error on duplicate skill/command/agent names |
| Forbidden in groups | `AGENTS.md`, `mcps.json` |
| Mid-life edits | Not in v1 (uninstall + reinstall) |

```text
my-module/
  module/          # baseline
  groups/
    frontend/
      skills/…
    api/
      commands/…
```

## Install

1. No `groups/` → unchanged install-everything.
2. Omit group flags → baseline; hint optional groups.
3. `-g` / `--all-groups` → baseline ∪ selection; record names for `update`.

## Non-goals (v1)

`group.yaml`, per-group `AGENTS.md`/`mcps.json`, multi-module `lola group` bundles.
