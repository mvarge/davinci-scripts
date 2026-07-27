# Contributing

Thanks for your interest! This project has two halves with slightly different
rules:

## `resolve_kit/` — the scripting library

- **Every change needs unit tests** in `tests/test_*.py` that run without
  Resolve installed. Use the fakes in `tests/conftest.py` — they reproduce
  the scripting bridge's real behaviors (fabricated attributes, setters that
  return `True` without effect), so tests catch what matters.
- If your change touches live-API behavior, also extend
  `tests/live_smoke.py` (must stay non-invasive and reversible by default).
- Read the **"Known API Pitfalls"** section of `RESOLVE_SCRIPTING_GUIDE.md`
  before wrapping new API calls — the bridge lies in several documented ways.
  If you discover a new pitfall, add it there with a minimal repro.

## `drfx/` — content generators (transitions, effects, LUTs)

- Generators emit plain-text artifacts (`.setting` Lua tables, `.cube`
  files). Keep them dependency-free and self-contained.
- Format rules (enforced by tests — see `tests/test_make_*.py`):
  - Transitions animate via `time/comp.RenderEnd` expressions only (never
    frame-keyed BezierSplines — they don't rescale with transition length).
  - Stock Fusion tools only; no `ofx.com.blackmagicdesign.*` nodes (they're
    version-pinned and break across Resolve releases).
  - No vestigial nodes (`MediaIn`, `AudioDisplay`, `CustomData` blocks).
  - Transitions: `MainInput1` + `MainInput2` + `MainOutput1`.
    Effects: `MainInput1` + `MainOutput1` only.
- When adding a tool type the generators haven't used before, get a
  **ground-truth serialization first**: create the tool in a live Resolve
  comp via the scripting API and call `SaveSettings()` on it, then match
  Resolve's own field names and `FuID` usage exactly. Guessing field names
  produces silent failures.
- Don't reference personal/local media by absolute path in shipped
  generators unless the code degrades gracefully when the media is absent
  (see the film-burn transitions for the pattern).

## Workflow

```bash
# run the test suite (no Resolve needed; this is what CI runs)
python3 -m pytest tests/ --ignore=tests/live_smoke.py -q

# optional: live verification against a running Resolve Studio
PYTHONPATH=. python3 tests/live_smoke.py
```

- Conventional Commits (`feat(drfx): …`, `fix(connection): …`).
- Keep PRs focused — one logical change per PR.
- CI must be green (unit tests run on Python 3.10 and 3.14).

## Reporting issues

Please include your OS, Resolve version (Studio/free), Python version, and —
for API misbehavior — a minimal script demonstrating it. Output from
`python3 -m resolve_kit` helps a lot.
