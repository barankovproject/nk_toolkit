# Acceptance Criteria

## Before starting a feature

Write "done when" criteria explicitly. No criteria = don't start.

Example format:
```
Done when:
- Gabion solid appears on correct layer for canal X
- No errors in log
- Tested on canal X and canal Y
- JSON export contains new field Z
```

## Acceptance checklist

- [ ] No errors or exceptions in the log
- [ ] Geometry is correct on at least two canals (see `docs/process/03_testing.md`)
- [ ] Algorithm-level docs updated if logic changed (same commit)
- [ ] No `# TODO: frozen` left in code paths that are now reachable

## What does NOT count as acceptance

- "It ran without crashing" — check the log for silent failures
- "Looks right on one canal" — must test more than one
- "Works in debug mode" — must work with the real launcher
