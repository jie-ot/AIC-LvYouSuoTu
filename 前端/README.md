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
pnpm install
pnpm build
pnpm start --hostname 0.0.0.0
```

看到 `Ready` 后保持终端运行。修改 `.env.local` 或前端代码后，先按 `Ctrl+C` 停止服务，再重新执行 `pnpm build` 和 `pnpm start --hostname 0.0.0.0`。

## 4. 访问前端

- 电脑访问：`http://localhost:3000`
- 手机访问：`http://电脑局域网IPv4:3000`

手机访问还需要确认后端使用 `--host 0.0.0.0` 启动，并允许电脑防火墙通过 `3000` 和 `8000` 端口。

## 5. Android 配置

Android 图标源文件为 `design/lvyousuotu-app-icon.png`。`capacitor.config.json` 中的 `plugins.CapacitorHttp.enabled` 应保持为 `true`，以便 Android 使用原生 HTTP 请求；如果后端通过 HTTP 提供图片，`server.androidScheme` 也应与实际部署协议保持一致。

## 6. 常见问题

如果页面能打开但没有数据或图片，确认后端已在 `8000` 端口启动，并检查 `.env.local` 中的两个地址是否指向同一个后端。修改配置后必须重新构建前端。

如果提示找不到 `pnpm`，执行 `corepack enable` 后重新打开终端。如果 `pnpm build` 失败，确认 Node.js 版本不低于 `20.9.0`，并重新执行 `pnpm install`。
