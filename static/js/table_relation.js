/* QueryForge 页面脚本 — 表关系维护（static/template/schema/table_relation.html）
   公共 apiRequest / e / fmt / QF 见 app_common.js */

let schemaList = [];          // [{name, ...}]，来自 /api/schema/schemas
let tableCache = {};          // `${schemaName}::${tableName}` → columns
let relationList = [];

const JOIN_LABELS = { 'INNER JOIN': '内连接', 'LEFT JOIN': '左连接', 'RIGHT JOIN': '右连接', 'FULL JOIN': '全连接' };

// ── 初始化 ────────────────────────────────────────────────
(async function init() {
    await loadSchemas();
    await loadRelations();
})();

async function loadSchemas() {
    try {
        const resp = await apiRequest('/api/schema/schemas');
        const data = await resp.json();
        schemaList = (data.schemas || []).map(n => ({ name: n }));
        // 过滤下拉
        const filter = document.getElementById('relSchemaFilter');
        filter.innerHTML = '<option value="">全部数据库</option>' +
            schemaList.map(s => `<option value="${e(s.name)}">${e(s.name)}</option>`).join('');
        // 弹窗左右两侧库下拉在 showRelModal 中按需填充
    } catch (err) {
        console.error(err);
        QF.toast('加载数据库列表失败', 'danger');
    }
}

// ── 列表 ─────────────────────────────────────────────────
async function loadRelations() {
    const schema = document.getElementById('relSchemaFilter').value;
    const qs = schema ? `?schema_name=${encodeURIComponent(schema)}` : '';
    try {
        const resp = await apiRequest('/api/schema/relations' + qs);
        const data = await resp.json();
        relationList = data.items || [];
        const tbody = document.getElementById('relTable');
        if (!relationList.length) {
            tbody.innerHTML = '<tr><td colspan="8" class="empty-state">暂无表关系，点击右上角「新增关系」维护</td></tr>';
            return;
        }
        tbody.innerHTML = relationList.map(r => `<tr>
            <td><span class="table-badge">${e(r.left_schema_name || '-')}</span> <span class="rel-arrow">⇄</span> <span class="table-badge">${e(r.right_schema_name || '-')}</span></td>
            <td class="text-monospace">${e(r.left_table)}.${e(r.left_column)}</td>
            <td><span class="badge badge-join">${JOIN_LABELS[r.join_type] || r.join_type}</span></td>
            <td class="text-monospace"><span class="rel-arrow">=</span> ${e(r.right_table)}.${e(r.right_column)}</td>
            <td>${e(r.relation_type || '-')}</td>
            <td>${e(r.description || '-')}</td>
            <td>${fmt(r.updated_at || r.created_at)}</td>
            <td>
                <button class="btn btn-sm btn-outline-primary" onclick="showRelModal(${r.id})" title="编辑"><i class="fas fa-edit"></i></button>
                <button class="btn btn-sm btn-outline-danger" onclick="deleteRelation(${r.id})" title="删除"><i class="fas fa-trash"></i></button>
            </td>
        </tr>`).join('');
    } catch (err) {
        console.error(err);
        QF.toast('加载表关系失败', 'danger');
    }
}

// ── 弹窗 ─────────────────────────────────────────────────
function fillSchemaOptions(selId) {
    const sel = document.getElementById(selId);
    sel.innerHTML = schemaList.map(s => `<option value="${e(s.name)}">${e(s.name)}</option>`).join('');
}

async function showRelModal(id) {
    const m = new bootstrap.Modal(document.getElementById('relModal'));
    document.getElementById('relId').value = id || '';
    document.getElementById('relModalTitle').textContent = id ? '编辑表关系' : '新增表关系';
    fillSchemaOptions('relLeftSchema');
    fillSchemaOptions('relRightSchema');

    if (id) {
        const r = relationList.find(x => x.id === id);
        if (!r) return;
        document.getElementById('relLeftSchema').value = r.left_schema_name;
        document.getElementById('relRightSchema').value = r.right_schema_name;
        await onSchemaChange('left');
        document.getElementById('relLeftTable').value = r.left_table;
        await onTableChange('left');
        document.getElementById('relLeftColumn').value = r.left_column;
        document.getElementById('relRightTable').value = r.right_table;
        await onSchemaChange('right');
        await onTableChange('right');
        document.getElementById('relRightColumn').value = r.right_column;
        document.getElementById('relJoinType').value = r.join_type || 'INNER JOIN';
        document.getElementById('relCardinality').value = r.relation_type || '1:N';
        document.getElementById('relDescription').value = r.description || '';
    } else {
        document.getElementById('relJoinType').value = 'INNER JOIN';
        document.getElementById('relCardinality').value = '1:N';
        document.getElementById('relDescription').value = '';
        // 预加载默认选中库（下拉第一项）的表列表：否则库下拉虽已默认选中 pjmall，
        // 但 onchange 仅在手动切换时触发，导致默认库对应的表下拉为空（表现即“选不到表”）
        await onTableChange('left');
        await onTableChange('right');
    }
    m.show();
}

async function onSchemaChange(side) {
    // 切库后重新加载该侧的表列表与字段列表
    await onTableChange(side);
}

async function onTableChange(side) {
    const schemaSel = document.getElementById(side === 'left' ? 'relLeftSchema' : 'relRightSchema');
    const schemaName = schemaSel.value;
    const tableSel = document.getElementById(side === 'left' ? 'relLeftTable' : 'relRightTable');
    const colSel = document.getElementById(side === 'left' ? 'relLeftColumn' : 'relRightColumn');

    // 加载表列表（同库只加载一次）
    const tablesKey = `tables::${schemaName}`;
    if (!tableCache[tablesKey]) {
        try {
            const resp = await apiRequest(`/api/schema/tables?schema_name=${encodeURIComponent(schemaName)}`);
            const data = await resp.json();
            tableCache[tablesKey] = (data.tables || []).map(t => t.name);
        } catch (err) {
            tableCache[tablesKey] = [];
        }
    }
    const tables = tableCache[tablesKey] || [];
    const prevTable = tableSel.value;
    tableSel.innerHTML = '<option value="">请选择表</option>' +
        tables.map(t => `<option value="${e(t)}">${e(t)}</option>`).join('');
    if (prevTable && tables.includes(prevTable)) tableSel.value = prevTable;

    // 加载所选表的字段列表
    colSel.innerHTML = '<option value="">请先选择表</option>';
    const tableName = tableSel.value;
    if (!tableName) return;
    const colsKey = `${schemaName}::${tableName}`;
    if (!tableCache[colsKey]) {
        try {
            const resp = await apiRequest(`/api/schema/table-columns?schema_name=${encodeURIComponent(schemaName)}&table_name=${encodeURIComponent(tableName)}`);
            const data = await resp.json();
            tableCache[colsKey] = data.columns || [];
        } catch (err) {
            tableCache[colsKey] = [];
        }
    }
    const cols = tableCache[colsKey] || [];
    const prevCol = colSel.value;
    colSel.innerHTML = cols.length
        ? cols.map(c => `<option value="${e(c.name)}">${e(c.name)}${c.data_type ? ' (' + e(c.data_type) + ')' : ''}</option>`).join('')
        : '<option value="">（该表无字段记录）</option>';
    if (prevCol && cols.some(c => c.name === prevCol)) colSel.value = prevCol;
}

async function saveRelation() {
    const id = document.getElementById('relId').value;
    const leftSchema = document.getElementById('relLeftSchema').value;
    const rightSchema = document.getElementById('relRightSchema').value;
    const body = {
        left_schema_name: leftSchema,
        left_table: document.getElementById('relLeftTable').value,
        left_column: document.getElementById('relLeftColumn').value,
        right_schema_name: rightSchema,
        right_table: document.getElementById('relRightTable').value,
        right_column: document.getElementById('relRightColumn').value,
        join_type: document.getElementById('relJoinType').value,
        relation_type: document.getElementById('relCardinality').value,
        description: document.getElementById('relDescription').value.trim(),
    };
    if (!leftSchema || !rightSchema || !body.left_table || !body.left_column ||
        !body.right_table || !body.right_column) {
        QF.toast('请完整选择两侧库、表和连接字段', 'warning');
        return;
    }
    try {
        const resp = await apiRequest(id ? '/api/schema/relations/' + id : '/api/schema/relations', {
            method: id ? 'PUT' : 'POST',
            body: JSON.stringify(body),
        });
        if (resp.ok) {
            QF.toast(id ? '表关系已更新' : '表关系已创建', 'success');
            bootstrap.Modal.getInstance(document.getElementById('relModal')).hide();
            tableCache = {};   // 缓存失效重载
            await loadSchemas();
            await loadRelations();
        } else {
            const err = await resp.json().catch(() => ({}));
            QF.toast(err.detail || '保存失败', 'danger');
        }
    } catch (err) {
        QF.toast('请求失败: ' + err.message, 'danger');
    }
}

async function deleteRelation(id) {
    if (!confirm('确认删除此表关系？删除后查询将不再使用该 JOIN 条件。')) return;
    try {
        const resp = await apiRequest('/api/schema/relations/' + id, { method: 'DELETE' });
        if (resp.ok) {
            QF.toast('已删除', 'success');
            loadRelations();
        } else {
            const err = await resp.json().catch(() => ({}));
            QF.toast(err.detail || '删除失败', 'danger');
        }
    } catch (err) {
        QF.toast('请求失败: ' + err.message, 'danger');
    }
}
