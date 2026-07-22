# MediaFetch

MediaFetch 是一个可自行部署的响应式视频解析与下载网站。它通过 yt-dlp Python API
读取公开视频元数据，通过 Redis + RQ 可靠排队，在需要时使用 FFmpeg 无损合并音视频，
并通过 SSE 实时显示任务进度。最终文件必须先经过短期签名令牌授权，再由 Nginx
内部传输。

本项目只用于下载您自己拥有、已获得权利人授权，或平台条款明确允许下载的内容。
普通用户不能上传 Cookie 或任意请求头。运维管理员可以在隐藏管理页通过哔哩哔哩官方
二维码登录流程建立服务器平台会话；这不会绕过账号权限、付费墙或 DRM。

在线演示：[https://mnzo.de](https://mnzo.de)

本项目采用 [MIT License](LICENSE) 开源。公开演示站可能根据服务器资源、平台限制和维护安排调整可用性。

## 功能

- 解析标题、封面、作者、平台、时长和全部可用格式
- 支持直接粘贴平台整段分享文案，自动提取其中的 HTTP/HTTPS 链接
- 默认展示 360P、480P、720P、1080P、1440P、2160P 和仅音频的推荐格式
- “高级格式”保留同一清晰度的其他编码、帧率和容器
- 视频/音频轨分别下载并用 FFmpeg 无损封装
- 自动选择 MP4、WebM 或 MKV，避免编码与容器不兼容
- 可选 H.264 + AAC 兼容转码
- 原始音频、M4A 和 MP3 输出
- RQ 任务队列、每 IP 并发限制、全局 worker 限制
- SSE 进度和 15 秒心跳
- 签名下载令牌、Nginx `X-Accel-Redirect`、Range 支持
- 下载、失败分片、取消任务和孤立文件自动清理
- IPv4/IPv6、DNS 答案和重定向逐级 SSRF 检查
- 移动端优先、iPhone Safari 可用、系统深色模式

## 重点支持平台

MediaFetch 对以下 7 个平台只使用平台官方页面、官方接口或 yt-dlp 的平台专用提取器，
不把用户链接发送给第三方解析站：

- 抖音：优先解析官方分享页 `_ROUTER_DATA` 和官方播放端点
- 快手：解析官方公开页面的 `INIT_STATE` 媒体列表
- 小红书：使用专用提取器读取官方媒体列表，并优先保留 `originVideoKey` 对应的原始流
- 哔哩哔哩：使用专用提取器及官方 DASH/播放接口，支持受控扫码会话
- 微博：使用专用提取器读取官方 `playback_list`
- 西瓜视频：使用专用提取器读取官方 SSR 数据中的 `videoResource`
- YouTube：使用专用提取器、Deno 和 EJS 处理官方播放器格式

“原始流”指平台在当前请求中实际提供的最高优先级媒体，并不绕过登录权限、付费墙、DRM、
地区限制或平台添加的来源标识。平台未提供的文件版本，服务不会通过修改 URL 或第三方接口伪造。

## 功能截图

> 截图预留位置：部署后可将首页、格式选择和任务完成页面截图放入
> `docs/screenshots/`，并在这里添加图片链接。

## 快速开始（Docker，推荐）

前置条件：

- Ubuntu 22.04/24.04 或其他支持 Docker Compose v2 的 Linux
- 至少 2 核 CPU、2 GB 内存和足够的下载磁盘空间
- 对外部署时准备域名和 HTTPS 证书

```bash
cp .env.example .env
```

公开部署前，至少修改 `.env` 中的 `TOKEN_SECRET`、`ADMIN_TOKEN`、`ALLOWED_ORIGINS` 和
`PUBLIC_BASE_URL`：

```bash
sed -i "s/^TOKEN_SECRET=.*/TOKEN_SECRET=$(openssl rand -hex 32)/" .env
sed -i "s/^ADMIN_TOKEN=.*/ADMIN_TOKEN=$(openssl rand -hex 32)/" .env
docker compose up -d --build
```

### 服务器平台会话

部署完成后访问 `https://您的域名/admin`，输入 `.env` 中的 `ADMIN_TOKEN`，点击“生成登录二维码”，
再使用哔哩哔哩 App 扫码并确认。MediaFetch 只保存官方接口返回的 `*.bilibili.com` Cookie，
不收集账号密码；管理员令牌只保存在当前浏览器标签的 `sessionStorage`，不会放入 URL。

平台会话保存在独立的 Docker 凭证卷 `/credentials/bilibili-cookies.txt`，文件权限为 `0600`。
API 和 worker 只会在目标主机属于 `bilibili.com` 或 `b23.tv` 时使用该会话，Cookie 不进入 Redis、
任务载荷或应用日志。重新扫码会原子替换旧会话，管理页也可立即删除会话。

登录只能获得该账号本身拥有的平台访问权限。会员高码率是否可用仍由账号等级、视频授权、地区、
平台接口及 yt-dlp 支持情况决定；疑似 DRM 的格式仍会被拒绝。请使用专门账号，并在不再需要时
删除平台会话或撤销对应登录设备。

抖音、Instagram 和 YouTube 没有接入账号密码登录，也没有向普通访客开放 Cookie。管理员可在
同一 `/admin` 页面导入从已登录浏览器导出的当前平台 Netscape `cookies.txt`。后端限制文件为
128 KB，并逐条校验 Cookie 域名：抖音只允许 `douyin.com` / `iesdouyin.com`，Instagram 只允许
`instagram.com`，YouTube 只允许 `youtube.com` / `google.com`。混入其他域名的文件会被整体拒绝。
不要导出整个浏览器的 Cookie 数据库。

会话文件保存在不对 Nginx 暴露的 `/credentials` 卷中。每次 yt-dlp 操作只使用一个进程私有快照，
结束后立即删除，避免 API 与 worker 同时更新同一个 Cookie 文件。快手公开作品使用 MediaFetch
内置的窄域名提取器，无需用户提供任意 yt-dlp 插件或参数。

查看服务：

```bash
docker compose ps
docker compose logs -f api
docker compose logs -f worker
```

停止服务：

```bash
docker compose down
```

如需同时删除 Redis 和媒体数据卷，必须明确执行
`docker compose down -v`。这会永久删除任务状态和下载文件。

## 本地开发

本地开发需要 Node.js 22、Python 3.12、Redis 和 FFmpeg。

后端：

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
export APP_ENV=development
export TOKEN_SECRET="$(openssl rand -hex 32)"
export REDIS_URL=redis://127.0.0.1:6379/0
export STORAGE_ROOT=../storage
export X_ACCEL_REDIRECT_ENABLED=false
export ALLOWED_ORIGINS=http://127.0.0.1:3000
uvicorn app.main:app --reload
```

另开终端启动 worker 和清理服务：

```bash
cd backend
source .venv/bin/activate
python -m app.workers.worker
python -m app.services.cleanup
```

前端：

```bash
cd frontend
npm ci
NEXT_PUBLIC_API_BASE=http://127.0.0.1:8000/api/v1 npm run dev
```

开发模式首页位于 `http://127.0.0.1:3000`，API 文档位于
`http://127.0.0.1:8000/api/docs`。生产模式不暴露交互式 API 文档。

## API 快捷接口

现有的 `POST /api/v1/inspect`、`POST /api/v1/downloads`、任务查询和 SSE 接口适合需要
精确选择编码、清晰度和音轨的客户端。另提供两个短视频快捷接口：

```http
POST /api/v1/parse
Content-Type: application/json

{"share_text":"7.89 abc:/ 复制打开平台应用 https://example.com/video"}
```

响应包含 `code`、`inspect_id`、标题、封面、平台和经过归一化的格式列表。为避免 CDN
地址泄漏、签名参数滥用和绕过下载限制，响应不会包含真实媒体直链。

```http
POST /api/v1/download
Content-Type: application/json

{
  "share_text":"https://example.com/video",
  "output_container":"mp4",
  "postprocess_preset":"remux",
  "compatibility_mode":false,
  "apply_ffmpeg_crop":false
}
```

快捷下载默认选择不高于 1080P 的推荐视频格式并返回 `202`、`job_id` 和 `queued`；随后仍通过
任务查询/SSE 获取进度，并使用签名下载令牌交付文件。需要指定格式时使用 `/inspect` +
`/downloads`。`apply_ffmpeg_crop=true` 会返回 `WATERMARK_REMOVAL_NOT_SUPPORTED`：项目不提供
删除、裁切或遮挡平台水印的功能。

`POST /api/v1/downloads` 与快捷下载都只接受两个后处理预设：

- `remux`：默认值，仅使用 FFmpeg 无损封装，编码不兼容时自动选择 WebM 或 MKV
- `transcode`：需要时使用服务端固定参数转换为 H.264 + AAC 的 MP4

`compatibility_mode` 为旧版客户端保留；设为 `true` 等同于 `postprocess_preset=transcode`。
API 不接受自定义滤镜、FFmpeg 参数、输出路径或其他后处理名称。

## 安全解析 Hook

`backend/app/parsers/hooks.py` 提供 `VideoParserHook` 扩展接口。Hook 必须在代码中注册并声明
规范化的来源域名白名单，系统只会对精确域名或其子域名选中 Hook。内置的抖音 Hook 添加
服务端固定的移动端请求身份，并校验 yt-dlp 的平台结果。

Hook 接口刻意不提供修改或返回媒体 URL、格式选择器、yt-dlp 参数、FFmpeg 参数和输出路径的
能力，运行时也不能从用户输入动态加载插件。抖音来源另有一个代码内置的窄域名解析器：它从
`iesdouyin.com/share/video/{id}` 的 `_ROUTER_DATA` 读取 `video.play_addr.uri`，并构造固定的
抖音官方播放端点。该播放地址仅保存在 Redis 任务数据中，不会返回前端；Worker 下载时仍由
安全网络层逐次校验目标和重定向。yt-dlp 已能解析的格式会继续保留，系统不会执行
`/playwm/` 到 `/play/` 的字符串替换。SSRF 校验、Redis 队列、Job ID 和签名文件交付流程不变。

## 环境变量

| 变量 | 默认示例 | 说明 |
| --- | --- | --- |
| `APP_ENV` | `production` | `development`、`test` 或 `production` |
| `LOG_LEVEL` | `INFO` | 后端日志级别 |
| `REDIS_URL` | `redis://redis:6379/0` | Redis 连接串，不应对公网暴露 |
| `PUBLIC_BASE_URL` | `http://localhost` | 站点对外地址 |
| `ALLOWED_ORIGINS` | `http://localhost,...` | 逗号分隔的精确 CORS 来源 |
| `X_ACCEL_REDIRECT_ENABLED` | `true` | Nginx 部署启用；直连 API 开发时设为 `false` |
| `TOKEN_SECRET` | 随机 64 位十六进制 | 文件令牌 HMAC 密钥；每个部署必须唯一 |
| `ADMIN_TOKEN` | 随机 64 位十六进制 | 隐藏管理页和平台登录 API 的独立管理员令牌 |
| `CREDENTIALS_ROOT` | `/credentials` | 运维平台会话的独立持久卷；不要映射到 Nginx |
| `MAX_CONCURRENT_JOBS_PER_IP` | `2` | 单 IP 同时活动任务数 |
| `MAX_GLOBAL_WORKERS` | `2` | worker 子进程数 |
| `WORKER_CPU_LIMIT` | `4.0` | worker 容器可使用的 CPU 核数上限 |
| `MAX_QUEUE_SIZE` | `100` | RQ 队列最大等待任务数 |
| `MAX_FILE_SIZE_MB` | `2048` | 预计及实际文件硬限制 |
| `MAX_DURATION_SECONDS` | `10800` | 最大视频时长 |
| `DOWNLOAD_TIMEOUT_SECONDS` | `3600` | 单任务下载时限 |
| `FFMPEG_TIMEOUT_SECONDS` | `1800` | 单次合并或转码时限 |
| `FFMPEG_THREADS` | `2` | FFmpeg 最大线程数 |
| `FFMPEG_X264_PRESET` | `veryfast` | 兼容模式的 H.264 编码速度预设 |
| `INSPECT_TIMEOUT_SECONDS` | `45` | 元数据解析时限 |
| `INSPECT_CACHE_TTL_SECONDS` | `600` | `inspect_id` 有效期 |
| `FILE_TTL_SECONDS` | `7200` | 文件与下载令牌有效期 |
| `JOB_TTL_SECONDS` | `86400` | 任务状态保留时间 |
| `CLEANUP_INTERVAL_SECONDS` | `300` | 清理扫描周期 |
| `MAX_REDIRECTS` | `5` | URL 预检最大重定向数 |
| `RATE_LIMIT_INSPECT_PER_MINUTE` | `20` | 每 IP 每分钟解析次数 |
| `RATE_LIMIT_DOWNLOAD_PER_MINUTE` | `10` | 每 IP 每分钟建任务次数 |
| `AUDIO_MP3_QUALITY` | `2` | FFmpeg LAME VBR 质量，0 最佳、9 最小 |
| `YTDLP_PROXY` | 空 | 仅运维人员可配置的 yt-dlp 出站代理 |
| `PARALLEL_DOWNLOAD_ENABLED` | `true` | 对支持 Range 的哔哩哔哩直连媒体启用安全分段下载 |
| `PARALLEL_DOWNLOAD_CONNECTIONS` | `8` | 单个媒体轨的并发连接数，允许 1–16 |
| `PARALLEL_DOWNLOAD_MIN_SPLIT_SIZE_MB` | `4` | 每个并发分段的最小目标大小 |
| `PARALLEL_DOWNLOAD_CHUNK_SIZE_MB` | `4` | 每次 Range 请求的最大块大小；较小的块可避免 CDN 中途断流 |
| `BILIBILI_USER_AGENT` | 固定 Chrome 标识 | 扫码登录、解析与下载使用的同一服务器端浏览器标识 |
| `NEXT_PUBLIC_API_BASE` | `/api/v1` | 浏览器访问的 API 前缀 |
| `HTTP_PORT` | `80` | Compose 暴露的 HTTP 端口 |

修改 `NEXT_PUBLIC_API_BASE` 后必须重新构建前端镜像。

## Nginx 与 HTTPS

`nginx/default.conf` 包含以下关键行为：

- `/api/` 代理到 FastAPI
- `/api/v1/jobs/` 关闭代理缓冲并提高读取超时，支持 SSE
- `/` 代理到 Next.js
- `/protected/` 使用 `internal`，公网不能直接读取共享目录
- FastAPI 校验签名令牌后返回 `X-Accel-Redirect`
- Nginx 使用 `sendfile` 并支持 HTTP Range
- 请求体限制为 32 KiB，storage 没有公开目录映射

若 Compose 前还有一层宿主机 Nginx，可参考 `nginx/host-mediafetch.conf.example`。文件下载
路径开启有限的内存代理缓冲但禁用临时文件落盘；SSE 路径仍必须关闭缓冲。Linux 内核支持 BBR
时，可安装 `ops/mediafetch-bbr.conf` 和 `ops/99-mediafetch-network.conf` 后执行
`modprobe tcp_bbr && sysctl --system`。启用前请先确认 VPS 提供商允许修改拥塞控制算法。

生产环境建议在本配置前增加 Caddy、Traefik、云负载均衡器，或直接为 Nginx
配置 TLS。反向代理必须覆盖（而不是追加用户提供的）`X-Real-IP`，并保持
`ALLOWED_ORIGINS` 为实际 HTTPS 域名。不要把 api、redis 或 worker 端口发布到公网。

## 格式与处理规则

API 只接受当前 `inspect_id` 中真实存在的格式 ID，用户不能传递 yt-dlp/FFmpeg
参数或服务器路径。视频轨没有音频时，后端从已解析音轨中自动选择兼容性最好的轨道。

- H.264 + AAC 优先 MP4
- VP9/AV1 + Opus/Vorbis 优先 WebM
- 混合或不兼容编码使用 MKV
- 默认使用 `-c copy`，不转码
- 只有 `postprocess_preset=transcode`（或旧版兼容模式）时才转为 H.264 + AAC
- 已经是 H.264 + AAC 的媒体即使勾选兼容模式也会自动跳过重复转码
- MP3 和非 AAC 的 M4A 输出会进行音频转换

如果用户请求了与编码不兼容的容器，后端会选择兼容容器，不会只修改扩展名。

## 数据与清理

每个任务使用服务器生成的随机 ID：

```text
/data/temp/{job_id}/
/data/downloads/{job_id}/{safe_filename}
```

用户输入从不作为目录名。成功、失败和取消任务会立即清理临时目录；cleanup
容器启动时先扫描一次，之后按周期删除：

- 超时或孤立的临时目录
- 超过 `FILE_TTL_SECONDS` 的下载目录
- 指向不存在文件或已过期的令牌
- 已删除文件对应的任务下载地址

手动触发一次清理：

```bash
docker compose run --rm cleanup python -m app.services.cleanup --once
```

删除失败会写入日志，下一轮会重试。

## 测试和质量检查

测试不访问真实视频网站，yt-dlp、DNS、重定向和 FFmpeg 都使用 fixture 或 mock。

```bash
docker compose --profile test run --rm backend-test
docker compose --profile test run --rm frontend-test
docker compose build
```

本地开发环境还可分别执行 `ruff check app tests`、`mypy app` 和
`npm run typecheck`；`Makefile` 的 `make test` 会运行两个隔离测试镜像。

后端测试覆盖 URL/IPv4/IPv6/DNS/重定向安全、格式排序、非法和过期格式、
文件名与路径、令牌过期、取消、大小限制、状态转换，以及 yt-dlp/FFmpeg
错误映射。前端测试覆盖 URL 输入、格式选择、任务进度、错误提示和完成状态。

## 更新 yt-dlp

yt-dlp、`yt-dlp-ejs` 与 Deno 在 `backend/requirements.txt` 中固定版本。YouTube 当前依赖
JavaScript Challenge 求解；升级 yt-dlp 时应按其 EJS 兼容表同步更新 EJS 和 Deno，再执行：

```bash
docker compose build --no-cache api worker cleanup
docker compose run --rm api pytest
docker compose up -d
```

不要在运行中的容器里直接 `pip install -U`，否则重建会丢失变更，也无法审计版本。

## 日志

```bash
docker compose logs -f api
docker compose logs -f worker
docker compose logs -f cleanup
docker compose logs --since=30m nginx
```

应用日志不会记录 URL 查询参数，并会隐藏 token、Cookie、Authorization、
signature、key 和 password 等字段。API 错误只返回统一错误代码、中文消息和
`request_id`，不返回堆栈或服务器路径。排障时可用 `request_id` 关联 API 日志。

## 常见问题

### 健康检查显示 `ffmpeg: false`

确认使用项目提供的后端镜像；该镜像会安装 FFmpeg。本地开发需执行
`ffmpeg -version` 并确保它在 `PATH`。

### `FORMAT_EXPIRED`

解析结果默认仅保留 10 分钟。重新解析链接后再提交下载。

### `BLOCKED_ADDRESS`

域名解析到私有、环回、链路本地、保留或其他非全局 IP，或重定向目标属于这些范围。
这是 SSRF 防护的预期行为。不要通过关闭检查来支持内网站点。

### `DRM_PROTECTED`、`LOGIN_REQUIRED` 或 `PRIVATE_VIDEO`

MediaFetch 不尝试绕过这些限制。哔哩哔哩账号有合法访问权限时，管理员可在 `/admin` 建立平台
会话；未授权、私密、风控拦截或 DRM 内容仍会拒绝。其他情况请使用平台提供的官方离线功能。

### 高画质输出变成 WebM 或 MKV

所选轨道可能是 VP9/AV1 + Opus。默认无损模式会选择兼容容器。需要老设备支持时，
启用 MP4 兼容模式，但它需要更多 CPU 和时间。

### 下载中断或显示 `FILE_TOO_LARGE`

检查 `MAX_FILE_SIZE_MB`、磁盘剩余空间、下载时限及 worker 日志。大小限制在解析估算、
下载进度钩子、FFmpeg 输出和最终文件四处执行。

### SSE 在外部代理后断开

确保外部代理也关闭事件流缓冲、读取超时大于任务时长，并允许 15 秒心跳通过。

### Redis 队列无法继续

```bash
docker compose ps
docker compose logs --tail=200 redis worker
docker compose restart worker
```

Redis 使用 AOF 持久化和 `noeviction`，磁盘满时会拒绝写入；清理磁盘后再恢复服务。

## 安全边界

- 只允许 `http` 和 `https`
- 拒绝认证信息、localhost、私有/保留 IPv4、非全局 IPv6、元数据地址和本地路径
- 异步 LinkResolver 使用 HTTPX 手动跟踪重定向，每一跳都重新校验 DNS
- LinkResolver 将 TCP 连接固定到刚通过校验的公网 IP，同时保留原主机名进行 TLS SNI 和证书验证
- yt-dlp 每个实际请求（含重定向和 manifest）再次解析和检查目标
- 限制重定向、解析时长、媒体时长、预计/实际大小、下载和 FFmpeg 执行时间
- 普通用户不能提供 Cookie、请求头、代理、yt-dlp 参数、FFmpeg 参数或输出路径
- 管理员平台会话受独立高强度令牌保护，只能用于固定的平台域名，并存放在不对 Nginx 暴露的凭证卷
- 每个任务目录和令牌都由密码学安全随机数生成
- CORS 使用明确来源列表；Redis/API 内部端口不对外发布

对多租户或高威胁环境，仍建议在宿主机/云防火墙层禁止 worker 和 api 访问 RFC1918、
链路本地、环回、IPv6 ULA 及云元数据网段，形成独立于应用代码的第二道防线。

## 法律与版权

运行者和使用者必须遵守版权法、网站服务条款、内容许可和所在地法律。公开可访问
不等于允许复制或再分发。本项目不提供规避技术保护措施的功能；对疑似 DRM、
需要登录或私密内容会明确拒绝。部署者应根据所在司法辖区增加使用政策、投诉流程、
访问日志保留策略和必要的滥用处置机制。

## 项目结构

```text
mediafetch/
├── frontend/              # Next.js + TypeScript + Tailwind
│   ├── app/
│   ├── components/
│   ├── lib/
│   └── Dockerfile
├── backend/
│   ├── app/
│   │   ├── api/           # inspect、downloads、jobs、health、admin
│   │   ├── core/          # 配置、Redis、安全、日志、错误
│   │   ├── models/
│   │   ├── services/      # 解析、格式、下载、平台会话、令牌、清理
│   │   └── workers/       # RQ 任务和 worker 池
│   ├── tests/
│   └── Dockerfile
├── nginx/default.conf
├── storage/
├── scripts/
├── .env.example
└── docker-compose.yml
```
