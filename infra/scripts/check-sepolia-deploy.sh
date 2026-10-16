#!/usr/bin/env bash
# Public Anvil identities; every broadcast below goes to an owned LOCAL fork.
set -euo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
cd "$root/contracts"
export FOUNDRY_PROFILE=deploy
export DEMO_OWNER=0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266
export DEMO_EXECUTOR=0x70997970C51812dc3A010C7d01b50e0d17dc79C8
export DEMO_APPROVER=0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC
export DEMO_GUARDIAN=0x90F79bf6EB2c4f870365E785982E1f101E93b906
export DEMO_PAYEE=0x15d34AAf54267DB7D7c367839AAf71A00a2C6A65
export DEMO_RECEIPT_ATTESTER=0x976EA74026E726554dB657fA54763abd0C3a0aa9
dev_key=0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80 # gitleaks:allow -- published Anvil fixture; LOCAL RPC only
fork_rpc=http://127.0.0.1:8554
artifact_dir=$(mktemp -d)
anvil --silent --hardfork cancun --chain-id 11155111 --port 8554 \
  --fork-url "${SEPOLIA_RPC_URL:-https://sepolia.drpc.org}" --fork-block-number 11890000 \
  > "$artifact_dir/anvil.log" 2>&1 &
fork_pid=$!
trap 'kill "$fork_pid" 2>/dev/null || true' EXIT
for attempt in $(seq 1 40); do
  cast chain-id --rpc-url "$fork_rpc" >/dev/null 2>&1 && break
  sleep 1
done
cp ../deployments/11155111.json "$artifact_dir/configured.json"
cp ../deployments/11155111.json "$artifact_dir/manifest.json"
# The local Anvil fork deploys with DEMO_RECEIPT_ATTESTER. The reviewed manifest
# records the real Sepolia attester, so exclude that chain-specific value from
# this disposable local-fork verification manifest. The committed file stays intact.
../.venv/bin/python - "$artifact_dir/manifest.json" <<'PYMANIFEST'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
manifest = json.loads(path.read_text(encoding="utf-8"))
manifest["easAttester"] = None
path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
PYMANIFEST
for run in first repeat; do
  forge script script/Deploy.s.sol:Deploy --rpc-url "$fork_rpc" --private-key "$dev_key" --broadcast
  ETH_RPC_URL="$fork_rpc" ../.venv/bin/python ../infra/scripts/publish_manifest.py \
    --prediction ../deployments/predictions/11155111.json --manifest "$artifact_dir/manifest.json"
  module=$(../.venv/bin/python -c 'import json,sys;print(json.load(open(sys.argv[1]))["module"])' "$artifact_dir/manifest.json")
  cast call "$module" 'payeeStatus(address)(uint8,uint64)' "$DEMO_PAYEE" --rpc-url "$fork_rpc" > "$artifact_dir/payee-$run.txt"
  cp "$artifact_dir/manifest.json" "$artifact_dir/$run.json"
done
cmp "$artifact_dir/payee-first.txt" "$artifact_dir/payee-repeat.txt"
../.venv/bin/python - "$artifact_dir" <<'PY'
import json
import sys
from pathlib import Path
directory = Path(sys.argv[1])
first = json.loads((directory / 'first.json').read_text())
repeat = json.loads((directory / 'repeat.json').read_text())
for field in ('implementation', 'factory', 'module', 'safeT', 'safeO1', 'safeO2',
              'safeSingleton', 'safeProxyFactory', 'multiSend', 'mandateExpiresAt'):
    assert first[field] == repeat[field], field
print('LOCAL Sepolia fork: canonical Safes/module and mandate expiry unchanged on repeat')
PY
nonce=$(cast nonce "$DEMO_OWNER" --rpc-url "$fork_rpc")
export DEMO_OWNER="$DEMO_EXECUTOR"
if forge script script/Deploy.s.sol:Deploy --rpc-url "$fork_rpc" --private-key "$dev_key" --broadcast > "$artifact_dir/wrong-owner.log" 2>&1; then
  echo 'Wrong broadcaster was accepted' >&2
  exit 1
fi
grep -q 'broadcast signer must be DEMO_OWNER' "$artifact_dir/wrong-owner.log"
test "$nonce" = "$(cast nonce 0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266 --rpc-url "$fork_rpc")"
cmp ../deployments/11155111.json "$artifact_dir/configured.json"
echo 'Wrong signer rejected before broadcasting; committed public configuration preserved'
