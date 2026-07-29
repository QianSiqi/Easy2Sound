# Easy2Sound 官网 — 完整结构与维护指南

> 最后更新：2026-07-29

---

## 目录

1. [项目概览](#项目概览)
2. [文件结构](#文件结构)
3. [技术栈](#技术栈)
4. [本地开发](#本地开发)
5. [前端架构](#前端架构)
6. [后端 API](#后端-api)
7. [数据库](#数据库)
8. [声库管理](#声库管理)
9. [页面内容修改](#页面内容修改)
10. [样式系统](#样式系统)
11. [安全机制](#安全机制)
12. [外部服务](#外部服务)
13. [服务器部署](#服务器部署)
14. [常见维护任务速查](#常见维护任务速查)
15. [故障排查](#故障排查)

---

## 项目概览

Easy2Sound 官网是一个前后端分离的单页应用（SPA）：

- **前端**：纯 HTML/CSS/JS，无框架，SPA hash 路由
- **后端**：Node.js + Express + SQLite
- **功能**：用户注册登录、头像上传、声库展示、反馈系统、下载页、投喂页

---

## 文件结构

```
website/
│
├── index.html              # 前端主页（SPA，所有页面都在这一个文件里）
├── 导航栏.css               # 全局样式（毛玻璃、导航栏、卡片、弹窗、响应式）
├── voicebanks.json         # 声库数据（改这个文件即可增删改声库）
├── serve.py                # 本地前端开发服务器（Python）
├── deploy.sh               # 一键部署脚本（Linux/macOS）
│
├── api/                    # 后端 API 服务
│   ├── server.js           # Express 服务器主文件
│   ├── package.json        # Node.js 依赖配置
│   ├── .env.example        # 环境变量模板
│   ├── data.db             # SQLite 数据库（运行后自动生成）
│   └── uploads/            # 用户上传的头像文件（运行后自动生成）
│
├── background_board.jpg    # 背景图（不能删）
├── 图标.jpg                # Easy2Sound 应用图标
├── shoukuan.jpg            # 投喂收款码
├── teto.bmp                # 重音テ卜声库头像
│
├── EXE/                    # Windows 安装包
│   └── Easy2Sound下载引导包.exe
│
├── Mac.jpg                 # macOS 截图
├── Linux.jpg               # Linux 截图
├── windows.jpg             # Windows 截图
├── 上传.jpg                # 上传功能截图
│
├── 404.html                # 404 错误页面
├── avatar.html             # [旧版] 头像页
├── details.html            # [旧版] 详情页
├── donation.html           # [旧版] 投喂页
├── down.html               # [旧版] 下载页
├── feedback.html           # [旧版] 反馈页
├── love.html               # [旧版] 感动人物页
├── yuandaima.html          # [旧版] 源代码页
└── proxy.properties        # 代理配置（不用管）
```

> 除 `index.html` 外的 `.html` 文件都是旧版独立页面，已保留但不再使用。所有功能都在 `index.html` 里以 SPA 方式运行。

---

## 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| 前端 | 原生 HTML/CSS/JS | 无框架依赖，单文件 SPA |
| 路由 | Hash 路由 | `#home` `#download` 等，`navigate()` 函数控制 |
| 样式 | CSS3 毛玻璃 | `backdrop-filter` + `rgba` 渐变背景 |
| 后端 | Express 4.x | Node.js HTTP API 服务 |
| 数据库 | SQLite (better-sqlite3) | 本地文件数据库，零配置 |
| 文件上传 | Multer | 头像上传，2MB 限制，仅 jpg/png |
| 反馈存储 | JSONBin 云端 | 外部 API，有 localStorage 缓存 |

---

## 本地开发

### 前置条件

- Python 3（前端静态服务器）
- Node.js 16+（后端 API）

### 启动步骤

**终端 1 — 启动后端 API：**

```bash
cd website/api
npm install          # 首次需要安装依赖
node server.js       # 启动 API 服务，默认端口 3000
```

**终端 2 — 启动前端：**

```bash
cd website
python serve.py      # 启动前端静态服务，默认端口 8080
```

**浏览器打开：** `http://localhost:8080`

### 开发说明

- 修改 `index.html` 或 `导航栏.css` 后刷新浏览器即可看到效果
- 修改 `voicebanks.json` 后刷新声库页面即可看到效果
- 修改 `api/server.js` 后需要重启后端（Ctrl+C 再 `node server.js`）
- 数据库文件在 `api/data.db`，可以用 SQLite 工具查看

---

## 前端架构

### SPA 路由系统

前端使用 hash 路由，所有页面切换在一个 HTML 文件内完成：

```
http://localhost:8080/#home        → 主页
http://localhost:8080/#download    → 下载页
http://localhost:8080/#voicebank   → 声库页
http://localhost:8080/#feedback    → 反馈页
http://localhost:8080/#love        → 感动人物
http://localhost:8080/#donate      → 投喂
http://localhost:8080/#source      → 源代码
```

### 路由流程

```
用户点击导航链接
    ↓
e.preventDefault() 阻止跳转
    ↓
navigate(page) 被调用
    ↓
容器 app 透明度 → 0（淡出 180ms）
    ↓
替换 app.innerHTML 为新页面模板
    ↓
容器 app 透明度 → 1（淡入）
    ↓
卡片 stagger-1/2/3... 错开入场动画
    ↓
页面特定初始化（如 feedback 加载列表）
```

### 页面模板

所有页面模板在 `index.html` 的 `const pages = { ... }` 对象中定义：

```javascript
const pages = {
    home: () => `<div class="glass-card stagger-1">...</div>`,
    download: () => `...`,
    voicebank: () => `...`,
    feedback: () => `...`,
    love: () => `...`,
    donate: () => `...`,
    source: () => `...`,
};
```

### API 地址自动检测

前端会自动判断运行环境：

- **本地开发**（`localhost`）：API 请求发到 `http://localhost:3000`
- **服务器部署**：API 请求发到 `http://当前域名:3000`

不需要手动修改任何地址。

### 反馈数据缓存

反馈列表使用 localStorage 缓存：

1. 进入反馈页 → 先从缓存秒渲染
2. 后台静默拉取 JSONBin 最新数据
3. 更新页面 + 刷新缓存

首次加载约 1-2 秒，之后秒加载。

---

## 后端 API

### 文件位置

`website/api/server.js`

### 启动命令

```bash
cd website/api
node server.js
# 或
HOST=0.0.0.0 PORT=3000 node server.js
```

### API 端点

| 方法 | 路径 | 功能 | 请求体 | 响应 |
|------|------|------|--------|------|
| `GET` | `/` | 健康检查 | — | `{ status, name, version, db }` |
| `POST` | `/register` | 用户注册 | `{ username, email, password, qq }` | `{ ok }` 或 `{ ok, error }` |
| `POST` | `/login` | 用户登录 | `{ username, password }` | `{ ok, user }` 或 `{ ok, error }` |
| `POST` | `/update-user-info` | 更新用户信息 | `{ userId, qq, avatar }` | `{ ok, user }` 或 `{ ok, error }` |
| `POST` | `/` | 头像上传 | `FormData: { avatar: File }` | `{ success, url }` |
| `GET` | `/uploads/:file` | 访问头像文件 | — | 图片文件 |

### 请求示例

**注册：**

```bash
curl -X POST http://localhost:3000/register \
  -H "Content-Type: application/json" \
  -d '{"username":"test","email":"test@example.com","password":"<sha256哈希>","qq":"123456"}'
```

**登录：**

```bash
curl -X POST http://localhost:3000/login \
  -H "Content-Type: application/json" \
  -d '{"username":"test","password":"<sha256哈希>"}'
```

### 环境变量

创建 `api/.env` 文件（参考 `.env.example`）：

```env
PORT=3000                  # API 端口
HOST=your-domain.com       # 服务器域名或 IP
FRONTEND_ORIGIN=http://your-domain.com  # 前端地址（CORS 白名单）
```

不设置时使用默认值（localhost:3000）。

---

## 数据库

### 技术

SQLite，通过 `better-sqlite3` 库访问。数据库文件：`api/data.db`

### 表结构

**users 表：**

```sql
CREATE TABLE users (
    id           TEXT PRIMARY KEY,     -- 用户唯一 ID（u_ + 随机 16 字符）
    username     TEXT UNIQUE NOT NULL,  -- 用户名（2-20 字符）
    email        TEXT UNIQUE NOT NULL,  -- 邮箱（正则校验）
    passwordHash TEXT NOT NULL,         -- SHA-256 哈希后的密码（64 字符）
    qq           TEXT DEFAULT '',       -- QQ 号
    avatar       TEXT DEFAULT '',       -- 头像 URL
    createdAt    TEXT NOT NULL          -- 注册时间（ISO 8601）
);
```

### 数据管理

**查看所有用户：**

```bash
cd website/api
node -e "
const Database = require('better-sqlite3');
const db = new Database('./data.db');
console.log(db.prepare('SELECT id, username, email, qq, createdAt FROM users').all());
db.close();
"
```

**删除用户：**

```bash
node -e "
const Database = require('better-sqlite3');
const db = new Database('./data.db');
db.prepare('DELETE FROM users WHERE username = ?').run('要删除的用户名');
db.close();
"
```

**备份数据库：**

```bash
cp api/data.db api/data.db.bak
```

### 从 JSON 迁移到 SQLite

如果之前使用的是 `db.json`，运行以下命令迁移：

```bash
cd website/api
node -e "
const Database = require('better-sqlite3');
const fs = require('fs');
const db = new Database('./data.db');
db.exec('CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, email TEXT UNIQUE NOT NULL, passwordHash TEXT NOT NULL, qq TEXT DEFAULT \"\", avatar TEXT DEFAULT \"\", createdAt TEXT NOT NULL)');
const insert = db.prepare('INSERT OR IGNORE INTO users VALUES (?, ?, ?, ?, ?, ?, ?)');
const data = JSON.parse(fs.readFileSync('./db.json', 'utf-8'));
data.users.forEach(u => insert.run(u.id, u.username, u.email, u.passwordHash, u.qq||'', u.avatar||'', u.createdAt));
console.log('迁移完成');
db.close();
"
```

---

## 声库管理

**只改 `voicebanks.json`，不用动 HTML。**

### 文件格式

```json
[
    {
        "id": "teto",
        "name": "重音テ卜",
        "desc": "重音テ卜（Kasane Teto）经典虚拟歌姬声库...",
        "img": "teto.bmp",
        "tag": "女声",
        "demo": "",
        "bvid": "BV11S3M6cEdY"
    }
]
```

### 字段说明

| 字段 | 必填 | 类型 | 说明 |
|------|------|------|------|
| `id` | ✅ | string | 唯一标识，不能重复 |
| `name` | ✅ | string | 显示名称 |
| `desc` | ✅ | string | 详细描述（弹窗完整显示，卡片截断 50 字） |
| `img` | ✅ | string | 图片文件名（放到 website/ 目录下，建议正方形） |
| `tag` | ✅ | string | 标签文字，如「女声」「男声」「其他」 |
| `demo` | ❌ | string | Demo 音频文件名，留空 `""` 不显示播放器 |
| `bvid` | ❌ | string | B 站视频 BV 号，留空 `""` 不显示视频 |

### 操作指南

**添加新声库：**

1. 把声库图片放到 `website/` 目录下（如 `新声库.jpg`）
2. 如有 Demo 音频，放到 `website/` 目录下（如 `demo.mp3`）
3. 编辑 `voicebanks.json`，在数组末尾加一条记录
4. 刷新声库页面即可看到

**修改声库信息：**

直接编辑 `voicebanks.json` 中对应条目的字段。

**删除声库：**

从 `voicebanks.json` 数组中删除对应条目。

**添加 B 站视频：**

1. 打开 B 站视频页面
2. 从 URL 中提取 BV 号，如 `https://www.bilibili.com/video/BV11S3M6cEdY/` → `BV11S3M6cEdY`
3. 填入 JSON 的 `bvid` 字段

### 声库卡片显示

- 桌面端：一行 5-6 个卡片
- 平板：一行 3 个
- 手机：一行 2 个
- 点击卡片弹出详情弹窗（图片 + 描述 + Demo 播放器 + B 站视频）

---

## 页面内容修改

### 页面列表

| 导航名 | 页面 key | 说明 |
|--------|----------|------|
| 主页 | `home` | Hero 区 + 特色介绍 + 详细介绍 + 系统要求 + 视频 |
| 下载 | `download` | 应用图标 + 版本介绍 + 平台下载按钮 + 文件信息 |
| 声库 | `voicebank` | 声库卡片网格（数据从 voicebanks.json 动态加载） |
| 反馈问题 | `feedback` | 反馈输入框 + 历史反馈列表（JSONBin 云端） |
| 感动人物 | `love` | 人物卡片网格 + Cloudflare 致谢 |
| 投喂 | `donate` | 收款码图片 |
| 源代码 | `source` | B 站视频链接 + GitHub 仓库链接 |

### 修改文字内容

在 `index.html` 中搜索 `pages` 对象，找到对应页面的模板函数，直接修改 HTML。

**示例 — 修改主页标题：**

```javascript
// 找到 pages.home，修改 h1 内容
home: () => `
    <div class="glass-card stagger-1" style="text-align:center;padding:60px 40px;">
        <h1 style="font-size:2.8rem;margin-bottom:16px;">新的标题</h1>
        ...
    </div>
`,
```

### 添加新页面

**第 1 步 — 添加模板：**

在 `const pages` 中添加新函数：

```javascript
mypage: () => `
    <div class="glass-card stagger-1">
        <h1>页面标题</h1>
        <p>页面内容</p>
    </div>
`,
```

**第 2 步 — 添加导航链接：**

在导航栏 HTML 中添加：

```html
<a href="#mypage" data-page="mypage">页面名</a>
```

**第 3 步 — 添加初始化逻辑（可选）：**

如果页面需要加载数据或绑定事件，在 `navigate()` 函数中添加：

```javascript
if (page === 'mypage') initMyPage();
```

### 修改下载链接

在 `pages.download` 中找到下载按钮的 `href` 属性修改：

```html
<a href="EXE/Easy2Sound下载引导包.exe" class="download-card">...</a>
```

### 修改系统要求

在 `pages.home` 中找到 `sys-table` 表格，直接修改 `<td>` 内容。

### 修改视频

在 `pages.home` 中找到 `video-embed` 的 iframe，修改 `bvid` 参数：

```html
<iframe src="https://player.bilibili.com/player.html?bvid=新的BV号&autoplay=0&high_quality=1"
        scrolling="no" allowfullscreen="true"
        sandbox="allow-top-navigation allow-same-origin allow-scripts allow-popups">
</iframe>
```

---

## 样式系统

### 全局样式文件

`导航栏.css` — 包含所有共享样式。

### 主题色

```css
主色渐变：#7c3aed → #3b82f6（紫→蓝）
高亮色：#a78bfa（淡紫）
文字色：#fff（标题）、rgba(255,255,255,0.75)（正文）
```

修改主题色：在 `导航栏.css` 中搜索 `#7c3aed` 和 `#a78bfa` 替换。

### 毛玻璃卡片

```css
.glass-card {
    background: rgba(20, 20, 40, 0.82);  /* 透明度在这里调 */
    backdrop-filter: blur(24px) saturate(160%);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 20px;
}
```

- 增大最后一个数字 → 更不透明（如 `0.90`）
- 减小最后一个数字 → 更透明（如 `0.60`）

### 导航栏

```css
.nav-container {
    background: rgba(12, 12, 28, 0.88);  /* 导航栏背景透明度 */
}
```

### 卡片错开入场动画

使用 CSS stagger 类：

| 类名 | 延迟 |
|------|------|
| `stagger-1` | 0ms |
| `stagger-2` | 80ms |
| `stagger-3` | 160ms |
| `stagger-4` | 240ms |
| `stagger-5` | 320ms |

在页面模板中按顺序给 `glass-card` 添加类名即可：

```html
<div class="glass-card stagger-1">第一张卡片</div>
<div class="glass-card stagger-2">第二张卡片</div>
<div class="glass-card stagger-3">第三张卡片</div>
```

### 声库卡片网格

```css
.vb-grid {
    grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
    gap: 14px;
}
```

- `180px` → 卡片最小宽度，越小一行越多
- `14px` → 卡片间距

### 响应式断点

| 断点 | 布局 |
|------|------|
| `> 768px` | 桌面端，多列网格 |
| `≤ 768px` | 平板，导航换行，声库 3 列 |
| `≤ 480px` | 手机，声库 2 列 |

---

## 安全机制

### 密码安全

**前端：**
- 密码在浏览器端使用 `crypto.subtle.digest('SHA-256', ...)` 哈希
- 传输的是 64 字符十六进制哈希值，不是明文
- 抓包只能看到哈希，无法还原密码

**后端：**
- 数据库存储的是 SHA-256 哈希值
- 登录时比对哈希值，不存储也不处理明文密码

### 表单验证

| 字段 | 前端校验 | 后端校验 |
|------|---------|---------|
| 用户名 | 2-20 字符 | 2-20 字符 + 唯一性检查 |
| 邮箱 | 正则 `/^[^\s@]+@[^\s@]+\.[^\s@]+$/` | 同前端 + 唯一性检查 |
| 密码 | 至少 6 字符 | 检查是否为 64 字符哈希 |

### 登录限流

- 同一 IP 连续 5 次登录失败后，锁定 1 分钟
- 登录成功后清零计数

### 输入过滤

所有用户输入经过 `sanitize()` 函数过滤，转义 `<>"'&` 字符，防止 XSS。

### CORS

API 仅允许来自配置的前端域名的跨域请求，通过环境变量 `FRONTEND_ORIGIN` 控制。

---

## 外部服务

| 服务 | 地址 | 用途 | 可替换 |
|------|------|------|--------|
| 用户 API | `http://localhost:3000` | 登录、注册、更新信息 | 已自建 |
| 头像上传 | `http://localhost:3000` | 上传用户头像 | 已自建 |
| QQ 头像 | `https://q1.qlogo.cn/g?b=qq&nk=QQ号&s=160` | 根据 QQ 号获取头像 | 腾讯服务 |
| B 站播放器 | `https://player.bilibili.com/player.html?bvid=BV号` | 嵌入视频 | B 站服务 |
| 反馈存储 | `https://api.jsonbin.io/v3/b/...` | 云端存储反馈 | 可迁移到自建 |
| Google Fonts | `fonts.googleapis.com` | Noto Sans SC 字体 | 可换本地字体 |

### JSONBin 反馈存储

- **Bin ID:** `69b6a3e2aa77b81da9e7df6c`
- **API Key:** 在 `index.html` 的 `JSONBIN_API_KEY` 常量中
- **数据格式：** `{ feedbacks: [{ timestamp, content, userAgent }] }`
- **缓存机制：** localStorage 缓存，首次慢，之后秒加载

如需迁移到自建存储，替换 `loadFeedbackList()` 和 `submitFeedback()` 函数中的 fetch 地址即可。

---

## 服务器部署

### 方式一：一键部署（推荐）

```bash
# 1. 复制 website/ 目录到服务器
scp -r website/ user@server:/var/www/easy2sound/

# 2. SSH 登录服务器
ssh user@server

# 3. 配置环境变量（可选）
cd /var/www/easy2sound/website
cp api/.env.example api/.env
vim api/.env

# 4. 一键部署
chmod +x deploy.sh
./deploy.sh
```

### 方式二：手动部署

```bash
# 1. 安装依赖
cd website/api
npm install --production

# 2. 配置环境变量
export HOST=your-domain.com
export PORT=3000
export FRONTEND_ORIGIN=http://your-domain.com

# 3. 启动后端（后台运行）
nohup node server.js > api.log 2>&1 &

# 4. 启动前端（后台运行）
cd ..
nohup python3 serve.py > frontend.log 2>&1 &
```

### 方式三：使用 PM2 进程管理（生产环境推荐）

```bash
# 安装 PM2
npm install -g pm2

# 启动后端
cd website/api
HOST=your-domain.com FRONTEND_ORIGIN=http://your-domain.com pm2 start server.js --name easy2sound-api

# 启动前端
cd ..
pm2 start serve.py --interpreter python3 --name easy2sound-web

# 开机自启
pm2 save
pm2 startup
```

### 方式四：使用 Nginx 反向代理（最正规）

**Nginx 配置：**

```nginx
server {
    listen 80;
    server_name your-domain.com;

    # 前端静态文件
    location / {
        root /var/www/easy2sound/website;
        index index.html;
        try_files $uri $uri/ /index.html;
    }

    # API 反向代理
    location /api/ {
        proxy_pass http://127.0.0.1:3000/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # 头像上传文件
    location /uploads/ {
        alias /var/www/easy2sound/website/api/uploads/;
    }
}
```

使用 Nginx 时，前端 API 地址需要改为 `/api`（相对路径），或修改 `index.html` 中的自动检测逻辑。

### 防火墙

确保开放端口：

```bash
# Ubuntu/Debian
sudo ufw allow 80/tcp    # 前端
sudo ufw allow 3000/tcp  # API

# CentOS
sudo firewall-cmd --permanent --add-port=80/tcp
sudo firewall-cmd --permanent --add-port=3000/tcp
sudo firewall-cmd --reload
```

### SSL 证书（HTTPS）

使用 Let's Encrypt：

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

---

## 常见维护任务速查

| 任务 | 改哪里 | 说明 |
|------|--------|------|
| 加声库 | `voicebanks.json` | 改 JSON 即可，不用动 HTML |
| 改声库图片 | 放图到 website/ + 改 JSON `img` | 建议正方形 |
| 加 Demo 音频 | 放 mp3 到 website/ + 改 JSON `demo` | 点击弹窗可试听 |
| 加演示视频 | 改 JSON `bvid` | B 站 BV 号 |
| 改首页文字 | `index.html` → `pages.home` | 搜索 `pages` 对象 |
| 改下载链接 | `index.html` → `pages.download` | 修改 `href` |
| 改系统要求 | `index.html` → `pages.home` 中的 `sys-table` | 修改表格内容 |
| 改视频 | `index.html` → `pages.home` 中的 iframe | 修改 `bvid` 参数 |
| 换背景图 | 替换 `background_board.jpg` | 文件名不能变 |
| 改主题色 | `导航栏.css` 搜索 `#7c3aed` `#a78bfa` | 全局替换 |
| 改毛玻璃透明度 | `导航栏.css` → `.glass-card` 的 `background` | 最后一个数字 |
| 改导航栏透明度 | `导航栏.css` → `.nav-container` 的 `background` | 最后一个数字 |
| 加新页面 | `index.html` → `pages` 对象 + 导航栏 HTML | 参考现有页面 |
| 查看用户 | `node -e "..."` 或 SQLite 工具 | 参考数据库章节 |
| 删除用户 | `node -e "..."` | 参考数据库章节 |
| 备份数据 | `cp api/data.db api/data.db.bak` | 定期备份 |
| 查看日志 | `cat api.log` / `cat frontend.log` | PM2 用 `pm2 logs` |

---

## 故障排查

### 声库页面显示「加载失败」

- **原因**：直接用 `file://` 打开 HTML，fetch 无法加载本地 JSON
- **解决**：用 `python serve.py` 启动后通过 `http://localhost:8080` 访问

### 登录/注册报「网络错误」

- **原因**：后端 API 未启动
- **解决**：`cd api && node server.js`

### 登录报「登录尝试过多」

- **原因**：连续 5 次密码错误触发限流
- **解决**：等 1 分钟自动解锁

### 头像上传失败

- **原因 1**：文件超过 2MB
- **原因 2**：文件格式不是 jpg/png
- **解决**：压缩图片或转换格式

### 反馈列表加载慢

- **原因**：JSONBin API 响应慢（首次加载）
- **说明**：有 localStorage 缓存，第二次访问秒加载

### B 站视频不显示

- **原因 1**：本地用 `file://` 打开（iframe 被浏览器阻止）
- **原因 2**：BV 号错误
- **解决**：用 localhost 访问，检查 BV 号

### 数据库损坏

```bash
# 用备份恢复
cp api/data.db.bak api/data.db

# 或删除数据库重新注册（会丢失所有用户数据）
rm api/data.db
node server.js  # 会自动创建新数据库
```

### 端口被占用

```bash
# 查看占用端口的进程
netstat -tlnp | grep 3000
netstat -tlnp | grep 8080

# 杀掉进程
kill -9 <PID>
```
