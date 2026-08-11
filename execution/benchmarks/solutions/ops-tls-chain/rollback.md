1. Verify the staged bundle with `./bin/verify-chain ./runtime/tls/edge-chain.pem`.
2. Replace `./runtime/tls/current` only after that local verification succeeds.
3. On verification failure, restore `./runtime/tls/previous` as the local current bundle and record the failed check.
