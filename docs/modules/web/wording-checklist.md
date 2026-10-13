# Web status-wording checklist (WEB-022, NFR-UX-04)

Reviewed against `apps/web/src/lib/status.ts` and the mandatory table in
[README §5](README.md). Automated by `apps/web/src/lib/status.test.ts` and
`apps/web/src/lib/wording.test.ts`.

- [x] Submitted / Pending read "Sent — waiting for the network".
- [x] Confirmed reads "Confirmed on-chain — verifying".
- [x] Verified / Final read "Paid · N confirmations" (+ "Final").
- [x] Unknown reads "Checking the chain — no new payment will be sent" and is never styled as a failure.
- [x] Pausing / paused read "Pausing…" / "Paused on-chain".
- [x] No status label uses "safe", "done" or "guaranteed".
- [x] In-flight, approved and scheduled requests never read as paid.
- [x] AI text sits in a box labelled **AI explanation**; validator reasons are labelled **Policy decision**.
- [x] Amounts show symbol + network; TEST assets carry a badge (dashboard test).

Reviewer sign-off: pending maintainer approval on the PR (Nostidus4).
