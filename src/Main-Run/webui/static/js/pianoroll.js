/**
 * Easy2Sound PianoRoll — 钢琴卷帘引擎
 * Canvas 渲染 + 鼠标交互
 */

class PianoRoll {
    constructor() {
        // ── 常量 ──
        this.TICKS_PER_BEAT = 480;
        this.MIN_NOTE = 0;   // MIDI note 0 = C-1
        this.MAX_NOTE = 127; // MIDI note 127 = G9
        this.BLACK_KEYS = [1, 3, 6, 8, 10]; // C# D# F# G# A#
        this.NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];

        // ── 视图状态 ──
        this.zoomX = 0.15;      // pixels per tick
        this.zoomY = 16;        // pixels per note row (= key height)
        this.scrollX = 0;       // horizontal scroll in ticks
        this.scrollY = 0;       // vertical scroll offset in pixels
        this.minZoomX = 0.02;
        this.maxZoomX = 1.0;

        // ── 数据 ──
        this.notes = [];
        this.selectedNoteIds = new Set();
        this.bpm = 120;
        this.beatsPerBar = 4;

        // ── 工具 ──
        this.currentTool = 'pencil'; // pencil | select | erase

        // ── 交互状态 ──
        this.hoveredNote = null;
        this.dragState = null; // { type: 'move'|'resize-left'|'resize-right', noteId, startX, startY, origNote }
        this.selectionRect = null;
        this.playheadTick = 0;
        this.isPlaying = false;

        // ── 渲染节流 ──
        this._rafId = null;
        this._dirty = false;

        // ── DOM ──
        this.pianoKeysContainer = document.getElementById('piano-keys-container');
        this.pianoKeysCanvas = document.getElementById('piano-keys-canvas');
        this.viewport = document.getElementById('pianoroll-viewport');
        this.canvas = document.getElementById('pianoroll-canvas');
        this.timelineCanvas = document.getElementById('timeline-canvas');
        this.ctx = this.canvas.getContext('2d');
        this.keysCtx = this.pianoKeysCanvas.getContext('2d');
        this.tlCtx = this.timelineCanvas.getContext('2d');

        this._bindEvents();
        this._resizeCanvases();
        this.scrollToPitch(60); // 初始居中到 C4
        window.addEventListener('resize', () => this._resizeCanvases());
    }

    // ════════════════════════════════════════════════════════════════════
    //  坐标换算
    // ════════════════════════════════════════════════════════════════════

    tickToX(tick) {
        return (tick - this.scrollX) * this.zoomX;
    }

    xToTick(x) {
        return x / this.zoomX + this.scrollX;
    }

    pitchToY(pitch) {
        // pitch 127 在顶部，pitch 0 在底部
        const row = (this.MAX_NOTE - pitch);
        return row * this.zoomY - this.scrollY;
    }

    yToPitch(y) {
        const row = (y + this.scrollY) / this.zoomY;
        return this.MAX_NOTE - Math.floor(row);
    }

    noteWidth(note) {
        return note.length * this.zoomX;
    }

    snapTick(tick, snapValue) {
        return Math.round(tick / snapValue) * snapValue;
    }

    getSnapTick() {
        // 网格吸附：默认 1/4 拍 = 120 ticks
        return 120;
    }

    // ════════════════════════════════════════════════════════════════════
    //  数据设置
    // ════════════════════════════════════════════════════════════════════

    setNotes(notes) {
        this.notes = notes || [];
        this.render();
    }

    setBpm(bpm) {
        this.bpm = bpm;
        this.renderTimeline();
    }

    setZoomX(z) {
        this.zoomX = Math.max(this.minZoomX, Math.min(this.maxZoomX, z));
        this._resizeCanvases();
        this.render();
        // 通知 app 更新 zoom 显示
        if (window.app) window.app.updateZoomDisplay();
    }

    zoomIn() { this.setZoomX(this.zoomX * 1.25); }
    zoomOut() { this.setZoomX(this.zoomX / 1.25); }

    scrollToTick(tick) {
        const vpWidth = this.viewport.clientWidth;
        const x = this.tickToX(tick);
        if (x < 0) {
            this.scrollX = tick;
        } else if (x > vpWidth) {
            this.scrollX = tick - vpWidth / this.zoomX;
        }
        this.render();
    }

    scrollToNote(note) {
        this.scrollToTick(note.start);
        const y = this.pitchToY(note.pitch);
        const vpHeight = this.viewport.clientHeight;
        if (y < 0 || y + this.zoomY > vpHeight) {
            this.scrollY = Math.max(0, (this.MAX_NOTE - note.pitch) * this.zoomY - vpHeight / 2);
            this.render();
        }
        this.pianoKeysContainer.scrollTop = this.viewport.scrollTop;
    }

    // ════════════════════════════════════════════════════════════════════
    //  Canvas 尺寸
    // ════════════════════════════════════════════════════════════════════

    _resizeCanvases() {
        const dpr = window.devicePixelRatio || 1;
        const vpW = this.viewport.clientWidth;
        const vpH = this.viewport.clientHeight;

        // 计算内容总宽度（至少到第 100 小节）
        const totalBars = 100;
        const ticksPerBar = this.TICKS_PER_BEAT * this.beatsPerBar;
        const contentW = Math.max(vpW, totalBars * ticksPerBar * this.zoomX);
        const contentH = (this.MAX_NOTE - this.MIN_NOTE + 1) * this.zoomY;

        // 主画布 — 视口尺寸（性能关键：避免巨大像素缓冲区）
        this.canvas.width = vpW * dpr;
        this.canvas.height = vpH * dpr;
        this.canvas.style.width = vpW + 'px';
        this.canvas.style.height = vpH + 'px';
        this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

        // 滚动垫片 — 提供原生滚动条所需的尺寸
        const spacer = document.getElementById('pianoroll-spacer');
        if (spacer) {
            spacer.style.width = Math.max(0, contentW - vpW) + 'px';
            spacer.style.height = Math.max(0, contentH - vpH) + 'px';
        }

        // 钢琴键画布 — 全内容高度（窄，仅 56px 宽，内存开销可忽略）
        const keysW = this.pianoKeysContainer.clientWidth;
        this.pianoKeysCanvas.width = keysW * dpr;
        this.pianoKeysCanvas.height = contentH * dpr;
        this.pianoKeysCanvas.style.width = keysW + 'px';
        this.pianoKeysCanvas.style.height = contentH + 'px';
        this.keysCtx.setTransform(dpr, 0, 0, dpr, 0, 0);

        // 时间线画布 — 与 viewport 等宽，用 margin-left 跳过钢琴键区域
        this.timelineCanvas.width = vpW * dpr;
        this.timelineCanvas.height = 24 * dpr;
        this.timelineCanvas.style.width = vpW + 'px';
        this.timelineCanvas.style.height = '24px';
        this.timelineCanvas.style.marginLeft = keysW + 'px';
        this.tlCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }

    // ════════════════════════════════════════════════════════════════════
    //  渲染
    // ════════════════════════════════════════════════════════════════════

    scrollToPitch(pitch) {
        const vpH = this.viewport.clientHeight;
        const target = Math.max(0, (this.MAX_NOTE - pitch) * this.zoomY - vpH / 2);
        // 直接设 scrollTop，scroll 事件会自动同步 scrollY
        this.viewport.scrollTop = target;
        this.pianoKeysContainer.scrollTop = target;
    }

    render() {
        if (this._rafId) return; // 已有排队的帧，跳过
        this._rafId = requestAnimationFrame(() => {
            this._rafId = null;
            // 主画布已是视口尺寸，tickToX/pitchToY 返回视口相对坐标，直接绘制
            this._drawGrid();
            this._drawNotes();
            this._drawPlayhead();
            this._drawSelectionRect();
            this.renderPianoKeys();
            this.renderTimeline();
        });
    }

    _drawGrid() {
        const ctx = this.ctx;
        const vpW = this.viewport.clientWidth;
        const vpH = this.viewport.clientHeight;
        const w = vpW; // 水平线只需要画到视口宽度

        ctx.clearRect(0, 0, vpW, vpH);

        const ticksPerBar = this.TICKS_PER_BEAT * this.beatsPerBar;

        // 找到可见区域的 tick 范围
        const startTick = Math.max(0, this.xToTick(0));
        const endTick = this.xToTick(w);
        const startBar = Math.floor(startTick / ticksPerBar);
        const endBar = Math.ceil(endTick / ticksPerBar) + 1;

        // 可见 pitch 范围（避免遍历全部 128 个音高）
        const minVP = Math.max(this.MIN_NOTE, this.yToPitch(vpH));
        const maxVP = Math.min(this.MAX_NOTE, this.yToPitch(0));

        // ── 行背景 + 水平线合并（批量绘制） ──
        ctx.strokeStyle = 'rgba(255,255,255,0.04)';
        ctx.lineWidth = 0.5;
        ctx.beginPath();
        let lastLineY = -1;
        for (let pitch = minVP; pitch <= maxVP; pitch++) {
            const y = this.pitchToY(pitch);

            const isBlack = this.BLACK_KEYS.includes(pitch % 12);
            const isC = pitch % 12 === 0;

            // 行背景
            if (isBlack) {
                ctx.fillStyle = 'rgba(255,255,255,0.02)';
                ctx.fillRect(0, y, w, this.zoomY);
            }
            if (isC) {
                ctx.fillStyle = 'rgba(255,255,255,0.03)';
                ctx.fillRect(0, y, w, this.zoomY);
            }

            // C 行线（单独画，样式不同）
            if (isC) {
                ctx.stroke(); // 先刷完普通线
                ctx.strokeStyle = 'rgba(255,255,255,0.12)';
                ctx.lineWidth = 1;
                ctx.beginPath();
                ctx.moveTo(0, y);
                ctx.lineTo(w, y);
                ctx.stroke();
                ctx.strokeStyle = 'rgba(255,255,255,0.04)';
                ctx.lineWidth = 0.5;
                ctx.beginPath();
            } else {
                ctx.moveTo(0, y);
                ctx.lineTo(w, y);
            }
        }
        ctx.stroke(); // 刷完剩余普通线

        // ── 垂直线（拍和小节）──
        // 先画所有小节线（同一样式，一次 stroke）
        ctx.strokeStyle = 'rgba(255,255,255,0.2)';
        ctx.lineWidth = 1;
        ctx.beginPath();
        for (let bar = startBar; bar <= endBar; bar++) {
            const x = this.tickToX(bar * ticksPerBar);
            if (x < 0 || x > vpW) continue;
            ctx.moveTo(x, 0);
            ctx.lineTo(x, vpH);
        }
        ctx.stroke();

        // 画拍线
        ctx.strokeStyle = 'rgba(255,255,255,0.08)';
        ctx.lineWidth = 0.5;
        ctx.beginPath();
        for (let bar = startBar; bar <= endBar; bar++) {
            for (let beat = 1; beat < this.beatsPerBar; beat++) {
                const tick = bar * ticksPerBar + beat * this.TICKS_PER_BEAT;
                const x = this.tickToX(tick);
                if (x < 0 || x > vpW) continue;
                ctx.moveTo(x, 0);
                ctx.lineTo(x, vpH);
            }
        }
        ctx.stroke();

        // 画子拍线
        if (this.zoomX > 0.1) {
            ctx.strokeStyle = 'rgba(255,255,255,0.03)';
            ctx.lineWidth = 0.5;
            ctx.beginPath();
            for (let bar = startBar; bar <= endBar; bar++) {
                for (let beat = 0; beat < this.beatsPerBar; beat++) {
                    const baseTick = bar * ticksPerBar + beat * this.TICKS_PER_BEAT;
                    for (let sub = 1; sub < 4; sub++) {
                        const x = this.tickToX(baseTick + sub * 120);
                        if (x > 0 && x < vpW) {
                            ctx.moveTo(x, 0);
                            ctx.lineTo(x, vpH);
                        }
                    }
                }
            }
            ctx.stroke();
        }
    }

    _drawNotes() {
        const ctx = this.ctx;
        const vpW = this.viewport.clientWidth;
        const vpH = this.viewport.clientHeight;

        for (const note of this.notes) {
            // 休止符不绘制
            if (note.lyric === 'sil') continue;

            const x = this.tickToX(note.start);
            const noteW = this.noteWidth(note);
            const y = this.pitchToY(note.pitch);

            // 裁剪：不在可见区域就跳过
            if (x + noteW < 0 || x > vpW || y + this.zoomY < 0 || y > vpH) continue;

            const isSelected = this.selectedNoteIds.has(note.id);
            const isHovered = this.hoveredNote && this.hoveredNote.id === note.id;

            // 音符矩形 — 无间隙 + 圆角 + 边框
            // 用终点反算宽度，消除浮点误差导致的缝隙
            const x2 = this.tickToX(note.start + note.length);
            const nw = Math.max(x2 - x, 4);
            const r = 2;

            // 同一条路径：先填充再描边，避免角点伪影
            ctx.beginPath();
            ctx.roundRect(x, y, nw, this.zoomY, r);

            if (isSelected) {
                ctx.fillStyle = '#f85149';
            } else {
                const vel = (note.velocity || 100) / 100;
                const r2 = Math.round(31 + vel * 40);
                const g = Math.round(111 + vel * 60);
                const b = Math.round(235);
                ctx.fillStyle = `rgb(${r2},${g},${b})`;
            }
            ctx.fill();

            ctx.strokeStyle = isSelected ? '#ffffff' : (isHovered ? '#58a6ff' : 'rgba(0,0,0,0.6)');
            ctx.lineWidth = 1.5;
            ctx.stroke();

            // 歌词文字
            if (nw > 16 && this.zoomY >= 12) {
                ctx.fillStyle = '#ffffff';
                ctx.font = `${Math.min(10, this.zoomY - 3)}px 'Segoe UI', sans-serif`;
                ctx.textBaseline = 'middle';
                ctx.save();
                ctx.beginPath();
                ctx.rect(x + 2, y, nw - 4, this.zoomY);
                ctx.clip();
                ctx.fillText(note.lyric || '', x + 3, y + this.zoomY / 2);
                ctx.restore();
            }

            // 拖拽手柄指示
            if (isHovered || isSelected) {
                ctx.fillStyle = 'rgba(255,255,255,0.6)';
                ctx.fillRect(x + nw - 4, y + 2, 2, this.zoomY - 4);
            }

            // 音高曲线
            this._drawPitchLine(note, x, y, nw);
        }
    }

    // ════════════════════════════════════════════════════════════════════
    //  音高曲线解码 & 绘制
    // ════════════════════════════════════════════════════════════════════

    static _getDecodeTable() {
        if (PianoRoll._decodeTbl) return PianoRoll._decodeTbl;
        const tbl = {};
        const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
        for (let i = 0; i < chars.length; i++) tbl[chars[i]] = i;
        PianoRoll._decodeTbl = tbl;
        return tbl;
    }

    /**
     * 解码 pitch_string → cents 偏移数组
     * 每 2 字符 = 1 个采样点，12-bit 有符号整数 (-2048~2047)
     * 100 cents = 1 半音
     */
    decodePitchString(pitchStr) {
        if (!pitchStr || pitchStr.length < 2) return [];
        const tbl = PianoRoll._getDecodeTable();
        const pts = [];
        let i = 0;
        while (i < pitchStr.length) {
            const ch = pitchStr[i];
            if (ch === '#') {
                const nextHash = pitchStr.indexOf('#', i + 1);
                if (nextHash === -1) break;
                const count = parseInt(pitchStr.substring(i + 1, nextHash), 10);
                const lastVal = pts.length > 0 ? pts[pts.length - 1] : 0;
                for (let r = 0; r < count; r++) pts.push(lastVal);
                i = nextHash + 1;
            } else {
                if (i + 1 >= pitchStr.length) break;
                const hi = tbl[pitchStr[i]];
                const lo = tbl[pitchStr[i + 1]];
                if (hi === undefined || lo === undefined) { i += 2; continue; }
                let val = hi * 64 + lo;
                if (val >= 2048) val -= 4096;
                pts.push(val);
                i += 2;
            }
        }
        return pts;
    }

    /**
     * 在音符上绘制音高曲线
     * @param {Object} note - 音符对象
     * @param {number} x - 音符矩形左边界（tickToX 转换后）
     * @param {number} y - 音符矩形上边界（pitchToY 转换后）
     * @param {number} nw - 音符矩形像素宽度
     */
    _drawPitchLine(note, x, y, nw) {
        const ps = note.pitch_string;
        if (!ps || ps.length < 2) return;
        const pts = this.decodePitchString(ps);
        if (pts.length === 0) return;

        const ctx = this.ctx;
        if (nw < 2) return;

        ctx.strokeStyle = 'rgba(255, 230, 100, 0.85)';
        ctx.lineWidth = 1.5;
        ctx.beginPath();

        const basePitch = note.pitch;
        const ticksPerSample = 5;

        for (let i = 0; i < pts.length; i++) {
            const pitch = basePitch + pts[i] / 100;
            const tick = note.start + i * ticksPerSample;
            const px = this.tickToX(tick);
            const py = this.pitchToY(pitch) + this.zoomY / 2;
            if (i === 0) ctx.moveTo(px, py);
            else ctx.lineTo(px, py);
        }
        ctx.stroke();
    }

    _drawPlayhead() {
        const x = this.tickToX(this.playheadTick);
        const vpW = this.viewport.clientWidth;
        if (x < 0 || x > vpW) return;

        const ctx = this.ctx;
        const vpH = this.viewport.clientHeight;
        ctx.strokeStyle = '#f85149';
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, vpH);
        ctx.stroke();

        // 顶部三角
        ctx.fillStyle = '#f85149';
        ctx.beginPath();
        ctx.moveTo(x - 5, 0);
        ctx.lineTo(x + 5, 0);
        ctx.lineTo(x, 8);
        ctx.closePath();
        ctx.fill();
    }

    _drawSelectionRect() {
        if (!this.selectionRect) return;
        const ctx = this.ctx;
        const { x, y, w, h } = this.selectionRect;
        ctx.fillStyle = 'rgba(31, 111, 235, 0.1)';
        ctx.strokeStyle = '#58a6ff';
        ctx.lineWidth = 1;
        ctx.fillRect(x, y, w, h);
        ctx.setLineDash([4, 4]);
        ctx.strokeRect(x, y, w, h);
        ctx.setLineDash([]);
    }

    // ════════════════════════════════════════════════════════════════════
    //  钢琴键渲染
    // ════════════════════════════════════════════════════════════════════

    renderPianoKeys() {
        const ctx = this.keysCtx;
        const w = this.pianoKeysCanvas.width / (window.devicePixelRatio || 1);
        const vpH = this.viewport.clientHeight;
        const scrollTop = this.pianoKeysContainer.scrollTop;

        // 画布是全内容高度，用 translate 把视口相对坐标映射到 canvas 像素坐标
        ctx.save();
        ctx.translate(0, scrollTop);
        ctx.clearRect(0, 0, w, vpH);

        // 可见 pitch 范围
        const minVP = Math.max(this.MIN_NOTE, this.yToPitch(vpH));
        const maxVP = Math.min(this.MAX_NOTE, this.yToPitch(0));
        const showAllLabels = this.zoomY >= 14;

        // 只画可见区域的键
        for (let pitch = minVP; pitch <= maxVP; pitch++) {
            const y = this.pitchToY(pitch);
            const isBlack = this.BLACK_KEYS.includes(pitch % 12);
            const isC = pitch % 12 === 0;

            // 键背景
            if (isBlack) {
                ctx.fillStyle = '#21262d';
                ctx.fillRect(0, y, w * 0.7, this.zoomY);
            } else {
                ctx.fillStyle = '#c9d1d9';
                ctx.fillRect(0, y, w, this.zoomY);
            }

            // 音名标签
            if (isC || showAllLabels) {
                const name = this.NOTE_NAMES[pitch % 12];
                const octave = Math.floor(pitch / 12) - 1;
                ctx.fillStyle = isBlack ? '#8b949e' : '#30363d';
                ctx.font = `${Math.min(10, this.zoomY - 2)}px 'Segoe UI', sans-serif`;
                ctx.textBaseline = 'middle';
                ctx.fillText(
                    isC ? `C${octave}` : name,
                    4,
                    y + this.zoomY / 2
                );
            }
        }

        // 批量画分隔线
        ctx.strokeStyle = 'rgba(0,0,0,0.3)';
        ctx.lineWidth = 0.5;
        ctx.beginPath();
        for (let pitch = minVP; pitch <= maxVP; pitch++) {
            const y = this.pitchToY(pitch);
            ctx.moveTo(0, y);
            ctx.lineTo(w, y);
        }
        ctx.stroke();
        ctx.restore();
    }

    // ════════════════════════════════════════════════════════════════════
    //  时间线渲染
    // ════════════════════════════════════════════════════════════════════

    renderTimeline() {
        const ctx = this.tlCtx;
        const w = this.timelineCanvas.width / (window.devicePixelRatio || 1);
        const h = 24;

        ctx.clearRect(0, 0, w, h);
        ctx.fillStyle = '#161b22';
        ctx.fillRect(0, 0, w, h);

        const ticksPerBar = this.TICKS_PER_BEAT * this.beatsPerBar;
        const startTick = this.xToTick(0);
        const endTick = this.xToTick(w);
        const startBar = Math.floor(startTick / ticksPerBar);
        const endBar = Math.ceil(endTick / ticksPerBar) + 1;

        for (let bar = startBar; bar <= endBar; bar++) {
            const x = this.tickToX(bar * ticksPerBar);
            if (x < -50 || x > w + 50) continue;

            // 小节线
            ctx.strokeStyle = 'rgba(255,255,255,0.3)';
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(x, 14);
            ctx.lineTo(x, h);
            ctx.stroke();

            // 小节号
            ctx.fillStyle = '#8b949e';
            ctx.font = '10px "Segoe UI", sans-serif';
            ctx.textBaseline = 'top';
            ctx.fillText(String(bar + 1), x + 3, 2);

            // 拍线
            for (let beat = 1; beat < this.beatsPerBar; beat++) {
                const bx = this.tickToX(bar * ticksPerBar + beat * this.TICKS_PER_BEAT);
                if (bx > 0 && bx < w) {
                    ctx.strokeStyle = 'rgba(255,255,255,0.12)';
                    ctx.lineWidth = 0.5;
                    ctx.beginPath();
                    ctx.moveTo(bx, 18);
                    ctx.lineTo(bx, h);
                    ctx.stroke();
                }
            }
        }

        // 播放头
        if (this.isPlaying) {
            const phX = this.tickToX(this.playheadTick);
            if (phX >= 0 && phX <= w) {
                ctx.fillStyle = '#f85149';
                ctx.beginPath();
                ctx.moveTo(phX - 4, 0);
                ctx.lineTo(phX + 4, 0);
                ctx.lineTo(phX, 6);
                ctx.closePath();
                ctx.fill();
            }
        }
    }

    // ════════════════════════════════════════════════════════════════════
    //  事件处理
    // ════════════════════════════════════════════════════════════════════

    _bindEvents() {
        // ── 滚动同步 ──
        this.viewport.addEventListener('scroll', () => {
            this.scrollX = this.viewport.scrollLeft / this.zoomX;
            this.scrollY = this.viewport.scrollTop;
            // 钢琴键面板垂直滚动同步
            this.pianoKeysContainer.scrollTop = this.viewport.scrollTop;
            this.render();
        });

        // ── 鼠标事件 ──
        this.canvas.addEventListener('mousedown', (e) => this._onMouseDown(e));
        this.canvas.addEventListener('mousemove', (e) => this._onMouseMove(e));
        this.canvas.addEventListener('mouseup', (e) => this._onMouseUp(e));
        this.canvas.addEventListener('mouseleave', () => {
            this.hoveredNote = null;
            this.render();
        });

        // ── 鼠标滚轮缩放 ──
        this.viewport.addEventListener('wheel', (e) => {
            if (e.ctrlKey || e.metaKey) {
                e.preventDefault();
                if (e.deltaY < 0) {
                    this.zoomIn();
                } else {
                    this.zoomOut();
                }
            }
        }, { passive: false });

        // ── 时间线点击跳转 ──
        this.timelineCanvas.addEventListener('mousedown', (e) => {
            const rect = this.timelineCanvas.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const tick = this.xToTick(x);
            this.playheadTick = Math.max(0, tick);
            this.render();
            if (window.app) window.app.onPlayheadChange(this.playheadTick);
        });

        // ── 钢琴键点击发声 ──
        this.pianoKeysCanvas.addEventListener('mousedown', (e) => {
            const rect = this.pianoKeysCanvas.getBoundingClientRect();
            const y = e.clientY - rect.top;
            const pitch = this.yToPitch(y);
            if (pitch >= 0 && pitch <= 127) {
                if (window.app) window.app.previewPitch(pitch);
            }
        });

        // ── 右键菜单 ──
        this.canvas.addEventListener('contextmenu', (e) => {
            e.preventDefault();
            if (window.app) window.app.showContextMenu(e.clientX, e.clientY);
        });
    }

    _getMousePos(e) {
        const rect = this.canvas.getBoundingClientRect();
        return {
            x: e.clientX - rect.left,
            y: e.clientY - rect.top
        };
    }

    _hitTest(mx, my) {
        // 从后往前遍历（后画的在上面）
        for (let i = this.notes.length - 1; i >= 0; i--) {
            const note = this.notes[i];
            const x = this.tickToX(note.start);
            const w = this.noteWidth(note);
            const y = this.pitchToY(note.pitch);
            if (mx >= x && mx <= x + w && my >= y && my <= y + this.zoomY) {
                return note;
            }
        }
        return null;
    }

    _hitTestEdge(mx, my) {
        // 检测是否在音符右边缘（调整大小用）
        for (let i = this.notes.length - 1; i >= 0; i--) {
            const note = this.notes[i];
            const x = this.tickToX(note.start);
            const w = this.noteWidth(note);
            const y = this.pitchToY(note.pitch);
            if (mx >= x + w - 6 && mx <= x + w + 2 && my >= y && my <= y + this.zoomY) {
                return { note, edge: 'right' };
            }
            if (mx >= x - 2 && mx <= x + 4 && my >= y && my <= y + this.zoomY) {
                return { note, edge: 'left' };
            }
        }
        return null;
    }

    _onMouseDown(e) {
        if (e.button !== 0) return;
        const pos = this._getMousePos(e);
        const tick = this.xToTick(pos.x);
        const pitch = this.yToPitch(pos.y);
        const snap = this.getSnapTick();
        const snappedTick = this.snapTick(tick, snap);

        if (this.currentTool === 'pencil') {
            const hit = this._hitTest(pos.x, pos.y);
            if (hit) {
                // 检查是否在边缘
                const edge = this._hitTestEdge(pos.x, pos.y);
                if (edge) {
                    this.dragState = {
                        type: edge.edge === 'right' ? 'resize-right' : 'resize-left',
                        noteId: edge.note.id,
                        startX: pos.x,
                        startY: pos.y,
                        origNote: { ...edge.note }
                    };
                    return;
                }
                // 点击已有音符 → 切换到移动
                this.dragState = {
                    type: 'move',
                    noteId: hit.id,
                    startX: pos.x,
                    startY: pos.y,
                    origNote: { ...hit }
                };
                return;
            }
            // 新建音符
            const newNote = {
                id: this._genId(),
                lyric: 'あ',
                phoneme: '',
                pitch: pitch,
                length: snap,
                velocity: 100,
                start: snappedTick,
                flags: '',
                offset: 0,
                consonant: 0,
                cutoff: 0,
                modulation: 0,
                pitch_string: '',
                intensity: '100'
            };
            this.notes.push(newNote);
            this.selectedNoteIds.clear();
            this.selectedNoteIds.add(newNote.id);
            this.render();
            if (window.app) {
                window.app.onNotesChanged();
                window.app.selectNote(newNote);
            }
        } else if (this.currentTool === 'select') {
            const hit = this._hitTest(pos.x, pos.y);
            if (hit) {
                const edge = this._hitTestEdge(pos.x, pos.y);
                if (edge) {
                    this.dragState = {
                        type: edge.edge === 'right' ? 'resize-right' : 'resize-left',
                        noteId: edge.note.id,
                        startX: pos.x,
                        startY: pos.y,
                        origNote: { ...edge.note }
                    };
                    return;
                }
                if (!e.shiftKey && !this.selectedNoteIds.has(hit.id)) {
                    this.selectedNoteIds.clear();
                }
                this.selectedNoteIds.add(hit.id);
                this.dragState = {
                    type: 'move',
                    noteId: hit.id,
                    startX: pos.x,
                    startY: pos.y,
                    origNote: { ...hit }
                };
                this.render();
                if (window.app) window.app.selectNote(hit);
            } else {
                // 开始框选
                if (!e.shiftKey) this.selectedNoteIds.clear();
                this.dragState = {
                    type: 'select',
                    startX: pos.x,
                    startY: pos.y
                };
                this.selectionRect = null;
                this.render();
            }
        } else if (this.currentTool === 'erase') {
            const hit = this._hitTest(pos.x, pos.y);
            if (hit) {
                this.notes = this.notes.filter(n => n.id !== hit.id);
                this.selectedNoteIds.delete(hit.id);
                this.render();
                if (window.app) {
                    window.app.onNotesChanged();
                    window.app.selectNote(null);
                }
            }
        }
    }

    _onMouseMove(e) {
        const pos = this._getMousePos(e);

        if (this.dragState) {
            const dx = pos.x - this.dragState.startX;
            const dy = pos.y - this.dragState.startY;
            const snap = this.getSnapTick();

            if (this.dragState.type === 'move') {
                const note = this.notes.find(n => n.id === this.dragState.noteId);
                if (!note) return;
                const dtick = dx / this.zoomX;
                const dpitch = Math.round(-dy / this.zoomY);
                note.start = Math.max(0, this.snapTick(this.dragState.origNote.start + dtick, snap));
                note.pitch = Math.max(0, Math.min(127, this.dragState.origNote.pitch + dpitch));
                this.render();
            } else if (this.dragState.type === 'resize-right') {
                const note = this.notes.find(n => n.id === this.dragState.noteId);
                if (!note) return;
                const dtick = dx / this.zoomX;
                note.length = Math.max(snap, this.snapTick(this.dragState.origNote.length + dtick, snap));
                this.render();
            } else if (this.dragState.type === 'resize-left') {
                const note = this.notes.find(n => n.id === this.dragState.noteId);
                if (!note) return;
                const dtick = dx / this.zoomX;
                const newStart = this.snapTick(this.dragState.origNote.start + dtick, snap);
                const newLen = this.dragState.origNote.length + (this.dragState.origNote.start - newStart);
                if (newLen >= snap) {
                    note.start = newStart;
                    note.length = newLen;
                }
                this.render();
            } else if (this.dragState.type === 'select') {
                const sx = Math.min(this.dragState.startX, pos.x);
                const sy = Math.min(this.dragState.startY, pos.y);
                const sw = Math.abs(pos.x - this.dragState.startX);
                const sh = Math.abs(pos.y - this.dragState.startY);
                this.selectionRect = { x: sx, y: sy, w: sw, h: sh };

                // 框选中的音符
                this.selectedNoteIds.clear();
                for (const note of this.notes) {
                    const nx = this.tickToX(note.start);
                    const nw = this.noteWidth(note);
                    const ny = this.pitchToY(note.pitch);
                    if (nx + nw > sx && nx < sx + sw && ny + this.zoomY > sy && ny < sy + sh) {
                        this.selectedNoteIds.add(note.id);
                    }
                }
                this.render();
            }
            return;
        }

        // Hover 检测
        const old = this.hoveredNote;
        this.hoveredNote = this._hitTest(pos.x, pos.y);

        // 光标样式
        if (this.currentTool === 'pencil' || this.currentTool === 'select') {
            const edge = this._hitTestEdge(pos.x, pos.y);
            if (edge) {
                this.canvas.style.cursor = 'ew-resize';
            } else if (this.hoveredNote) {
                this.canvas.style.cursor = this.currentTool === 'pencil' ? 'move' : 'default';
            } else {
                this.canvas.style.cursor = this.currentTool === 'pencil' ? 'crosshair' : 'default';
            }
        } else if (this.currentTool === 'erase') {
            this.canvas.style.cursor = 'pointer';
        }

        if (old !== this.hoveredNote) {
            this.render();
        }
    }

    _onMouseUp(e) {
        if (!this.dragState) return;

        if (this.dragState.type === 'select') {
            this.selectionRect = null;
        }

        this.dragState = null;
        this.render();

        if (window.app) {
            window.app.onNotesChanged();
            const selected = this.notes.filter(n => this.selectedNoteIds.has(n.id));
            if (selected.length === 1) {
                window.app.selectNote(selected[0]);
            } else if (selected.length === 0) {
                window.app.selectNote(null);
            }
        }
    }

    // ════════════════════════════════════════════════════════════════════
    //  选中操作
    // ════════════════════════════════════════════════════════════════════

    selectNote(note) {
        this.selectedNoteIds.clear();
        if (note) this.selectedNoteIds.add(note.id);
        this.render();
    }

    selectAll() {
        this.selectedNoteIds = new Set(this.notes.map(n => n.id));
        this.render();
    }

    deleteSelected() {
        this.notes = this.notes.filter(n => !this.selectedNoteIds.has(n.id));
        this.selectedNoteIds.clear();
        this.render();
        if (window.app) {
            window.app.onNotesChanged();
            window.app.selectNote(null);
        }
    }

    getSelectedNotes() {
        return this.notes.filter(n => this.selectedNoteIds.has(n.id));
    }

    // ════════════════════════════════════════════════════════════════════
    //  工具辅助
    // ════════════════════════════════════════════════════════════════════

    _genId() {
        return Math.random().toString(36).substring(2, 10);
    }
}

// 全局实例
const pianoRoll = new PianoRoll();
