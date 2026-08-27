/* QueryForge 页面脚本 — 自 static/template/chatSQL/chat.html 拆出，公共 apiRequest/e/QF 见 app_common.js */
// ── API helper ─────────────────────────────────────────────

// ── State ──────────────────────────────────────────────────
let currentConvId = null;
let isLoading = false;

// ── Init ───────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    loadConvList();
    loadSchemas();
    loadLlmConfigs();
    loadKnowledge();
});

// ── Conversation List ──────────────────────────────────────
async function loadConvList() {
    try {
        const resp = await apiRequest('/api/conversation');
        if (!resp.ok) return;
        const list = await resp.json();
        renderConvList(list);
    } catch (e) {
        console.error('加载对话列表失败:', e);
    }
}

function renderConvList(list) {
    const el = document.getElementById('convList');
    if (!list || list.length === 0) {
        el.innerHTML = '<div style="padding:20px;text-align:center;color:#888;font-size:13px;">暂无对话</div>';
        return;
    }
    el.innerHTML = list.map(c => `
        <div class="conv-item${c.id === currentConvId ? ' active' : ''}"
             onclick="openConv(${c.id})">
            <div class="conv-item-title">${escapeHtml(c.title || '(无标题)')}</div>
            <div class="conv-item-meta">${escapeHtml(c.schema_name || '默认')} · ${c.message_count} 条消息</div>
            <span class="conv-item-delete" onclick="event.stopPropagation();deleteConv(${c.id})" title="删除">×</span>
        </div>
    `).join('');
}

async function openConv(id) {
    currentConvId = id;
    loadConvList(); // refresh active state

    const emptyEl = document.getElementById('chatEmpty');
    if (emptyEl) emptyEl.style.display = 'none';
    document.getElementById('chatInputArea').style.display = 'block';

    const msgContainer = document.getElementById('chatMessages');
    msgContainer.innerHTML = '<div style="text-align:center;color:#aaa;padding:40px;">加载中...</div>';

    try {
        const resp = await apiRequest(`/api/conversation/${id}/messages`);
        if (!resp.ok) throw new Error('加载失败');
        const messages = await resp.json();

        // 获取标题
        const convResp = await apiRequest('/api/conversation');
        const convs = await convResp.json();
        const conv = convs.find(c => c.id === id);
        document.getElementById('chatHeader').textContent =
            (conv ? conv.title : 'Chat SQL') + ' — 连续对话';

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
        const resp = await apiRequest(`/api/conversation/${currentConvId}/messages`, {
            method: 'POST',
            body: JSON.stringify({ content })
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
    // 重置表单：清空问题、错误提示，下拉恢复默认（保留默认模型预选）
    document.getElementById('newConvQuery').value = '';
    document.getElementById('newConvSchema').value = '';
    document.getElementById('newConvKnowledge').value = '';
    setNewConvError('');
    const llmSel = document.getElementById('newConvLlmConfig');
    const def = llmSel.querySelector('option[selected]') || llmSel.querySelector('option[data-default="1"]');
    llmSel.value = def ? def.value : '';
}

function setNewConvError(msg) {
    const el = document.getElementById('newConvError');
    if (!el) return;
    el.textContent = msg;
    el.style.display = msg ? 'block' : 'none';
    if (!msg) el.style.color = '#dc3545';   // 清空时恢复默认红色
}

// 选库即确定数据库类型（类型由库本身存储，后端也会兜底取库的类型）
function onSchemaSelect() {
    const schema = document.getElementById('newConvSchema').value;
    window._selectedSchemaType = (window._schemaTypes || {})[schema] || '';
}

async function createConv() {
    if (_convSubmitting) return;   // 防重复提交
    const query = document.getElementById('newConvQuery').value.trim();
    if (!query) { setNewConvError('请输入问题'); return; }

    const schemaName = document.getElementById('newConvSchema').value || null;
    // 数据库类型由所选库自动带出（未选库/库无类型时后端按默认处理）
    const dbType = window._selectedSchemaType || 'sqlite';
    const llmConfigId = document.getElementById('newConvLlmConfig').value || null;
    const knowledgeId = document.getElementById('newConvKnowledge').value || null;

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
                query, schema_name: schemaName, db_type: dbType,
                llm_config_id: llmConfigId ? parseInt(llmConfigId) : null,
                knowledge_id: knowledgeId ? parseInt(knowledgeId) : null
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

// ── Schema & LLM Config Loaders ────────────────────────────
async function loadSchemas() {
    try {
        const resp = await apiRequest('/api/schema/schemas');
        if (!resp.ok) return;
        const data = await resp.json();
        window._schemaTypes = data.schema_types || {};   // 库名 → db_type，选库自动带出
        const sel = document.getElementById('newConvSchema');
        sel.innerHTML = '<option value="">全部数据库</option>';
        const groups = data.datasources && data.datasources.length
            ? data.datasources
            : [{ datasource_id: -1, datasource_name: '数据库', schemas: data.schemas || [] }];
        groups.forEach(g => {
            const schemas = (g.schemas || []).filter(Boolean);
            if (!schemas.length) return;
            const og = document.createElement('optgroup');
            og.label = g.datasource_name || '数据库';
            schemas.forEach(s => {
                const opt = document.createElement('option');
                opt.value = s;
                opt.textContent = s;
                og.appendChild(opt);
            });
            sel.appendChild(og);
        });
    } catch (e) { console.error('加载数据库列表失败:', e); }
}

async function loadLlmConfigs() {
    try {
        const resp = await apiRequest('/api/llm-config/list');
        if (!resp.ok) return;
        const data = await resp.json();
        const sel = document.getElementById('newConvLlmConfig');
        (data.items || []).forEach(c => {
            const opt = document.createElement('option');
            opt.value = c.id;
            opt.textContent = `${c.provider} - ${c.model}`;
            if (c.is_default) {
                opt.selected = true;
                opt.dataset.default = '1';   // 重置表单时保留默认模型预选
            }
            sel.appendChild(opt);
        });
    } catch (e) { console.error('加载 LLM 配置失败:', e); }
}

async function loadKnowledge() {
    try {
        const resp = await apiRequest('/api/knowledge');
        if (!resp.ok) return;
        const data = await resp.json();
        const sel = document.getElementById('newConvKnowledge');
        (data.items || []).forEach(k => {
            const opt = document.createElement('option');
            opt.value = k.id;
            opt.textContent = k.title || '(无标题)';
            sel.appendChild(opt);
        });
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
