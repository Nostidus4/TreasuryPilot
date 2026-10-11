# Runtime infrastructure

The local Docker Compose stack runs PostgreSQL 16, Redis 7, MinIO, Anvil, the API, core/AI workers, Celery beat, the internal signer and the Vite production build.

```bash
cp infra/env/.env.example infra/env/.env
# Add optional provider keys when the matching feature needs them.
make dev
make smoke
make down
```

The fixed Anvil mnemonic and chain id `31337` are public test fixtures. Never send real assets to the generated addresses. The `worker-ai` service receives neither signer credentials nor policy-attestation keys.
