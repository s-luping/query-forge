/* knowledge.html — 知识库管理交互逻辑 */
const TYPE_LABELS = {
    note: '笔记', terminology: '术语', calculation: '计算', relation: '关系',
    value_domain: '取值域', convention: '约定', entity_map: '实体映射', sample_qa: '样例',
    quality: '数据质量'
};
const ACTION_LABELS = { create: '创建', update: '更新', delete: '删除', restore: '恢复' };
const TYPE_HINTS = {
    note: '自由文本知识，适合沉淀业务规则、口径说明等通用内容',
    terminology: '业务黑话与标准字段的对应关系，如「GMV」指向哪个字段',
    calculation: '指标的计算公式与口径，如「退款率 = 退款单数 / 支付单数」',
    relation: '两张表的关联方式，配置后 AI 可自动生成正确的 JOIN',
    value_domain: '枚举字段的取值含义，如订单状态各值的业务含义',
    convention: '团队约定或命名规范，如表名前缀、时区约定等',
    entity_map: '用户自然语言中的实体到库表字段的映射',
    sample_qa: '典型问题与期望的查询方式，作为 Few-shot 示例召回',
    quality: '数据质量陷阱与清洗注意事项，避免 AI 生成错误的查询'
};
const TYPE_TIPS = {
    note: ['标题要具体，内容写「AI 需要知道的事实」', '把常用叫法加进别名，召回命中率更高', '内容会注入提示词，请避免敏感信息'],
    terminology: ['写清业务叫法对应的标准字段或表名', '例如：GMV → orders.pay_amount', '多个叫法可直接填在「别名」里'],
    calculation: ['写明指标的完整计算公式与口径', '例如：退款率 = 退款单数 / 支付单数', '注明口径边界，如「不含已取消订单」'],
    relation: ['分别选择左右表的库、表与关联字段', 'ON 条件留空会按所选字段自动生成', '业务含义写进「说明」，便于他人理解'],
    value_domain: ['列出枚举字段的每个取值及含义', '例如：pending=待处理, completed=已完成', '有映射关系的值写在一起更易召回'],
    convention: ['写明团队命名规范或流程约定', '例如：表名前缀 d_ 维度、f_ 事实', '约定类知识适合勾选「常驻上下文」'],
    entity_map: ['写清用户口语实体到库表字段的映射', '例如：一线城市 → city.tier = 1', '配合「别名」可显著提升命中率'],
    sample_qa: ['给出典型问题与期望的查询写法', '例如：上月销售额 → 按 pay_time 所在月汇总', '示例越贴近真实提问，召回越准'],
    quality: ['写明数据陷阱与清洗注意事项', '例如：test_ 开头订单需排除', '说明脏数据的判断标准与处理方式']
};
let currentPage = 1;
const pageSize = 10;
let _schemaIds = {};   // name -> id（作用域下拉）
let _isAdmin = false;
let _users = [];            // 全部用户 [{user_id, username, role}]（管理员加载，供所有者下拉）
let _versionItemId = null;  // 版本弹窗当前条目
let _listItems = [];        // 当前页列表数据（供弹窗按 id 取标题，避免把标题插进 onclick JS 串）

document.addEventListener('DOMContentLoaded', async () => {
    await loadAdminStatus();
    loadScopeOptions();
    loadList(1);
    // 类型胶囊选择器：点击同步到隐藏 select 并触发表单切换
    document.querySelectorAll('#typePills .type-pill').forEach(btn => {
        btn.addEventListener('click', () => {
            document.getElementById('knowledgeType').value = btn.dataset.value;
            onTypeChange();
        });
    });
});

function syncTypePills(type) {
    document.querySelectorAll('#typePills .type-pill').forEach(b =>
        b.classList.toggle('active', b.dataset.value === type));
}

async function loadAdminStatus() {
    try {
        const resp = await apiRequest('/api/user/profile');
        if (resp.ok) {
            const p = await resp.json();
            _isAdmin = p.role === 'admin';
        }
    } catch (e) { /* 默认按普通用户处理 */ }
    // 可见范围控件与筛选对所有用户开放；条目级"常驻"仅管理员（对全人生效）
    document.getElementById('visibilityBlock').classList.remove('d-none');
    document.getElementById('visibilityFilter').classList.remove('d-none');
    document.getElementById('pinnedBlock').classList.toggle('d-none', !_isAdmin);
    loadMyPinned();
    if (_isAdmin) loadUsers();
}

// ── 用户自选常驻（每人独立，仅注入本人对话） ──────────────
let _myPinnedIds = new Set();

async function loadMyPinned() {
    try {
        const resp = await apiRequest('/api/user/preferences/pinned-knowledge');
        if (!resp.ok) return;
        const data = await resp.json();
        _myPinnedIds = new Set((data.knowledge_ids || []).map(String));
    } catch (e) { /* 加载失败按空处理 */ }
}

async function toggleMyPin(id, btn) {
    const key = String(id);
    const next = new Set(_myPinnedIds);
    if (next.has(key)) next.delete(key); else next.add(key);
    try {
        const resp = await apiRequest('/api/user/preferences/pinned-knowledge', {
            method: 'PUT',
            body: JSON.stringify({ knowledge_ids: Array.from(next).map(Number) })
        });
        if (!resp.ok) throw new Error((await resp.json()).detail || '设置失败');
        _myPinnedIds = next;
        if (btn) {
            btn.classList.toggle('btn-warning', next.has(key));
            btn.classList.toggle('btn-outline-secondary', !next.has(key));
        }
        QF.toast(next.has(key) ? '已设为我的常驻（每次对话自动注入，仅对自己生效）' : '已取消我的常驻', 'success');
    } catch (e) {
        QF.toast('常驻设置失败: ' + e.message, 'danger');
    }
}

async function loadUsers() {
    try {
        const resp = await apiRequest('/api/user/list');
        if (!resp.ok) return;
        _users = await resp.json() || [];
        const sel = document.getElementById('knowledgeOwner');
        sel.innerHTML = _users.map(u =>
            `<option value="${u.user_id}">${escapeHtml(u.username)}${u.role === 'admin' ? '（管理员）' : ''}</option>`
        ).join('');
    } catch (e) { /* 所有者下拉加载失败按空处理 */ }
}

// ═══════════════════════════════════════════════════════
// 列表
// ═══════════════════════════════════════════════════════
async function loadList(page) {
    currentPage = page;
    document.getElementById('knowledgeLoading').classList.remove('d-none');
    document.getElementById('knowledgeContent').classList.add('d-none');
    document.getElementById('knowledgeEmpty').classList.add('d-none');
    document.getElementById('formSection').classList.add('d-none');
    document.getElementById('listSection').classList.remove('d-none');

    try {
        const vf = document.getElementById('visibilityFilter').value;
        const kw = document.getElementById('knowledgeSearch').value.trim();
        const tf = document.getElementById('typeFilter').value;
        const sf = document.getElementById('statusFilter').value;
        const pf = document.getElementById('pinnedFilter').value;
        const uf = document.getElementById('updatedFilter').value;
        const sort = document.getElementById('sortFilter').value;
        const resp = await apiRequest(`/api/knowledge?limit=${pageSize}&offset=${(page-1)*pageSize}` +
            (vf ? `&visibility=${vf}` : '') +
            (kw ? `&keyword=${encodeURIComponent(kw)}` : '') +
            (tf ? `&knowledge_type=${encodeURIComponent(tf)}` : '') +
            (sf ? `&status=${sf}` : '') +
            (pf ? `&pinned=${pf}` : '') +
            (uf ? `&updated_within=${uf}` : '') +
            `&sort=${sort}`);
        if (!resp.ok) throw new Error('加载失败');
        const data = await resp.json();
        const items = data.items || [];

        document.getElementById('knowledgeLoading').classList.add('d-none');

        if (items.length === 0 && page === 1) {
            document.getElementById('emptyText').textContent = kw
                ? `未找到与「${kw}」相关的知识` : '暂无知识';
            document.getElementById('knowledgeEmpty').classList.remove('d-none');
        } else {
            document.getElementById('knowledgeContent').classList.remove('d-none');
            renderList(items);
            const total = data.total || 0;
            const totalPages = Math.max(1, Math.ceil(total / pageSize));
            document.getElementById('prevBtn').disabled = page <= 1;
            document.getElementById('nextBtn').disabled = page >= totalPages || items.length < pageSize;
            document.getElementById('pageInfo').textContent = `第 ${page} / ${totalPages} 页 · 共 ${total} 条`;
        }
    } catch (e) {
        document.getElementById('knowledgeLoading').classList.add('d-none');
        QF.toast('加载失败: ' + e.message, 'danger');
    }
}

function relationSummary(p) {
    if (!p || typeof p !== 'object') return '';
    const l = p.left || {}, r = p.right || {};
    const on = p.on || ((l.table && r.table && l.column && r.column) ? `${l.table}.${l.column} = ${r.table}.${r.column}` : '');
    return `${l.table || ''} ${l.alias || ''} ${(p.join_type || 'INNER JOIN')} ${r.table || ''} ${r.alias || ''} ON ${on}`.trim();
}

function renderList(items) {
    const el = document.getElementById('knowledgeList');
    _listItems = items;   // 供 openVersionModal 按 id 安全取标题（标题含引号时不能拼进 onclick JS 串）
    el.innerHTML = items.map(k => {
        let summary = '';
        if (k.knowledge_type === 'relation' && k.payload && typeof k.payload === 'object') {
            summary = relationSummary(k.payload);
        }
        const aliasText = (k.aliases && k.aliases.length) ? `｜别名: ${k.aliases.join(', ')}` : '';
        const visBadge = k.visibility === 'global' ? `<span class="badge bg-dark">全局</span> ` : '';
        const pinBadge = k.is_pinned ? `<span class="badge bg-warning text-dark">全员常驻</span> ` : '';
        const visBtn = _isAdmin ? `<button class="btn btn-sm btn-outline-primary ms-1" onclick="event.stopPropagation();openVersionModal(${k.id})">版本</button>` : '';
        const myPin = _myPinnedIds.has(String(k.id));
        const pinBtn = `<button class="btn btn-sm ${myPin ? 'btn-warning' : 'btn-outline-secondary'} ms-1"
            title="${myPin ? '取消我的常驻' : '设为我的常驻（每次对话自动注入，仅对自己生效）'}"
            onclick="event.stopPropagation();toggleMyPin(${k.id}, this)">📌</button>`;
        return `
        <div class="knowledge-item p-3" onclick="editKnowledge(${k.id})">
            <div class="d-flex justify-content-between align-items-start">
                <div class="flex-grow-1" style="min-width:0;">
                    <div class="title">${visBadge}${pinBadge}${escapeHtml(k.title || '(无标题)')}<span class="type-badge">${TYPE_LABELS[k.knowledge_type] || k.knowledge_type || '笔记'}</span></div>
                    ${summary ? `<div class="preview text-primary">${escapeHtml(summary)}</div>` : `<div class="preview">${escapeHtml((k.content || '').substring(0, 120))}</div>`}
                    <div class="meta">
                        创建: ${k.created_at ? k.created_at.substring(0,10) : '-'}
                        · 更新: ${k.updated_at ? k.updated_at.substring(0,10) : '-'}
                        · 所有者: ${escapeHtml(k.owner_name || ('#' + (k.user_id ?? '-')))}
                        ${aliasText}
                    </div>
                </div>
                <div class="ms-3 text-end flex-shrink-0">
                    <span class="badge ${k.is_active ? 'badge-active' : 'badge-inactive'}">${k.is_active ? '启用' : '禁用'}</span>
                    ${pinBtn}
                    ${visBtn}
                    <button class="btn btn-sm btn-outline-danger ms-2" onclick="event.stopPropagation();deleteKnowledge(${k.id})">删除</button>
                </div>
            </div>
        </div>`;
    }).join('');
}

// ═══════════════════════════════════════════════════════
// 作用域 / 级联下拉
// ═══════════════════════════════════════════════════════
async function loadScopeOptions() {
    try {
        const resp = await apiRequest('/api/schema/schemas');
        if (!resp.ok) return;
        const data = await resp.json();
        _schemaIds = data.schema_ids || {};
        const sel = document.getElementById('knowledgeScope');
        const cur = sel.value;
        sel.innerHTML = '<option value="">全局</option>' +
            Object.keys(_schemaIds).map(n => `<option value="${_schemaIds[n]}">${e(n)}</option>`).join('');
        sel.value = cur;
        // relation 子表单的库下拉
        ['left', 'right'].forEach(side => {
            const s = document.getElementById('rel' + side.charAt(0).toUpperCase() + side.slice(1) + 'Schema');
            const cur2 = s.value;
            s.innerHTML = '<option value="">数据库</option>' +
                Object.keys(_schemaIds).map(n => `<option value="${e(n)}">${e(n)}</option>`).join('');
            s.value = cur2;
        });
    } catch (e) { console.error('加载作用域失败', e); }
}

async function onRelSchemaChange(side) {
    const cap = side.charAt(0).toUpperCase() + side.slice(1);
    const schemaName = document.getElementById('rel' + cap + 'Schema').value;
    const tableSel = document.getElementById('rel' + cap + 'Table');
    tableSel.innerHTML = '<option value="">表</option>';
    document.getElementById('rel' + cap + 'Column').innerHTML = '<option value="">关联字段</option>';
    if (!schemaName) return;
    try {
        const resp = await apiRequest(`/api/schema/tables?schema_name=${encodeURIComponent(schemaName)}`);
        if (resp.ok) {
            const d = await resp.json();
            (d.tables || []).forEach(t => {
                tableSel.innerHTML += `<option value="${e(t.name)}">${e(t.name)}${t.description ? ' - ' + e(t.description) : ''}</option>`;
            });
        }
    } catch (e) { console.error(e); }
}

async function onRelTableChange(side) {
    const cap = side.charAt(0).toUpperCase() + side.slice(1);
    const schemaName = document.getElementById('rel' + cap + 'Schema').value;
    const tableName = document.getElementById('rel' + cap + 'Table').value;
    const colSel = document.getElementById('rel' + cap + 'Column');
    colSel.innerHTML = '<option value="">关联字段</option>';
    if (!schemaName || !tableName) return;
    try {
        const resp = await apiRequest(`/api/schema/list?schema_name=${encodeURIComponent(schemaName)}&table_name=${encodeURIComponent(tableName)}&limit=500`);
        if (resp.ok) {
            const d = await resp.json();
            (d.items || []).forEach(it => {
                colSel.innerHTML += `<option value="${e(it.column_name)}">${e(it.column_name)}</option>`;
            });
        }
    } catch (e) { console.error(e); }
    refreshOnPreview();
}

function refreshOnPreview() {
    const l = {
        table: document.getElementById('relLeftTable').value,
        column: document.getElementById('relLeftColumn').value
    };
    const r = {
        table: document.getElementById('relRightTable').value,
        column: document.getElementById('relRightColumn').value
    };
    const join = document.getElementById('relJoinType').value;
    const onInput = document.getElementById('relOn').value.trim();
    const on = onInput || ((l.table && r.table && l.column && r.column) ? `${l.table}.${l.column} = ${r.table}.${r.column}` : '');
    document.getElementById('relOnPreview').textContent = (l.table && r.table)
        ? `${l.table} ${join} ${r.table} ON ${on}` : '（选择左/右表与关联字段后生成）';
}

function onTypeChange() {
    const type = document.getElementById('knowledgeType').value;
    const isRel = type === 'relation';
    syncTypePills(type);
    const hint = document.getElementById('typeHint');
    if (hint) hint.textContent = TYPE_HINTS[type] || '';
    const tips = document.getElementById('tipsList');
    if (tips) tips.innerHTML = (TYPE_TIPS[type] || TYPE_TIPS.note)
        .map(t => `<li>${t}</li>`).join('');
    document.getElementById('relationForm').classList.toggle('d-none', !isRel);
    // 关系类型下，自由文本正文可隐藏（内容由结构化生成）；保留以便填写补充说明
    document.getElementById('contentBlock').style.display = isRel ? 'none' : 'block';
}

// 搜索防抖
let _searchTimer = null;
function onSearchInput() {
    clearTimeout(_searchTimer);
    _searchTimer = setTimeout(() => loadList(1), 300);
}

// ═══════════════════════════════════════════════════════
// 表单
// ═══════════════════════════════════════════════════════
function showCreateForm() {
    document.getElementById('knowledgeId').value = '';
    document.getElementById('knowledgeTitle').value = '';
    document.getElementById('knowledgeType').value = 'note';
    document.getElementById('knowledgeScope').value = '';
    document.getElementById('knowledgeAliases').value = '';
    document.getElementById('knowledgeContent2').value = '';
    document.getElementById('knowledgeActive').value = '1';
    document.getElementById('knowledgeVisibility').value = 'personal';
    document.getElementById('knowledgePinned').checked = false;
    document.getElementById('versionHistoryBtn').classList.add('d-none');
    // 新建时所有者恒为创建者本人，不提供更改
    document.getElementById('ownerBlock').classList.add('d-none');
    document.getElementById('knowledgeOwner').disabled = true;
    _versionItemId = null;
    // 清空 relation 子表单
    ['Left', 'Right'].forEach(cap => {
        document.getElementById('rel' + cap + 'Schema').value = '';
        document.getElementById('rel' + cap + 'Table').innerHTML = '<option value="">表</option>';
        document.getElementById('rel' + cap + 'Column').innerHTML = '<option value="">关联字段</option>';
        document.getElementById('rel' + cap + 'Alias').value = '';
    });
    document.getElementById('relJoinType').value = 'INNER JOIN';
    document.getElementById('relOn').value = '';
    document.getElementById('relNote').value = '';
    refreshOnPreview();
    onTypeChange();
    document.getElementById('formTitle').textContent = '新建知识';
    document.getElementById('listSection').classList.add('d-none');
    document.getElementById('formSection').classList.remove('d-none');
}

async function editKnowledge(id) {
    document.getElementById('knowledgeLoading').classList.remove('d-none');
    document.getElementById('listSection').classList.add('d-none');
    try {
        const resp = await apiRequest(`/api/knowledge/${id}`);
        if (!resp.ok) throw new Error('加载失败');
        const k = await resp.json();
        document.getElementById('knowledgeId').value = k.id;
        document.getElementById('knowledgeTitle').value = k.title || '';
        document.getElementById('knowledgeType').value = k.knowledge_type || 'note';
        document.getElementById('knowledgeScope').value = k.scope_schema_id != null ? String(k.scope_schema_id) : '';
        document.getElementById('knowledgeAliases').value = (k.aliases || []).join(', ');
        document.getElementById('knowledgeContent2').value = k.content || '';
        document.getElementById('knowledgeActive').value = k.is_active ? '1' : '0';
        document.getElementById('knowledgeVisibility').value = k.visibility || 'personal';
        document.getElementById('knowledgePinned').checked = !!k.is_pinned;
        // 所有者（管理员可改；下拉未加载完时回退显示 user_id）
        document.getElementById('ownerBlock').classList.toggle('d-none', !_isAdmin);
        const ownerSel = document.getElementById('knowledgeOwner');
        ownerSel.disabled = !_isAdmin;
        if (_isAdmin) {
            if (!_users.length) ownerSel.innerHTML = `<option value="${k.user_id}">#${k.user_id}</option>`;
            ownerSel.value = String(k.user_id);
            if (ownerSel.value !== String(k.user_id)) {
                ownerSel.insertAdjacentHTML('beforeend',
                    `<option value="${k.user_id}">#${k.user_id}（已删除）</option>`);
                ownerSel.value = String(k.user_id);
            }
        }
        _versionItemId = k.id;
        document.getElementById('versionHistoryBtn').classList.toggle('d-none', !_isAdmin);
        // 关系子表单回填
        ['Left', 'Right'].forEach(cap => {
            document.getElementById('rel' + cap + 'Schema').value = '';
            document.getElementById('rel' + cap + 'Table').innerHTML = '<option value="">表</option>';
            document.getElementById('rel' + cap + 'Column').innerHTML = '<option value="">关联字段</option>';
            document.getElementById('rel' + cap + 'Alias').value = '';
        });
        document.getElementById('relJoinType').value = 'INNER JOIN';
        document.getElementById('relOn').value = '';
        document.getElementById('relNote').value = '';
        if (k.knowledge_type === 'relation' && k.payload && typeof k.payload === 'object') {
            const p = k.payload;
            const fill = (side) => {
                const cap = side.charAt(0).toUpperCase() + side.slice(1);
                const s = p[side] || {};
                document.getElementById('rel' + cap + 'Schema').value = s.schema || '';
                document.getElementById('rel' + cap + 'Alias').value = s.alias || '';
                if (s.schema && s.table) {
                    // 异步加载表/字段下拉后回填
                    loadRelSelects(cap, s.schema, s.table, s.column);
                }
            };
            fill('left'); fill('right');
            document.getElementById('relJoinType').value = p.join_type || 'INNER JOIN';
            document.getElementById('relOn').value = p.on || '';
            document.getElementById('relNote').value = p.note || '';
        }
        refreshOnPreview();
        onTypeChange();
        document.getElementById('knowledgeLoading').classList.add('d-none');
        document.getElementById('formTitle').textContent = '编辑知识';
        document.getElementById('formSection').classList.remove('d-none');
    } catch (e) {
        document.getElementById('knowledgeLoading').classList.add('d-none');
        showList();
        QF.toast('加载失败: ' + e.message, 'danger');
    }
}

async function loadRelSelects(cap, schemaName, tableName, column) {
    try {
        const resp = await apiRequest(`/api/schema/tables?schema_name=${encodeURIComponent(schemaName)}`);
        if (resp.ok) {
            const d = await resp.json();
            const tableSel = document.getElementById('rel' + cap + 'Table');
            tableSel.innerHTML = '<option value="">表</option>' +
                (d.tables || []).map(t => `<option value="${e(t.name)}">${e(t.name)}</option>`).join('');
            tableSel.value = tableName;
        }
        const cresp = await apiRequest(`/api/schema/list?schema_name=${encodeURIComponent(schemaName)}&table_name=${encodeURIComponent(tableName)}&limit=500`);
        if (cresp.ok) {
            const d = await cresp.json();
            const colSel = document.getElementById('rel' + cap + 'Column');
            colSel.innerHTML = '<option value="">关联字段</option>' +
                (d.items || []).map(it => `<option value="${e(it.column_name)}">${e(it.column_name)}</option>`).join('');
            colSel.value = column || '';
        }
    } catch (e) { console.error(e); }
}

function showList() {
    document.getElementById('formSection').classList.add('d-none');
    document.getElementById('listSection').classList.remove('d-none');
    loadList(currentPage);
}

function buildRelationPayload() {
    const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
    const side = (s) => {
        const c = cap(s);
        return {
            schema: document.getElementById('rel' + c + 'Schema').value,
            table: document.getElementById('rel' + c + 'Table').value,
            alias: document.getElementById('rel' + c + 'Alias').value.trim(),
            column: document.getElementById('rel' + c + 'Column').value
        };
    };
    const l = side('left'), r = side('right');
    const join = document.getElementById('relJoinType').value;
    const onInput = document.getElementById('relOn').value.trim();
    const on = onInput || ((l.table && r.table && l.column && r.column) ? `${l.table}.${l.column} = ${r.table}.${r.column}` : '');
    return {
        left: l, right: r, join_type: join, on: on,
        note: document.getElementById('relNote').value.trim()
    };
}

async function saveKnowledge(event) {
    event.preventDefault();
    const id = document.getElementById('knowledgeId').value;
    const type = document.getElementById('knowledgeType').value;
    const title = document.getElementById('knowledgeTitle').value.trim();
    const scopeVal = document.getElementById('knowledgeScope').value;
    const scope_schema_id = scopeVal === '' ? null : parseInt(scopeVal);
    const aliases = document.getElementById('knowledgeAliases').value
        .split(',').map(s => s.trim()).filter(Boolean);
    const content = document.getElementById('knowledgeContent2').value.trim();
    const isActive = parseInt(document.getElementById('knowledgeActive').value);

    const body = { title, knowledge_type: type, scope_schema_id, aliases, is_active: isActive };
    if (_isAdmin) {
        body.visibility = document.getElementById('knowledgeVisibility').value;
        if (document.getElementById('pinnedBlock').classList.contains('d-none') === false) {
            body.is_pinned = document.getElementById('knowledgePinned').checked ? 1 : 0;
        }
        if (id) body.owner_user_id = parseInt(document.getElementById('knowledgeOwner').value) || null;
    } else {
        body.visibility = document.getElementById('knowledgeVisibility').value;
    }
    if (type === 'relation') {
        body.payload = buildRelationPayload();
        // relation 类型下自由文本作为补充说明（note）
        body.content = content;
    } else {
        body.content = content;
        body.payload = {};
    }

    try {
        let resp;
        if (id) {
            resp = await apiRequest(`/api/knowledge/${id}`, { method: 'PUT', body: JSON.stringify(body) });
        } else {
            resp = await apiRequest('/api/knowledge', { method: 'POST', body: JSON.stringify(body) });
        }
        if (!resp.ok) throw new Error((await resp.json()).detail || '保存失败');
        QF.toast(id ? '更新成功' : '创建成功', 'success');
        showList();
    } catch (e) {
        QF.toast('保存失败: ' + e.message, 'danger');
    }
}

async function deleteKnowledge(id) {
    if (!confirm('确定删除此知识？将彻底删除该条目及其全部版本历史，不可恢复。')) return;
    try {
        const resp = await apiRequest(`/api/knowledge/${id}`, { method: 'DELETE' });
        if (!resp.ok) throw new Error('删除失败');
        loadList(currentPage);
    } catch (e) {
        QF.toast('删除失败: ' + e.message, 'danger');
    }
}

// ═══════════════════════════════════════════════════════
// 版本历史 / 恢复
// ═══════════════════════════════════════════════════════
function openVersionModal(id) {
    _versionItemId = id;
    // 标题从当前页列表缓存取（textContent 渲染，杜绝把用户输入插进 JS 串）
    const item = (_listItems || []).find(k => k.id === id);
    document.getElementById('versionItemTitle').textContent = (item && item.title) || '';
    showVersionModal();
}

async function showVersionModal() {
    if (!_versionItemId) return;
    try {
        const resp = await apiRequest(`/api/knowledge/${_versionItemId}/versions`);
        if (!resp.ok) throw new Error('加载失败');
        const data = await resp.json();
        const items = data.items || [];
        const el = document.getElementById('versionList');
        if (!items.length) {
            el.innerHTML = '<div class="text-center text-muted py-4">暂无版本记录</div>';
        } else {
            el.innerHTML = items.map(v => {
            const s = v.snapshot || {};
            const action = ACTION_LABELS[v.action] || v.action;
            const active = s.is_active ? '' : ' <span class="badge bg-secondary">已禁用</span>';
            const typeLabel = TYPE_LABELS[s.knowledge_type] || s.knowledge_type || '';
            const typeBadge = typeLabel ? `<span class="type-badge">${typeLabel}</span>` : '';
            const titleLine = s.title ? `<div class="fw-semibold mt-2" style="font-size:13px;">${escapeHtml(s.title)}${typeBadge}</div>` : '';
            // 快照里的 aliases 可能是数组 / JSON 字符串 / 逗号分隔字符串 / null，统一归一成数组
            const snapAliases = (function (v) {
                if (Array.isArray(v)) return v;
                if (typeof v === 'string' && v.trim()) {
                    try {
                        const p = JSON.parse(v);
                        if (Array.isArray(p)) return p.map(String);
                    } catch (e) { /* 非合法 JSON，按逗号分隔处理 */ }
                    return v.split(',').map(x => x.trim()).filter(Boolean);
                }
                return [];
            })(s.aliases);
            const aliasLine = snapAliases.length
                ? `<div class="small text-muted mt-1">别名：${escapeHtml(snapAliases.join(', '))}</div>` : '';
            return `
            <div class="list-group-item">
                <div class="d-flex justify-content-between align-items-start">
                    <div class="flex-grow-1" style="min-width:0;">
                        <div class="d-flex align-items-center flex-wrap gap-1">
                            <b>v${v.version_no}</b> <span class="badge bg-info text-dark">${action}</span>${active}
                            <span class="small text-muted ms-1">${v.created_at || ''} · 操作人 ${v.operator_name ? escapeHtml(v.operator_name) : ('#' + (v.operator_id ?? '-'))}</span>
                        </div>
                        ${titleLine}${aliasLine}
                        <div class="version-content">${escapeHtml(s.content || '（无内容）')}</div>
                    </div>
                    <button class="btn btn-sm btn-outline-primary flex-shrink-0 ms-2"
                        onclick="restoreVersion(${v.version_no})">恢复到此版本</button>
                </div>
            </div>`;
        }).join('');
        }
        // 打开 bootstrap 弹窗
        const modal = bootstrap.Modal.getOrCreateInstance(document.getElementById('versionModal'));
        modal.show();
    } catch (e) {
        QF.toast('版本历史加载失败: ' + e.message, 'danger');
    }
}

async function restoreVersion(versionNo) {
    if (!confirm(`确定恢复到版本 v${versionNo}？当前内容将被覆盖（也会记录新版本，可再次恢复）。`)) return;
    try {
        const resp = await apiRequest(`/api/knowledge/${_versionItemId}/restore`, {
            method: 'POST',
            body: JSON.stringify({ version_no: versionNo })
        });
        if (!resp.ok) throw new Error((await resp.json()).detail || '恢复失败');
        QF.toast(`已恢复到 v${versionNo}`, 'success');
        const modal = bootstrap.Modal.getInstance(document.getElementById('versionModal'));
        if (modal) modal.hide();
        showList();
    } catch (e) {
        QF.toast('恢复失败: ' + e.message, 'danger');
    }
}

// escapeHtml 由 app_common.js 提供
function loadPage(page) { loadList(page); }
