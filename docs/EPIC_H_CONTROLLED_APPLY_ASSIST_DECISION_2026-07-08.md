# Epic H Controlled Apply Assist Decision — 2026-07-08

## Audit summary

Before this epic:

- `briefing` already produced the decision context and persisted it in `briefing_reports`;
- `apply-pack` already produced a deterministic draft with validator gating;
- `vacancy_events` already tracked review and briefing actions;
- there was still no explicit boundary between "draft is ready" and "operator may proceed to the HH form".

## Decision

Implement `apply-assist` as a separate command and service, not as another mode of
`apply-pack`.

Reason:

- `apply-pack` stays a pure draft/export tool;
- `apply-assist` becomes the only explicit transition into operator handoff;
- the existing online-first search/auth/UI flows stay unchanged.

## Boundary: assist vs forbidden auto-apply

Allowed:

- validate that the vacancy is shortlisted and ready;
- require saved briefing and saved draft;
- re-check the deterministic letter validator before handoff;
- print the operator checklist;
- optionally open the vacancy URL in the browser, but only after explicit
  `--approve`.

Forbidden:

- sending any HH application request;
- implicit browser opening;
- silent clipboard actions;
- bulk assist / bulk apply behavior;
- auto-marking `review apply` after browser handoff.

## Mandatory gates

`apply-assist` is blocked unless all of the following are true:

- `score >= 85`
- `confidence >= 60`
- `noise <= 35`
- `review.status == interesting`
- vacancy is not already marked `applied`
- briefing exists in `briefing_reports`
- draft exists in `vacancy_reviews.cover_letter_draft`
- letter validator passes again
- no configured hard red flags are found in title/description
- vacancy has `alternate_url` for a manual browser handoff

## Audit trail

New event types:

- `apply_assist_requested`
- `apply_assist_blocked`
- `apply_assist_ready`
- `apply_assist_approved`
- `apply_assist_handoff_opened`

`approved` and `handoff_opened` also go to `integration_outbox` so future sync
work can observe operator actions without changing the assist flow itself.

## Operator scenario

```powershell
python -m src.main review queue --min-score 70 --decision strong_match --limit 10
python -m src.main review set VACANCY_ID --status interesting
python -m src.main briefing VACANCY_ID --save-review
python -m src.main apply-pack VACANCY_ID --save-review
python -m src.main apply-assist VACANCY_ID
python -m src.main apply-assist VACANCY_ID --approve --open-browser
python -m src.main review apply VACANCY_ID --date today
```

The first `apply-assist` call is a readiness check. The second is the explicit
operator handoff. The actual HH submission remains manual.
