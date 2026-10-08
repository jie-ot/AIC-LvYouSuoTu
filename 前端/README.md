# 《旅有所图》前端使用说明

前端是基于 Next.js 的旅行助手界面，提供照片创作、旅行记忆、旅行人格报告、明信片和个性化行程规划功能。请先按照[后端使用说明](../后端/README.md)启动后端。

## 1. 准备环境

前端需要 Node.js 20.9.0 或更高版本和 pnpm。检查环境：

```bash
node --version
corepack enable
pnpm --version
```

如果尚未安装 Node.js，请从 [Node.js 官网](https://nodejs.org/) 安装当前 LTS 版本。Windows 选择 `.msi`，macOS 选择 `.pkg`。

## 2. 配置后端地址

在本目录复制配置模板：

```powershell
Copy-Item .env.local.example .env.local
```

macOS 或 Linux 可执行：

```bash
cp .env.local.example .env.local
```

电脑本机访问时，将 `.env.local` 设置为：

```env
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api
NEXT_PUBLIC_ASSET_BASE_URL=http://localhost:8000
```

如果手机访问，将两个配置中的 `localhost` 都替换为运行后端电脑的局域网 IPv4 地址，并保留 `8000` 端口：

```env
NEXT_PUBLIC_API_BASE_URL=http://192.168.10.222:8000/api
NEXT_PUBLIC_ASSET_BASE_URL=http://192.168.10.222:8000
```

手机和电脑必须连接同一个局域网；实际 IP 以电脑当前联网网卡为准。环境变量会在构建时写入前端，修改 `.env.local` 后必须重新执行 `pnpm build`。

需要手机访问时，Windows PowerShell 可使用下面的命令查询局域网 IPv4：

```powershell
$socket = New-Object Net.Sockets.UdpClient; $socket.Connect('8.8.8.8', 53); $socket.Client.LocalEndPoint.Address.IPAddressToString; $socket.Dispose()
```

macOS 可执行：

```bash
ipconfig getifaddr "$(route -n get default | awk '/interface:/{print $2}')"
```

## 3. 安装依赖并启动前端

在前端项目根目录执行：

```bash
pnpm install --frozen-lockfile
pnpm build
pnpm start
```

看到本地访问地址后保持终端运行。修改 `.env.local` 或前端代码后，先按 `Ctrl+C` 停止服务，再重新执行 `pnpm build` 和 `pnpm start`。

本项目使用 `output: "export"`，构建产物位于 `out/`；`pnpm start` 使用静态服务器提供这些文件。它与 Capacitor 共用同一份产物。开发时直接运行 `pnpm dev`，无需每次修改都重新构建。静态部署需要把 `/planning` 等路径解析到对应的 `.html` 文件；不要把所有路径统一返回首页。

请使用完整的 `pnpm build`：构建后会检查 Next.js 16 在 Windows 上的 RSC 预加载路径，为受影响的文本载荷补齐对应文件名，避免静态部署与 App WebView 的预加载 404。原文件保留，已正确导出的版本无需额外处理。运行 `pnpm test` 可验证这一兼容处理和请求边界。

## 4. 访问前端

- 电脑访问：`http://localhost:3000`
- 手机访问：`http://电脑局域网IPv4:3000`

手机保留底部导航和纵向操作流程，电脑使用原有较宽的页面框架与侧边导航，两端共用账户和数据。照片创作与行程调整继续采用原有页面结构。

照片生成和旅行规划会显示实际步骤、已用时间及预计剩余时间。预估会受照片数量、模型和外部查询速度影响；暂时无法取得进度时会提示重新连接，生成请求会继续执行。

手机访问还需要确认后端使用 `--host 0.0.0.0` 启动，并允许电脑防火墙通过 `3000` 和 `8000` 端口。

还需在后端 `.env` 的 `FRONTEND_ORIGINS` 中加入实际网页来源（协议、IP 和端口），例如 `http://localhost:3000,http://192.168.10.222:3000`，然后重启后端。只修改前端 API 地址仍可能被浏览器的 CORS 检查拦截。

## 5. Android 配置

Android 图标源文件为 `design/lvyousuotu-app-icon.png`。`capacitor.config.json` 中的 `plugins.CapacitorHttp.enabled` 应保持为 `true`，以便 Android 使用原生 HTTP 请求；如果后端通过 HTTP 提供图片，`server.androidScheme` 也应与实际部署协议保持一致。

重新打包前先执行 `pnpm build`，再运行 `pnpm exec cap sync android`，将最新的手机界面和静态资源同步到原 Android 工程，然后按原签名配置构建 APK。

## 6. 常见问题

如果页面能打开但没有数据或图片，确认后端已在 `8000` 端口启动，并检查 `.env.local` 中的两个地址是否指向同一个后端。修改配置后必须重新构建前端。

如果提示找不到 `pnpm`，执行 `corepack enable` 后重新打开终端。如果 `pnpm build` 失败，确认 Node.js 版本不低于 `20.9.0`，并重新执行 `pnpm install`。
