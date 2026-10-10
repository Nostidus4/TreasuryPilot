# M13 · Notifications

**Status:** Draft for gate G2 · **Path:** `docs/modules/notifications/`

## Purpose
Route domain events to users (in-app, Telegram; email/webhooks/chat platforms Later).

## Features
F-100, F-101, F-102–F-105 (Later)

## Inputs
Domain events.

## Outputs
Notifications; Telegram messages.

## APIs
`/notifications…`, `/me/channels…`, `/integrations/telegram/webhook` (API_SPEC §8).

## Data model
notifications, notification_channels

## Dependencies
M01 (roles), Telegram API.

## Security concerns
PII on third-party chat (opt-in amounts, OQ-17); webhook auth (secret token); no actions from chat.

## Failure scenarios
Telegram down → in-app still delivered; retries.

## Open questions
None.
