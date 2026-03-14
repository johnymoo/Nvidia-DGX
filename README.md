# Nvidia-DGX

NVIDIA DGX 相关项目集合，包括 DGX Spark (GB10) 部署指南、模型推理优化和系统配置。

---

## 项目目录

| 目录 | 描述 |
|------|------|
| [`qwen35-dgx-spark/`](./qwen35-dgx-spark/) | Qwen3.5 在 DGX Spark 上的部署指南与性能测试 |
| [`nemotron-120b-dgx-spark/`](./nemotron-120b-dgx-spark/) | Nemotron-3-Super-120B 在 DGX Spark 上的部署指南与 Web 界面 |

---

## 仓库贡献规则

### Rule 1: 阅读 README 首先
在修改前阅读整个 README 和子目录的 README。

### Rule 2: 不要在根目录提交项目实现文件
根目录只放公共元数据文件（如 `README.md`、`LICENSE`、`.gitignore`、全局配置等）；所有具体项目代码、脚本、数据等必须放在子目录中。

### Rule 3: 不要提交凭证或私有配置
- 密码、API Token、密钥
- 与具体环境相关或私有的硬编码 IP 地址或主机名（例如内网 IP、生产服务域名）。文档示例中使用的 `127.0.0.1` / `localhost` / `0.0.0.0` 等本地地址除外。
- 使用环境变量或 `.env` 文件管理机密配置

### Rule 4: 每个项目必须有 README
包含：目的、上下文、架构、文件清单、安装步骤、配置、使用说明、依赖、已知限制。

### Rule 5: 分支和 PR Workflow
- 从 main 创建分支：`feature/<描述>`、`fix/<描述>`、`docs/<描述>`、`chore/<描述>`
- 提交清晰的原子提交
- 通过 Pull Request 合并到 main

### Rule 6: Python 项目优先使用 uv
优先使用 `uv` 进行依赖管理，已有使用 `pip` 的项目可在合适时机逐步迁移。

### Rule 7: 保持 .gitignore 更新
确保 `.gitignore` 与项目实际情况保持一致，例如忽略环境配置、虚拟环境目录、缓存、日志和构建产物等。

### Rule 8: 提交规范
- 原子提交
- 不提交大文件（模型权重、视频等）
- 不提交可生成的文件

### Rule 9: 提交前测试
- 运行测试
- 验证脚本在目标平台可运行

### Rule 10: Issue 驱动的开发
新功能先创建 Issue，包含：动机、设计、范围、文件变更、验收标准。

### Rule 11: 文档变更
修改时同步更新项目 README；如在本项目中新增或调整规则，请确保根 README 中的贡献规则保持为唯一可信来源。

---

## 快速开始

```bash
# 查看可用项目
ls -la */

# 进入项目目录
cd qwen35-dgx-spark/
cat README.md
```

## 系统要求

- NVIDIA DGX Spark (GB10) 或兼容设备
- CUDA 12.1+
- Docker (用户需在 docker 组)
