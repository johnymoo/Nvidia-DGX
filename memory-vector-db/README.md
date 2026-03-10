# Memory Vector DB Service

多用户记忆向量数据库服务，支持语义搜索和用户数据隔离。

## 目的

为 OpenClaw 实例提供集中式的记忆存储和检索服务，支持多用户数据隔离。

---

## 🔑 API Key 与用户管理

### 如何创建新用户？

**无需注册！**API Key 就是用户标识符，首次使用自动创建。

### 使用步骤：

1. **选择一个唯一的用户标识符**（如`alice`、`claw_laptop`、`office_instance`）
2. **在请求中带上 `X-API-Key` header**
3. **系统自动为你创建独立的数据空间**

### API Key 规则：

| 规则 | 说明 |
|------|------|
| 格式 | 字母、数字、下划线、短横线 |
| 长度 | 最长 64 字符 |
| 认证 | 无密码，身份即认证 |

### 示例：创建新用户并添加第一条记忆

```bash
# 用户 "alice" 的第一次请求 - 自动创建用户
curl -X POST http://YOUR_GB10_IP:8000/memories/add \
  -H "X-API-Key: alice"\
  -H "Content-Type: application/json" \
  -d '{"summary": "Alice 的第一条记忆", "type": "note"}'

# 用户 "bob" 使用不同的 key - 数据完全隔离
curl -X POST http://YOUR_GB10_IP:8000/memories/add \
  -H "X-API-Key: bob" \
  -H "Content-Type: application/json" \
  -d '{"summary": "Bob 的第一条记忆", "type": "note"}'
```

### 多个 Claw 实例如何使用？

```bash
# Claw 实例 1
-H "X-API-Key: claw_laptop"

# Claw 实例 2
-H "X-API-Key: claw_office"

# Claw 实例 3
-H "X-API-Key: claw_mobile"
```

每个实例使用不同的 API Key，数据自动隔离。

---

## 上下文

- 部署在 GB10 服务器上
- 使用 Ollama + bge-m3 进行文本嵌入
- 使用 SQLite + sqlite-vec 进行向量存储和检索

## 架构

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  OpenClaw A     │     │  OpenClaw B     │     │  OpenClaw C     │
│  (X-API-Key: A) │     │  (X-API-Key: B) │     │  (X-API-Key: C) │
└────────┬────────┘     └────────┬────────┘     └────────┬────────┘
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 │
                                 ▼
                    ┌────────────────────────┐
                    │  Memory API Server     │
                    │  (FastAPI + uvicorn)   │
                    │  http://0.0.0.0:8000   │
                    └───────────┬────────────┘
                                │
                    ┌───────────┼───────────┐
                    │           │           │
                    ▼           ▼           ▼
              ┌──────────┐ ┌──────────┐ ┌──────────┐
              │ Ollama   │ │ SQLite   │ │ sqlite-  │
              │ bge-m3   │ │Database  │ │ vec      │
              └──────────┘ └──────────┘ └──────────┘
```

## 文件清单

| 文件 | 描述 |
|------|------|
| `memory_api_server.py` | FastAPI 服务主程序 |
| `.gitignore` | Git 忽略规则 |
| `README.md` | 本文档 |

## 安装步骤

### 1. 安装 Ollama

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull bge-m3
```

### 2. 安装 Python 依赖

```bash
pip install fastapi uvicorn numpy sqlite-vec
```

### 3. 编译 sqlite-vec (ARM64)

PyPI 上的 sqlite-vec wheel 包含 32-bit ARM 二进制，需要从源码编译：

```bash
sudo apt-get install -y libsqlite3-dev
git clone https://github.com/asg017/sqlite-vec.git
cd sqlite-vec
make loadable
cp dist/vec0.so ~/.local/lib/python3.12/site-packages/sqlite_vec/
```

### 4. 启动服务

```bash
python3 memory_api_server.py --host 0.0.0.0 --port 8000
```

## 配置

支持以下环境变量：

| 环境变量 | 默认值 | 描述 |
|----------|--------|------|
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama 服务地址 |
| `OLLAMA_MODEL` | `bge-m3` | 嵌入模型（注意：需与 EMBEDDING_DIM 兼容） |

**注意：** 修改 `OLLAMA_MODEL` 需确保新模型的 embedding 维度与数据库 schema 兼容（默认 1024）。

## 使用说明

### 健康检查

```bash
curl http://localhost:8000/health
```

### 添加记忆

```bash
curl -X POST http://localhost:8000/memories/add \
  -H "X-API-Key: your_user_id" \
  -H "Content-Type: application/json" \
  -d '{"summary": "测试记忆", "type": "note", "tags": ["test"]}'
```

### 搜索记忆

```bash
curl -X POST http://localhost:8000/search \
  -H "X-API-Key: your_user_id" \
  -H "Content-Type: application/json" \
  -d '{"query": "测试"}'
```

### 获取最近记忆

```bash
curl -H "X-API-Key: your_user_id" \
  http://localhost:8000/memories/recent?days=7&limit=20
```

### 用户统计

```bash
curl -H "X-API-Key: your_user_id" \
  http://localhost:8000/user/stats
```

### 删除所有记忆

```bash
curl -X DELETE -H "X-API-Key: your_user_id" \
  http://localhost:8000/memories/all
```

## API 端点

| 端点 | 方法 | 认证 | 描述 |
|------|------|------|------|
| `/health` | GET | 不需要 | 健康检查 |
| `/embed` | POST | X-API-Key | 获取文本嵌入向量 |
| `/search` | POST | X-API-Key | 语义搜索 |
| `/memories/add` | POST | X-API-Key | 添加记忆 |
| `/memories/recent` | GET | X-API-Key | 获取最近记忆 |
| `/memories/all` | DELETE | X-API-Key | 删除用户所有记忆 |
| `/user/stats` | GET | X-API-Key | 用户统计 |

## 依赖

- Python 3.12+
- Ollama (bge-m3 模型)
- FastAPI, uvicorn
- sqlite-vec

## 已知限制

- **⚠️ API Key 安全性**：当前设计中 `X-API-Key` 即 `user_id`，任何能访问服务的客户端都可以冒充其他用户。此设计仅适用于受信任的内部网络。生产环境需添加真正的认证层。
- 暂不支持记忆更新操作
- 向量维度固定为 1024 (bge-m3)

## 部署信息

- **服务器**: GB10 (DGX Spark)
- **部署日期**: 2026-03-10
- **服务地址**: `http://<GB10_IP>:8000`