# davinci-scripts — AGENTS.md

Python scripting for DaVinci Resolve, plus a local searchable copy of the
official manual.

## Git workflow (project override)

This is a small personal package: **direct commits to `main` are fine — no
feature branches or PRs needed for now.** Keep commits small and
conventional. Every library change must come with unit tests
(`tests/test_*.py`, runnable without Resolve) and pass the full suite before
pushing.

## Driving Resolve from prompts (no MCP needed)

An agent with shell access can control Resolve directly via the scripting
API. Requirements: Resolve **Studio** running, a project open, and
Preferences > General > External scripting using = **Local**.

The loop:

1. **Verify connection & state first**: `python3 -m resolve_kit` prints a
   JSON snapshot (project, timeline, fps, tracks, marker count). If it
   errors, surface the hint to the user — don't guess.
2. **Write a small script** using `resolve_kit` (see README) plus
   `RESOLVE_API_REFERENCE.md` / `RESOLVE_SCRIPTING_GUIDE.md` for API details.
   **Read the "Known API Pitfalls" section of the scripting guide first** —
   the bridge lies (hasattr always True, setters return True without effect,
   marker frames are timeline-relative). Use `has_method()` before calling
   optional APIs and `verify_by_readback()` for writes that must land.
   Run scripts with `PYTHONPATH=<repo root>` or from the repo root.
3. **Destructive changes**: use `dry_run=True` first (built into
   `delete_markers`; implement the same in new scripts); tag created objects
   via marker `custom_data` (invisible in UI) so they can be reverted with
   `delete_markers(custom_data=...)`.
4. **Verify after writing**: re-read RAW state (`tl.GetMarkers()`,
   `rk.summary()`, item iteration) and report what actually changed.
5. **Sanity check**: `PYTHONPATH=. python3 tests/live_smoke.py` runs a
   non-invasive live test suite (reversible ops only).

Rules:

- Never render, delete media, save/close projects, or modify the Media Pool
  without the user explicitly asking.
- Prefer reversible operations; when irreversible (e.g. overwriting Fusion
  tool inputs), remind the user that Cmd+Z in Resolve undoes it.
- Scratch scripts go in `temp_*.py` (gitignored) or the OS temp dir — don't
  commit one-off scripts.

## Answering questions from the DaVinci Resolve manual (local machine only)

NOTE: `manual/` is gitignored (copyrighted Blackmagic content) — it exists
only on Marcelo's machine. If it's missing, answer from the API docs and
general knowledge instead, and say so.

The full **DaVinci Resolve 21 Reference Manual** (4444 pages) lives at
`manual/Resolve Manual.pdf`. Its text has already been extracted — **do not
re-extract or read the PDF directly** for questions; use the text files:

- `manual/INDEX.md` — table of contents: every section/chapter mapped to its
  text file and PDF page number. Read this first to pick the right file.
- `manual/text/NN_<section>.txt` — one file per top-level section, containing
  `===== [PDF page N] =====` markers so answers can cite exact manual pages.

Workflow for "how do I X in Resolve?" questions:

1. Check `manual/INDEX.md` to identify the relevant section file(s).
2. Grep the section file(s) for keywords (e.g. `grep -n "Smart Bin" manual/text/04_*.txt`).
   If unsure which section, grep across `manual/text/*.txt`.
3. Read the surrounding lines / page block for context.
4. Cite the PDF page number (from the nearest `[PDF page N]` marker) in the
   answer so Marcelo can look it up in the actual manual.

Section overview (file → topic):

| File | Topic | PDF pages |
|------|-------|-----------|
| 01_getting-started | Getting started | 10–11 |
| 02_davinci-resolve-interface | UI overview | 12–73 |
| 03_setup-and-workflows | Prefs, project settings, proxies, color mgmt, HDR | 74–350 |
| 04_ingest-and-organize-media | Media page, Media Pool, metadata, conform | 351–588 |
| 05_photo | Photo page | 589–652 |
| 06_cut | Cut page | 653–812 |
| 07_edit | Edit page | 813–1175 |
| 08_editing-effects-and-transitions | Effects & transitions | 1176–1316 |
| 09_fusion-fundamentals | Fusion basics | 1317–1968 |
| 10_fusion-page-effects | Fusion node reference | 1969–3083 |
| 11_color | Color page | 3084–3553 |
| 12_color-page-effects | Color page effects | 3554–3593 |
| 13_resolve-fx-overview | ResolveFX reference | 3594–3813 |
| 14_fairlight | Fairlight (audio) | 3814–4169 |
| 15_deliver | Deliver page | 4170–4251 |
| 16_blackmagic-cloud | Blackmagic Cloud | 4252–4305 |
| 17_project-libraries-collaborative... | Collaboration, remote workflows | 4306–4350 |
| 18_immersive-and-vr | Immersive / VR | 4351–4408 |
| 19_advanced-workflows | Advanced workflows | 4409–4428 |
| 20_menu-descriptions | Menu-by-menu reference | 4429–4444 |

Note: the scripting API is NOT covered in the manual — for API questions use
`RESOLVE_API_REFERENCE.md` and `RESOLVE_SCRIPTING_GUIDE.md` in the repo root.

## Repo contents

- `resolve_kit/` — helper library for scripting Resolve (connection, markers,
  Fusion tools). `python3 -m resolve_kit` = connection smoke test.
- `copy_text_style.py`, `create_beat_markers.py` — Resolve scripting utilities.
- `RESOLVE_API_REFERENCE.md` / `RESOLVE_SCRIPTING_GUIDE.md` — scripting API docs.
- `temp_*.py` — scratch scripts (gitignored).
