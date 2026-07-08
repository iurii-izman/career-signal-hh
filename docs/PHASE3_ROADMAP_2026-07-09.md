# Phase 3 Roadmap — 2026-07-09

## Decision

Phase 3 should not start with another broad feature hunt.

The correct next move is now:

1. merge the consolidated post-L baseline into `main`;
2. activate live operator flows that already exist in code;
3. only then expand operator productivity and distribution maturity.

## Why this is the right move

After Tail-0 and Epics A-L, the core product loop already exists and is
verified:

```text
search -> score -> queue -> briefing -> apply-pack -> apply-assist
-> manual apply -> review tracking -> outbox -> HH sync/operator UI
```

The main gaps are no longer "missing core features". They are:

- live activation of managed OAuth, HH sync, and outbox delivery;
- better operator productivity around already-shipped flows;
- selective architecture relief where growth pressure is now visible.

## What is explicitly not Phase 3

The following remain out of scope unless there is a later explicit decision:

- auto-apply;
- hidden browser submission flows;
- hidden writes to hh.ru;
- background self-healing that hides operator state transitions;
- major architecture rewrites for their own sake;
- marketplace/multi-user/SaaS expansion before the local operator product
  becomes fully consolidated.

## Recommended Epic Order

1. Epic N — Live Activation: OAuth, HH Sync, Outbox
2. Epic O — Operator Productivity Layer
3. Epic P — Architecture Relief for Storage/UI Aggregation
4. Epic Q — Distribution & Packaging Maturity

## Epic M — Baseline Consolidation & Release Freeze

### Status

Completed on 2026-07-09 as release baseline `v0.8.0`.

### Goal

Turn the real post-L branch state into one explicit and documented baseline.

### Scope

- merge/align post-K and post-L work into the official baseline branch;
- refresh `README.md`, `CHANGELOG.md`, release checklist, current-state docs;
- add missing Epic L decision documentation;
- cut the consolidated release as `0.8.0`;
- run full verification and freeze the baseline.

### Exit criteria

- one branch is clearly the official baseline;
- docs no longer describe completed epics as future work;
- release/version story is internally coherent.

## Epic N — Live Activation: OAuth, HH Sync, Outbox

### Goal

Move managed operator flows from implemented code into real local operation.

### Scope

- complete managed OAuth login on the operator machine;
- verify `oauth refresh` on real credentials;
- run `hh-sync me`, `hh-sync resumes`, `hh-sync negotiations`,
  `hh-sync messages`, and `hh-sync reconcile`;
- connect the real webhook target for `notion-sync`;
- verify one real delivery for `briefing_saved` and one for `review_applied`.

### Exit criteria

- local OAuth metadata is populated and healthy;
- HH sync tables contain real snapshots;
- outbox delivery is enabled and verified end-to-end;
- operator docs reflect the live setup sequence.

### Risks

- real HH scopes or endpoint behavior may differ from local assumptions;
- downstream webhook dedupe/contract issues may surface only in live activation.

## Epic O — Operator Productivity Layer

### Goal

Reduce manual friction in the daily operator loop without widening the safety
boundary.

### Scope

- stronger readiness surfacing for assist/briefing/draft gaps;
- direct dashboard shortcuts into queue/briefing/apply-pack actions;
- richer follow-up and stale-review attention views;
- optional reminders/checklists/exported daily summary artifacts.

### Exit criteria

- operator can navigate the highest-value daily tasks with fewer CLI hops;
- no auto-apply or hidden actioning is introduced.

## Epic P — Architecture Relief for Storage/UI Aggregation

### Goal

Reduce concentration pressure in the heaviest service files without rewriting
the system.

### Scope

- split selected aggregation logic out of `src/storage.py`;
- tighten boundaries around dashboard/operator state builders;
- keep DB schema and CLI behavior stable while reducing file-level sprawl.

### Exit criteria

- the highest-pressure files become easier to reason about;
- no product behavior changes are required to land the refactor.

## Epic Q — Distribution & Packaging Maturity

### Goal

Advance from "desktop-ready local wrapper" to a more distributable local tool.

### Scope

- decide packaging target:
  - native installer baseline, or
  - bundled local runtime, or
  - shell/shortcut hardening only;
- improve app startup/shutdown observability;
- document support boundaries and upgrade path.

### Exit criteria

- local delivery story is clearer and less developer-centric;
- packaging choices are explicit rather than implied.

## Management Rules For Phase 3

- Keep the no-auto-apply boundary absolute.
- Prefer activation and consolidation over speculative features.
- Do not hide state transitions from the operator.
- Avoid adding more broad responsibilities into `src/storage.py`.
- Every epic should end with updated docs, green `ruff`, green `pytest`,
  clean git state, commit, and push.
