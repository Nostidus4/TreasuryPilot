# Submission documents

## Baseline and evidence revisions

- Implementation baseline for the reports below: main
  `0c79d0731ad730e7c2f9f6644e90c36453b02d7e` (reviewed for these drafts on
  2026-10-15).
- CI revision for contract/security evidence:
  `02e4d674d1a76aa60cf2ac1c242f2aed20a6fb5c` (runs dated 2026-10-14).

Both reports require developer review and an update at feature freeze; the two
revisions are stated only here, and the reports refer to this section.

| Document | Tracking | Contents |
| --- | --- | --- |
| [Security self-assessment](security-self-assessment.md) | #235 / DOM-011 | Permission tiers, control boundaries, proposed known risks, evidence and operational release gates |
| [Technical documentation](technical-documentation.md) | #236 / DOM-012 | Architecture, money/authorization model, deterministic algorithms, execution design and evaluation status |

The published [PBCSF checklist](https://www.its.ac.id/international/wp-content/uploads/sites/66/2026/10/PBCSF-Appendix-2-Problem-Description-and-Competition-Rules-for-International-Track.pdf)
lists technical documentation as item 01 and a security self-assessment as item 05.
The reports explicitly identify implemented components, incomplete integrations
and evidence whose scope is historical/local. Model benchmark results and public
deployment/transaction evidence must be recorded from actual artifacts when
available. Passing CI and merged documentation do not establish operational
release readiness.

Other deliverables are tracked separately: presentation #237, optional demo video
#238, compliance positioning/license inventory #239, and the repository license
decision #241. For video, checklist item 03 specifies an optional submission of
at most five minutes. See [M20](../modules/domain-evidence/README.md) for the team's
work plan and [OQ-01](../OPEN_QUESTIONS.md) for execution-evidence source review.

At feature freeze, refresh code and evidence revisions, measured benchmark status,
deployment links and reviewer decisions in both reports. A PDF can be exported
from the reviewed Markdown if needed; #236 accepts Markdown as the deliverable.
