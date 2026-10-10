# M06 · Chain Reader & Transaction Tracking

**Status:** Draft for gate G2 · **Path:** `docs/modules/chain-reader/`

## Purpose
Consistent snapshots at a block, receipt tracking with confirmations, reorg handling, event indexing for the module and Safes, and RPC failover.

## Features
F-050, F-070 (and support for F-011/F-012/F-071)

## Inputs
Treasury config, tx hashes and nonces, block stream.

## Outputs
Snapshots with coverage; transaction status updates; observed events.

## APIs
Internal service only (used by worker/api).

## Data model
snapshots, transactions (status fields), observed_events

## Dependencies
M02 (config), RPC providers.

## Security concerns
Lying or lagging RPC (cross-check block hash across providers for critical reads; mark UNKNOWN on disagreement); reorgs (blockHash tracking).

## Failure scenarios
All RPCs down → snapshots UNKNOWN → execution blocked; tracker retries with backoff; nothing is marked failed.

## Open questions
Confirmation depth per chain (depends on ADR-012).
