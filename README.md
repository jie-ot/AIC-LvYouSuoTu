# 旅有所图

《旅有所图》是一款旅行 AI 应用。上传旅行照片后，可以整理旅行记录、生成旅行人格报告和明信片，结合旅行记忆规划下一次行程，也可以在“发现”中浏览、分享旅行笔记。支持用户名和密码注册、登录，现有旅行资料保留在演示账号中。

本教程介绍 **Windows 和 Mac 电脑的网页端**。第一次使用按“准备环境 → 启动后端 → 启动前端”的顺序操作；以后直接看下面的“下次怎么启动”。

## 1. 找到项目文件夹

如果从 GitHub 下载，在仓库页面点击 **Code → Download ZIP**，下载后先解压。打开同时包含下面三个项目的文件夹，这就是本教程说的“项目根目录”：

```text
README.md
前端/
后端/
```

前端负责显示网页，后端负责账号、数据和 AI 功能，两者都要运行。你需要保留两个终端窗口：窗口 A 运行后端，窗口 B 运行前端。

| 要打开什么 | 浏览器地址 | 说明 |
| --- | --- | --- |
| 使用应用 | http://localhost:3000 | 注册、登录和使用各项功能 |
| 检查后端 | http://localhost:8000/docs | 能看到接口文档页面，说明后端已启动 |

## 2. 安装运行工具（只需一次）

需要安装 Node.js、pnpm 和 uv。Node.js 用于运行前端，pnpm 用于安装前端依赖，uv 用于安装后端依赖和管理 Python。Python 3.11 会由 uv 自动准备，无需单独安装；数据库使用 SQLite，也无需另装数据库软件。

### Windows

先打开 [Node.js 下载页](https://nodejs.org/en/download)，选择 **24.x LTS** 和 **Windows Installer（.msi）**，下载后双击安装，保持默认选项即可。

安装完成后，从开始菜单打开 **Windows PowerShell**。依次执行下面两行，每行粘贴后按回车，等这一行执行完再执行下一行：

```powershell
npm.cmd install --global pnpm@10.33.3
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

关闭这个窗口，重新打开 PowerShell，检查安装结果：

```powershell
node --version
pnpm.cmd --version
uv --version
```

三行都显示版本号就可以继续。Windows 教程统一使用 `npm.cmd`、`pnpm.cmd`，可避免 PowerShell 提示“禁止运行脚本”。

### Mac

先打开 [Node.js 下载页](https://nodejs.org/en/download)，选择 **24.x LTS** 和 **macOS Installer（.pkg）**，下载后双击安装，按提示完成即可。

按 `Command + 空格`，输入“终端”并打开。依次执行下面两行，每行粘贴后按回车，等这一行执行完再执行下一行：

```bash
curl -fsSL https://get.pnpm.io/install.sh | env PNPM_VERSION=10.33.3 sh -
curl -LsSf https://astral.sh/uv/install.sh | sh
```

退出终端应用后重新打开，检查安装结果：

```bash
node --version
pnpm --version
uv --version
```

三行都显示版本号就可以继续。如果仍提示找不到命令，按安装结束时显示的提示刷新终端环境后再试。

安装方法来自 [pnpm 官方说明](https://pnpm.io/10.x/installation)和 [uv 官方说明](https://docs.astral.sh/uv/getting-started/installation/)。本教程固定使用 pnpm 10.33.3，与项目现有依赖文件配套。

## 3. 首次启动：先后端，再前端

先在项目根目录打开终端窗口 A。Windows 可以在资源管理器进入项目文件夹，点击顶部地址栏，输入 `powershell` 后按回车。Mac 可以打开“终端”，输入 `cd` 和一个空格，再把项目文件夹从 Finder 拖进终端，按回车。

按[后端教程](后端/README.md)完成安装依赖、填写配置、更新数据库和启动服务。看到 `Application startup complete` 后保留窗口 A，再打开一个终端窗口 B，同样先进入项目根目录，按[前端教程](前端/README.md)安装、配置和启动网页。

命令块中的命令逐行执行；遇到报错时先按对应教程的“常见问题”处理，再继续下一步。第一次下载依赖和构建网页可能需要几分钟，等待完成即可。服务启动后终端会一直显示运行日志，这是正常的，不要关闭窗口。

注册、登录和浏览已有演示资料可以先不填 API Key。照片分析、AI 报告、明信片生成和行程规划需要在 `后端/.env` 填写对应服务的有效 Key，详见[后端配置说明](后端/README.md)。这些 Key 由后端统一使用，所有账号共用这份服务配置。

## 4. 打开网页并使用

在浏览器地址栏输入 **http://localhost:3000**。首次打开会看到登录页：

| 使用方式 | 操作 | 权限和资料 |
| --- | --- | --- |
| 浏览现有演示资料 | 点击“体验演示账号” | 只读，可以查看已有旅行、照片、报告和明信片 |
| 使用自己的账号 | 点击“注册”，填写用户名和密码，再点“注册并进入” | 新账号的旅行资料从空白开始，可以上传、生成、保存和管理自己的内容 |
| 维护演示资料 | 在“登录”中输入 `demo` 和维护密码 | 可以管理演示账号的资料；密码由后端首次初始化时设置 |

用户名为 2–24 个字符，支持中文、字母、数字、下划线和短横线；密码为 8–128 个字符。注册后会直接登录，以后使用同一组用户名和密码进入。需要换账号时，点击页面顶部的账号菜单，选择“退出登录 / 切换账号”。

浏览演示资料可以先了解功能。使用自己的账号时，可以上传旅行照片、创建旅行记录，再体验报告、明信片和行程规划。新账号没有原演示账号的私人资料；主动发布到“发现”的笔记可以共享浏览。

## 5. 下次怎么启动

首次安装、配置和构建成功后，日常启动只需以下命令。每个窗口都先进入项目根目录。

窗口 A 启动后端，Windows 和 Mac 使用相同命令：

```bash
cd 后端
uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000
```

窗口 B 启动前端，Windows PowerShell 执行：

```powershell
cd 前端
pnpm start
```

Mac 终端执行：

```bash
cd 前端
pnpm start
```

然后访问 http://localhost:3000。停止服务时，分别在两个窗口中按 `Ctrl + C`；关闭浏览器不会停止服务。电脑重启后，需要重新启动这两个服务。

修改后端 `.env` 后重启后端；修改前端 `.env.local` 或前端代码后，需要重新构建，操作见[前端教程](前端/README.md)。更新项目代码后，应重新检查依赖并执行数据库迁移，操作见[后端教程](后端/README.md)。已有服务正在运行时先使用它，不要重复启动占用同一端口。

## 数据保存在哪里

旅行数据保存在 `后端/data/lvyousuotu.db`，账号及登录信息保存在 `后端/data/auth.db`，照片和生成文件保存在 `后端/static/`。关闭网页或正常停止服务不会删除已保存的资料。需要备份时，先停止服务，再一起复制这两个数据库和 `static/` 文件夹；不要删除数据库来解决启动问题。

API Key 保存在本机的 `后端/.env`，前端连接地址保存在 `前端/.env.local`。保留已有配置，真实密钥、账号库和私人资料不要上传到公开仓库。项目使用 Next.js、React、TypeScript、FastAPI、SQLModel、Alembic 和 SQLite。
