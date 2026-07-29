const express = require('express');
const cors = require('cors');
const crypto = require('crypto');
const path = require('path');
const multer = require('multer');
const Database = require('better-sqlite3');

const app = express();
const PORT = process.env.PORT || 3000;
const HOST = process.env.HOST || 'localhost';
const FRONTEND_ORIGIN = process.env.FRONTEND_ORIGIN || `http://${HOST}:8080`;

// ========== 数据库（SQLite） ==========
const db = new Database(path.join(__dirname, 'data.db'));

// 建表
db.exec(`
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        email TEXT UNIQUE NOT NULL,
        passwordHash TEXT NOT NULL,
        qq TEXT DEFAULT '',
        avatar TEXT DEFAULT '',
        createdAt TEXT NOT NULL
    )
`);

// 预编译 SQL
const stmts = {
    insertUser: db.prepare('INSERT INTO users (id, username, email, passwordHash, qq, avatar, createdAt) VALUES (?, ?, ?, ?, ?, ?, ?)'),
    findByUsername: db.prepare('SELECT * FROM users WHERE username = ?'),
    findByEmail: db.prepare('SELECT * FROM users WHERE email = ?'),
    findById: db.prepare('SELECT * FROM users WHERE id = ?'),
    updateUser: db.prepare('UPDATE users SET qq = ?, avatar = ? WHERE id = ?'),
};

// ========== 中间件 ==========
app.use(cors({ origin: [FRONTEND_ORIGIN, `http://${HOST}:3000`, `http://${HOST}:8080`] }));
app.use(express.json({ limit: '1mb' }));

app.use((req, res, next) => {
    console.log(`[${new Date().toLocaleTimeString()}] ${req.method} ${req.path}`);
    next();
});

// ========== 工具函数 ==========
function sha256(str) {
    return crypto.createHash('sha256').update(str).digest('hex');
}

function genId() {
    return 'u_' + crypto.randomBytes(8).toString('hex');
}

function sanitize(str) {
    return String(str || '').replace(/[<>"'&]/g, '');
}

function safeUser(row) {
    if (!row) return null;
    const { passwordHash, ...rest } = row;
    return rest;
}

// ========== 输入校验 ==========
function validateUsername(u) {
    return typeof u === 'string' && u.length >= 2 && u.length <= 20;
}

function validateEmail(e) {
    return typeof e === 'string' && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(e);
}

function validatePassword(p) {
    return typeof p === 'string' && p.length === 64; // SHA-256 固定 64 字符
}

// ========== 登录限流 ==========
const loginAttempts = {};
const MAX_ATTEMPTS = 5;
const LOCKOUT_MS = 60 * 1000;

function checkRateLimit(ip) {
    const now = Date.now();
    const entry = loginAttempts[ip];
    if (!entry) return true;
    if (now - entry.lastAttempt > LOCKOUT_MS) {
        delete loginAttempts[ip];
        return true;
    }
    return entry.count < MAX_ATTEMPTS;
}

function recordAttempt(ip) {
    const now = Date.now();
    if (!loginAttempts[ip]) loginAttempts[ip] = { count: 0, lastAttempt: now };
    loginAttempts[ip].count++;
    loginAttempts[ip].lastAttempt = now;
}

function clearAttempts(ip) {
    delete loginAttempts[ip];
}

// ========== 文件上传 ==========
const uploadsDir = path.join(__dirname, 'uploads');
const fs = require('fs');
if (!fs.existsSync(uploadsDir)) fs.mkdirSync(uploadsDir);

const storage = multer.diskStorage({
    destination: uploadsDir,
    filename: (req, file, cb) => {
        const ext = path.extname(file.originalname).toLowerCase();
        cb(null, `avatar_${Date.now()}${ext}`);
    }
});

const upload = multer({
    storage,
    limits: { fileSize: 2 * 1024 * 1024 },
    fileFilter: (req, file, cb) => {
        if (['image/jpeg', 'image/png'].includes(file.mimetype)) cb(null, true);
        else cb(new Error('仅支持 jpg/png 格式'));
    }
});

app.use('/uploads', express.static(uploadsDir));

// ========== API 路由 ==========

// 注册
app.post('/register', (req, res) => {
    const { username, email, password, qq } = req.body;

    if (!validateUsername(username)) return res.json({ ok: false, error: '用户名需 2-20 个字符' });
    if (!validateEmail(email)) return res.json({ ok: false, error: '请输入有效的邮箱地址' });
    if (!validatePassword(password)) return res.json({ ok: false, error: '密码格式错误' });

    if (stmts.findByUsername.get(username)) {
        return res.json({ ok: false, error: '用户名已存在' });
    }
    if (stmts.findByEmail.get(email)) {
        return res.json({ ok: false, error: '邮箱已被注册' });
    }

    const id = genId();
    const avatar = qq ? `https://q1.qlogo.cn/g?b=qq&nk=${qq}&s=160` : '';
    const createdAt = new Date().toISOString();

    stmts.insertUser.run(id, sanitize(username), sanitize(email), password, sanitize(qq || ''), sanitize(avatar), createdAt);

    console.log(`[注册] ${username} (${id})`);
    res.json({ ok: true });
});

// 登录
app.post('/login', (req, res) => {
    const ip = req.ip || req.connection.remoteAddress;

    if (!checkRateLimit(ip)) {
        return res.json({ ok: false, error: '登录尝试过多，请 1 分钟后再试' });
    }

    const { username, password } = req.body;
    if (!username || !password) {
        return res.json({ ok: false, error: '请输入用户名和密码' });
    }

    const user = stmts.findByUsername.get(username);
    if (!user || user.passwordHash !== password) {
        recordAttempt(ip);
        return res.json({ ok: false, error: '用户名或密码错误' });
    }

    clearAttempts(ip);
    console.log(`[登录] ${user.username} (${user.id})`);
    res.json({ ok: true, user: safeUser(user) });
});

// 更新用户信息
app.post('/update-user-info', (req, res) => {
    const { userId, qq, avatar } = req.body;
    if (!userId) return res.json({ ok: false, error: '缺少用户 ID' });

    const user = stmts.findById.get(userId);
    if (!user) return res.json({ ok: false, error: '用户不存在' });

    const newQq = qq !== undefined ? sanitize(qq) : user.qq;
    const newAvatar = avatar !== undefined ? sanitize(avatar) : user.avatar;

    stmts.updateUser.run(newQq, newAvatar, userId);

    const updated = stmts.findById.get(userId);
    console.log(`[更新] ${updated.username} (${updated.id})`);
    res.json({ ok: true, user: safeUser(updated) });
});

// 头像上传
app.post('/', upload.single('avatar'), (req, res) => {
    try {
        if (!req.file) return res.json({ success: false, message: '未收到文件' });
        const url = `http://${HOST}:${PORT}/uploads/${req.file.filename}`;
        console.log(`[上传] ${req.file.filename} (${req.file.size} bytes)`);
        res.json({ success: true, url });
    } catch (e) {
        res.json({ success: false, message: e.message });
    }
});

// 错误处理
app.use((err, req, res, next) => {
    if (err instanceof multer.MulterError) {
        return res.json({ success: false, message: `上传错误: ${err.message}` });
    }
    console.error(err);
    res.status(500).json({ ok: false, error: '服务器内部错误' });
});

// 健康检查
app.get('/', (req, res) => {
    res.json({ status: 'ok', name: 'Easy2Sound API', version: '1.0.0', db: 'SQLite' });
});

// ========== 启动 ==========
app.listen(PORT, '0.0.0.0', () => {
    console.log(`\n✅ Easy2Sound API 已启动: http://${HOST}:${PORT}`);
    console.log(`📁 数据库: ${path.join(__dirname, 'data.db')}`);
    console.log(`🌐 前端域名: ${FRONTEND_ORIGIN}\n`);
});
