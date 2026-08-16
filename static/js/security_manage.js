/* QueryForge 页面脚本 — 自 static/template/system/security_manage.html 拆出，公共 apiRequest/e/QF 见 app_common.js */
// fmtTime 由 app_common.js 提供（window.fmtTime）

const LEVEL_BADGES = {
    'public': '<span class="badge bg-public">公开</span>',
    'internal': '<span class="badge bg-internal">内部</span>',
    'sensitive': '<span class="badge bg-sensitive">敏感</span>',
    'confidential': '<span class="badge bg-confidential">机密</span>',
};
const LEVEL_LABELS = window.QF.LEVEL_LABELS || { public: '公开', internal: '内部', sensitive: '敏感', confidential: '机密' };
const LEVEL_OPTIONS = ['public', 'internal', 'sensitive', 'confidential'];

let currentTab = 'overview';
let logsPage = 0;
let logsCache = [];
const logsPageSize = 50;
// 敏感字段列表分页（数据量可能很大）
let sensitiveCache = [], sensitivePage = 1;
const LIST_PS = 50;

function switchTab(tab) {
    currentTab = tab;
    ['overview', 'logs', 'sensitive', 'rowscope'].forEach(t => {
        document.getElementById('tab-' + t).style.display = t === tab ? '' : 'none';
    });
    // 页签已下沉到左侧菜单，这里保持 URL hash 同步（#tab）
    if (location.hash !== '#' + tab) history.replaceState(null, '', '#' + tab);
    if (tab === 'overview') loadOverview();
    if (tab === 'logs') loadLogs();
    if (tab === 'sensitive') { loadSchemaFilters(); loadSensitive(); }
    if (tab === 'rowscope') { loadUserSelect('rsUserSelect'); loadRowScopes(); loadAllTablesForSelect(); }
}

// ═══════════════════════════════════════════════════════
// Tab: 审计概览
// ═══════════════════════════════════════════════════════
async function loadOverview() {
    try {
        const [statsResp, logsResp] = await Promise.all([
            apiRequest('/api/audit/stats'),
            apiRequest('/api/audit/logs?limit=10&offset=0&blocked_only=true')
        ]);
        const stats = await statsResp.json();
        const logs = await logsResp.json();
        document.getElementById('stat-total').textContent = stats.total_queries;
        document.getElementById('stat-blocked').textContent = stats.blocked_queries;
        document.getElementById('stat-sensitive').textContent = stats.sensitive_hits;
        document.getElementById('stat-rate').textContent = stats.block_rate;
        const tbody = document.getElementById('recentBlocked');
        if (!logs.items || logs.items.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" class="empty-state">暂无拦截记录</td></tr>';
            return;
        }
        tbody.innerHTML = logs.items.map(r => `
            <tr>
                <td>${fmtTime(r.created_at)}</td>
                <td>${e(r.username)}</td>
                <td class="sql-cell" title="${e(r.query)}">${e(r.query)}</td>
                <td class="sql-cell" title="${e(r.block_reason)}">${e(r.block_reason)}</td>
                <td>${r.duration_ms}ms</td>
            </tr>`).join('');
    } catch (err) { console.error('loadOverview error:', err); }
}

// ═══════════════════════════════════════════════════════
// Tab: 审计日志
// ═══════════════════════════════════════════════════════
async function loadLogs() {
    const blockedOnly = document.getElementById('logBlockedOnly').checked;
    const offset = logsPage * logsPageSize;
    try {
        const resp = await apiRequest(`/api/audit/logs?limit=${logsPageSize}&offset=${offset}&blocked_only=${blockedOnly}`);
        const data = await resp.json();
        logsCache = data.items || [];
        const tbody = document.getElementById('logsTable');
        if (!data.items || data.items.length === 0) {
            tbody.innerHTML = '<tr><td colspan="10" class="empty-state">暂无记录</td></tr>';
        } else {
            tbody.innerHTML = data.items.map(r => `
                <tr>
                    <td>${fmtTime(r.created_at)}</td>
                    <td>${e(r.username)}</td>
                    <td class="sql-cell" title="${e(r.query)}">${e(r.query)}</td>
                    <td class="sql-cell pointer" onclick="showDetail(${r.id})" title="点击查看">${e(r.generated_sql) || '-'}</td>
                    <td class="sql-cell pointer" onclick="showDetail(${r.id})" title="点击查看">${e(r.modified_sql) || '-'}</td>
                    <td>${e(r.tables_accessed)}</td>
                    <td>${e(r.columns_accessed)}</td>
                    <td>${r.was_blocked ? '<span class="badge bg-danger">拦截</span>' : r.hit_sensitive ? '<span class="badge bg-warning text-dark">敏感</span>' : '<span class="badge bg-success">正常</span>'}</td>
                    <td>${r.duration_ms}ms</td>
                    <td><button class="btn btn-outline-primary btn-sm py-0 px-2" onclick="showDetail(${r.id})">详情</button></td>
                </tr>`).join('');
        }
        const start = data.total > 0 ? offset + 1 : 0;
        const end = Math.min(offset + logsPageSize, data.total);
        document.getElementById('logsPageInfo').textContent = `${start}-${end} / ${data.total}`;
        document.getElementById('logsPrev').disabled = logsPage === 0;
        document.getElementById('logsNext').disabled = offset + logsPageSize >= data.total;
    } catch (err) { console.error('loadLogs error:', err); }
}
function logsPrevPage() { if (logsPage > 0) { logsPage--; loadLogs(); } }
function logsNextPage() { logsPage++; loadLogs(); }

async function showDetail(logId) {
    const item = logsCache.find(r => r.id === logId);
    if (!item) return;
    const body = document.getElementById('detailBody');
    body.innerHTML = `
        <table class="table table-sm">
            <tr><td style="width:120px;">用户</td><td>${e(item.username)} (ID: ${item.user_id})</td></tr>
            <tr><td>时间</td><td>${fmtTime(item.created_at)}</td></tr>
            <tr><td>问题</td><td>${e(item.query)}</td></tr>
            <tr><td>命中表</td><td>${e(item.tables_accessed)}</td></tr>
            <tr><td>命中字段</td><td>${e(item.columns_accessed)}</td></tr>
            <tr><td>敏感命中</td><td>${item.hit_sensitive ? '是' : '否'}</td></tr>
            <tr><td>是否拦截</td><td>${item.was_blocked ? '<span class="text-danger">是 — ' + e(item.block_reason) + '</span>' : '否'}</td></tr>
            <tr><td>耗时</td><td>${item.duration_ms}ms</td></tr>
            <tr><td>生成SQL</td><td><pre>${e(item.generated_sql)}</pre></td></tr>
            <tr><td>修改后SQL</td><td><pre>${e(item.modified_sql) || '(未修改)'}</pre></td></tr>
        </table>`;
    new bootstrap.Modal(document.getElementById('detailModal')).show();
}

// ═══════════════════════════════════════════════════════
// Tab: 敏感字段
// ═══════════════════════════════════════════════════════
async function loadSchemaFilters() {
    if (document.getElementById('sensSchemaFilter').children.length > 1) return;
    try {
        const resp = await apiRequest('/api/schema/schemas');
        const data = await resp.json();
        const sel = document.getElementById('sensSchemaFilter');
        (data.schemas || []).forEach(s => {
            const opt = document.createElement('option');
            opt.value = s; opt.textContent = s;
            sel.appendChild(opt);
        });
        sel.onchange = () => loadTableFilter();
    } catch (err) { console.error(err); }
}

async function loadTableFilter() {
    const schemaName = document.getElementById('sensSchemaFilter').value;
    const sel = document.getElementById('sensTableFilter');
    sel.innerHTML = '<option value="">全部表</option>';
    if (!schemaName) return;
    try {
        const resp = await apiRequest(`/api/schema/tables?schema_name=${encodeURIComponent(schemaName)}`);
        const data = await resp.json();
        (data.tables || []).forEach(t => {
            const opt = document.createElement('option');
            opt.value = t.name; opt.textContent = t.name;
            sel.appendChild(opt);
        });
    } catch (err) { console.error(err); }
}

async function loadSensitive() {
    const schemaName = document.getElementById('sensSchemaFilter').value;
    const tableName = document.getElementById('sensTableFilter').value;
    let url = '/api/audit/all-columns?';
    if (schemaName) url += `schema_name=${encodeURIComponent(schemaName)}&`;
    if (tableName) url += `table_name=${encodeURIComponent(tableName)}&`;
    try {
        const resp = await apiRequest(url);
        const data = await resp.json();
        sensitiveCache = data.items || [];
        sensitivePage = 1;
        renderSensitive();
    } catch (err) { console.error('loadSensitive error:', err); }
}

function renderSensitive() {
    const tbody = document.getElementById('sensitiveTable');
    const pageItems = sensitiveCache.slice((sensitivePage - 1) * LIST_PS, sensitivePage * LIST_PS);
    if (!pageItems.length) {
        tbody.innerHTML = '<tr><td colspan="5" class="empty-state">暂无字段</td></tr>';
    } else {
        tbody.innerHTML = pageItems.map(c => `
            <tr>
                <td>${e(c.schema_name)}</td>
                <td>${e(c.table_name)}</td>
                <td><strong>${e(c.column_name)}</strong></td>
                <td>${LEVEL_BADGES[c.sensitive_level] || LEVEL_BADGES['public']}</td>
                <td>
                    <select class="form-select form-select-sm d-inline-block" style="width:auto;" onchange="updateSensitiveLevel(${c.column_id}, this.value)">
                        ${LEVEL_OPTIONS.map(lv => `<option value="${lv}" ${lv === c.sensitive_level ? 'selected' : ''}>${LEVEL_LABELS[lv] || lv}</option>`).join('')}
                    </select>
                </td>
            </tr>`).join('');
    }
    QF.renderPager('sensPager', {
        total: sensitiveCache.length, page: sensitivePage, pageSize: LIST_PS,
        onPage: p => { sensitivePage = p; renderSensitive(); }
    });
}

async function updateSensitiveLevel(columnId, level) {
    try {
        const resp = await apiRequest('/api/audit/sensitive-level', {
            method: 'PUT',
            body: JSON.stringify({ column_id: columnId, sensitive_level: level })
        });
        const data = await resp.json();
        if (data.success) {
            loadSensitive();
        } else {
            alert('更新失败');
        }
    } catch (err) { alert('更新失败: ' + err.message); }
}

// ═══════════════════════════════════════════════════════
// 用户下拉（行级规则使用）
// ═══════════════════════════════════════════════════════
async function loadUserSelect(selectId) {
    const sel = document.getElementById(selectId);
    if (sel.children.length > 1) return;
    try {
        const resp = await apiRequest('/api/permission/users');
        const users = await resp.json();
        users.filter(u => u.role !== 'admin').forEach(u => {
            const opt = document.createElement('option');
            opt.value = u.id; opt.textContent = `${u.username} (ID: ${u.id})`;
            sel.appendChild(opt);
        });
    } catch (err) { console.error(err); }
}

// ═══════════════════════════════════════════════════════
// Tab: 行级规则
// ═══════════════════════════════════════════════════════
async function loadAllTablesForSelect() {
    const sel = document.getElementById('rsNewTable');
    if (sel.children.length > 1) return;
    try {
        const resp = await apiRequest('/api/audit/all-tables');
        const data = await resp.json();
        (data.items || []).forEach(t => {
            const opt = document.createElement('option');
            opt.value = t.table_id;
            opt.textContent = `${t.schema_name}.${t.table_name}`;
            sel.appendChild(opt);
        });
    } catch (err) { console.error(err); }
}

async function loadRowScopes() {
    const userId = document.getElementById('rsUserSelect').value;
    const tbody = document.getElementById('rowScopeTable');
    if (!userId) { tbody.innerHTML = '<tr><td colspan="4" class="empty-state">请先选择用户</td></tr>'; return; }
    try {
        const resp = await apiRequest(`/api/audit/row-scope-rules?target_user_id=${userId}`);
        const data = await resp.json();
        if (!data.items || data.items.length === 0) {
            tbody.innerHTML = '<tr><td colspan="4" class="empty-state">暂无行级规则</td></tr>';
            return;
        }
        tbody.innerHTML = data.items.map(r => `
            <tr>
                <td>${e(r.schema_name)}</td>
                <td>${e(r.table_name)}</td>
                <td><code class="text-monospace">${e(r.filter_expression)}</code></td>
                <td><button class="btn btn-outline-danger btn-sm py-0 px-2" onclick="delRowScope(${r.user_id}, ${r.table_id})">删除</button></td>
            </tr>`).join('');
    } catch (err) { console.error('loadRowScopes error:', err); }
}

async function addRowScope() {
    const userId = document.getElementById('rsUserSelect').value;
    const tableSel = document.getElementById('rsNewTable');
    const tableId = tableSel.value;
    const expr = document.getElementById('rsNewExpr').value.trim();
    if (!userId) { alert('请先选择用户'); return; }
    if (!tableId) { alert('请选择表'); return; }
    if (!expr) { alert('请输入过滤表达式'); return; }
    try {
        await apiRequest('/api/audit/row-scope-rule', {
            method: 'POST',
            body: JSON.stringify({ user_id: parseInt(userId), table_id: parseInt(tableId), filter_expression: expr })
        });
        document.getElementById('rsNewExpr').value = '';
        loadRowScopes();
    } catch (err) { alert('添加失败: ' + err.message); }
}

async function delRowScope(userId, tableId) {
    if (!confirm('确认删除此行级规则？')) return;
    try {
        await apiRequest(`/api/audit/row-scope-rule?user_id=${userId}&table_id=${tableId}`, { method: 'DELETE' });
        loadRowScopes();
    } catch (err) { alert('删除失败: ' + err.message); }
}

// Init：优先按 URL hash（#logs/#sensitive/#rowscope）直达子页签，默认审计概览
document.addEventListener('DOMContentLoaded', () => {
    const h = location.hash.replace('#', '');
    switchTab(['overview', 'logs', 'sensitive', 'rowscope'].includes(h) ? h : 'overview');
});
