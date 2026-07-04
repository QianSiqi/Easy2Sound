/**
 * Easy2Sound App — 应用层控制器
 * 绑定所有工具栏/菜单/快捷键，管理项目状态，与后端 API 通信
 */

class Easy2SoundApp {
    constructor() {
        this.pianoRoll = pianoRoll;
        this.currentTrackId = null;
        this.tracks = [];
        this.bpm = 120;
        this.projectName = 'Untitled';

        // 撤销/重做
        this.undoStack = [];
        this.redoStack = [];
        this.maxUndo = 50;

        // 当前活跃工具按钮组（互斥）
        this.toolButtons = ['btn-pencil', 'btn-select', 'btn-erase'];

        // phonemer
        this.phonemerList = [];
        this._phonemerPending = false;

        this._bindToolbar();
        this._bindMenus();
        this._bindKeyboard();
        this._bindPropertyPanel();
        this._bindContextMenu();
        this._bindFileInput();
        this._loadProject();
    }

    // ════════════════════════════════════════════════════════════════════
    //  初始化加载
    // ════════════════════════════════════════════════════════════════════

    async _loadProject() {
        try {
            const res = await fetch('/api/project');
            const data = await res.json();
            this.tracks = data.tracks || [];
            this.bpm = data.bpm || 120;
            this.projectName = data.name || 'Untitled';
            document.title = `${this.projectName} - Easy2Sound`;

            // 设置 BPM 输入
            const bpmInput = document.getElementById('input-bpm');
            if (bpmInput) bpmInput.value = this.bpm;
            this.pianoRoll.setBpm(this.bpm);

            // 加载第一个轨道的音符
            if (this.tracks.length > 0) {
                this.currentTrackId = this.tracks[0].id;
                this.pianoRoll.setNotes(this.tracks[0].notes || []);
            }
            this._renderTrackList();
            this._updateStatusBar();

            // 加载 phonemer 列表
            await this._loadPhonemerList();
            this._renderTrackList();
        } catch (e) {
            console.error('Failed to load project:', e);
        }
    }

    // ════════════════════════════════════════════════════════════════════
    //  工具栏绑定
    // ════════════════════════════════════════════════════════════════════

    _bindToolbar() {
        const $ = (id) => document.getElementById(id);
        const pr = this.pianoRoll;

        // ── 文件操作 ──
        $('btn-new')?.addEventListener('click', () => this.newProject());
        $('btn-open')?.addEventListener('click', () => this.openProject());
        $('btn-save')?.addEventListener('click', () => this.saveProject());

        // ── 运输控制 ──
        $('btn-rewind')?.addEventListener('click', () => {
            pr.playheadTick = 0;
            pr.render();
        });
        $('btn-play')?.addEventListener('click', () => this.togglePlay());
        $('btn-stop')?.addEventListener('click', () => {
            pr.playheadTick = 0;
            pr.isPlaying = false;
            pr.render();
            this._updateStatusBar();
        });

        // ── 撤销/重做 ──
        $('btn-undo')?.addEventListener('click', () => this.undo());
        $('btn-redo')?.addEventListener('click', () => this.redo());

        // ── 工具切换 ──
        $('btn-pencil')?.addEventListener('click', () => this._setTool('pencil'));
        $('btn-select')?.addEventListener('click', () => this._setTool('select'));
        $('btn-erase')?.addEventListener('click', () => this._setTool('erase'));

        // ── 缩放 ──
        $('btn-zoom-in')?.addEventListener('click', () => pr.zoomIn());
        $('btn-zoom-out')?.addEventListener('click', () => pr.zoomOut());

        // ── BPM ──
        $('input-bpm')?.addEventListener('change', (e) => {
            this.bpm = parseFloat(e.target.value) || 120;
            pr.setBpm(this.bpm);
        });

        // ── 拍号 ──
        $('select-time-sig')?.addEventListener('change', (e) => {
            const parts = e.target.value.split('/');
            pr.beatsPerBar = parseInt(parts[0]) || 4;
            pr.render();
        });

        // ── MIDI 导入/导出 ──
        $('btn-import-midi')?.addEventListener('click', () => {
            document.getElementById('file-input')?.click();
        });
        $('btn-export-midi')?.addEventListener('click', () => this.exportMidi());

        // ── 添加轨道 ──
        $('btn-add-track')?.addEventListener('click', () => this.addTrack());
    }

    _setTool(tool) {
        this.pianoRoll.currentTool = tool;
        // 更新按钮状态
        this.toolButtons.forEach((id) => {
            const btn = document.getElementById(id);
            if (btn) btn.classList.remove('active');
        });
        const activeId = `btn-${tool}`;
        const activeBtn = document.getElementById(activeId);
        if (activeBtn) activeBtn.classList.add('active');
    }

    // ════════════════════════════════════════════════════════════════════
    //  播放（占位，后续接 server.py 渲染）
    // ════════════════════════════════════════════════════════════════════

    togglePlay() {
        const pr = this.pianoRoll;
        // 简单的播放头模拟
        if (this._playInterval) {
            clearInterval(this._playInterval);
            this._playInterval = null;
            pr.isPlaying = false;
            document.getElementById('btn-play')?.classList.remove('active');
            this._updateStatusBar();
            pr.render();
            return;
        }
        pr.isPlaying = true;
        document.getElementById('btn-play')?.classList.add('active');
        const ticksPerBeat = 480;
        const ticksPerSec = (this.bpm / 60) * ticksPerBeat;
        const frameInterval = 1000 / 60;

        this._playInterval = setInterval(() => {
            this.pianoRoll.playheadTick += ticksPerSec * (frameInterval / 1000);
            // 滚动跟随
            this.pianoRoll.scrollToTick(this.pianoRoll.playheadTick);
            this.pianoRoll.render();
        }, frameInterval);

        this._updateStatusBar('播放中...');
    }

    // ════════════════════════════════════════════════════════════════════
    //  撤销 / 重做
    // ════════════════════════════════════════════════════════════════════

    _pushUndo() {
        this.undoStack.push(JSON.parse(JSON.stringify(this.pianoRoll.notes)));
        if (this.undoStack.length > this.maxUndo) this.undoStack.shift();
        this.redoStack = [];
    }

    undo() {
        if (this.undoStack.length === 0) return;
        this.redoStack.push(JSON.parse(JSON.stringify(this.pianoRoll.notes)));
        this.pianoRoll.notes = this.undoStack.pop();
        this.pianoRoll.selectedNoteIds.clear();
        this.pianoRoll.render();
        this._syncNotesToTrack();
    }

    redo() {
        if (this.redoStack.length === 0) return;
        this.undoStack.push(JSON.parse(JSON.stringify(this.pianoRoll.notes)));
        this.pianoRoll.notes = this.redoStack.pop();
        this.pianoRoll.selectedNoteIds.clear();
        this.pianoRoll.render();
        this._syncNotesToTrack();
    }

    // ════════════════════════════════════════════════════════════════════
    //  菜单系统
    // ════════════════════════════════════════════════════════════════════

    _bindMenus() {
        const menubar = document.getElementById('menubar');
        const dropdown = document.getElementById('dropdown-menu');
        const dropdownContent = document.getElementById('dropdown-content');

        if (!menubar || !dropdown || !dropdownContent) return;

        let activeMenu = null;

        const menuDefs = {
            file: [
                { label: '新建项目', shortcut: 'Ctrl+N', action: () => this.newProject() },
                { label: '打开项目...', shortcut: 'Ctrl+O', action: () => this.openProject() },
                { type: 'separator' },
                { label: '保存项目', shortcut: 'Ctrl+S', action: () => this.saveProject() },
                { type: 'separator' },
                { label: '导入 MIDI...', shortcut: 'Ctrl+I', action: () => document.getElementById('file-input')?.click() },
                { label: '导出 MIDI...', shortcut: 'Ctrl+E', action: () => this.exportMidi() },
                { type: 'separator' },
                { label: '退出', action: () => { if (window.pywebview) window.pywebview.window.close(); } },
            ],
            edit: [
                { label: '撤销', shortcut: 'Ctrl+Z', action: () => this.undo() },
                { label: '重做', shortcut: 'Ctrl+Y', action: () => this.redo() },
                { type: 'separator' },
                { label: '全选', shortcut: 'Ctrl+A', action: () => { this.pianoRoll.selectAll(); } },
                { label: '删除选中', shortcut: 'Delete', action: () => { this._pushUndo(); this.pianoRoll.deleteSelected(); this._syncNotesToTrack(); } },
                { type: 'separator' },
                { label: '剪切', shortcut: 'Ctrl+X', action: () => this.cutNotes() },
                { label: '复制', shortcut: 'Ctrl+C', action: () => this.copyNotes() },
                { label: '粘贴', shortcut: 'Ctrl+V', action: () => this.pasteNotes() },
            ],
            playback: [
                { label: '播放/暂停', shortcut: 'Space', action: () => this.togglePlay() },
                { label: '停止', shortcut: 'Enter', action: () => { this.pianoRoll.playheadTick = 0; this.pianoRoll.isPlaying = false; this.pianoRoll.render(); } },
                { label: '回到开头', shortcut: 'Home', action: () => { this.pianoRoll.playheadTick = 0; this.pianoRoll.isPlaying = false; this.pianoRoll.render(); } },
            ],
            view: [
                { label: '放大', shortcut: 'Ctrl++', action: () => this.pianoRoll.zoomIn() },
                { label: '缩小', shortcut: 'Ctrl+-', action: () => this.pianoRoll.zoomOut() },
            ],
            options: [
                { label: '铅笔工具', shortcut: 'P', action: () => this._setTool('pencil') },
                { label: '选择工具', shortcut: 'S', action: () => this._setTool('select') },
                { label: '橡皮擦', shortcut: 'E', action: () => this._setTool('erase') },
            ],
            help: [
                { label: '关于 Easy2Sound', action: () => this._showAbout() },
            ],
        };

        const showMenu = (menuKey, anchorEl) => {
            const items = menuDefs[menuKey];
            if (!items) return;

            dropdownContent.innerHTML = '';
            items.forEach(item => {
                if (item.type === 'separator') {
                    const sep = document.createElement('div');
                    sep.className = 'dd-separator';
                    dropdownContent.appendChild(sep);
                } else {
                    const el = document.createElement('div');
                    el.className = 'dd-item';
                    el.innerHTML = `<span>${item.label}</span>${item.shortcut ? `<span class="dd-shortcut">${item.shortcut}</span>` : ''}`;
                    el.addEventListener('click', () => {
                        hideMenu();
                        item.action();
                    });
                    dropdownContent.appendChild(el);
                }
            });

            const rect = anchorEl.getBoundingClientRect();
            dropdown.style.left = rect.left + 'px';
            dropdown.style.top = rect.bottom + 'px';
            dropdown.classList.remove('hidden');
            activeMenu = menuKey;
            anchorEl.classList.add('active');
        };

        const hideMenu = () => {
            dropdown.classList.add('hidden');
            if (activeMenu) {
                const prev = menubar.querySelector(`.menu-item[data-menu="${activeMenu}"]`);
                if (prev) prev.classList.remove('active');
            }
            activeMenu = null;
        };

        menubar.querySelectorAll('.menu-item').forEach(item => {
            item.addEventListener('click', (e) => {
                e.stopPropagation();
                const key = item.dataset.menu;
                if (activeMenu === key) {
                    hideMenu();
                } else {
                    hideMenu();
                    showMenu(key, item);
                }
            });

            item.addEventListener('mouseenter', () => {
                if (activeMenu && item.dataset.menu !== activeMenu) {
                    hideMenu();
                    showMenu(item.dataset.menu, item);
                }
            });
        });

        document.addEventListener('click', (e) => {
            if (!dropdown.contains(e.target) && !menubar.contains(e.target)) {
                hideMenu();
            }
        });
    }

    // ════════════════════════════════════════════════════════════════════
    //  键盘快捷键
    // ════════════════════════════════════════════════════════════════════

    _bindKeyboard() {
        document.addEventListener('keydown', (e) => {
            // 忽略输入框中的键盘事件
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') return;

            const ctrl = e.ctrlKey || e.metaKey;

            if (ctrl && e.key === 'z') { e.preventDefault(); this.undo(); }
            else if (ctrl && e.key === 'y') { e.preventDefault(); this.redo(); }
            else if (ctrl && e.key === 'a') { e.preventDefault(); this.pianoRoll.selectAll(); this.pianoRoll.render(); }
            else if (ctrl && e.key === 's') { e.preventDefault(); this.saveProject(); }
            else if (ctrl && e.key === 'n') { e.preventDefault(); this.newProject(); }
            else if (ctrl && e.key === 'o') { e.preventDefault(); this.openProject(); }
            else if (ctrl && e.key === 'i') { e.preventDefault(); document.getElementById('file-input')?.click(); }
            else if (ctrl && e.key === 'e') { e.preventDefault(); this.exportMidi(); }
            else if (ctrl && (e.key === '=' || e.key === '+')) { e.preventDefault(); this.pianoRoll.zoomIn(); }
            else if (ctrl && e.key === '-') { e.preventDefault(); this.pianoRoll.zoomOut(); }
            else if (e.key === 'Delete' || e.key === 'Backspace') {
                if (this.pianoRoll.selectedNoteIds.size > 0) {
                    e.preventDefault();
                    this._pushUndo();
                    this.pianoRoll.deleteSelected();
                    this._syncNotesToTrack();
                }
            }
            else if (e.key === ' ') { e.preventDefault(); this.togglePlay(); }
            else if (e.key === 'Home') { this.pianoRoll.playheadTick = 0; this.pianoRoll.isPlaying = false; this.pianoRoll.render(); }
            else if (e.key === 'p' || e.key === 'P') { if (!ctrl) this._setTool('pencil'); }
            else if (e.key === 's' && !ctrl) { this._setTool('select'); }
            else if (e.key === 'e' && !ctrl) { this._setTool('erase'); }
        });
    }

    // ════════════════════════════════════════════════════════════════════
    //  属性面板
    // ════════════════════════════════════════════════════════════════════

    _bindPropertyPanel() {
        const fields = ['lyric', 'phoneme', 'pitch', 'length', 'velocity', 'offset', 'consonant', 'cutoff', 'modulation', 'flags'];

        fields.forEach(field => {
            const el = document.getElementById(`prop-${field}`);
            if (!el) return;
            const eventType = el.type === 'range' ? 'input' : 'change';
            el.addEventListener(eventType, () => this._applyProperty(field, el.value));
        });
    }

    _applyProperty(field, value) {
        const selected = this.pianoRoll.getSelectedNotes();
        if (selected.length === 0) return;

        this._pushUndo();

        selected.forEach(note => {
            if (field === 'lyric') {
                note.lyric = value;
            } else if (field === 'phoneme') {
                note.phoneme = value;
            } else if (field === 'flags') {
                note.flags = value;
            } else {
                note[field] = parseFloat(value) || 0;
            }
        });

        this.pianoRoll.render();
        this._syncNotesToTrack();

        // 更新力度值显示
        if (field === 'velocity') {
            const velSpan = document.getElementById('prop-velocity-value');
            if (velSpan) velSpan.textContent = value;
        }
        // 更新音高名称
        if (field === 'pitch') {
            const nameSpan = document.getElementById('prop-pitch-name');
            if (nameSpan) nameSpan.textContent = this._midiToNoteName(parseInt(value));
        }
        // 歌词修改时自动触发 phonemer
        if (field === 'lyric') {
            const track = this.tracks.find(t => t.id === this.currentTrackId);
            if (track && track.phonemer) {
                this.runPhonemer(track.id);
            }
        }
    }

    _midiToNoteName(midi) {
        const names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];
        return `${names[midi % 12]}${Math.floor(midi / 12) - 1}`;
    }

    // ════════════════════════════════════════════════════════════════════
    //  右键菜单
    // ════════════════════════════════════════════════════════════════════

    _bindContextMenu() {
        const ctxMenu = document.getElementById('context-menu');
        if (!ctxMenu) return;

        document.addEventListener('click', () => {
            ctxMenu.classList.add('hidden');
        });

        ctxMenu.querySelectorAll('.ctx-item').forEach(item => {
            item.addEventListener('click', () => {
                const action = item.dataset.action;
                this._handleContextAction(action);
                ctxMenu.classList.add('hidden');
            });
        });
    }

    showContextMenu(x, y) {
        const ctxMenu = document.getElementById('context-menu');
        if (!ctxMenu) return;
        ctxMenu.style.left = x + 'px';
        ctxMenu.style.top = y + 'px';
        ctxMenu.classList.remove('hidden');
    }

    _handleContextAction(action) {
        const pr = this.pianoRoll;
        switch (action) {
            case 'cut': this.cutNotes(); break;
            case 'copy': this.copyNotes(); break;
            case 'paste': this.pasteNotes(); break;
            case 'delete':
                this._pushUndo();
                pr.deleteSelected();
                this._syncNotesToTrack();
                break;
            case 'selectAll':
                pr.selectAll();
                break;
            case 'pitch-up':
                this._pushUndo();
                pr.getSelectedNotes().forEach(n => { n.pitch = Math.min(127, n.pitch + 1); });
                pr.render();
                this._syncNotesToTrack();
                break;
            case 'pitch-down':
                this._pushUndo();
                pr.getSelectedNotes().forEach(n => { n.pitch = Math.max(0, n.pitch - 1); });
                pr.render();
                this._syncNotesToTrack();
                break;
            case 'insert-note':
                this._pushUndo();
                const newNote = {
                    id: Math.random().toString(36).substring(2, 10),
                    lyric: 'あ',
                    phoneme: '',
                    pitch: 60,
                    length: 480,
                    velocity: 100,
                    start: pr.playheadTick,
                    flags: '', offset: 0, consonant: 0, cutoff: 0, modulation: 0,
                    pitch_string: '', intensity: '100'
                };
                pr.notes.push(newNote);
                pr.render();
                this._syncNotesToTrack();
                break;
        }
    }

    // ════════════════════════════════════════════════════════════════════
    //  剪贴板
    // ════════════════════════════════════════════════════════════════════

    cutNotes() {
        this.copyNotes();
        this._pushUndo();
        this.pianoRoll.deleteSelected();
        this._syncNotesToTrack();
    }

    copyNotes() {
        this._clipboard = this.pianoRoll.getSelectedNotes().map(n => ({ ...n }));
    }

    pasteNotes() {
        if (!this._clipboard || this._clipboard.length === 0) return;
        this._pushUndo();
        this.pianoRoll.selectedNoteIds.clear();

        const offset = this.pianoRoll.playheadTick;
        const minStart = Math.min(...this._clipboard.map(n => n.start));

        this._clipboard.forEach(n => {
            const copy = { ...n, id: Math.random().toString(36).substring(2, 10), start: n.start - minStart + offset };
            this.pianoRoll.notes.push(copy);
            this.pianoRoll.selectedNoteIds.add(copy.id);
        });
        this.pianoRoll.render();
        this._syncNotesToTrack();
    }

    // ════════════════════════════════════════════════════════════════════
    //  文件输入
    // ════════════════════════════════════════════════════════════════════

    _bindFileInput() {
        const fileInput = document.getElementById('file-input');
        if (!fileInput) return;

        fileInput.addEventListener('change', async (e) => {
            const file = e.target.files[0];
            if (!file) return;

            const formData = new FormData();
            formData.append('file', file);

            try {
                this._updateStatusBar('正在导入...');
                const res = await fetch('/api/upload', { method: 'POST', body: formData });
                const data = await res.json();
                if (data.error) {
                    this._updateStatusBar(`导入失败: ${data.error}`);
                    return;
                }
                this._applyProjectData(data);
                this._updateStatusBar(`已导入: ${file.name}`);
            } catch (err) {
                this._updateStatusBar(`导入出错: ${err.message}`);
            }

            fileInput.value = '';
        });
    }

    // ════════════════════════════════════════════════════════════════════
    //  后端 API 交互
    // ════════════════════════════════════════════════════════════════════

    async newProject() {
        try {
            const res = await fetch('/api/project/new', { method: 'POST' });
            const data = await res.json();
            this._applyProjectData(data);
            this.undoStack = [];
            this.redoStack = [];
            this._updateStatusBar('新项目已创建');
        } catch (err) {
            this._updateStatusBar(`新建失败: ${err.message}`);
        }
    }

    async openProject() {
        document.getElementById('file-input')?.click();
    }

    async saveProject() {
        try {
            this._syncNotesToTrack();
            const data = {
                name: this.projectName,
                bpm: this.bpm,
                beats_per_bar: this.pianoRoll.beatsPerBar,
                tracks: this.tracks,
            };
            const res = await fetch('/api/project/save', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data),
            });
            const result = await res.json();
            if (result.ok) {
                this._updateStatusBar(`已保存: ${result.path || this.projectName}`);
            }
        } catch (err) {
            this._updateStatusBar(`保存失败: ${err.message}`);
        }
    }

    async exportMidi() {
        try {
            this._syncNotesToTrack();
            this._updateStatusBar('正在导出 MIDI...');
            const res = await fetch('/api/export/midi', { method: 'POST' });
            if (res.ok) {
                const blob = await res.blob();
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `${this.projectName}.mid`;
                a.click();
                URL.revokeObjectURL(url);
                this._updateStatusBar('MIDI 导出完成');
            } else {
                const err = await res.json();
                this._updateStatusBar(`导出失败: ${err.error}`);
            }
        } catch (err) {
            this._updateStatusBar(`导出出错: ${err.message}`);
        }
    }

    async addTrack() {
        try {
            const res = await fetch('/api/tracks/add', { method: 'POST' });
            const data = await res.json();
            this._applyProjectData(data);
            this._updateStatusBar('已添加新轨道');
        } catch (err) {
            this._updateStatusBar(`添加轨道失败: ${err.message}`);
        }
    }

    // ════════════════════════════════════════════════════════════════════
    //  数据同步
    // ════════════════════════════════════════════════════════════════════

    async _applyProjectData(data) {
        this.tracks = data.tracks || [];
        this.bpm = data.bpm || 120;
        this.projectName = data.name || 'Untitled';
        document.title = `${this.projectName} - Easy2Sound`;

        const bpmInput = document.getElementById('input-bpm');
        if (bpmInput) bpmInput.value = this.bpm;
        this.pianoRoll.setBpm(this.bpm);

        if (this.tracks.length > 0) {
            this.currentTrackId = this.tracks[0].id;
            this.pianoRoll.setNotes(this.tracks[0].notes || []);
        } else {
            this.pianoRoll.setNotes([]);
        }

        // 确保 phonemer 列表已加载，再渲染轨道列表
        if (!this.phonemerList.length) {
            await this._loadPhonemerList();
        }
        this._renderTrackList();
    }

    _syncNotesToTrack() {
        const track = this.tracks.find(t => t.id === this.currentTrackId);
        if (track) {
            track.notes = this.pianoRoll.notes;
        }
    }

    async _loadPhonemerList() {
        try {
            const res = await fetch('/api/phonemer/list');
            this.phonemerList = await res.json();
        } catch (e) {
            console.error('Failed to load phonemer list:', e);
            this.phonemerList = [];
        }
    }

    async runPhonemer(trackId) {
        if (this._phonemerPending) return;
        const track = this.tracks.find(t => t.id === trackId);
        if (!track || !track.phonemer) return;
        this._phonemerPending = true;
        this._updateStatusBar('正在生成音素...');
        try {
            const res = await fetch('/api/phonemer/run', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    track_id: trackId,
                    phonemer: track.phonemer,
                }),
            });
            const data = await res.json();
            if (data.error) {
                this._updateStatusBar(`音素生成失败: ${data.error}`);
                return;
            }
            // 更新项目数据
            this.tracks = data.tracks || this.tracks;
            const updatedTrack = this.tracks.find(t => t.id === trackId);
            if (trackId === this.currentTrackId && updatedTrack) {
                this.pianoRoll.setNotes(updatedTrack.notes || []);
            }
            this._renderTrackList();
            this._updateStatusBar('音素生成完成');
        } catch (e) {
            console.error('phonemer error:', e);
            this._updateStatusBar(`音素生成出错: ${e.message}`);
        } finally {
            this._phonemerPending = false;
        }
    }

    // ════════════════════════════════════════════════════════════════════
    //  轨道列表
    // ════════════════════════════════════════════════════════════════════

    _renderTrackList() {
        const container = document.getElementById('track-list');
        if (!container) return;
        container.innerHTML = '';

        this.tracks.forEach(track => {
            const el = document.createElement('div');
            el.className = 'track-item' + (track.id === this.currentTrackId ? ' active' : '');
            el.innerHTML = `
                <div class="track-top-row">
                    <button class="track-btn mute-btn${track.muted ? ' muted' : ''}" title="静音">M</button>
                    <button class="track-btn solo-btn${track.solo ? ' solo' : ''}" title="独奏">S</button>
                    <span class="track-name" contenteditable="true" spellcheck="false">${track.name}</span>
                    <button class="track-btn del-track-btn" title="删除轨道">×</button>
                </div>
                <div class="track-bottom-row">
                    <span class="track-singer-label">${track.singer || '无音源'}</span>
                    <select class="track-phonemer-select" data-track-id="${track.id}">
                        <option value="">无注音</option>
                        ${this.phonemerList.map(p => {
                            // 兼容完整路径、文件名、有无 .exe 后缀
                            const phonemerFile = (track.phonemer || '').split(/[\\\\/]/).pop().replace(/\.exe$/i, '');
                            const listName = p.name.replace(/\.exe$/i, '');
                            const isMatch = phonemerFile === listName;
                            return `<option value="${p.name}" ${isMatch ? 'selected' : ''}>${p.label}</option>`;
                        }).join('')}
                    </select>
                </div>
            `;

            el.addEventListener('click', (e) => {
                if (e.target.classList.contains('track-btn')) return;
                this._switchTrack(track.id);
            });

            el.querySelector('.mute-btn')?.addEventListener('click', () => {
                track.muted = !track.muted;
                el.querySelector('.mute-btn').classList.toggle('muted');
            });

            el.querySelector('.solo-btn')?.addEventListener('click', () => {
                track.solo = !track.solo;
                el.querySelector('.solo-btn').classList.toggle('solo');
            });

            el.querySelector('.del-track-btn')?.addEventListener('click', () => {
                if (this.tracks.length <= 1) return;
                this.tracks = this.tracks.filter(t => t.id !== track.id);
                if (this.currentTrackId === track.id) {
                    this.currentTrackId = this.tracks[0]?.id || null;
                    this.pianoRoll.setNotes(this.tracks[0]?.notes || []);
                }
                this._renderTrackList();
            });

            el.querySelector('.track-name')?.addEventListener('blur', (e) => {
                track.name = e.target.textContent.trim() || track.name;
            });
            el.querySelector('.track-name')?.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') { e.preventDefault(); e.target.blur(); }
                e.stopPropagation();
            });

            el.querySelector('.track-phonemer-select')?.addEventListener('change', (e) => {
                track.phonemer = e.target.value;
                if (track.phonemer) {
                    this.runPhonemer(track.id);
                }
            });

            container.appendChild(el);
        });
    }

    _switchTrack(trackId) {
        if (trackId === this.currentTrackId) return;
        this._syncNotesToTrack();
        this.currentTrackId = trackId;
        const track = this.tracks.find(t => t.id === trackId);
        this.pianoRoll.setNotes(track?.notes || []);
        this.pianoRoll.selectedNoteIds.clear();
        this.pianoRoll.render();
        this._renderTrackList();
        this.selectNote(null);
    }

    // ════════════════════════════════════════════════════════════════════
    //  PianoRoll 回调接口（pianoroll.js 调用）
    // ════════════════════════════════════════════════════════════════════

    onNotesChanged() {
        this._syncNotesToTrack();
        const track = this.tracks.find(t => t.id === this.currentTrackId);
        if (track && track.phonemer) {
            this.runPhonemer(track.id);
        }
    }

    selectNote(note) {
        const noteProps = document.getElementById('note-properties');
        const noSelection = document.getElementById('no-selection-hint');

        if (!note) {
            if (noteProps) noteProps.style.display = 'none';
            if (noSelection) noSelection.style.display = '';
            return;
        }

        if (noteProps) noteProps.style.display = '';
        if (noSelection) noSelection.style.display = 'none';

        const set = (id, val) => {
            const el = document.getElementById(id);
            if (el) el.value = val;
        };

        set('prop-lyric', note.lyric || '');
        set('prop-phoneme', note.phoneme || '');
        set('prop-pitch', note.pitch);
        set('prop-length', note.length);
        set('prop-velocity', note.velocity || 100);
        set('prop-offset', note.offset || 0);
        set('prop-consonant', note.consonant || 0);
        set('prop-cutoff', note.cutoff || 0);
        set('prop-modulation', note.modulation || 0);
        set('prop-flags', note.flags || '');

        const pitchName = document.getElementById('prop-pitch-name');
        if (pitchName) pitchName.textContent = this._midiToNoteName(note.pitch);

        const velValue = document.getElementById('prop-velocity-value');
        if (velValue) velValue.textContent = note.velocity || 100;
    }

    previewPitch(pitch) {
        // TODO: 接入音频预览
        console.log('Preview pitch:', pitch);
    }

    onPlayheadChange(tick) {
        // 时间线点击时更新状态栏
        this._updateStatusBar();
    }

    updateZoomDisplay() {
        const el = document.getElementById('zoom-level');
        if (el) {
            el.textContent = Math.round(this.pianoRoll.zoomX / 0.15 * 100) + '%';
        }
    }

    // ════════════════════════════════════════════════════════════════════
    //  状态栏
    // ════════════════════════════════════════════════════════════════════

    _updateStatusBar(msg) {
        const left = document.getElementById('status-left');
        const right = document.getElementById('status-right');
        const center = document.getElementById('status-center');

        if (left) left.textContent = `${this.projectName} - Easy2Sound`;
        if (center) {
            const beat = Math.floor(this.pianoRoll.playheadTick / 480) + 1;
            const tick = Math.floor(this.pianoRoll.playheadTick % 480);
            center.textContent = `Beat ${beat} | Tick ${tick} | BPM ${this.bpm}`;
        }
        if (right && msg) right.textContent = msg;
    }

    // ════════════════════════════════════════════════════════════════════
    //  关于对话框
    // ════════════════════════════════════════════════════════════════════

    _showAbout() {
        alert('Easy2Sound v0.1\n歌声合成编辑器\n基于 Canvas 的钢琴卷帘窗');
    }
}

// ── 启动 ──
window.app = new Easy2SoundApp();
