/* QueryForge 页面脚本 — 自 static/template/chatSQL/chat.html 拆出，公共 apiRequest/e/QF 见 app_common.js */
// ── API helper ─────────────────────────────────────────────

// ── State ──────────────────────────────────────────────────
let currentConvId = null;
let isLoading = false;
// 对话列表分页状态
let convPage = 0;
let convHasMore = false;
const CONV_PAGE_SIZE = 20;

// ── Init ───────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    loadConvList();
    loadLlmConfigs();
    loadKnowledge();
});

// ── Conversation List ──────────────────────────────────────
async function loadConvList() {
    convPage = 0;
    try {
        const resp = await apiRequest(`/api/conversation?limit=${CONV_PAGE_SIZE}&offset=0`);
        if (!resp.ok) return;
        const data = await resp.json();
        const list = data.items || [];
        convHasMore = list.length >= CONV_PAGE_SIZE && (data.total || 0) > list.length;
        renderConvList(list);
    } catch (e) {
        console.error('加载对话列表失败:', e);
    }
}

async function loadMoreConvs() {
    const nextOffset = (convPage + 1) * CONV_PAGE_SIZE;
    try {
        const resp = await apiRequest(`/api/conversation?limit=${CONV_PAGE_SIZE}&offset=${nextOffset}`);
        if (!resp.ok) return;
        const data = await resp.json();
        const list = data.items || [];
        convPage += 1;
        convHasMore = (data.total || 0) > (convPage + 1) * CONV_PAGE_SIZE;
        appendConvList(list);
    } catch (e) {
        console.error('加载更多对话失败:', e);
    }
}

function renderConvList(list) {
    const el = document.getElementById('convList');
    if (!list || list.length === 0) {
        el.innerHTML = '<div style="padding:20px;text-align:center;color:#888;font-size:13px;">暂无对话</div>';
        return;
    }
    el.innerHTML = list.map(convItemHtml).join('');
    renderConvMoreBtn();
}

function appendConvList(list) {
    if (!list || list.length === 0) {
        convHasMore = false;
        renderConvMoreBtn();
        return;
    }
    const el = document.getElementById('convList');
    // 先移除底部"加载更多"按钮（可能已渲染在末尾）
    el.querySelector('.conv-more-btn')?.remove();
    el.insertAdjacentHTML('beforeend', list.map(convItemHtml).join(''));
    renderConvMoreBtn();
}

function convItemHtml(c) {
    return `
        <div class="conv-item${c.id === currentConvId ? ' active' : ''}"
             data-id="${c.id}"
             onclick="openConv(${c.id}, '${escapeAttr(c.title || '(无标题)')}')">
            <div class="conv-item-title">${escapeHtml(c.title || '(无标题)')}</div>
            <div class="conv-item-meta">${escapeHtml(c.schema_name || '默认')} · ${c.message_count} 条消息</div>
            <span class="conv-item-delete" onclick="event.stopPropagation();deleteConv(${c.id})" title="删除">×</span>
        </div>
    `;
}

function renderConvMoreBtn() {
    const el = document.getElementById('convList');
    el.querySelector('.conv-more-btn')?.remove();
    if (convHasMore) {
        el.insertAdjacentHTML('beforeend',
            `<div class="conv-more-btn" onclick="loadMoreConvs()">加载更多</div>`);
    }
}

async function openConv(id, title) {
    currentConvId = id;
    // 本地切换 active 状态（不再全量重载列表）
    document.querySelectorAll('.conv-item').forEach(el =>
        el.classList.toggle('active', Number(el.dataset.id) === id));

    const emptyEl = document.getElementById('chatEmpty');
    if (emptyEl) emptyEl.style.display = 'none';
    document.getElementById('chatInputArea').style.display = 'block';

    document.getElementById('chatHeader').textContent =
        (title || 'Chat SQL') + ' — 连续对话';

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

    const msgContainer = document.getElementById('chatMessages');
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
        if (currentConvId === id) {
            currentConvId = null;
            document.getElementById('chatMessages').innerHTML = '';
            document.getElementById('chatEmpty').style.display = 'flex';
            document.getElementById('chatInputArea').style.display = 'none';
        }
        loadConvList();
    } catch (e) {
        QF.toast('删除失败: ' + e.message, 'danger');
    }
}

// ── Messages ───────────────────────────────────────────────
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
        row.innerHTML = html;
        container.appendChild(row);
    }

    scrollToBottom();
}

function scrollToBottom() {
    const el = document.getElementById('chatMessages');
    setTimeout(() => { el.scrollTop = el.scrollHeight; }, 50);
}

// ── Send Message ───────────────────────────────────────────
async function sendMsg() {
    if (isLoading) return;

    const input = document.getElementById('msgInput');
    const content = input.value.trim();
    if (!content) return;

    if (!currentConvId) {
        QF.toast('请先选择或创建一个对话', 'warning');
        return;
    }

    isLoading = true;
    input.disabled = true;
    document.getElementById('sendBtn').disabled = true;

    // Show user message immediately
    renderMessage({ role: 'user', content: content });
    input.value = '';
    input.style.height = 'auto';

    // Show loading
    const container = document.getElementById('chatMessages');
    const loadingRow = document.createElement('div');
    loadingRow.className = 'msg-row assistant';
    loadingRow.id = 'loadingMsg';
    loadingRow.innerHTML = '<div class="msg-bubble"><div class="loading-dots"><span></span><span></span><span></span></div></div>';
    container.appendChild(loadingRow);
    scrollToBottom();

    try {
        // 发送时带上当前切换器选择的模型/知识库（后端切换并持久化到会话）
        const prefs = getConvPref(currentConvId);
        const resp = await apiRequest(`/api/conversation/${currentConvId}/messages`, {
            method: 'POST',
            body: JSON.stringify({
                content,
                llm_config_id: prefs.llm_config_id ? parseInt(prefs.llm_config_id) : null,
                knowledge_ids: (prefs.knowledge_ids || []).map(id => parseInt(id))
            })
        });
        if (!resp.ok) throw new Error((await resp.json()).detail || '请求失败');

        const data = await resp.json();

        // Remove loading
        document.getElementById('loadingMsg')?.remove();

        // Show assistant message
        renderMessage({
            role: 'assistant',
            sql: data.assistant_message.sql,
            is_valid: data.assistant_message.is_valid,
            error_message: data.assistant_message.error_message,
            columns: data.assistant_message.columns,
            query_result: data.assistant_message.query_result
        });

        loadConvList(); // refresh sidebar
    } catch (e) {
        document.getElementById('loadingMsg')?.remove();
        renderMessage({
            role: 'assistant',
            sql: '',
            is_valid: false,
            error_message: '发送失败: ' + e.message
        });
    }

    isLoading = false;
    input.disabled = false;
    document.getElementById('sendBtn').disabled = false;
    input.focus();
}

// ── New Conversation ───────────────────────────────────────
let _convSubmitting = false;

function showNewConvModal() {
    resetNewConvForm();
    document.getElementById('newConvModal').classList.add('show');
    document.getElementById('newConvQuery').focus();
}

function hideNewConvModal() {
    document.getElementById('newConvModal').classList.remove('show');
}

function resetNewConvForm() {
    // 重置表单：清空问题、错误提示（模型/知识库在对话中切换，不在创建弹窗选择）
    document.getElementById('newConvQuery').value = '';
    setNewConvError('');
}

function setNewConvError(msg) {
    const el = document.getElementById('newConvError');
    if (!el) return;
    el.textContent = msg;
    el.style.display = msg ? 'block' : 'none';
    if (!msg) el.style.color = '#dc3545';   // 清空时恢复默认红色
}

async function createConv() {
    if (_convSubmitting) return;   // 防重复提交
    const query = document.getElementById('newConvQuery').value.trim();
    if (!query) { setNewConvError('请输入问题'); return; }

    _convSubmitting = true;
    const submitBtn = document.getElementById('newConvSubmit');
    if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = '开始对话'; }
    setNewConvError('');

    // ── 立即关闭弹窗、进入对话界面，显示加载中 ──
    hideNewConvModal();
    resetNewConvForm();
    const msgContainer = document.getElementById('chatMessages');
    msgContainer.innerHTML = '';
    const emptyEl = document.getElementById('chatEmpty');
    if (emptyEl) emptyEl.style.display = 'none';
    document.getElementById('chatInputArea').style.display = 'block';
    document.getElementById('chatHeader').textContent = '生成中... — 连续对话';

    // 用户问题气泡
    renderMessage({ role: 'user', content: query });
    // 加载中气泡
    const loadingRow = document.createElement('div');
    loadingRow.className = 'msg-row assistant';
    loadingRow.id = 'convLoading';
    loadingRow.innerHTML = '<div class="msg-bubble"><div class="loading-dots"><span></span><span></span><span></span></div><div style="font-size:12px;color:#888;margin-top:4px;">正在生成 SQL 并查询结果，请稍候...</div></div>';
    msgContainer.appendChild(loadingRow);
    scrollToBottom();

    try {
        // 60 秒超时兜底（含模型加载 + LLM 调用 + 查询执行）
        const timeoutCtrl = new AbortController();
        const timer = setTimeout(() => timeoutCtrl.abort(), 60000);
        const resp = await fetch('/api/conversation', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            body: JSON.stringify({
                query,
                schema_name: null   // 全库模式：由权限自动决定可用数据范围
                // 模型/知识库不在创建时选择，对话中通过切换器随时调整
            }),
            signal: timeoutCtrl.signal
        });
        clearTimeout(timer);
        if (resp.status === 401) {
            window.top.location.href = '/login';
            throw new Error('登录已过期');
        }
        if (!resp.ok) throw new Error((await resp.json()).detail || '创建失败');

        const data = await resp.json();

        // 移除加载中气泡
        document.getElementById('convLoading')?.remove();

        currentConvId = data.conversation.id;
        document.getElementById('chatHeader').textContent =
            data.conversation.title + ' — 连续对话';

        // 新对话采用当前切换器选择（模型/知识库），供后续消息发送
        _convPrefs[currentConvId] = {
            llm_config_id: (document.getElementById('chatLlmConfig').value || null),
            knowledge_ids: getSelectedKbIds()
        };

        // Render messages（对话界面内展示结果）
        renderMessage({
            role: 'assistant',
            sql: data.message.sql,
            is_valid: data.message.is_valid,
            error_message: data.message.error_message,
            columns: data.message.columns,
            query_result: data.message.query_result
        });

        loadConvList();
    } catch (e) {
        // 失败：对话界面内展示错误（弹窗已关）
        document.getElementById('convLoading')?.remove();
        const isTimeout = (e && e.name === 'AbortError');
        renderMessage({
            role: 'assistant',
            sql: '',
            is_valid: false,
            error_message: isTimeout ? '生成超时（60秒），请重试' : ('创建对话失败: ' + e.message)
        });
        document.getElementById('chatHeader').textContent = '生成失败 — 连续对话';
    } finally {
        _convSubmitting = false;
        if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = '开始对话'; }
    }
}

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
            <label><input type="checkbox" value="${it.id}" data-name="${escapeAttr(it.title || '(无标题)')}"${checked}>${escapeHtml(it.title || '(无标题)')}</label>
        </div>`;
    }).join('');
    document.getElementById('chatKbEmpty').style.display =
        (terms.length && !list.length) ? 'block' : 'none';
    box.querySelectorAll('input[type="checkbox"]').forEach(cb => {
        cb.addEventListener('change', () => {
            if (cb.checked) _kbChecked.add(cb.value); else _kbChecked.delete(cb.value);
            updateKbLabel();
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
    } catch (e) { console.error('加载 LLM 配置失败:', e); }
}

async function loadKnowledge() {
    try {
        // 拉取尽量多的条目（接口上限 100），保证搜索/多选覆盖全量
        const resp = await apiRequest('/api/knowledge?limit=100');
        if (!resp.ok) return;
        const data = await resp.json();
        _kbItems = (data.items || []).map(k => ({
            id: k.id,
            title: k.title || '(无标题)',
            aliases: Array.isArray(k.aliases) ? k.aliases : [],
            content: k.content || ''
        }));
        renderKbOptions();
    } catch (e) { console.error('加载知识库失败:', e); }
}

// ── Utils ──────────────────────────────────────────────────
// escapeHtml / e 由 app_common.js 提供
function escapeAttr(text) {
    return text.replace(/'/g, "\\'").replace(/"/g, '&quot;');
}

function copySql(btn, sql) {
    navigator.clipboard.writeText(sql).then(() => {
        btn.textContent = '✓ 已复制';
        setTimeout(() => { btn.textContent = '📋 复制'; }, 1500);
    }).catch(() => {
        QF.toast('复制失败，请手动复制', 'danger');
    });
}

// Close modal on click-outside
document.getElementById('newConvModal').addEventListener('click', function(e) {
    if (e.target === this) hideNewConvModal();
});

// Enter 发送（Shift+Enter 换行），Esc 关闭
document.getElementById('newConvQuery').addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        createConv();
    } else if (e.key === 'Escape') {
        hideNewConvModal();
    }
});

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
