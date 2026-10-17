/* role_manage.js — 角色与权限页逻辑（四分区授权 + 数据源门控语义） */
let roles = [], selectedRole = null, catalog = {};
let dsState = {}, schemaState = {}, tableState = {}, knowledgeState = {};
let tableFilter = '', knFilter = '';
const LEVEL_OPTS = [['', '未设置'], ['ALLOW', '允许'], ['DENY', '拒绝']];
const TYPE_STATE = { datasource: () => dsState, schema: () => schemaState, table: () => tableState, knowledge: () => knowledgeState };

async function load() {
    [roles, catalog] = await Promise.all([
        apiRequest('/api/permission/roles').then(r => r.json()),
        apiRequest('/api/permission/permission-catalog').then(r => r.json())
    ]);
    buildCatalog();
    renderRoles();
    if (roles.length) selectRole(roles[0].id);
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
    await loadPermissions();
}

async function loadPermissions() {
    if (!selectedRole) return;
    const assigned = await (await apiRequest(`/api/permission/roles/${selectedRole.id}/permissions`)).json();
    dsState = {}; schemaState = {}; tableState = {}; knowledgeState = {};
    for (const p of assigned) {
        const at = ['ALLOW', 'SELECT', 'DENY'].includes(p.access_type) ? p.access_type : null;
        if (!at) continue;
        const key = String(p.resource_id);
        if (p.resource_type === 'datasource') dsState[key] = at;
        else if (p.resource_type === 'schema') schemaState[key] = at;
        else if (p.resource_type === 'table') tableState[key] = at;
        else if (p.resource_type === 'knowledge') knowledgeState[key] = at;
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

function renderAll() { renderDatasources(); renderSchemas(); renderTables(); renderKnowledge(); }

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

function resetAll() {
    dsState = {}; schemaState = {}; tableState = {}; knowledgeState = {};
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
    const resp = await apiRequest(`/api/permission/roles/${selectedRole.id}/permissions`, {
        method: 'PUT', body: JSON.stringify({ permissions: payload })
    });
    const data = await resp.json();
    if (!resp.ok) return QF.toast(data.detail || '保存失败', 'danger');
    QF.toast(data.message || '已保存', 'success');
    await loadPermissions();
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
    ['ds', 'schema', 'table', 'knowledge'].forEach(tab => document.getElementById('tab-' + tab).hidden = tab !== button.dataset.tab);
}));

load();
