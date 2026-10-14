# Web status-wording checklist (WEB-022, NFR-UX-04)

Reviewed against `apps/web/src/lib/status.ts` and the mandatory table in
[README §5](README.md). Automated by `apps/web/src/lib/status.test.ts`,
`apps/web/src/lib/wording.test.ts` and `apps/web/src/app.test.tsx` (AI /
policy labels, symbol + network + TEST badge). Boxes stay unticked until the
maintainer signs off.

- [ ] Submitted / Pending read "Sent — waiting for the network".
- [ ] Confirmed reads "Confirmed on-chain — verifying".
- [ ] Verified / Final read "Paid · N confirmations" (+ "Final").
- [ ] Unknown reads "Checking the chain — no new payment will be sent" and is never styled as a failure.
- [ ] Pausing / paused read "Pausing…" / "Paused on-chain".
- [ ] No status label uses "safe", "done" or "guaranteed".
- [ ] In-flight, approved and scheduled requests never read as paid.
- [ ] AI text sits in a box labelled **AI explanation**; validator reasons are labelled **Policy decision**.
- [ ] Amounts show symbol + network; TEST assets carry a badge (dashboard test).
- [ ] Colour contrast meets WCAG AA (manual: axe `color-contrast` is off in jsdom, see `apps/web/src/test/axe.ts`).

Reviewer sign-off: pending maintainer approval on the PR (Nostidus4).
