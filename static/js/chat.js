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
        alert('删除失败: ' + e.message);
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
        alert('请先选择或创建一个对话');
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
            columns: data.assistant_message.columns
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

    // 提交期间：锁定按钮，保留弹窗与输入（失败可恢复）
    _convSubmitting = true;
    const submitBtn = document.getElementById('newConvSubmit');
    if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = '生成中...'; }
    setNewConvError('');

    // 不提前清空消息区：仅成功后切换为新对话内容，失败时原有内容保留
    const msgContainer = document.getElementById('chatMessages');

    try {
        const resp = await apiRequest('/api/conversation', {
            method: 'POST',
            body: JSON.stringify({
                query, schema_name: schemaName, db_type: dbType,
                llm_config_id: llmConfigId ? parseInt(llmConfigId) : null,
                knowledge_id: knowledgeId ? parseInt(knowledgeId) : null
            })
        });
        if (!resp.ok) throw new Error((await resp.json()).detail || '创建失败');

        const data = await resp.json();

        // 成功：关闭弹窗、重置表单、切换为新对话内容
        hideNewConvModal();
        resetNewConvForm();
        msgContainer.innerHTML = '';
        const emptyEl = document.getElementById('chatEmpty');
        if (emptyEl) emptyEl.style.display = 'none';
        document.getElementById('chatInputArea').style.display = 'block';

        currentConvId = data.conversation.id;
        document.getElementById('chatHeader').textContent =
            data.conversation.title + ' — 连续对话';

        // Render messages
        renderMessage({ role: 'user', content: query });
        renderMessage({
            role: 'assistant',
            sql: data.message.sql,
            is_valid: data.message.is_valid,
            error_message: data.message.error_message,
            columns: data.message.columns
        });

        loadConvList();
    } catch (e) {
        // 失败：弹窗保留、输入保留，仅提示错误，不做任何清空
        setNewConvError('创建对话失败: ' + e.message);
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
        alert('复制失败，请手动复制');
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
