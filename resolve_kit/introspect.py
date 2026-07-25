"""Defenses against the fusionscript bridge's silent-failure modes.

Two traps (see RESOLVE_SCRIPTING_GUIDE.md "Known API Pitfalls"):

1. hasattr() on any API object ALWAYS returns True — the bridge fabricates a
   callable for any attribute name. Calling a fabricated method returns
   None/False with no error. Use has_method() before optional API calls.
2. Many setters return True regardless of effect. Use verify_by_readback()
   when a write must actually have landed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional


def has_method(obj: Any, name: str) -> bool:
    """True if `name` is a real method on the API object.

    hasattr() is useless here: the bridge fabricates a callable for ANY
    attribute name, so hasattr(obj, "TotallyMadeUp") is True and calling it
    silently returns None. dir() only lists real members.
    """
    try:
        return name in dir(obj)
    except Exception:
        return False


@dataclass
class ReadbackResult:
    """Outcome of a mutate-then-verify operation.

    ok            — the observed state confirms the mutation.
    raw_success   — what the mutate call itself returned (may lie).
    observed      — the post-mutation observation.
    contradiction — raw_success was truthy but observation failed (the
                    classic Resolve trap), or vice versa.
    """

    ok: bool
    raw_success: Any
    observed: Any
    contradiction: bool

    def __bool__(self) -> bool:
        return self.ok


def verify_by_readback(
    mutate: Callable[[], Any],
    observe: Callable[[], Any],
    compare: Optional[Callable[[Any], bool]] = None,
) -> ReadbackResult:
    """Run a mutation, then confirm it via a fresh read of Resolve state.

    Many Resolve setters return True without doing anything (and a few useful
    calls return None even on success). The only trustworthy signal is
    observation.

    mutate  — performs the write; its return value is recorded but not trusted.
    observe — reads back the relevant state.
    compare — predicate over the observation; defaults to truthiness.

    Example:
        result = verify_by_readback(
            mutate=lambda: clip.SetClipProperty("Reel Name", "A001"),
            observe=lambda: clip.GetClipProperty("Reel Name"),
            compare=lambda v: v == "A001",
        )
        if not result:
            ...
    """
    raw = mutate()
    observed = observe()
    ok = bool(compare(observed)) if compare else bool(observed)
    return ReadbackResult(
        ok=ok,
        raw_success=raw,
        observed=observed,
        contradiction=bool(raw) != ok,
    )
