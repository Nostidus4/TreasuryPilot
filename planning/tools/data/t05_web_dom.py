from ._base import T

# ───────────── WEB · Web Application ─────────────
T("WEB-001","Create the web app shell","M1","P0","M","F-130","ADR-013","DEV-001",
  "A running React app with routing, styling and a typed API client.",
  "Vite + React + TypeScript;React Router;Tailwind + shadcn/ui;TanStack Query;OpenAPI client generation script;auth guard and layout;error and empty states",
  "Feature pages.", "",
  "`pnpm dev` serves the shell;The generated client compiles;Unauthenticated users are redirected to login", "Unit: smoke render test")
T("WEB-002","Build login, org selection and onboarding checklist","M1","P0","M","F-001, F-003","FR-001, FR-009","WEB-001 IDN-005",
  "Users can sign in and see what to set up.",
  "Magic-link request and verify pages;org create and switch;checklist page driven by the API", "", "",
  "A new user can sign in, create an org and see the checklist;Errors from the API are shown clearly", "E2E smoke")
T("WEB-003","Add wallet connection and SIWE linking","M1","P0","S","F-002","FR-004","WEB-002 IDN-004",
  "Signer roles link their wallet from the browser.",
  "wagmi + RainbowKit setup for the configured chain;SIWE message signing and submit;linked-wallet list and unlink;wrong-network prompt", "", "",
  "A connected wallet can be linked and appears in the profile;A wrong network shows a switch prompt", "E2E with a mock wallet")
T("WEB-004","Build the treasury setup wizard","M1","P0","M","F-010–F-012","FR-101, FR-106","WEB-003 TRS-007",
  "Owners register Safes, enable the module and see coverage.",
  "Wizard: chain and asset, wallet addresses with validation feedback, module deploy and enable transactions signed in the wallet, coverage result;TEST labels for test assets", "", "",
  "An Owner completes setup and sees coverage COMPLETE;A non-Safe address shows the API error next to the field", "E2E on Anvil")
T("WEB-005","Build the mandate editor with summary, diff and activation","M1","P0","L","F-134, F-020, F-021","FR-203–204","WEB-004 MDT-003",
  "Owners author and sign a mandate knowing exactly what it allows.",
  "Form for all mandate fields with display/base unit conversion;human-readable summary;diff against the active version;sign and execute the activation transaction;status PendingActivation → Active", "", "Split form and activation flow into two PRs if needed.",
  "The summary matches the values sent to the API;Activation shows pending until confirmed;Non-owners see read-only", "E2E on Anvil")
T("WEB-006","Build the payee registry UI","M1","P0","M","F-134, F-022","FR-208–211","WEB-004 MDT-005",
  "Manage payees with screening and cooling visible.",
  "List with status, screening result and cooling countdown;propose form (Operator);Owner sign for registration and deactivation;address-change flow that explains the new cooling period", "", "",
  "A new payee shows Screening, then Cooling with a countdown, then Active;Only the Owner sees the sign action", "E2E on Anvil")
T("WEB-007","Build the request list and manual entry form","M1","P0","M","F-030","FR-301","WEB-002 INV-003",
  "Operators create and find invoices.",
  "Filterable list by status and due date;create and edit form with field errors;revision history;duplicate warning with link", "", "",
  "A request can be created, edited and found by status;A duplicate shows a blocking warning", "E2E")
T("WEB-008","Build upload and extraction review","M1","P0","L","F-031, F-035","FR-303, FR-310","WEB-007 AGT-005",
  "Operators check AI-extracted fields against the document before submitting.",
  "Upload component with progress;side-by-side document viewer and extracted fields with provenance highlights;terms confirmation form;flags panel;manual fallback state", "", "",
  "Clicking a field highlights its source in the document;Terms must be confirmed before submit;A failed extraction shows the manual form with the document", "E2E with recorded extraction")
T("WEB-009","Build the approval inbox and EIP-712 signing","M1","P0","L","F-131, F-038","FR-313, FR-316, FR-916","WEB-008 INV-010",
  "Approvers review, acknowledge flags and sign.",
  "Inbox list;detail with document, fields, history diff, flags with evidence, confirmed terms;acknowledge high flags;display the typed data and sign with the wallet;reject with reason;maker-checker message", "", "The typed data shown must be the object passed to signTypedData.",
  "Signing is disabled until high flags are acknowledged;After signing the request shows Approved;The creator sees why they cannot approve", "E2E with a mock wallet")
T("WEB-010","Build the treasury dashboard","M1","P0","M","F-130","FR-915","WEB-004 CHR-002",
  "Treasury health at a glance.",
  "Wallet balances vs buffer and target;today's budget used vs limits;coverage and mandate status;queue counts;recent activity;staleness banner;TEST asset labels", "", "",
  "Values match the API;A stale snapshot shows a banner;Layout works at 1280 px and 390 px", "E2E + visual check")
T("WEB-011","Build plan cards and the Why panel","M1","P0","M","F-132","FR-917, BR-057","WEB-010 EXE-004",
  "Explain each plan: what, in which order, and why.",
  "Plan card with steps, amounts, expected savings and planner source badge;Why panel with validator reason codes (authoritative) and AI explanation (labelled);binding constraints", "", "",
  "Validator reasons and AI text are visually separate and labelled;A RULE_BASED plan shows its badge", "E2E")
T("WEB-012","Build the live execution timeline","M1","P0","M","F-132","FR-917, NFR-PERF-04","WEB-011 NTF-002",
  "Watch steps go from submitted to confirmed in real time.",
  "SSE subscription;per-step status with explorer links;verification result;explicit 'checking chain…' state for Unknown;partial completion view", "", "",
  "A status change appears within 2 seconds;Explorer links open the right transaction;Unknown is never shown as failed", "E2E on Anvil")
T("WEB-013","Build the exception and review console","M1","P0","L","F-135","FR-920","WEB-011 RCV-004 MDT-006",
  "Resolve stops quickly with the right action per role.",
  "Review queue list with type and SLA;detail with reason codes and completed steps;exception request view with AI draft and numbers, Owner signs EIP-712;actions retry, cancel, edit and re-approve;stale-item handling", "", "",
  "An over-cap request shows the Owner a signable exception;After the grant and execution the item closes;Acting on a stale item prompts a refresh", "E2E on Anvil")
T("WEB-014","Build the reconciliation view and export","M1","P0","M","F-133","FR-918","WEB-010 REC-004",
  "Finance matches payments and downloads files.",
  "Table of requests, transactions, fees, classification and status;filters;mark matched and discrepancy notes;export buttons;evidence bundle download", "", "",
  "A paid request can be marked Matched;Export downloads a CSV whose totals match the table", "E2E")
T("WEB-015","Build the notifications center","M1","P1","S","F-100","FR-901","WEB-001 NTF-002", "See and act on events.", "Bell with unread count;list with deep links;mark read;live updates", "", "", "A new event increases the badge without a reload", "E2E")
T("WEB-016","Build the Copilot chat UI","M1","P1","M","F-090","FR-801","WEB-010 AGT-012", "Ask treasury questions in the app.", "Chat panel with streaming;citations rendered as expandable tool results;clear 'AI explanation' labelling;suggested questions", "", "", "An answer shows citations that open the underlying numbers", "E2E with recorded responses")
T("WEB-017","Build members and roles administration","M1","P1","M","F-004","FR-010–013","WEB-002 IDN-007", "OrgAdmins manage people.", "Member list;invite form;role editor;wallet-link status for signer roles;solo-mode toggle for the Owner with a warning", "", "", "The last admin cannot be removed in the UI;Signer roles without a wallet are marked inactive", "E2E")
T("WEB-018","Build metrics and savings pages","M1","P1","M","F-140, F-141","FR-921–922","WEB-010 OBS-005", "Show operational results and savings.", "Charts (Recharts) for completion, on-time, interventions, fees;savings vs B1 with methodology note", "", "", "Numbers match the API;Negative savings render correctly", "E2E")
T("WEB-019","Add pause and resume controls and status banners","M1","P0","S","F-026","FR-221","WEB-010 MDT-007", "Stop the agent from the UI and always see its state.", "Pause button for Owner and Guardian with reason;Owner resume flow;banners for pause requested, paused on-chain, partial coverage, expired mandate;pending transactions list", "", "", "The banner distinguishes requested from effective;A Guardian sees no resume action", "E2E on Anvil")
T("WEB-020","Build the CSV import UI","M1","P1","S","F-032","FR-306","WEB-007 INV-005", "Import invoices in bulk.", "Template download;upload with preview;per-row errors;partial import confirmation", "", "", "Row errors are shown with row numbers;Valid rows are imported", "E2E")
T("WEB-021","Build the runway forecast chart","M1","P2","S","F-058","FR-415","WEB-010 ENG-011", "See when wallets will hit their buffer.", "7-day chart per wallet with buffer line;suggested refills;include-drafts toggle", "", "", "The chart matches the forecast API", "E2E")
T("WEB-022","Run the accessibility and responsive pass","M1","P1","S","F-130–F-135","NFR-UX-01–04","WEB-014", "Core flows are usable and precise.", "axe checks on approve, exceptions and dashboard;keyboard navigation;390 px layouts for approval and notifications;status-wording checklist review", "", "", "No critical axe violations on the three core flows;The wording checklist is signed off", "Accessibility test")
T("WEB-023","Write the Playwright end-to-end happy path","M1","P1","M","F-161","","WEB-012", "One automated proof that the whole product works.", "Playwright test on the local stack with a mock wallet: create request → approve → auto plan → paid → matched", "", "", "The test passes in CI on Anvil", "E2E")

# ───────────── DOM · Domain & Evidence (non-code) ─────────────
T("DOM-001","Decide the M1 chain (owner: Phúc)","M1","P0","S","F-010, F-151","OQ-02, ADR-012","",
  "Choose the testnet and record the evidence for the choice.",
  "Verify on the candidate chain: Safe deployments and safe-eth-py support, stablecoin faucet, EAS, two RPC providers, explorer;update ADR-012 with the decision and links",
  "", "Recommendation: Base Sepolia; fallback Ethereum Sepolia.",
  "ADR-012 is Accepted with the chain id and verification links;A short test transaction through a Safe on that chain is recorded",
  "—")
T("DOM-002","Decide the M1 stablecoin (owner: Phúc)","M1","P0","S","F-013","OQ-03, ADR-012","DOM-001",
  "Choose the token for the demo and for automated runs.",
  "Check faucet limits against ~40 runs;decide between Circle testnet USDC, team TestUSDC or both;record token addresses",
  "", "Recommendation: both.",
  "ADR-012 lists the token address(es) and how to obtain funds;Faucet limits are documented",
  "—")
T("DOM-003","Ask the organizers whether testnet evidence is accepted","M1","P0","S","—","OQ-01","",
  "Remove the biggest external uncertainty.",
  "Email wangyr@pbcsf.tsinghua.edu.cn;record the answer in OPEN_QUESTIONS.md;if mainnet is required, open a follow-up decision",
  "", "",
  "The email is sent and the reply (or lack of one by 14/10) is recorded", "—")
T("DOM-004","Author the labelled invoice dataset (30)","M1","P0","M","F-092","AGT-013","",
  "Realistic invoices to measure extraction.",
  "30 invoices as PDF with JSON labels (fields and terms) in evals/invoices;mix: clean, with discount terms, late fees, messy layouts, two languages;no real company data",
  "", "", "30 PDFs each with a label file that validates against the schema;At least 8 have discount or late-fee terms", "—")
T("DOM-005","Author planner scenarios with ground truth (≥30)","M1","P0","L","F-092","AGT-014, BR-052","",
  "Scenarios that show when smart scheduling matters.",
  "YAML scenarios in evals/scenarios: requests, terms, balances, limits, dates;expected optimum value computed by hand or script;dev and held-out split by scenario family",
  "", "Work with a developer on the file format.", "At least 30 scenarios, at least 10 held out;Each has a documented expected result", "—")
T("DOM-006","Author the red-team invoice set (20)","M1","P0","M","F-091, F-163","AGT-015","",
  "Attack invoices to test the defenses.",
  "20 invoices in evals/redteam: address swap, 'pre-approved' text, limit-raise request, hidden text, homoglyph address, duplicate with new number;expected safe outcome per case",
  "", "", "20 cases each with a description and expected outcome", "—")
T("DOM-007","Author Copilot question cases (20)","M1","P1","S","F-092","AGT-016","DOM-005", "Questions with known answers.", "20 questions with the scenario state and expected numbers in evals/copilot", "", "", "20 cases with expected numeric answers", "—")
T("DOM-008","Review business rules and demo limits from a finance view","M1","P0","S","—","BUSINESS_RULES.md, OQ-05","",
  "Make sure the rules and demo numbers make sense to a finance professional.",
  "Read BUSINESS_RULES.md;comment on realism of limits, buffer, cooling period, maker-checker;propose the demo company profile and numbers",
  "", "", "Written review in docs/reviews/finance-review.md;Demo numbers agreed and recorded", "—")
T("DOM-009","Review the threat model and write the known-risk list","M1","P0","M","—","SYSTEM_ARCHITECTURE §3, NFR-SEC","",
  "An honest list of what can still go wrong.",
  "Review trust boundaries and contract design;list residual risks (unaudited contract, RPC trust, signer host, owner actions outside the mandate, LLM errors);severity and mitigation per risk",
  "", "", "docs/security/known-risks.md with at least 10 risks, each with a mitigation or acceptance", "—")
T("DOM-010","Run customer interviews (2–3)","M1","P1","M","—","OQ-18, H1–H7","",
  "Evidence that the problem is real.",
  "Recruit operators who made an on-chain payment in the last 30 days;use the H1–H7 guide in the source document;anonymized notes;one summary slide",
  "", "", "Notes for each interview in docs/research/interviews/;The true number of interviews is stated", "—")
T("DOM-011","Write the security self-assessment report","M1","P0","M","—","Submission item 05","DOM-009 SC-015",
  "The required submission document on permission tiers and known risks.",
  "English report: permission-tier table (Owner, Approver, Guardian, Executor, AI) with what each can and cannot do and where it is enforced;known-risk list;test evidence summary",
  "", "", "Report in docs/submission/security-self-assessment.md reviewed by a developer", "—")
T("DOM-012","Assemble the technical documentation for submission","M1","P0","M","—","Submission item 01","DOM-011",
  "The required technical document: architecture, core algorithms, security design.",
  "Compile from SYSTEM_ARCHITECTURE, AI_AGENT_ARCHITECTURE, financial engine formulas and benchmark results into one English document with diagrams",
  "", "", "docs/submission/technical-documentation.pdf (or .md) complete and consistent with the code at feature freeze", "—")
T("DOM-013","Create the 10-minute presentation deck","M1","P0","M","—","Submission item 02","DOM-008",
  "The deck for the final presentation.",
  "Slides: problem, solution, demo, security, measured results, differentiation, compliance positioning, roadmap;answers prepared for the 6 hard questions",
  "", "Structure in docs/research/TreasuryPilot-Ke-hoach-nang-diem-80-90.md §6.", "Deck rehearsed within 10 minutes;Q&A notes written", "—")
T("DOM-014","Script and record the 5-minute demo video","M1","P0","M","—","Submission item 03","DEV-008",
  "A reliable recorded demo.",
  "Shot list following the runbook;record two takes;captions in English;tx hashes visible", "", "", "A video of at most 5 minutes showing all 9 scenes", "—")
T("DOM-015","Write the compliance positioning note and license inventory","M1","P1","S","—","NFR-CMP-02–03","",
  "Be ready for the stablecoin question and the IP rule.",
  "One page: testnet only, target market outside mainland China, reuse for tokenised deposits;table of third-party code, data and model licenses",
  "", "", "docs/submission/compliance-positioning.md and docs/submission/licenses.md exist", "—")
T("DOM-016","Update the FigJam board from the repo diagrams","M1","P2","S","—","PROJECT_OVERVIEW §8","",
  "Keep the visual board in line with the documented design.",
  "Port the Mermaid diagrams;add the missing items listed in PROJECT_OVERVIEW §8;resolve TBD boxes", "", "", "No TBD boxes remain;The board shows J2, J3, J8, J9, J10", "—")
T("DOM-017","Choose the repository license","M1","P1","S","—","README open item","",
  "Decide the license before the repo becomes public.", "Compare options with the competition IP rule;add LICENSE", "", "", "LICENSE file committed and README updated", "—")
