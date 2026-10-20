/* role_manage.js — 角色与权限页逻辑（五分区授权 + 数据源门控语义） */
let roles = [], selectedRole = null, catalog = {};
let dsState = {}, schemaState = {}, tableState = {}, knowledgeState = {};
let rowState = {};   // 行级过滤 {tableId: filter_expression}，仅收录非空表达式
let tableFilter = '', knFilter = '', rowFilter = '';
const LEVEL_OPTS = [['', '未设置'], ['ALLOW', '允许'], ['DENY', '拒绝']];
const TYPE_STATE = { datasource: () => dsState, schema: () => schemaState, table: () => tableState, knowledge: () => knowledgeState };

async function load(keepId) {
    [roles, catalog] = await Promise.all([
        apiRequest('/api/permission/roles').then(r => r.json()),
        apiRequest('/api/permission/permission-catalog').then(r => r.json())
    ]);
    buildCatalog();
    renderRoles();
    const target = keepId ? roles.find(r => String(r.id) === String(keepId)) : null;
    if (target) await selectRole(target.id);
    else if (roles.length) selectRole(roles[0].id);
    else renderMeta(null);
}

function buildCatalog() {
    const dsName = id => { const d = (catalog.datasources || []).find(x => x.id === id); return d ? d.name : ''; };
    (catalog.schemas || []).forEach(s => {
        s.display = (dsName(s.datasource_id) ? dsName(s.datasource_id) + '/' : '') + s.name;
    });
    (catalog.tables || []).forEach(t => {
        const s = (catalog.schemas || []).find(x => x.id === t.schema_id);
        const pre = s ? (s.display || s.name) : '';
        t.display = (pre ? pre + '.' : '') + t.name;
    });
}

function renderRoles() {
    const sel = document.getElementById('roleSelect');
    sel.innerHTML = '<option value="">请选择角色...</option>' + roles.map(r =>
        `<option value="${r.id}" ${selectedRole && selectedRole.id === r.id ? 'selected' : ''}>${esc(r.name)}（${esc(r.code)}）· ${r.user_count}用户</option>`).join('');
}

async function selectRole(id) {
    selectedRole = roles.find(r => String(r.id) === String(id));
    if (!selectedRole) return;
    document.getElementById('roleTitle').textContent = `${selectedRole.name}（${selectedRole.code}）`;
    document.getElementById('roleDescription').value = selectedRole.description || '';
    document.getElementById('btnDeleteRole').style.display = selectedRole.is_system ? 'none' : '';
    renderRoles();
    renderMeta(selectedRole);
    await loadPermissions();
}

/* 角色信息条：权限数 / 创建时间 / 绑定用户 */
function renderMeta(role) {
    const el = document.getElementById('roleMeta');
    if (!role) { el.innerHTML = ''; return; }
    el.innerHTML = `
        <span class="meta-item">权限条数 <span class="meta-val">${role.permission_count ?? 0}</span></span>
        <span class="meta-item">绑定用户 <span class="meta-val">${role.user_count ?? 0}</span></span>
        ${role.created_at ? `<span class="meta-item">创建于 <span class="meta-val">${esc(role.created_at)}</span></span>` : ''}
        <span class="meta-item" id="metaUsers">成员加载中...</span>`;
    apiRequest(`/api/permission/roles/${role.id}/users`).then(r => r.json()).then(users => {
        const holder = document.getElementById('metaUsers');
        if (!holder) return;
        if (!users.length) { holder.textContent = '成员：暂无绑定用户'; return; }
        holder.innerHTML = '成员：' + users.map(u =>
            `<span class="meta-user${u.is_active ? '' : ' inactive'}" title="${u.is_active ? '' : '已停用'}">${esc(u.username)}</span>`).join('');
    }).catch(() => { const h = document.getElementById('metaUsers'); if (h) h.textContent = '成员加载失败'; });
}

async function loadPermissions() {
    if (!selectedRole) return;
    const assigned = await (await apiRequest(`/api/permission/roles/${selectedRole.id}/permissions`)).json();
    dsState = {}; schemaState = {}; tableState = {}; knowledgeState = {}; rowState = {};
    for (const p of assigned) {
        const at = ['ALLOW', 'SELECT', 'DENY'].includes(p.access_type) ? p.access_type : null;
        if (!at) continue;
        const key = String(p.resource_id);
        if (p.resource_type === 'datasource') dsState[key] = at;
        else if (p.resource_type === 'schema') schemaState[key] = at;
        else if (p.resource_type === 'table') tableState[key] = at;
        else if (p.resource_type === 'knowledge') knowledgeState[key] = at;
        else if (p.resource_type === 'row' && p.filter_expression) rowState[key] = p.filter_expression;
    }
    renderAll();
}

function stateOf(type, id) { const m = TYPE_STATE[type](); return m[String(id)] || ''; }
function setState(type, id, at) { const m = TYPE_STATE[type](); const k = String(id); if (at) m[k] = at; else delete m[k]; }

/* 级别三态分段按钮：未设置(灰) / 允许(绿) / 拒绝(红) */
function levelCtl(type, id) {
    const cur = stateOf(type, id);
    const idArg = id === null ? 'null' : id;
    const btn = (v, label, cls) =>
        `<button type="button" class="lvl-btn ${cls} ${cur === v ? 'active' : ''}" onclick="onLevel(this,'${type}',${idArg},'${v}')">${label}</button>`;
    return `<div class="lvl-group">${btn('', '未设置', 'lvl-off')}${btn('ALLOW', '允许', 'lvl-allow')}${btn('DENY', '拒绝', 'lvl-deny')}</div>`;
}

function onLevel(el, type, id, at) {
    setState(type, id, at);
    const group = el.parentElement;
    group.querySelectorAll('.lvl-btn').forEach(b => b.classList.remove('active'));
    el.classList.add('active');
}

function levelRow(type, id, label, sub, allTag) {
    const tag = allTag ? '<span class="all-tag">全量</span>' : '';
    return `<div class="res-row${allTag ? ' is-all' : ''}"><div class="res-cell">
        <div class="lbl">${esc(label)}${tag}</div>${sub ? `<div class="sub">${esc(sub)}</div>` : ''}</div>${levelCtl(type, id)}</div>`;
}

function empty(msg) { return `<div class="area-empty">${msg}</div>`; }

function renderAll() { renderDatasources(); renderSchemas(); renderTables(); renderKnowledge(); renderRows(); }

function renderDatasources() {
    const rows = [levelRow('datasource', null, '全部数据源', '不限具体资源，授予所有数据源、全部库表', true)];
    for (const d of (catalog.datasources || [])) {
        rows.push(levelRow('datasource', d.id, d.name, d.db_type || '', false));
    }
    document.getElementById('dsArea').innerHTML = rows.join('');
}

function renderSchemas() {
    const byDs = {};
    for (const s of (catalog.schemas || [])) { const k = String(s.datasource_id); (byDs[k] = byDs[k] || []).push(s); }
    const dsName = id => { const d = (catalog.datasources || []).find(x => x.id === id); return d ? d.name : '未关联数据源'; };
    const keys = Object.keys(byDs);
    if (!keys.length) { document.getElementById('schemaArea').innerHTML = empty('暂无库'); return; }
    let html = '';
    for (const k of keys) {
        const dsid = k === 'null' ? null : Number(k);
        html += `<details class="res-group" open><summary><span class="caret">▸</span>${esc(dsName(dsid))} <span class="count">（${byDs[k].length}）</span></summary>`;
        html += `<div class="res-body">`;
        for (const s of byDs[k]) html += levelRow('schema', s.id, s.display || s.name, '', false);
        html += `</div></details>`;
    }
    document.getElementById('schemaArea').innerHTML = html;
}

function renderTables(f) {
    if (f !== undefined) tableFilter = f;
    const kw = (tableFilter || '').toLowerCase();
    const bySch = {};
    for (const t of (catalog.tables || [])) { const k = String(t.schema_id); (bySch[k] = bySch[k] || []).push(t); }
    const schName = id => { const s = (catalog.schemas || []).find(x => x.id === id); return s ? (s.display || s.name) : ('库#' + id); };
    const keys = Object.keys(bySch);
    if (!keys.length) { document.getElementById('tableArea').innerHTML = empty('暂无表'); return; }
    let html = '';
    for (const k of keys) {
        const schid = Number(k);
        let items = bySch[k];
        if (kw) items = items.filter(t => (t.name || '').toLowerCase().includes(kw));
        if (!items.length) continue;
        html += `<details class="res-group"><summary><span class="caret">▸</span>${esc(schName(schid))} <span class="count">（${items.length}）</span></summary>`;
        html += `<div class="res-body">`;
        for (const t of items) html += levelRow('table', t.id, t.display || t.name, '', false);
        html += `</div></details>`;
    }
    document.getElementById('tableArea').innerHTML = html || empty(kw ? `无匹配表（共 ${catalog.tables.length} 张）` : '暂无表');
}

function renderKnowledge(f) {
    if (f !== undefined) knFilter = f;
    const kw = (knFilter || '').toLowerCase();
    const items = (catalog.knowledge || []).filter(k => !kw || (k.name || '').toLowerCase().includes(kw));
    document.getElementById('knowledgeArea').innerHTML = items.map(k => levelRow('knowledge', k.id, k.name, '', false)).join('')
        || empty(kw ? '无匹配条目' : '暂无知识条目');
}

/* 行级过滤分区：表 + 过滤表达式输入 */
function renderRows(f) {
    if (f !== undefined) rowFilter = f;
    const kw = (rowFilter || '').toLowerCase();
    const bySch = {};
    for (const t of (catalog.tables || [])) { const k = String(t.schema_id); (bySch[k] = bySch[k] || []).push(t); }
    const schName = id => { const s = (catalog.schemas || []).find(x => x.id === id); return s ? (s.display || s.name) : ('库#' + id); };
    const keys = Object.keys(bySch);
    if (!keys.length) { document.getElementById('rowArea').innerHTML = empty('暂无表，请先完成元数据同步'); return; }
    let html = '', shown = 0;
    for (const k of keys) {
        const schid = Number(k);
        let items = bySch[k];
        if (kw) items = items.filter(t => (t.name || '').toLowerCase().includes(kw));
        if (!items.length) continue;
        shown += items.length;
        html += `<details class="res-group"${kw ? ' open' : ''}><summary><span class="caret">▸</span>${esc(schName(schid))} <span class="count">（${items.length}）</span></summary>`;
        html += `<div class="res-body">`;
        for (const t of items) html += rowRuleRow(t);
        html += `</div></details>`;
    }
    document.getElementById('rowArea').innerHTML = (html || empty(kw ? `无匹配表（共 ${catalog.tables.length} 张）` : '暂无表'))
        + (shown ? `<div class="rule-count">已配置规则 ${Object.keys(rowState).length} 条</div>` : '');
}

function rowRuleRow(t) {
    const expr = rowState[String(t.id)] || '';
    const tag = expr ? '<span class="rule-tag">已配置</span>' : '';
    return `<div class="res-row rule-row"><div class="res-cell">
        <div class="lbl">${esc(t.display || t.name)}${tag}</div></div>
        <input class="form-control form-control-sm rule-input" spellcheck="false"
            placeholder="如：sales_region = '华东'" value="${esc(expr)}"
            oninput="onRowExpr(this, ${t.id})"></div>`;
}

function onRowExpr(el, id) {
    const expr = (el.value || '').trim();
    if (expr) rowState[String(id)] = expr; else delete rowState[String(id)];
    const lbl = el.closest('.res-row').querySelector('.lbl');
    let tag = lbl.querySelector('.rule-tag');
    if (expr && !tag) { tag = document.createElement('span'); tag.className = 'rule-tag'; tag.textContent = '已配置'; lbl.appendChild(tag); }
    else if (!expr && tag) tag.remove();
    const counter = document.querySelector('#rowArea .rule-count');
    if (counter) counter.textContent = `已配置规则 ${Object.keys(rowState).length} 条`;
}

function resetAll() {
    dsState = {}; schemaState = {}; tableState = {}; knowledgeState = {}; rowState = {};
    renderAll();
    QF.toast('已重置未保存的改动', 'info');
}

async function savePermissions() {
    if (!selectedRole) return;
    const payload = [];
    const collect = (type, state) => {
        for (const k in state) {
            const rid = k === 'null' ? null : Number(k);
            payload.push({ permission_code: 'access', resource_type: type, resource_id: rid, access_type: state[k] });
        }
    };
    collect('datasource', dsState);
    collect('schema', schemaState);
    collect('table', tableState);
    collect('knowledge', knowledgeState);
    for (const k in rowState) {
        payload.push({ permission_code: 'access', resource_type: 'row', resource_id: Number(k),
                       access_type: 'ALLOW', filter_expression: rowState[k] });
    }
    const resp = await apiRequest(`/api/permission/roles/${selectedRole.id}/permissions`, {
        method: 'PUT', body: JSON.stringify({ permissions: payload })
    });
    const data = await resp.json();
    if (!resp.ok) return QF.toast(data.detail || '保存失败', 'danger');
    QF.toast(data.message || '已保存', 'success');
    await load(selectedRole.id);   // 重新拉取角色列表，刷新权限数/用户数
}

async function saveDescription() {
    if (!selectedRole) return;
    selectedRole.description = document.getElementById('roleDescription').value;
    await savePermissions();
}

async function deleteRole() {
    if (!selectedRole) return;
    if (!confirm(`确认删除角色「${selectedRole.name}」？其授权关系将一并清除。`)) return;
    const resp = await apiRequest(`/api/permission/roles/${selectedRole.id}`, { method: 'DELETE' });
    if (!resp.ok) return QF.toast((await resp.json()).detail || '删除失败', 'danger');
    QF.toast('角色已删除', 'success');
    selectedRole = null;
    load();
}

let createRoleModal = null;
function openCreateRole() {
    document.getElementById('crName').value = '';
    document.getElementById('crCode').value = '';
    document.getElementById('crDesc').value = '';
    if (!createRoleModal) createRoleModal = new bootstrap.Modal(document.getElementById('createRoleModal'));
    createRoleModal.show();
}
async function submitCreateRole() {
    const name = document.getElementById('crName').value.trim();
    const code = document.getElementById('crCode').value.trim();
    const desc = document.getElementById('crDesc').value.trim();
    if (!name || !code) return QF.toast('角色名称和编码必填', 'warning');
    const resp = await apiRequest('/api/permission/roles', { method: 'POST', body: JSON.stringify({ name, code, description: desc || null }) });
    const data = await resp.json();
    if (!resp.ok) return QF.toast(data.detail || '创建失败', 'danger');
    QF.toast('角色创建成功', 'success');
    createRoleModal.hide();
    load();
}

function esc(v) { return String(v || '').replace(/[&<>"']/g, x => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[x])); }

/* 授权分区页签切换 */
document.querySelectorAll('[data-tab]').forEach(button => button.addEventListener('click', () => {
    document.querySelectorAll('[data-tab]').forEach(item => item.classList.remove('active'));
    button.classList.add('active');
    ['ds', 'schema', 'table', 'knowledge', 'row'].forEach(tab => document.getElementById('tab-' + tab).hidden = tab !== button.dataset.tab);
}));

load();
