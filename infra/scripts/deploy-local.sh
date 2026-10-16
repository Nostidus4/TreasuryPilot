#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
anvil_log="$(mktemp)"
anvil_pid=""
cleanup() {
  if [[ -n "$anvil_pid" ]]; then
    kill "$anvil_pid" 2>/dev/null || true
    wait "$anvil_pid" 2>/dev/null || true
  fi
  rm -f "$anvil_log"
}
trap cleanup EXIT

# Reuse the Compose Anvil (make dev/infra) when it is already up. Only the core contracts are
# CREATE2; the demo Safes use `new`, so each deploy yields new Safe addresses.
if existing_chain="$(cast chain-id --rpc-url http://127.0.0.1:8545 2>/dev/null)"; then
  if [[ "$existing_chain" != "31337" ]]; then
    echo "Port 8545 serves chain id $existing_chain, expected 31337; refusing to deploy there" >&2
    exit 1
  fi
else
  anvil --silent --chain-id 31337 --port 8545 >"$anvil_log" 2>&1 &
  anvil_pid=$!
fi

ready=false
for _ in $(seq 1 40); do
  if cast chain-id --rpc-url http://127.0.0.1:8545 >/dev/null 2>&1; then
    ready=true
    break
  fi
  sleep 1
done
if [[ "$ready" != true ]]; then
  cat "$anvil_log" >&2
  echo "Anvil did not become ready on port 8545" >&2
  exit 1
fi

# A bare Anvil has no Multicall3; the worker's block-pinned snapshots need it (CHR-002).
cast rpc anvil_setCode 0xcA11bde05977b3631167028862bE2a173976CA11 \
  "$(tr -d '[:space:]' < "$repo_root/services/worker/tests/chain/multicall3.runtime.hex")" \
  --rpc-url http://127.0.0.1:8545 >/dev/null

export FOUNDRY_PROFILE=deploy
export DEMO_OWNER="${DEMO_OWNER:-0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266}"
export DEMO_EXECUTOR="${DEMO_EXECUTOR:-0x70997970C51812dc3A010C7d01b50e0d17dc79C8}"
export DEMO_APPROVER="${DEMO_APPROVER:-0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC}"
export DEMO_GUARDIAN="${DEMO_GUARDIAN:-0x90F79bf6EB2c4f870365E785982E1f101E93b906}"
export DEMO_PAYEE="${DEMO_PAYEE:-0x15d34AAf54267DB7D7c367839AAf71A00a2C6A65}"
export DEMO_RECEIPT_ATTESTER="${DEMO_RECEIPT_ATTESTER:-0x976EA74026E726554dB657fA54763abd0C3a0aa9}"
anvil_key="${ANVIL_PRIVATE_KEY:-0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80}"
cd "$repo_root/contracts"
forge script script/Deploy.s.sol:Deploy --rpc-url http://127.0.0.1:8545 --private-key "$anvil_key" --broadcast
"$repo_root/.venv/bin/python" "$repo_root/infra/scripts/publish_manifest.py" --prediction "$repo_root/deployments/predictions/31337.json" --manifest "$repo_root/deployments/31337.json" --rpc-url http://127.0.0.1:8545
echo "Local deployment manifest: $repo_root/deployments/31337.json"
