# cluster-display-status（ESP32 触摸屏集群仪表盘 · 主机侧）

gb10 head 上的状态端点（`:9108`），供 Waveshare ESP32-S3-Touch-LCD-1.47
（项目库：gb10-2 `~/project/esp32-s3-touch-1.47`，GitHub `johnymoo/ESP32-LCD`）
通过 WiFi 每 2 s 轮询 `/status` 渲染 GB10 集群仪表盘。节点指标来自本机
与 worker 的一次批量 SSH 快照，模型指标来自 vLLM `/metrics`。

## 2026-09-21 变更：模型名改为上游自动发现

- 原实现 `MODEL_NAME = "deepseek-v4-flash-0731"` 硬编码；B12X/NVFP4 栈上线后
  服务名变为 `GLM-5.3-Flash-EXL3`，需要跟着推理栈切换而不再手工改。
- 新实现 `served_model_name(now)`：从 `http://127.0.0.1:8890/v1/models` 自动发现
  第一个 served model id，30 s TTL 进程内缓存；查询失败沿用最后已知名，
  从未成功过则显示 `unavailable`。改动仅 3 处 `"name"` 引用 + 1 个常量块。
- 部署侧备份：gb10 `~/cluster-display-status/cluster_status_server.py.bak-20260921`。

## 运维要点（2026-09-21 固化）

- 单元为 **用户级 systemd**：`~/.config/systemd/user/cluster-display-status.service`
  （gb10，chriswang）。必须 `systemctl --user enable` + `sudo loginctl enable-linger chriswang`
  ——否则服务随最后一个 ssh 会话退出而停止（2026-09-21 07:54 掉线根因）。
- `Restart=on-failure` 已有：9/20 23:17 被 B12X 部署期间的主机 OOM 风暴误杀后自动拉起过。
- 本目录快照 = gb10 `~/cluster-display-status/`（脚本）+ 用户单元文件。更新部署：
  `scp cluster_status_server.py gb10:~/cluster-display-status/ && ssh gb10 systemctl --user restart cluster-display-status`。
- 验证：`curl :9108/health` → `{"ok":true}`；`/status` 的 `model.name` 应等于
  `curl :8890/v1/models` 的 served id。注意该服务 **不打 HTTP 访问日志**，
  判断 ESP32 是否在轮询要用 `tcpdump -nn -i any port 9108`（正常 ~2 s 一连）。
