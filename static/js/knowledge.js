/* knowledge.html — 知识库管理交互逻辑 */
const TYPE_LABELS = {
    note: '笔记', terminology: '术语', calculation: '计算', relation: '关系',
    value_domain: '取值域', convention: '约定', entity_map: '实体映射', sample_qa: '样例'
};
let currentPage = 1;
const pageSize = 10;
let _schemaIds = {};   // name -> id（作用域下拉）

document.addEventListener('DOMContentLoaded', () => { loadScopeOptions(); loadList(1); });

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
        const resp = await apiRequest(`/api/knowledge?limit=${pageSize}&offset=${(page-1)*pageSize}`);
        if (!resp.ok) throw new Error('加载失败');
        const data = await resp.json();
        const items = data.items || [];

        document.getElementById('knowledgeLoading').classList.add('d-none');

        if (items.length === 0 && page === 1) {
            document.getElementById('knowledgeEmpty').classList.remove('d-none');
        } else {
            document.getElementById('knowledgeContent').classList.remove('d-none');
            renderList(items);
            document.getElementById('prevBtn').disabled = page <= 1;
            document.getElementById('nextBtn').disabled = items.length < pageSize;
            document.getElementById('pageInfo').textContent = `第 ${page} 页`;
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
    el.innerHTML = items.map(k => {
        let summary = '';
        if (k.knowledge_type === 'relation' && k.payload && typeof k.payload === 'object') {
            summary = relationSummary(k.payload);
        }
        const aliasText = (k.aliases && k.aliases.length) ? `｜别名: ${k.aliases.join(', ')}` : '';
        return `
        <div class="knowledge-item p-3" onclick="editKnowledge(${k.id})">
            <div class="d-flex justify-content-between align-items-start">
                <div class="flex-grow-1" style="min-width:0;">
                    <div class="title">${escapeHtml(k.title || '(无标题)')}<span class="type-badge">${TYPE_LABELS[k.knowledge_type] || k.knowledge_type || '笔记'}</span></div>
                    ${summary ? `<div class="preview text-primary">${escapeHtml(summary)}</div>` : `<div class="preview">${escapeHtml((k.content || '').substring(0, 120))}</div>`}
                    <div class="meta">
                        创建: ${k.created_at ? k.created_at.substring(0,10) : '-'}
                        · 更新: ${k.updated_at ? k.updated_at.substring(0,10) : '-'}
                        ${aliasText}
                    </div>
                </div>
                <div class="ms-3 text-end flex-shrink-0">
                    <span class="badge ${k.is_active ? 'badge-active' : 'badge-inactive'}">${k.is_active ? '启用' : '禁用'}</span>
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
    document.getElementById('relationForm').classList.toggle('d-none', !isRel);
    // 关系类型下，自由文本正文可隐藏（内容由结构化生成）；保留以便填写补充说明
    document.getElementById('contentBlock').style.display = isRel ? 'none' : 'block';
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
    if (!confirm('确定删除此知识？')) return;
    try {
        const resp = await apiRequest(`/api/knowledge/${id}`, { method: 'DELETE' });
        if (!resp.ok) throw new Error('删除失败');
        loadList(currentPage);
    } catch (e) {
        QF.toast('删除失败: ' + e.message, 'danger');
    }
}

// escapeHtml 由 app_common.js 提供
function loadPage(page) { loadList(page); }
