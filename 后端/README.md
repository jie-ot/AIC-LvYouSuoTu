# 《旅有所图》后端使用说明

后端基于 FastAPI，负责照片理解、旅行记忆、旅行人格报告、明信片生成和个性化行程规划。运行环境支持 Windows 和 macOS。

## 环境要求

- Python 3.11 或更高版本（由 `uv` 管理）
- `uv`
- Node.js 20.9 或更高版本（铁路查询工具需要 `node`/`npx`）

安装 `uv` 后，在本目录执行：

```bash
uv sync
```

## 配置环境变量

首次运行时复制配置模板：

```bash
cp .env.example .env
```

Windows PowerShell 可执行：

```powershell
Copy-Item .env.example .env
```

然后在 `.env` 中填写实际 API Key。主要配置包括：

- `ARK_PLAN_API_KEY`：照片理解、报告、明信片创意等文本任务
- `ARK_IMAGE_API_KEY`：Seedream 图片生成
- `DEEPSEEK_API_KEY`：旅行规划
- `AMAP_API_KEY`、`QWEATHER_API_KEY`、`VARIFLIGHT_API_KEY`：对应旅行信息工具（按需填写）
- `FRONTEND_ORIGINS`：允许访问后端的前端地址；手机访问时追加 `http://电脑局域网IP:3000`

真实 `.env` 只保存在本机，不要提交到 Git；`.env.example` 只用于说明配置项。

## 启动后端

在 `后端` 目录执行数据库迁移，再启动服务：

```bash
uv run alembic upgrade head
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

启动成功后，后端地址为 `http://localhost:8000`，接口文档为 `http://localhost:8000/docs`。保持该终端运行，再按照[前端使用说明](../前端/README.md)启动前端。停止服务时按 `Ctrl+C`。

每次拉取包含新数据库迁移的代码后，都应先执行 `uv run alembic upgrade head`；不要通过删除数据库来绕过迁移。

## 手机访问

手机和电脑连接同一个局域网。在电脑上查询局域网 IPv4 地址，将 `.env` 中的 `FRONTEND_ORIGINS` 设置为类似下面的内容：

```env
FRONTEND_ORIGINS=http://localhost:3000,http://192.168.10.222:3000
```

把示例 IP 换成电脑当前联网网卡的实际地址，并重启后端。还需要确认防火墙允许 `8000` 端口通过。

## 常见问题

如果出现 `no such table` 或 `no such column`，先停止服务并执行 `uv run alembic upgrade head`。如果手机能打开前端但请求失败，检查手机与电脑是否在同一局域网、后端是否使用 `--host 0.0.0.0`，以及 `FRONTEND_ORIGINS` 是否包含手机访问的前端地址。

本项目是单用户比赛演示版本，不包含生产级身份系统、私有对象存储和分布式任务队列；模型生成和旅行信息查询依赖外部服务及其 API Key。
