# X570 OPF Memory Operations

Status: active on 2026-08-12 (Asia/Shanghai)

## Current State

- Host: `x570` (`192.168.88.75`)
- Privacy Filter: user service `privacy-filter.service`, port `8765`
- Repository: `/home/chriswang/project/docker/privacy-filter-service`
- Active commit: `99106fe6b087e80b92c2366adb8261ecc7dd01d5`
- VoxCPM2: stopped; port `8808` closed
- Measured OPF residency after 198,000-character input: 3,490 MiB
- Measured GPU free memory after acceptance: 20,558 MiB

## Status

```bash
ssh x570 'systemctl --user is-active privacy-filter.service'
ssh x570 'curl -fsS http://127.0.0.1:8765/health'
ssh x570 'curl -fsS http://127.0.0.1:8765/model-info'
ssh x570 'nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader,nounits'
ssh x570 'ss -ltnp sport = :8765; ss -ltnp sport = :8808'
```

## Restart

```bash
ssh x570 'systemctl --user restart privacy-filter.service'
ssh x570 'curl -fsS --retry 60 --retry-delay 1 --retry-connrefused http://127.0.0.1:8765/health'
```

## Rollback OPF Patch

The previous production identity was
`741cdc27c056f4618d88600386b3e75058f99859`. Preserve evidence before
rollback, then revert the single deployed commit and restart:

```bash
ssh x570 'cd /home/chriswang/project/docker/privacy-filter-service && git revert --no-edit 99106fe6b087e80b92c2366adb8261ecc7dd01d5'
ssh x570 'systemctl --user restart privacy-filter.service'
ssh x570 'curl -fsS --retry 60 --retry-delay 1 --retry-connrefused http://127.0.0.1:8765/health'
```

Do not restore VoxCPM2 as part of an OPF rollback unless its GPU allocation is
also intended. Its captured start command was:

```bash
ssh x570 'cd /home/chriswang/project/Shili/workspace/boxcpm && nohup bash start_webui.sh > voxcpm2.log 2>&1 &'
```

After restoring VoxCPM2, verify `:8808`, `:8765`, and GPU free memory. Do not
admit a vision model solely from the current idle-memory reading; measure
simultaneous peak and post-soak memory with production OPF active.
