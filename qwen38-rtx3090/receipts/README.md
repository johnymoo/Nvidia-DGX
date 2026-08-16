# Deployment receipt

`deployment-20260815T144804Z.json` 是 2026-08-15 已通过候选验收的脱敏快照。
它由原始 receipt、acceptance JSON、容器 inspect 和 GPU 监控摘要重建；原始证据
包含私有主机路径，因此不进入公开仓库。`source_evidence` 保存原始文件哈希，便于
持有原件的维护者核对。

该 receipt 记录固定权重、投影、镜像和运行参数在一张 RTX 3090 上完成了列出的
验收项。它不证明服务现在在线；候选容器在验收后已停止。公开仓库不包含带私有环境
信息的原始 acceptance、inspect 和 GPU 监控，因此 source hashes 只能由持有原件的
维护者核对。任一 `invalidated_by` 条件发生时必须重新执行 `scripts/accept.sh`，不能
沿用本 receipt。

验证：

```bash
python3 scripts/validate_receipt.py receipts/deployment-20260815T144804Z.json
sha256sum receipts/deployment-20260815T144804Z.json
```
