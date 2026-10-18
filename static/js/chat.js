/* QueryForge 页面脚本 — 自 static/template/chatSQL/chat.html 拆出，公共 apiRequest/e/QF 见 app_common.js */
// ── API helper ─────────────────────────────────────────────

// ── State ──────────────────────────────────────────────────
let currentConvId = null;
let isLoading = false;
// 对话列表分页状态
let convPage = 0;
let convHasMore = false;
const CONV_PAGE_SIZE = 20;
// 会话搜索状态（300ms 防抖）
let convSearchKw = '';
let _convSearchTimer = null;

// ── Init ───────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    loadConvList();
    loadLlmConfigs();
    loadKnowledge();
});

// ── Conversation List（左侧栏，按时间分组） ─────────────────
function _convListUrl(offset) {
    const kw = encodeURIComponent(convSearchKw);
    return `/api/conversation?limit=${CONV_PAGE_SIZE}&offset=${offset}&search=${kw}`;
}

// 已加载的会话累积（分页追加后整体重渲染分组）
let _convItems = [];

async function loadConvList() {
    convPage = 0;
    try {
        const resp = await apiRequest(_convListUrl(0));
        if (!resp.ok) return;
        const data = await resp.json();
        const list = data.items || [];
        convHasMore = list.length >= CONV_PAGE_SIZE && (data.total || 0) > list.length;
        _convItems = list;
        renderConvGroups();
    } catch (e) {
        console.error('加载对话列表失败:', e);
    }
}

// 会话搜索（防抖后走后端过滤：标题 / 会话内消息内容）
function onConvSearch(value) {
    convSearchKw = (value || '').trim();
    clearTimeout(_convSearchTimer);
    _convSearchTimer = setTimeout(loadConvList, 300);
}

async function loadMoreConvs() {
    const nextOffset = (convPage + 1) * CONV_PAGE_SIZE;
    try {
        const resp = await apiRequest(_convListUrl(nextOffset));
        if (!resp.ok) return;
        const data = await resp.json();
        const list = data.items || [];
        convPage += 1;
        convHasMore = (data.total || 0) > (convPage + 1) * CONV_PAGE_SIZE;
        _convItems = _convItems.concat(list);
        renderConvGroups();
    } catch (e) {
        console.error('加载更多对话失败:', e);
    }
}

// updated_at（后端北京时间 ISO 字符串）→ 分组：今天 / 昨天 / 7天内 / 更早
function _convGroupKey(updatedAt) {
    if (!updatedAt) return '更早';
    const d = new Date(updatedAt);
    if (isNaN(d.getTime())) return '更早';
    const now = new Date();
    const startOfDay = x => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
    const days = Math.floor((startOfDay(now) - startOfDay(d)) / 86400000);
    if (days <= 0) return '今天';
    if (days === 1) return '昨天';
    if (days <= 7) return '7天内';
    return '更早';
}

const _GROUP_ORDER = ['今天', '昨天', '7天内', '更早'];

function renderConvGroups() {
    const el = document.getElementById('convList');
    if (!_convItems || _convItems.length === 0) {
        const hint = convSearchKw ? '无匹配的会话' : '暂无对话';
        el.innerHTML = `<div style="padding:20px;text-align:center;color:#98a2b3;font-size:13px;">${hint}</div>`;
        return;
    }
    // 按分组顺序聚合（接口本身按 updated_at 倒序，分组内天然保持新→旧）
    const groups = new Map();
    _convItems.forEach(c => {
        const key = _convGroupKey(c.updated_at);
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(c);
    });
    let html = '';
    _GROUP_ORDER.forEach(key => {
        const items = groups.get(key);
        if (!items || !items.length) return;
        html += `<div class="conv-group-title">${key}</div>`;
        html += items.map(convItemHtml).join('');
    });
    if (convHasMore) {
        html += `<div class="conv-more-btn" onclick="loadMoreConvs()">加载更多</div>`;
    }
    el.innerHTML = html;
}

function convItemHtml(c) {
    const tip = `${escapeHtml(c.schema_name || '默认')} · ${c.message_count} 条消息`;
    return `
        <div class="conv-item${c.id === currentConvId ? ' active' : ''}"
             data-id="${c.id}" title="${escapeAttr(tip)}"
             onclick="openConv(${c.id}, '${escapeAttr(c.title || '(无标题)')}')">
            <div class="conv-item-title">${escapeHtml(c.title || '(无标题)')}</div>
            <span class="conv-item-delete" onclick="event.stopPropagation();deleteConv(${c.id})" title="删除">×</span>
        </div>
    `;
}

// ── 侧栏收起 / 展开 ─────────────────────────────────────────
function toggleSidebar() {
    const sb = document.getElementById('chatSidebar');
    const ex = document.getElementById('sideExpand');
    const collapsed = sb.classList.toggle('collapsed');
    ex.style.display = collapsed ? 'flex' : 'none';
}

// 输入框自动增高（上限由 CSS max-height 约束）
function autoGrowInput(el) {
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 160) + 'px';
}

// 侧栏底部用户信息（认证由 app_common.js 完成）
window.QF.onReady = function (user) {
    const name = (user && user.username) || '用户';
    document.getElementById('sideUserName').textContent = name;
    document.getElementById('sideUserAvatar').textContent = name.charAt(0).toUpperCase();
};

// ── 新对话：清空当前视图，回到待输入状态（首条消息发送时才真正创建） ──
function startNewConv() {
    if (isLoading) return;
    currentConvId = null;
    document.getElementById('chatMessages').style.display = 'none';
    document.getElementById('chatMessages').innerHTML = '';
    document.getElementById('chatEmpty').style.display = 'flex';
    document.getElementById('chatHeader').textContent = 'Chat SQL';
    document.getElementById('msgInput').focus();
}

async function openConv(id, title) {
    currentConvId = id;
    // 侧栏内切换 active 状态（不再全量重载列表）
    document.querySelectorAll('.conv-item').forEach(el =>
        el.classList.toggle('active', Number(el.dataset.id) === id));

    const emptyEl = document.getElementById('chatEmpty');
    if (emptyEl) emptyEl.style.display = 'none';
    const msgContainer = document.getElementById('chatMessages');
    msgContainer.style.display = '';

    document.getElementById('chatHeader').textContent = title || 'Chat SQL';

    // 恢复该对话的模型/知识库切换器选择（有记忆则恢复，无则默认）
    const prefs = getConvPref(id);
    const llmSel = document.getElementById('chatLlmConfig');
    if (prefs.llm_config_id && llmSel.querySelector(`option[value="${prefs.llm_config_id}"]`)) {
        llmSel.value = prefs.llm_config_id;
    } else {
        llmSel.value = '';
    }
    // 知识库多选恢复（基于全量数据重渲染，不受搜索过滤影响）
    _kbChecked = new Set((prefs.knowledge_ids || []).map(String));
    renderKbOptions();
    updateKbLabel();

    msgContainer.innerHTML = '<div style="text-align:center;color:#aaa;padding:40px;">加载中...</div>';

    try {
        const resp = await apiRequest(`/api/conversation/${id}/messages`);
        if (!resp.ok) throw new Error('加载失败');
        const messages = await resp.json();

        msgContainer.innerHTML = '';
        messages.forEach(m => renderMessage(m));
        scrollToBottom();
    } catch (e) {
        msgContainer.innerHTML = '<div style="text-align:center;color:red;padding:40px;">加载消息失败</div>';
    }
}

async function deleteConv(id) {
    if (!confirm('确定删除此对话？')) return;
    try {
        await apiRequest(`/api/conversation/${id}`, { method: 'DELETE' });
        if (currentConvId === id) startNewConv();
        loadConvList();
    } catch (e) {
        QF.toast('删除失败: ' + e.message, 'danger');
    }
}

// ── Messages ───────────────────────────────────────────────
// 助手消息元信息：渲染为轻量胶囊标签（模型 / 耗时 / Token 各一枚，模型与 Token 为绿色）
function llmMetaHtml(info) {
    if (!info || (!info.model && !info.total_tokens && !info.duration_ms)) return '';
    const pill = (text, green) =>
        `<span class="msg-meta-pill${green ? ' green' : ''}">${text}</span>`;
    const parts = [];
    if (info.model) parts.push(pill(`模型 ${escapeHtml(info.model)}`, true));
    if (info.duration_ms != null && info.duration_ms > 0) {
        const sec = info.duration_ms / 1000;
        parts.push(pill(`耗时 ${sec >= 100 ? Math.round(sec) : sec.toFixed(1)}s`, false));
    }
    if (info.total_tokens) {
        let tk = `Token ${info.total_tokens}`;
        if (info.prompt_tokens || info.completion_tokens) {
            tk += `（入 ${info.prompt_tokens || 0} / 出 ${info.completion_tokens || 0}`;
            if (info.reasoning_tokens) tk += `，含思考 ${info.reasoning_tokens}`;
            tk += '）';
        }
        parts.push(pill(tk, true));
    }
    return `<div class="msg-llm-meta">${parts.join('')}</div>`;
}

function renderMessage(msg) {
    const container = document.getElementById('chatMessages');

    if (msg.role === 'user') {
        const row = document.createElement('div');
        row.className = 'msg-row user';
        row.innerHTML = `<div class="msg-bubble">${escapeHtml(msg.content)}</div>`;
        container.appendChild(row);
    } else if (msg.role === 'assistant') {
        const row = document.createElement('div');
        row.className = 'msg-row assistant';
        let html = '<div class="msg-bubble">';

        if (msg.sql) {
            html += `<div class="msg-sql-block">${escapeHtml(msg.sql)}</div>`;
            html += `<div class="msg-sql-actions">`;
            html += `<button class="btn btn-sm btn-outline-secondary" onclick="copySql(this, '${escapeAttr(msg.sql)}')">📋 复制</button>`;
            html += `</div>`;
        }

        if (msg.is_valid) {
            html += `<span class="msg-valid-badge ok">✓ 校验通过</span>`;
        } else {
            html += `<span class="msg-valid-badge err">✗ 校验未通过</span>`;
            if (msg.error_message) {
                html += `<div class="msg-error">${escapeHtml(msg.error_message)}</div>`;
            }
        }

        // 权限提示（后端网关改写：行级过滤注入/敏感字段仅聚合返回）
        if (msg.permission_note) {
            html += `<div class="msg-perm-note">🛡 ${escapeHtml(msg.permission_note)}</div>`;
        }

        // 查询结果表格（query_result: {columns, rows, row_count, error, duration_ms}）
        // 会话内只显示前 N 行，完整结果在弹窗中分页查看
        if (msg.query_result) {
            const qr = msg.query_result;
            if (qr.error) {
                html += `<div class="msg-error" style="margin-top:8px;">⚠ 查询失败: ${escapeHtml(qr.error)}</div>`;
            } else if (qr.columns && qr.columns.length) {
                const PREVIEW_ROWS = 10;
                const total = qr.row_count != null ? qr.row_count : (qr.rows || []).length;
                const preview = (qr.rows || []).slice(0, PREVIEW_ROWS);
                html += `<div style="margin-top:8px;font-size:12px;color:#6c757d;">查询结果：共 ${total} 行${qr.duration_ms != null ? ` · ${qr.duration_ms}ms` : ''}</div>`;
                if (total === 0 && !msg.permission_note) {
                    // 历史消息可能无后端归因提示，前端兜底提示空结果可能原因
                    html += `<div class="msg-perm-note" style="margin-top:4px;">ℹ️ 返回 0 行：可能筛选条件过严或数据本身为空；如涉及数据权限过滤，请联系管理员确认</div>`;
                }
                html += `<div style="overflow-x:auto;margin-top:4px;"><table class="table table-sm table-bordered mb-0" style="font-size:12px;"><thead><tr>${qr.columns.map(c => `<th>${escapeHtml(c)}</th>`).join('')}</tr></thead><tbody>`;
                html += preview.map(r => `<tr>${r.map(v => `<td>${escapeHtml(v ?? '')}</td>`).join('')}</tr>`).join('');
                html += `</tbody></table></div>`;
                if (total > PREVIEW_ROWS) {
                    const msgId = msg.id || ('m' + Math.random().toString(36).slice(2, 8));
                    window._queryResults = window._queryResults || {};
                    window._queryResults[msgId] = qr;
                    html += `<div style="margin-top:6px;"><button class="btn btn-sm btn-outline-primary" onclick="showFullResult('${msgId}')">查看完整结果（共 ${total} 行）</button></div>`;
                }
            } else {
                html += `<div class="msg-error" style="margin-top:8px;">⚠ 无查询结果</div>`;
            }
        }

        html += '</div>';
        html += llmMetaHtml(msg.llm_info);
        row.innerHTML = html;
        container.appendChild(row);
    }

    scrollToBottom();
}

function scrollToBottom() {
    const el = document.getElementById('chatMessages');
    setTimeout(() => { el.scrollTop = el.scrollHeight; }, 50);
}

// ── Send Message（无当前对话时，首条消息直接创建新对话，DeepSeek 风格） ──
async function sendMsg() {
    if (isLoading) return;

    const input = document.getElementById('msgInput');
    const content = input.value.trim();
    if (!content) return;

    isLoading = true;
    input.disabled = true;
    document.getElementById('sendBtn').disabled = true;

    // Show user message immediately
    renderMessage({ role: 'user', content: content });
    input.value = '';
    input.style.height = 'auto';

    // 进入对话视图：隐藏空状态、显示消息区
    document.getElementById('chatEmpty').style.display = 'none';
    const container = document.getElementById('chatMessages');
    container.style.display = '';

    // Show loading
    const loadingRow = document.createElement('div');
    loadingRow.className = 'msg-row assistant';
    loadingRow.id = 'loadingMsg';
    loadingRow.innerHTML = '<div class="msg-bubble"><div class="loading-dots"><span></span><span></span><span></span></div>'
        + (currentConvId ? '' : '<div style="font-size:12px;color:#888;margin-top:4px;">正在创建对话并生成 SQL，请稍候...</div>')
        + '</div>';
    container.appendChild(loadingRow);
    scrollToBottom();

    try {
        // 发送时实时取切换器当前值（模型下拉 + 知识库勾选），而非历史快照。
        // 此前用 _convPrefs 快照导致：勾选知识库后 _convPrefs 不更新，发出空数组，
        // 后端还会把会话知识库清空（[] 非 None 会被持久化）。
        const llmVal = document.getElementById('chatLlmConfig').value || null;
        const kbIds = getSelectedKbIds();
        // 兜底超时：与建对话路径一致，防止后端长生成时前端无限等待
        const timeoutCtrl = new AbortController();
        const timer = setTimeout(() => timeoutCtrl.abort(), GEN_TIMEOUT_MS);

        let resp;
        if (currentConvId) {
            resp = await apiRequest(`/api/conversation/${currentConvId}/messages`, {
                method: 'POST',
                signal: timeoutCtrl.signal,
                body: JSON.stringify({
                    content,
                    llm_config_id: llmVal ? parseInt(llmVal) : null,
                    knowledge_ids: kbIds.map(id => parseInt(id))
                })
            });
        } else {
            // 首条消息创建新对话：数据范围由管理员授权自动决定（schema_name=null），
            // 模型/知识库用当前切换器选择
            resp = await apiRequest('/api/conversation', {
                method: 'POST',
                signal: timeoutCtrl.signal,
                body: JSON.stringify({
                    query: content,
                    schema_name: null,
                    llm_config_id: llmVal ? parseInt(llmVal) : null,
                    knowledge_ids: kbIds.map(id => parseInt(id))
                })
            });
        }
        clearTimeout(timer);
        if (!resp.ok) throw new Error((await resp.json()).detail || '请求失败');
        const data = await resp.json();

        // Remove loading
        document.getElementById('loadingMsg')?.remove();

        if (currentConvId) {
            // 发送成功后把本次选择写回记忆（切走再切回可恢复最新选择）
            _convPrefs[currentConvId] = { llm_config_id: llmVal, knowledge_ids: kbIds };
            renderMessage({
                role: 'assistant',
                sql: data.assistant_message.sql,
                is_valid: data.assistant_message.is_valid,
                error_message: data.assistant_message.error_message,
                columns: data.assistant_message.columns,
                query_result: data.assistant_message.query_result,
                llm_info: data.assistant_message.llm_info,
                permission_note: data.assistant_message.permission_note
            });
        } else {
            currentConvId = data.conversation.id;
            document.getElementById('chatHeader').textContent =
                data.conversation.title || 'Chat SQL';
            _convPrefs[currentConvId] = { llm_config_id: llmVal, knowledge_ids: kbIds };
            renderMessage({
                role: 'assistant',
                sql: data.message.sql,
                is_valid: data.message.is_valid,
                error_message: data.message.error_message,
                columns: data.message.columns,
                query_result: data.message.query_result,
                llm_info: data.message.llm_info,
                permission_note: data.message.permission_note
            });
        }

        loadConvList(); // refresh history dropdown
    } catch (e) {
        document.getElementById('loadingMsg')?.remove();
        const isTimeout = (e && e.name === 'AbortError');
        renderMessage({
            role: 'assistant',
            sql: '',
            is_valid: false,
            error_message: isTimeout ? `生成超时（${GEN_TIMEOUT_MS / 60000}分钟），请重试` : ('发送失败: ' + e.message)
        });
    }

    isLoading = false;
    input.disabled = false;
    document.getElementById('sendBtn').disabled = false;
    input.focus();
}

// ── 生成类请求的前端兜底超时（毫秒） ────────────────────────
// 后端首条消息链路 = 可行性判断 + SQL 生成 共两次 LLM 调用（每次各受
// LLM 配置 timeout 约束，默认 300s）+ SQL 执行时间，最坏 ≈ 2×timeout + SQL。
// 660s 覆盖默认配置的最坏情况；此前 60s 会过早掐断正常生成（报"生成超时（60秒）"）。
const GEN_TIMEOUT_MS = 660000;

// ── LLM Config & Knowledge Loaders（对话切换器） ───────────
// 创建对话不再选择模型/知识库；对话过程中通过输入区上方的切换器随时切换，
// 切换值记录在 _convPrefs（按对话 id 记忆），下一条消息发送时生效。
// 知识库支持多选（checkbox 下拉）。
let _convPrefs = {};   // {convId: {llm_config_id, knowledge_ids: []}}

function getConvPref(convId) {
    const p = _convPrefs[convId];
    return p || { llm_config_id: null, knowledge_ids: [] };
}

// ── 知识库多选：全量数据 + 勾选状态独立管理 ────────────────
// _kbItems 保存全部条目（标题/同义词/内容），_kbChecked 独立记录勾选，
// 搜索过滤只影响展示列表，不影响已勾选状态与标签显示。
let _kbItems = [];          // [{id, title, aliases, content}]
let _kbChecked = new Set(); // 已勾选知识 id（字符串）
let _kbSearch = '';

function getSelectedKbIds() {
    return Array.from(_kbChecked).filter(v => v !== '');
}

function updateKbLabel() {
    const ids = getSelectedKbIds();
    const label = document.getElementById('chatKbLabel');
    if (!ids.length) { label.textContent = '不使用知识库'; return; }
    const names = ids.map(id => {
        const it = _kbItems.find(x => String(x.id) === id);
        return it ? it.title : id;
    });
    label.textContent = names.join('、') + (ids.length > 3 ? ` (+${ids.length - 3})` : '');
}

function renderKbOptions() {
    const box = document.getElementById('chatKbOptions');
    // 拆词过滤：每个词需在 标题/同义词/内容 中命中（大小写不敏感，子串模糊匹配）
    const terms = _kbSearch.trim().toLowerCase().split(/\s+/).filter(Boolean);
    const list = _kbItems.filter(it => {
        if (!terms.length) return true;
        const hay = [it.title || '', (it.aliases || []).join(' '), it.content || '']
            .join(' ').toLowerCase();
        return terms.every(t => hay.includes(t));
    });
    box.innerHTML = list.map(it => {
        const checked = _kbChecked.has(String(it.id)) ? ' checked' : '';
        return `<div class="chat-kb-option">
            <label><input type="checkbox" value="${it.id}" data-name="${escapeAttr(it.title || '(无标题)')}"${checked}>${escapeHtml(it.title || '(无标题)')}${it.visibility === 'global' ? '（全局）' : ''}</label>
        </div>`;
    }).join('');
    document.getElementById('chatKbEmpty').style.display =
        (terms.length && !list.length) ? 'block' : 'none';
    box.querySelectorAll('input[type="checkbox"]').forEach(cb => {
        cb.addEventListener('change', () => {
            if (cb.checked) _kbChecked.add(cb.value); else _kbChecked.delete(cb.value);
            updateKbLabel();
            // 勾选变化即时同步到当前对话记忆（不发送也保留选择）
            if (currentConvId) {
                const p = getConvPref(currentConvId);
                p.knowledge_ids = getSelectedKbIds();
                _convPrefs[currentConvId] = p;
            }
        });
    });
}

function onKbSearch(value) {
    _kbSearch = value || '';
    renderKbOptions();
}

function toggleKbDropdown(e) {
    e.stopPropagation();
    const dd = document.getElementById('chatKbDropdown');
    const willShow = !dd.classList.contains('show');
    dd.classList.toggle('show');
    if (willShow) {
        // 每次打开重置搜索词（已勾选状态保留），并聚焦搜索框
        onKbSearch('');
        const input = document.getElementById('chatKbSearch');
        input.value = '';
        setTimeout(() => input.focus(), 0);
    }
}

// 点击页面其它区域关闭知识库下拉
document.addEventListener('click', function (e) {
    const wrap = document.getElementById('chatKnowledgeWrap');
    if (wrap && !wrap.contains(e.target)) {
        document.getElementById('chatKbDropdown')?.classList.remove('show');
    }
});

async function loadLlmConfigs() {
    try {
        const resp = await apiRequest('/api/llm-config/list');
        if (!resp.ok) return;
        const data = await resp.json();
        const sel = document.getElementById('chatLlmConfig');
        (data.items || []).forEach(c => {
            const opt = document.createElement('option');
            opt.value = c.id;
            opt.textContent = `${c.provider} - ${c.model}`;
            if (c.is_default) {
                opt.selected = true;
                opt.dataset.default = '1';
            }
            sel.appendChild(opt);
        });
        // 模型切换即时记忆（即使不发送就切走对话，再切回也能恢复）
        sel.addEventListener('change', () => {
            if (!currentConvId) return;
            const p = getConvPref(currentConvId);
            p.llm_config_id = sel.value || null;
            _convPrefs[currentConvId] = p;
        });
    } catch (e) { console.error('加载 LLM 配置失败:', e); }
}

async function loadKnowledge() {
    try {
        // mine=1：仅全局 + 本人条目（管理员也不混入他人个人条目）
        const resp = await apiRequest('/api/knowledge?limit=100&mine=1');
        if (!resp.ok) return;
        const data = await resp.json();
        const all = (data.items || []).map(k => ({
            id: k.id,
            title: k.title || '(无标题)',
            aliases: Array.isArray(k.aliases) ? k.aliases : [],
            content: k.content || '',
            visibility: k.visibility || 'personal',
            is_pinned: !!k.is_pinned
        }));
        // 全局 = 所有人可见（可被关键词自动召回）；是否注入对话还要勾选。
        // 仅 is_pinned=1 的全局条目才常驻注入所有人对话：无需勾选、不进勾选列表。
        const globals = all.filter(it => it.visibility === 'global');
        const pinnedGlobals = globals.filter(it => it.is_pinned);
        _kbItems = all.filter(it => it.visibility !== 'global' || !it.is_pinned);
        const hint = document.getElementById('chatKbGlobalHint');
        if (hint) {
            const parts = [];
            if (pinnedGlobals.length) parts.push(`已发布 ${pinnedGlobals.length} 条全局常驻规则，自动注入所有人对话，无需勾选`);
            const optional = globals.length - pinnedGlobals.length;
            if (optional) parts.push(`另有 ${optional} 条全局规则对所有人可见，勾选后注入对话`);
            if (parts.length) {
                hint.style.display = 'block';
                hint.textContent = parts.join('；');
            } else {
                hint.style.display = 'none';
            }
        }
        await loadDefaultKb();
        renderKbOptions();
    } catch (e) { console.error('加载知识库失败:', e); }
}

// 我的常驻（与知识库页 📌 同一偏好：勾选预填 + 「保存为我的常驻」写回，双端联动）
let _kbDefaultIds = [];

async function loadDefaultKb() {
    try {
        const resp = await apiRequest('/api/user/preferences/pinned-knowledge');
        if (!resp.ok) return;
        const data = await resp.json();
        _kbDefaultIds = (data.knowledge_ids || []).map(String);
        // 无会话记忆时以我的常驻为初始勾选
        if (!_kbChecked.size && _kbDefaultIds.length) {
            _kbChecked = new Set(_kbDefaultIds.filter(id =>
                _kbItems.some(it => String(it.id) === id)));
        }
    } catch (e) { /* 常驻加载失败按空处理 */ }
}

async function saveDefaultKb() {
    try {
        const resp = await apiRequest('/api/user/preferences/pinned-knowledge', {
            method: 'PUT',
            body: JSON.stringify({ knowledge_ids: getSelectedKbIds().map(id => parseInt(id)) })
        });
        if (!resp.ok) throw new Error((await resp.json()).detail || '保存失败');
        _kbDefaultIds = getSelectedKbIds();
        QF.toast(_kbDefaultIds.length ? '已保存为我的常驻（📌 同步，每次对话自动带上）' : '已清空我的常驻', 'success');
    } catch (e) {
        QF.toast('保存我的常驻失败: ' + e.message, 'danger');
    }
}

// ── Utils ──────────────────────────────────────────────────
// escapeHtml / e / escapeAttr 均由 app_common.js 提供

function copySql(btn, sql) {
    navigator.clipboard.writeText(sql).then(() => {
        btn.textContent = '✓ 已复制';
        setTimeout(() => { btn.textContent = '📋 复制'; }, 1500);
    }).catch(() => {
        QF.toast('复制失败，请手动复制', 'danger');
    });
}

// ── 完整查询结果弹窗（分页） ────────────────────────────────
const RESULT_PAGE_SIZE = 50;
let _resultData = null;      // 当前完整结果 {columns, rows, row_count}
let _resultPage = 1;

function showFullResult(key) {
    const qr = (window._queryResults || {})[key];
    if (!qr) { QF.toast('结果数据不存在，请重新查询', 'danger'); return; }
    _resultData = qr;
    _resultPage = 1;
    renderResultPage();
    document.getElementById('resultModalTitle').textContent =
        `查询结果（共 ${qr.row_count != null ? qr.row_count : (qr.rows || []).length} 行）`;
    document.getElementById('resultModal').classList.add('show');
}
function hideResultModal() {
    document.getElementById('resultModal').classList.remove('show');
}
function renderResultPage() {
    if (!_resultData) return;
    const { columns = [], rows = [], row_count } = _resultData;
    const total = row_count != null ? row_count : rows.length;
    const maxPage = Math.max(1, Math.ceil(total / RESULT_PAGE_SIZE));
    if (_resultPage > maxPage) _resultPage = maxPage;
    const start = (_resultPage - 1) * RESULT_PAGE_SIZE;
    const pageRows = rows.slice(start, start + RESULT_PAGE_SIZE);
    document.getElementById('resultModalBody').innerHTML = `
        <table class="table table-sm table-bordered mb-0" style="font-size:12px;">
            <thead><tr>${columns.map(c => `<th>${escapeHtml(c)}</th>`).join('')}</tr></thead>
            <tbody>${pageRows.map(r => `<tr>${r.map(v => `<td>${escapeHtml(v ?? '')}</td>`).join('')}</tr>`).join('') || '<tr><td colspan="' + columns.length + '" class="text-center text-muted">无数据</td></tr>'}</tbody>
        </table>`;
    document.getElementById('resultPageInfo').textContent = `第 ${_resultPage} / ${maxPage} 页 · 共 ${total} 行`;
    document.getElementById('resultPrev').disabled = _resultPage <= 1;
    document.getElementById('resultNext').disabled = _resultPage >= maxPage;
}
function resultPageNav(delta) {
    const next = _resultPage + delta;
    if (next < 1) return;
    _resultPage = next;
    renderResultPage();
}
// 点击遮罩关闭
document.getElementById('resultModal').addEventListener('click', function (e) {
    if (e.target === this) hideResultModal();
});
