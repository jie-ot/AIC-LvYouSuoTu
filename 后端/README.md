# 《旅有所图》后端使用说明

后端负责注册登录、保存旅行资料、照片分析、报告与明信片生成、行程规划。请先按[项目首页的“安装运行工具”](../README.md)安装 uv 和 Node.js；本教程使用 Python 3.11，由 uv 自动准备，数据库无需另外安装。

以下操作只针对 Windows 和 Mac 电脑本机使用。所有后端命令都要在 **`后端` 文件夹**执行，服务运行时保留这个终端窗口。

## 1. 安装依赖并打开配置文件

从项目根目录打开终端，选择自己电脑对应的一组命令，逐行执行。如果不清楚怎么打开终端或进入项目目录，先看[项目首页](../README.md)。

### Windows PowerShell

```powershell
cd 后端
uv sync --locked --python 3.11
if (-not (Test-Path -LiteralPath ".env")) { Copy-Item -LiteralPath ".env.example" -Destination ".env" }
notepad .env
```

### Mac 终端

```bash
cd 后端
uv sync --locked --python 3.11
[ -f .env ] || cp .env.example .env
open -e .env
```

第一次安装会下载 Python 和依赖，需要联网并等待完成。复制配置的命令只在 `.env` 不存在时创建文件，已有配置会保留。最后一行会打开配置文件，Windows 使用记事本，Mac 使用文本编辑。

## 2. 填写配置并保存

`.env` 是普通文本文件，每行格式是 `配置名称=配置值`。修改等号右侧的内容，保留其他配置。电脑本机访问时，确认这一行是：

```env
FRONTEND_ORIGINS=http://localhost:3000
```

API Key 就是外部 AI 或旅行信息服务的访问密钥，可以向项目维护者获取当前可用配置，或填写自己在对应服务中申请的 Key：

| 配置项 | 对应功能 | 填写要求 |
| --- | --- | --- |
| `ARK_PLAN_API_KEY` | 照片分析、人格报告、明信片创意和图片生成 | 使用火山方舟 Agent Plan 对应的有效 Key |
| `DEEPSEEK_API_KEY` | AI 行程规划 | 使用 DeepSeek 的有效 Key |
| `AMAP_API_KEY` | 地点、地图和路线等旅行信息查询 | 需要对应查询功能时填写 |
| `VARIFLIGHT_API_KEY` | 航班、铁路和空铁联运等信息查询 | 需要对应查询功能时填写 |

如果只是先试注册、登录和浏览已有演示资料，可以保持 Key 为空。使用 AI 功能时，需要对应的 Key 有效，并且有模板中所配置模型或服务的调用权限。所有账号共用后端这份 Key 配置，注册用户无需各自填写。

如果希望用密码登录 `demo` 并维护原演示资料，在**首次启动后端前**将 `AUTH_DEMO_PASSWORD=` 的等号右侧填上自己设置的 8–128 位密码，并记住它。留空也可以使用只读演示入口，但会生成无法公开获取的随机维护密码。账号建立后，再改 `.env` 中这一项不会修改已有账号密码；已有账号的维护密码应向初始化项目的人获取。

其余项目先保持模板默认值，包括数据库路径、模型名称和服务地址。按 `Ctrl + S`（Windows）或 `Command + S`（Mac）保存，关闭编辑器，回到原终端。文件名必须是 `.env`，不要另存为 `.env.txt`；真实 Key 只放在本机 `.env`，不要写入 `.env.example` 或上传公开仓库。

## 3. 更新数据库并启动后端

仍在 `后端` 文件夹，Windows 和 Mac 都逐行执行：

```bash
uv run --locked alembic upgrade head
uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000
```

第一行是数据库迁移，用来补齐当前版本需要的数据表，已有旅行资料会保留。只有第一行成功完成后，才执行第二行启动服务。账号数据库会在后端启动时自动初始化，无需另外创建账号表。

看到类似下面的输出，说明服务已启动：

```text
Uvicorn running on http://127.0.0.1:8000
Application startup complete.
```

浏览器打开 **http://localhost:8000/docs**，能看到接口文档页面即可。直接打开 `http://localhost:8000` 可能显示 `Not Found`，请使用带 `/docs` 的地址检查。

保持当前窗口运行，新开另一个终端窗口，按[前端教程](../前端/README.md)启动网页。后端窗口不再返回命令输入位置是正常的；不要在这个窗口继续输入前端命令。

## 4. 日常启动、停止和更新

下次使用时，在 `后端` 文件夹直接执行：

```bash
uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000
```

停止后端时在这个窗口按 `Ctrl + C`。修改 `.env` 后，要停止并重新启动后端，配置才会生效。

更新项目代码后，先停止后端，再在 `后端` 文件夹依次执行：

```bash
uv sync --locked --python 3.11
uv run --locked alembic upgrade head
uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## 账号和数据怎么保存

用户在网页注册后，自己的旅行、照片、记忆、报告、明信片、行程和收藏独立保存。已有旅行资料沿用 `DEFAULT_USER_ID=demo_user_001`，默认归 `demo` 演示账号；原有演示笔记及作者标记保留，用户主动发布的发现笔记可以共享浏览。

| 登录方式 | 权限 |
| --- | --- |
| 点击“体验演示账号” | 只读；可以查看已有资料，不能上传、生成、修改、删除、收藏或发布 |
| 输入 `demo` 和维护密码登录 | 可以维护演示账号自己的资料 |
| 注册并登录个人账号 | 可以管理自己的资料，不能修改其他用户的私人资料 |

`AUTH_DEMO_USERNAME` 默认为 `demo`。将 `AUTH_DEMO_LOGIN_ENABLED=false` 可关闭公开体验入口，密码登录仍然有效。用户名英文字母不区分大小写，密码保存为 Argon2 哈希，登录有效期默认 30 天；退出后对应的登录和私有图片访问凭证失效。

| 路径（相对于 `后端` 文件夹） | 内容 |
| --- | --- |
| `data/lvyousuotu.db` | 旅行、照片记录、报告、明信片、记忆、行程等业务数据 |
| `data/auth.db` | 注册账号、密码哈希和登录会话，首次启动自动创建 |
| `static/` | 上传的照片、生成图片等实际文件 |
| `.env` | 本机 API Key 和后端配置 |

备份或迁移整套应用时，先停止前后端，再一起复制两个数据库和 `static/`，另外安全保留 `.env`。账号库、真实密钥和私人资料不应随公开演示资料分享。已有旅行库备份可放在 `data/backups/`；不要删除数据库来绕过迁移或重置密码。

## 常见问题

| 现象 | 处理方法 |
| --- | --- |
| 提示找不到 `uv` | 按[项目首页](../README.md)安装后重新打开终端，用 `uv --version` 检查 |
| 提示找不到 `pyproject.toml` 或无法导入 `app` | 当前目录应是 `后端`；Windows 用 `Get-Location`、Mac 用 `pwd` 查看位置 |
| 安装过程中下载失败 | 检查网络后重新执行 `uv sync --locked --python 3.11` |
| 出现 `no such table` 或 `no such column` | 先停止后端，在 `后端` 文件夹执行 `uv run --locked alembic upgrade head`，成功后再启动 |
| 提示端口被占用、`address already in use` 或 Windows 错误 `10048` | 可能已有后端运行；先打开 `/docs` 检查。需要重启时，在原运行窗口按 `Ctrl + C`，再启动 |
| 网页能打开，但登录或请求失败 | 先确认 `/docs` 能打开；检查后端 `FRONTEND_ORIGINS` 是否为 `http://localhost:3000`，保存后重启，并核对[前端连接配置](../前端/README.md) |
| AI 功能报错、超时或提示 Key 未配置 | 检查对应 Key、模型调用权限和网络，修改 `.env` 后重启；外部服务出错时可查看这个终端的错误日志 |
| 演示账号提示只读 | 公开体验入口的正常权限；需要编辑时注册个人账号，维护原演示资料时用 `demo` 和维护密码登录 |
