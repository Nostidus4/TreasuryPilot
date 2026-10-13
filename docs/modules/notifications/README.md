# M13 · Notifications (`api` + `worker`)

**Status:** Detailed — decisions finalized by the tech lead under the project lead's delegation (2026-10-11) · **Path:** `docs/modules/notifications/` · **Code:** `services/api/.../events`, `services/worker/.../notify` · **Epic:** `[EPIC] M13 · Notifications`
**ADRs:** ADR-010 (REST + SSE) · **Decisions:** M13-D1 … M13-D9 (§14)

---

## 1. Purpose and boundaries

M13 makes sure **the right person learns about the right event quickly, without leaking sensitive data**, and that the UI updates live. Notifications never carry an action that moves money: every link goes back to the app, where permissions and signatures apply.

| In scope (M1) | Out of scope |
|---|---|
| Domain event bus (outbox table + publisher) | Email notifications, webhooks, Slack/Lark/WeCom, preferences (Later NTF-L01…L04) |
| Routing event → roles, dedup by event id | |
| In-app notifications + SSE stream for live status | |
| Telegram channel with linking, minimal content, opt-in amounts (P2) | |

## 2. Features, requirements and rules

F-100 (FR-901), F-101 (FR-902, OQ-17), F-132 (live timeline via SSE); Later F-102…F-105.

## 3. Concepts

| Term | Definition |
|---|---|
| **Domain event** | `{id, org_id, treasury_id?, type, entity, payload (ids only), at}` written in the same DB transaction as the change (outbox). |
| **Routing rule** | event type → roles (+ specific user, e.g. the creator). |
| **Mandatory event** | Cannot be muted later (security: pause, unexpected outflow, discrepancy, coverage drop, circuit breaker). |

## 4. Data model

| Table | Columns |
|---|---|
| `domain_events` | id, org_id, treasury_id, type, entity_type, entity_id, payload jsonb, created_at, published_at |
| `notifications` | id, org_id, user_id, event_id, type, title, body, link, severity enum(INFO, ACTION, CRITICAL), read_at — unique(user_id, event_id) |
| `notification_channels` | id, user_id, kind enum(TELEGRAM), target (encrypted chat id), verified_at, show_amounts bool |
| `telegram_link_codes` | code_hash (SHA-256), user_id, expires_at, used_at |
| `telegram_deliveries` | id, notification_id, channel_id, status enum(PENDING, SENT, FAILED), attempts, next_attempt_at, sent_at, last_error — unique(notification_id, channel_id) |

`notification_channels` also holds `target_hash` (keyed HMAC of the chat id, unique per kind, so one chat belongs to one user), `active` and `last_sent_at` (the rate-limit anchor). `target` is an AES-GCM `FieldCipher` envelope bound to the column.

## 5. Routing table (M1)

| Event | Roles | Severity |
|---|---|---|
| ApprovalNeeded (request submitted) | Approver | ACTION |
| HighFlagRaised | Approver, Operator | ACTION |
| ExceptionNeeded (NEEDS_APPROVAL) | Owner | ACTION |
| GovernanceSignatureNeeded | User IDs linked to owners of that Safe (`ownerUserIds`) | ACTION |
| FeeAcceptanceNeeded | Finance, Operator, Owner | ACTION |
| PaymentDone (Paid) | Operator, Finance, request creator | INFO |
| NeedsReview (any review item) | routed role (M12) | ACTION |
| UnknownOperation | Operator, Owner | CRITICAL |
| PauseRequested / PauseEffective / Resumed | Owner, Guardian, Operator | CRITICAL |
| CircuitBreakerTripped | Owner, Guardian | CRITICAL |
| UnexpectedOutflow | Owner, Finance | CRITICAL |
| CoverageChanged (not COMPLETE) | Owner, OrgAdmin | CRITICAL |
| LowGas (executor/sentinel/receipt) | Operator, OrgAdmin | ACTION |
| MandateExpiring (7 d / 48 h / 1 h) | Owner | ACTION |
| Discrepancy | Finance, Owner | CRITICAL |

## 6. Interfaces

| Method | Endpoint | Perm |
|---|---|---|
| GET | `/orgs/{o}/notifications?unread=` | auth member |
| POST | `/orgs/{o}/notifications/read` `{ids}` | auth |
| GET | `/orgs/{o}/events` (SSE; `Last-Event-ID` resume; heartbeat 15 s) | auth member |
| POST | `/me/channels/telegram/link-code` → `{code, botUrl}` | auth |
| POST | `/integrations/telegram/webhook` (secret header) | Telegram |
| PATCH | `/me/channels/{id}` `{showAmounts}` | auth |

SSE event types: `request.status`, `plan.status`, `operation.status`, `review.created`, `notification.created`, `treasury.status`.

## 7. Flows

Change + `domain_events` row in one transaction → publisher task (every 1 s, `FOR UPDATE SKIP LOCKED`) → routing → `notifications` rows (dedup) → SSE push via Redis pub/sub per org → Telegram sender (P2) for ACTION/CRITICAL to linked users.

## 8. Algorithms

- **Telegram content (OQ-17):** default `"[TreasuryPilot] Approval needed for request R-1042 · open: <link>"` — no amounts, addresses, vendor names; with `show_amounts` opt-in: adds amount and vendor display name. Deep links require app login.
- **Telegram flow:** the user requests a link code (128-bit, only its hash stored, 10 min, one live code per user, consumed by an atomic `UPDATE … WHERE used_at IS NULL AND expires_at > now()`), opens `botUrl` and sends `/start <code>` in a private chat; the webhook (header `X-Telegram-Bot-Api-Secret-Token`, constant-time compare) links the chat. The webhook understands nothing else, so no action is possible from Telegram. The worker task `deliver-telegram` (every 1 s) queues ACTION/CRITICAL notifications of linked, active channels (created after linking, within 1 h) into `telegram_deliveries` and sends one message per channel per 10 s. A bot-blocked response (403) deactivates the channel; transient errors retry 3 times, permanent ones fail at once. Amount and vendor name are read at send time, only for opted-in channels and only from the notification's own organization; addresses are not sent.
- **Dedup:** unique(user_id, event_id). **Rate:** at most 1 Telegram message per user per 10 s, bursts merged into a digest line.
- Governance signature events include `ownerUserIds` with the organization user IDs linked to that Safe's current owners. The publisher delivers only to those active organization members.
- `NeedsReview:<Role>` encodes the routed M12 role in the event type (for example, `NeedsReview:Finance`); event payloads still contain IDs only.
- If `ownerUserIds` is missing or empty, the event goes to every Owner and a warning is logged, so a pending signature never reaches nobody.
- `ApprovalNeeded` carries `excludeUserIds` (the request's creator and last editor) unless the org has solo mode on, so people maker-checker forbids from approving get no action item.
- The publisher (beat, every 1 s, task expiry 2 s) routes each event in its own savepoint with one `INSERT … SELECT` per event. An event that cannot be routed is dead-lettered (`failed_at`, `last_error`) and logged instead of blocking the outbox; unknown event types or review roles fall back to the CRITICAL policy with a warning, and an event with no recipients is logged. Each worker process reuses one connection pool.

## 9. Configuration

Publisher interval 1 s; SSE heartbeat 15 s; Telegram link code 10 min; Telegram retries 3 with backoff (5 s, then 20 s).

Telegram env: API `TP_TELEGRAM_BOT_USERNAME`, `TP_TELEGRAM_WEBHOOK_SECRET`, `TP_FIELD_ENCRYPTION_KEY`; core worker `TP_TELEGRAM_BOT_TOKEN`, `TP_FIELD_ENCRYPTION_KEY`, `TP_APP_BASE_URL`. Without them the channel is simply off (link-code returns `TELEGRAM_UNAVAILABLE`, the delivery task is a no-op). The bot token is read from the environment only and never logged.

## 10. Security

Org-scoped streams; payloads carry ids only (UI fetches details with permissions); Telegram webhook secret; no actions possible from Telegram; chat ids encrypted (Confidential).

## 11. Failure scenarios

Telegram down → in-app still delivered, retries; Redis pub/sub down → SSE clients fall back to polling every 10 s; publisher crash → outbox rows re-published (dedup prevents duplicates).

## 12. Test plan

Routing table tests; dedup; SSE org isolation and < 2 s latency; Telegram content with/without opt-in; link-code expiry.

## 13. Tickets

NTF-001 → NTF-002 → NTF-003 (P2). Later NTF-L01…L04.

## 14. Decisions

| ID | Decision |
|---|---|
| M13-D1 | Domain events via an outbox table in the same transaction as the change. |
| M13-D2 | Routing table §5; mandatory CRITICAL events defined now for future preferences. |
| M13-D3 | SSE per org with Last-Event-ID resume. |
| M13-D4 | Payloads carry ids only. |
| M13-D5 | Telegram minimal by default, amounts only on opt-in (OQ-17). |
| M13-D6 | No action can be completed from a notification channel. |
| M13-D7 | Telegram rate 1 msg / 10 s per user with merging. |
| M13-D8 | SSE fallback to 10 s polling when pub/sub is down. |
| M13-D9 | New events added by grilling: GovernanceSignatureNeeded, FeeAcceptanceNeeded, UnexpectedOutflow, CircuitBreakerTripped. |
