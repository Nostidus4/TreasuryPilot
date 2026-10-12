# Deployment manifests

`chains.json` is the platform chain configuration. Each enabled chain must provide
at least two distinct RPC URLs and has a matching `<chainId>.json` manifest.

```json
{
  "chains": [
    {
      "chainId": 11155111,
      "name": "Ethereum Sepolia",
      "isTestnet": true,
      "confirmations": 3,
      "explorerUrl": "https://sepolia.etherscan.io",
      "rpcUrls": ["https://rpc-one.example", "https://rpc-two.example"],
      "enabled": true
    }
  ]
}
```

Deployment scripts write reviewed `<chainId>.json` manifests using this shape:

```json
{
  "chainId": 11155111,
  "deployments": {
    "TREASURY_MODULE_IMPLEMENTATION": {
      "address": "0x1111111111111111111111111111111111111111",
      "codeHash": "0x1111111111111111111111111111111111111111111111111111111111111111",
      "version": "1.0.0"
    }
  }
}
```

The module implementation is mandatory. Every deployment address and code hash
must be a non-zero 20-byte and 32-byte hexadecimal value, respectively. Never
place private keys, authenticated RPC URLs, or other credentials in these files.

The API reads these paths from `TP_PLATFORM_CHAIN_CONFIG_PATH` and
`TP_DEPLOYMENTS_DIR`; both default to this directory.
