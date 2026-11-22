# MediaFetch 2.0

MediaFetch 是一个支持 Docker Compose 一键自托管部署的**国内外全平台无水印视频与高清图集在线解析下载系统**。它采用**多引擎纯净源流提取 + 智能三级传输架构**，自动识别分享口令、还原短链、过滤平台水印版本，并根据流媒体特征智能选择**零落盘流式直传**或 **FFmpeg 云端无损合并**。

本项目仅用于下载您拥有权利、已获授权或平台条款允许下载的公开媒体内容，不提供绕过付费墙、访问控制或 DRM 的能力，也不对画面做破坏性裁切去水印——所有无水印结果均来自平台公开返回的原始纯净媒体流。

本项目采用 [MIT License](LICENSE) 开源。

---

## 核心特性

### 1. 多引擎全平台纯净无水印提取
- **口令清洗与短链追踪**：支持直接粘贴带中文文案的混合分享口令（如抖音、小红书、快手、B站、微博等），自动提取 URL 并通过 IP-Pinned 安全传输层追踪 301/302 短链重定向。
- **平台专用无水印源流提取器**：
  - **抖音**：内置 `_ROUTER_DATA` 多码率 `bit_rate` 原画流与 `/aweme/v1/play/` 纯净端点提取，支持**图文笔记与实况图（Live Photo）**无水印提取；同时支持一键挂载 `Douyin_TikTok_Download_API` 混合引擎容器（`--profile hybrid`）。
  - **小红书**：内置 `__INITIAL_STATE__` 提取器，优先直取 `originVideoKey` 无水印母版视频流，并支持**无水印高清原图集与 Live 实况动态视频**提取。
  - **快手**：内置 `INIT_STATE` / `__APOLLO_STATE__` 提取器，提取无水印多清晰度 MP4 与 `atlas` 高清图集。
  - **皮皮虾**：内置专用提取器读取 `origin_video_download` 无水印原始上传流（自动跳过带水印的 `video_download`）与多图笔记。
  - **哔哩哔哩**：支持官方高码率 DASH 4K/1080P60 音画分离流、多 P 合集（`?p=N`）精确选集、多线程 Range 分段加速及后台扫码会话。
  - **TikTok / YouTube / X (Twitter) / Instagram / 微博 / 西瓜视频 / Reddit / Vimeo / Twitch / 1000+ 站点**：内置 `yt-dlp` + `curl_cffi` 浏览器 TLS 指纹伪装（`YTDLP_IMPERSONATE=chrome`）+ Deno/EJS + `YOUTUBE_PO_TOKEN` 支持。
- **全局水印流拦截器**：归一化阶段自动识别并剔除 `download_addr`、`playwm`、`watermark=1` 等带平台水印格式；若上游仅返回带水印流则直接拦截报错（`WATERMARKED_ONLY`），绝不混入水印版本。

### 2. 智能三级传输与零落盘带宽优化
1. **流式反代直传模式（`stream` · 零落盘免排队）**：对于抖音、小红书、快手、TikTok、X、Instagram、微博、皮皮虾等音画一体的单文件源流，签发短期 HMAC 令牌并通过 `/api/v1/stream/{token}` 携带受控 `Referer` / `User-Agent` / 平台会话流式转发（支持 HTTP `Range` 断点续传与自定义文件名），**服务器零磁盘占用、点击即下无需排队**。
2. **无水印图集流式打包（`gallery` ZIP）**：对于小红书、抖音、快手、皮皮虾等高清图集与实况图，支持单张原图/实况 MP4 直下及 `/api/v1/gallery/{token}` 一键打包下载 `.zip`。
3. **异步无损合并模式（`async_merge` · RQ + FFmpeg）**：仅当遇到 YouTube 1080P+/4K、B站高码率 DASH 等音画分离流，或用户主动要求提取 MP3 / H.264 兼容转码时，推入 Redis + RQ 队列由 Worker 调用 FFmpeg 无损封装，通过 SSE 实时推送进度，完成后经 Nginx `X-Accel-Redirect` 交付并定时自动清理。

### 3. 国内外双出口代理分流与安全防护
- **双代理隔离**：支持通过 `.env` 分别配置 `CN_PROXY_URL`（国内平台专用出口）和 `GLOBAL_PROXY_URL`（海外平台专用出口），互不干扰。
- **可选前台访问口令**：设置 `ACCESS_TOKEN` 即可一键开启前台访问密码保护（留空则公开免登）。
- **受控多平台 Cookie 中心（`/admin`）**：支持哔哩哔哩官方二维码扫码登录，以及抖音、TikTok、小红书、快手、微博、X (Twitter)、Instagram、YouTube 的域名白名单 `cookies.txt` 导入与进程私有快照隔离。
- **全链路防 SSRF（DNS Rebinding 防护）**：短链追踪、提取器、流式直传与分片下载均逐跳校验公网 IP 并锁定连接地址，彻底阻断内网探测。

---

## 快速开始（Docker Compose 一键部署）

```bash
cp .env.example .env
sed -i "s/^TOKEN_SECRET=.*/TOKEN_SECRET=$(openssl rand -hex 32)/" .env
sed -i "s/^ADMIN_TOKEN=.*/ADMIN_TOKEN=$(openssl rand -hex 32)/" .env
docker compose up -d --build
```

如需同时启用独立的 `Douyin_TikTok_Download_API` 容器作为抖音/TikTok 第一优先级引擎：

```bash
echo "DOUYIN_API_BASE_URL=http://douyin-api:80" >> .env
docker compose --profile hybrid up -d --build
```

部署完成后：
- 前台解析工作台：`http://您的域名/`
- 运维平台会话后台：`http://您的域名/admin`（使用 `.env` 中的 `ADMIN_TOKEN` 登录）

---

## 本地开发与验证

需要 Node.js 22+、Python 3.12+、Redis 和 FFmpeg。

### 后端

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .\.venv\Scripts\activate
pip install -r requirements-dev.txt
export APP_ENV=development
export TOKEN_SECRET="$(openssl rand -hex 32)"
export REDIS_URL=redis://127.0.0.1:6379/0
export STORAGE_ROOT=../storage
export X_ACCEL_REDIRECT_ENABLED=false
export ALLOWED_ORIGINS=http://127.0.0.1:3000
uvicorn app.main:app --reload
```

另开终端启动异步合并 Worker 与定时清理服务：

```bash
cd backend
python -m app.workers.worker
python -m app.services.cleanup
```

### 前端

```bash
cd frontend
npm install
NEXT_PUBLIC_API_BASE=http://127.0.0.1:8000/api/v1 npm run dev
```

---

## 核心 API 概览

| 方法与路径 | 说明 |
| --- | --- |
| `GET /api/v1/health` | 服务、Redis、FFmpeg 与 yt-dlp 健康检查 |
| `GET /api/v1/auth/config` | 查询站点是否开启前台 `ACCESS_TOKEN` 访问口令 |
| `POST /api/v1/inspect` | 解析分享文本或 URL，返回无水印视频流、音轨、图集及直传令牌 URL |
| `POST /api/v1/parse` | 快捷解析接口（兼容集成调用） |
| `GET /api/v1/stream/{token}` | 零落盘流式反代直传（支持 `Range` 断点续传与防盗链 Header 注入） |
| `GET /api/v1/gallery/{token}` | 无水印图集与实况视频流式打包 `.zip` 下载 |
| `POST /api/v1/downloads` | 创建异步音视频无损合并 / MP3 提取 / H.264 兼容转码任务 |
| `GET /api/v1/jobs/{job_id}/events` | 任务实时进度 SSE 流（含 15 秒心跳） |
| `GET /api/v1/files/{token}` | 合并完成文件的短期签名令牌下载（Nginx `X-Accel-Redirect`） |

---

## 关键环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `TOKEN_SECRET` | 必填（>=32 字符） | 文件、流式直传与图集令牌的 HMAC 签名密钥 |
| `ADMIN_TOKEN` | 可选（>=32 字符） | `/admin` 平台会话控制台管理员密钥 |
| `ACCESS_TOKEN` | 空 | 可选前台访问口令，非空时要求前端携带 `X-Access-Token` |
| `CN_PROXY_URL` | 空 | 国内平台（抖音/小红书/快手/B站/微博/皮皮虾等）专用出站代理 |
| `GLOBAL_PROXY_URL` | 空 | 海外平台（YouTube/TikTok/X/Instagram/Reddit 等）专用出站代理 |
| `YTDLP_PROXY` | 空 | 通用兜底出站代理 |
| `DOUYIN_API_BASE_URL` | 空 | 可选内部 `Douyin_TikTok_Download_API` 地址（如 `http://douyin-api:80`） |
| `YTDLP_IMPERSONATE` | `chrome` | `curl_cffi` 浏览器 TLS 指纹伪装目标 |
| `YOUTUBE_PO_TOKEN` | 空 | 可选 YouTube `po_token` 参数 |
| `STREAM_TOKEN_TTL_SECONDS` | `1800` | 零落盘直传令牌与图集打包令牌有效期（秒） |
| `FILE_TTL_SECONDS` | `1800` | 异步合并落盘文件保留时间（秒） |

---

## 测试与质量检查

```bash
# 后端单元测试、Ruff 代码检查与 Mypy 类型检查
cd backend
python -m pytest
python -m ruff check app tests
python -m mypy app

# 前端组件测试、TypeScript 检查、ESLint 与生产构建
cd frontend
npm test -- --run
npm run typecheck
npm run lint
npm run build
```

---

## 项目目录结构

```text
mediafetch/
├── frontend/
│   ├── app/                   # Next.js App Router 主工作台与 /admin 平台会话页
│   ├── components/            # UrlInput、FormatSelector、GalleryGrid、JobProgress 等
│   └── lib/                   # API 封装、链接提取与任务状态恢复
├── backend/
│   ├── app/
│   │   ├── api/               # inspect、stream、downloads、convenience、jobs、admin
│   │   ├── core/              # 配置与双代理分流、访问口令、Redis、SSRF 安全、日志
│   │   ├── models/            # 请求与响应 Pydantic 模型
│   │   ├── parsers/           # 域名白名单安全解析 Hook
│   │   ├── services/          # 抖音/小红书/快手/皮皮虾/混合引擎无水印提取、格式过滤、令牌
│   │   └── workers/           # RQ + FFmpeg 异步无损合并 Worker
│   └── tests/                 # 130+ 项全链路安全与多平台提取测试
├── nginx/default.conf         # SSE 与流式直传零缓冲反代 + X-Accel-Redirect 配置
├── .env.example
└── docker-compose.yml
```
