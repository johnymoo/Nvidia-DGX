# GB10 Operations Reference

- Head `gb10`, worker `gb10-2`; project roots are `/home/chriswang/gb10-ds4`
  and `/home/admin/gb10-ds4`.
- Official Compose is `execution/docker-compose.yml` plus active
  `docker-compose.f277b3d-timeout.yml`; memory-profile override is inactive.
- Qwen Compose is `/home/chriswang/.hermes/profiles/capital-avatar/deployments/qwen36-35b-nvfp4/compose.yml`;
  health is `http://192.168.88.181:8004/v1/models`.
- Unsloth uses its base Compose plus `docker-compose.reasoning-off.yml`.
  Worker RPC is `192.168.192.198:50052`, head RPC `127.0.0.1:50053`, API 8891.
- Capture logs, inspect, and events before stopping a failed service.
