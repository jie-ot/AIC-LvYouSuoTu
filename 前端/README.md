# 《旅有所图》前端使用说明

前端就是在浏览器中使用的网页，提供注册登录、照片创作、旅行记忆、报告、明信片、行程规划和“发现”等功能。本教程只介绍 Windows 和 Mac 电脑本机使用。

开始前，先按[项目首页](../README.md)安装 **Node.js 24.x LTS 和 pnpm 10.33.3**，再按[后端教程](../后端/README.md)启动后端。浏览器能打开 http://localhost:8000/docs 后，保留后端窗口，新开一个终端窗口准备运行前端。

所有前端命令都要在 **`前端` 文件夹**执行。第一次需要安装依赖、配置连接地址并构建；日常使用只需要启动服务。

## 1. 安装依赖并打开配置文件

在新窗口先进入项目根目录，选择自己电脑对应的一组命令，逐行执行。打开终端和进入目录的方法见[项目首页](../README.md)。

### Windows PowerShell

```powershell
cd 前端
pnpm.cmd install --frozen-lockfile
if (-not (Test-Path -LiteralPath ".env.local")) { Copy-Item -LiteralPath ".env.local.example" -Destination ".env.local" }
notepad .env.local
```

### Mac 终端

```bash
cd 前端
pnpm install --frozen-lockfile
[ -f .env.local ] || cp .env.local.example .env.local
open -e .env.local
```

第一次安装依赖需要联网，等命令执行完再继续。复制配置的命令会保留已有 `.env.local`，最后一行会用文本编辑器打开它。

## 2. 把连接地址改成本机后端

将 `.env.local` 中下面两个配置项设置为以下内容，即使刚复制了模板，也要检查并替换地址：

```env
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api
NEXT_PUBLIC_ASSET_BASE_URL=http://localhost:8000
```

第一行是接口地址，末尾保留 `/api`；第二行是图片等文件的地址，末尾不加 `/api`。它们都连接这台电脑上运行的后端。

按 `Ctrl + S`（Windows）或 `Command + S`（Mac）保存并关闭编辑器。文件名必须为 `.env.local`，不要另存为 `.env.local.txt`。后端 `.env` 中的 `FRONTEND_ORIGINS` 应为 `http://localhost:3000`。

这些地址会在构建时写入网页，所以先完成配置，再执行下一步。之后修改 `.env.local`，也需要重新构建前端。

## 3. 构建并启动网页

仍在 `前端` 文件夹，Windows PowerShell 逐行执行：

```powershell
pnpm.cmd build
pnpm.cmd start
```

Mac 终端逐行执行：

```bash
pnpm build
pnpm start
```

构建可能需要几分钟。只有 `build` 成功完成并返回命令输入位置后，才执行 `start`。本项目把网页构建到 `out/` 文件夹，启动命令会提供这些网页；请使用完整的 `build` 命令，让项目自带的静态文件处理也一并执行。

启动后会显示类似下面的本地地址：

```text
Local: http://localhost:3000
```

保持这个窗口运行，在浏览器地址栏输入 **http://localhost:3000**。现在两个终端窗口都需要保持运行：后端负责数据，前端负责网页。

## 4. 注册、登录和体验演示

首次打开会看到登录页。点击“体验演示账号”，可以查看已有的旅行、照片、人格报告和明信片；该入口为只读，不能上传、生成、修改、删除或保存收藏。

需要使用自己的资料时，切到“注册”，填写用户名、密码和确认密码，再点击“注册并进入”。用户名为 2–24 个字符，支持中文、字母、数字、下划线和短横线；密码为 8–128 个字符。注册成功后会直接进入应用，新账号的旅行资料从空白开始，之后可以上传照片、生成内容并保存自己的旅行记录。

以后切到“登录”，使用注册时的用户名和密码进入。页面顶部账号菜单会显示当前用户名和只读状态，可选择“退出登录 / 切换账号”。退出不会删除已保存的资料，未保存的行程草稿会清除。

维护原演示资料时，用 `demo` 和维护密码在普通“登录”中进入。维护密码是在后端首次初始化时设置的，详见[后端账号说明](../后端/README.md)。各个人账号资料独立，主动发布到“发现”的笔记可以共享浏览。

注册、登录和浏览已有演示资料不需要 AI Key。照片分析、报告、明信片和规划等 AI 功能需要[后端配置对应的 Key](../后端/README.md)；注册用户共用后端服务配置。生成时按页面提示等待，完成后再查看或保存结果。

## 5. 日常启动和修改后的操作

下次使用时，先启动后端，再在 `前端` 文件夹执行 `pnpm.cmd start`（Windows）或 `pnpm start`（Mac），然后打开 http://localhost:3000。已经构建过且代码和配置没有变化时，无需重新安装或构建。

停止前端时，在运行前端的窗口按 `Ctrl + C`。修改前端代码或 `.env.local` 后，先停止前端，再执行：

Windows PowerShell：

```powershell
pnpm.cmd build
pnpm.cmd start
```

Mac 终端：

```bash
pnpm build
pnpm start
```

更新项目代码后，先重新执行 `pnpm.cmd install --frozen-lockfile`（Windows）或 `pnpm install --frozen-lockfile`（Mac），再构建、启动。修改后端 `.env` 只需要重启后端；修改前端 `.env.local` 则需要重新构建前端。

## 常见问题

| 现象 | 处理方法 |
| --- | --- |
| 找不到 `pnpm` 或 `pnpm.cmd` | 按[项目首页](../README.md)安装 pnpm 10.33.3，重新打开终端后检查版本 |
| Windows 提示 `pnpm.ps1` 无法加载或禁止运行脚本 | 使用教程中的 `pnpm.cmd`，例如 `pnpm.cmd start` |
| 找不到 `package.json` | 当前目录应是 `前端`；Windows 用 `Get-Location`、Mac 用 `pwd` 查看位置 |
| 下载依赖失败 | 检查网络后重新执行对应系统的 `install --frozen-lockfile` 命令 |
| 构建提示 Node.js 版本不支持 | 用 `node --version` 检查，按项目首页安装 Node.js 24.x LTS，然后重新打开终端 |
| 提示没有 `out/` 文件夹，或网页打不开 | 先执行并成功完成 `build`，再执行 `start`；确认前端终端仍在运行 |
| 启动显示其他端口，或提示 `3000` 被占用 | 先检查 http://localhost:3000 是否已有前端运行；需要重启时，在原窗口按 `Ctrl + C` 后再启动，保持教程中的 `3000` 端口 |
| 页面能打开，但登录失败、加载不了资料或图片 | 先检查 http://localhost:8000/docs 能否打开；确认 `.env.local` 的两行本机地址正确，修改后重新构建，并检查后端允许的前端地址 |
| 注册成功，但没有原来的旅行资料 | 新账号从空白旅行资料开始；查看现有演示资料时切换到“体验演示账号” |
| 演示账号无法生成或保存 | 只读演示的正常权限，需要使用自己的账号，或用维护密码登录 `demo` |
