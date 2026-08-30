# modelctl — 统一模型 Compose 管理(Nvidia-DGX issue #26)

`modelctl` 是覆盖 gb10 / gb10-2 双机的统一模型管理层:一份 `models.yaml` 注册表、
一个 CLI、一个 Web UI。它是**非侵入**的——不改任何既有 Compose 文件,只做登记、
只读发现、预检和受控启停;DeepSeek 这类带自有编排器的模型继续走它的 controller。

## 组成

| 组件 | 位置 | 说明 |
|---|---|---|
| `models.yaml` | `operations/modelctl/models.yaml`(部署到 `gb10:~/modelctl/models.yaml`) | 模型/主机/端口/健康检查/互斥约束的唯一事实源 |
| `modelctl` CLI | `tools/modelctl/`(部署到 `gb10:~/modelctl/tools/modelctl/`) | 只读:`list/status/ports/discover/check/validate`;受控:`start/stop/restart/switch` |
| Web UI | `tools/modelctl/webui.py` + `static/index.html` | CLI 之上的瘦客户端,默认 `:8461` |

## models.yaml 要点

- `hosts`:每台机一个条目;`ssh_target: null` 表示 modelctl 运行所在的本机。
- `models.<name>.hosts`:每主机角色(head/worker/standalone)+ compose 工程与
  config 文件(只读引用,用于状态归因,绝不被改写)。
- `controller`:
  - `type: script` — 外部持久化编排器(DeepSeek 的
    `run-vllm-service.sh`,worker-first/head-second、`active.json`、qwen 回滚
    语义都由它自己维护,modelctl 只做委托);
  - `type: compose` — modelctl 直接按 `start_order` 逐机 `docker compose up -d`
    (停止按 `stop_order` 逆序 `down`);
  - `type: none` + `managed: false` — 仅可见性(报告,不接管)。
- `ports`:声明端口(host/bind/port/protocol),`ports` 命令把它与 `ss -ltnH`
  实听比对——`network_mode: host` 下 `docker ps` 看不到的端口靠这一步补全。
- `conflict_groups`(GPU/统一内存域)+ `conflicts_with`(显式互斥)共同表达
  "谁能和谁同时在线"。
- `protected: true` 的模型(stop/conflict 解决路径涉及它)必须显式
  `--allow-protected`(Web UI 中为输入确认短语 + token)。
- **本文件禁止出现任何凭据**:加载器直接拒绝 `token/password/secret/api_key`
  形态的键。

## CLI

```bash
export MODELCTL_CONFIG=~/modelctl/models.yaml
export MODELCTL_STATE_DIR=~/modelctl/var

modelctl list                    # 全部模型 + 双机状态(运行/部分/停止/降级)
modelctl status glm53-exl3       # 单模型明细(容器、健康)
modelctl ports                   # 声明端口 vs 实听 + 未注册监听(仅报告)
modelctl discover                # 双机 docker compose ls + 未纳管工程
modelctl check glm53-exl3        # 启动预检:端口/互斥/失联/受保护冲突
modelctl validate                # 只校验 models.yaml

modelctl switch glm53-exl3       # 停掉冲突模型 → 按 worker→head 拉起 GLM-5.3
modelctl switch deepseek-v4-flash  # 反向切换(controller 接管,恢复 active.json 语义)
modelctl start qwen36-rollback --allow-protected   # 涉及受保护服务时
modelctl stop glm53-exl3
```

每个命令都支持 `--json`,输出版本化信封:

```json
{"schema_version":1,"tool":"modelctl","command":"check","generated_at":"…",
 "data":{"model":"glm53-exl3","would_conflict":true,"conflicts":[…]}}
```

退出码:`0` 成功 · `2` 用法 · `3` 注册表校验 · `4` 冲突 · `5` 需要确认 ·
`6` 主机失联 · `7` controller 失败 · `8` 锁超时 · `9` 健康等待超时。

每次变更动作写回执 `~/modelctl/var/receipts/<ts>-<action>-<model>.json`
(逐步 argv、退出码、耗时);`~/modelctl/var/audit.log` 记录 Web UI 操作。

## Web UI

```bash
python3 -m tools.modelctl.webui --config ~/modelctl/models.yaml --port 8461
```

- 只读视图:模型卡片(状态灯/主机/端口/健康 + 每容器 CPU/内存占用,来自
  `docker stats --no-stream`,`status --stats` 带出)、注册端口表、未注册监听表;
  自动刷新间隔可调(右上角输入框,**默认 10s**,持久化到浏览器,3–600s)。
- 操作(启动/停止/重启/切换):POST 走异步 job,需
  `Authorization: Bearer <token>`(token 在 `~/modelctl/var/webui-token`,
  首次启动自动生成)并输入 `confirm <model>` 确认短语;涉及受保护服务时前端
  自动带 `allow_protected` 重试。
- 后端只允许白名单命令(`list/status/ports/discover/check` + 四个受控动作),
  无任意 shell;所有请求写审计日志。

## 安全边界(与 issue #26 对应)

1. 不修改既有 Compose 文件;GLM kit 的参数改动只发生在它自己的 `.env`。
2. DeepSeek 只能经 controller 启停;`active.json` / 受保护服务快照 /
   qwen 回滚语义保持原样。
3. 只读命令不改变容器、端口、服务与远端文件。
4. 未注册服务只报告(`ports` 的未注册监听、`discover` 的未纳管工程),不接管。
5. 互斥以显式声明为准(GPU/统一内存域),不依赖 `nvidia-smi` 现猜。
6. 变更动作串行(host-level flock);逐动作出回执,可审计。

## 部署形态(gb10)

```
~/modelctl/
├── models.yaml                  # 本注册表
├── tools/modelctl/…             # 包(与仓库 tools/modelctl 一致)
└── var/{modelctl.lock,receipts/,jobs/,audit.log,webui-token}
~/glm53-exl3-deploy/             # GLM kit(controller: compose 引用的就是它)
~/gb10-ds4/execution/            # DeepSeek(controller: script 引用的就是它)
```

## 测试

`python3 -m unittest discover -s tests -p 'test_modelctl*.py'` —
离线跑(schema/冲突/状态/动作/FakeRunner 固件,覆盖通配绑定、host 网络、
Partial 态、未纳管工程),不需要 docker/ssh/集群。
