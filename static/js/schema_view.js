/* schema_view.html — 数据浏览页交互逻辑 */
let currentPage = 1, pageSize = 20, totalItems = 0, totalPages = 1, searchTimeout = null;

async function loadSchemaList() {
    const schema = document.getElementById('filterSchema').value;
    const table = document.getElementById('filterTable').value;
    const search = document.getElementById('searchInput').value.trim();
    const offset = (currentPage - 1) * pageSize;
    let url = `/api/schema/list?limit=${pageSize}&offset=${offset}`;
    if (schema) url += `&schema_name=${encodeURIComponent(schema)}`;
    if (table) url += `&table_name=${encodeURIComponent(table)}`;
    if (search) url += `&search=${encodeURIComponent(search)}`;

    try {
        const resp = await apiRequest(url);
        if (!resp || !resp.ok) return;
        const data = await resp.json();
        totalItems = data.total || 0;
        totalPages = Math.ceil(totalItems / pageSize) || 1;

        const tbody = document.getElementById('schemaTableBody');
        if (data.items && data.items.length > 0) {
            const isAdmin = window.QF && QF.isAdmin();
            if (isAdmin) document.getElementById('thOps').style.display = '';
            tbody.innerHTML = data.items.map(item => `
                <tr>
                    <td><span class="schema-badge">${e(item.schema_name)}</span></td>
                    <td><span class="table-badge">${e(item.table_name)}</span></td>
                    <td class="table-cell-ellipsis">${e(item.column_name)}</td>
                    <td class="table-cell-ellipsis">${e(item.column_type || '')}</td>
                    <td class="table-cell-ellipsis">${e(item.column_description || '')}</td>
                    <td class="table-cell-ellipsis">${e(item.table_description || '')}</td>
                    <td>${item.column_key ? '<span class="pk-badge">PK</span>' : ''}</td>
                    <td class="table-cell-ellipsis">${e(item.foreign_key || '')}</td>
                    <td class="text-center">
                        ${isAdmin
                            ? `<input type="checkbox" id="dim_${item.id}" ${item.is_dimension ? 'checked' : ''} onchange="saveColumnMeta(${item.id})" title="标记为维度字段">`
                            : (item.is_dimension ? '✓' : '–')}
                    </td>
                    <td class="text-center">
                        ${isAdmin
                            ? `<input type="checkbox" id="meas_${item.id}" ${item.is_measure ? 'checked' : ''} onchange="saveColumnMeta(${item.id})" title="标记为度量字段">`
                            : (item.is_measure ? '✓' : '–')}
                    </td>
                    <td>${new Date(item.created_at).toLocaleString()}</td>
                    ${isAdmin ? `<td><button class="btn btn-outline-danger btn-sm py-0 px-2" title="删除字段 ${e(item.column_name)}" onclick="deleteColumn(${item.id}, '${e(item.schema_name).replace(/'/g, "\\'")}', '${e(item.table_name).replace(/'/g, "\\'")}', '${e(item.column_name).replace(/'/g, "\\'")}')"><i class="fas fa-trash-alt"></i></button></td>` : ''}
                </tr>
            `).join('');

            document.getElementById('paginationContainer').style.display = 'flex';
            document.getElementById('paginationInfo').textContent = `第 ${currentPage} 页，共 ${totalPages} 页，总计 ${totalItems} 条`;
            document.getElementById('prevPageBtn').disabled = currentPage === 1;
            document.getElementById('nextPageBtn').disabled = currentPage >= totalPages;
        } else {
            tbody.innerHTML = '<tr><td colspan="12" class="text-center py-4 text-muted">暂无数据</td></tr>';
            document.getElementById('paginationContainer').style.display = 'none';
        }
    } catch (e) {
        console.error('加载 数据库 列表失败:', e);
    }
}

let _schemaGroups = [];   // /api/schema/schemas 返回的 数据源→库 分组

async function loadSchemaNames() {
    try {
        const resp = await apiRequest('/api/schema/schemas');
        if (resp && resp.ok) {
            const data = await resp.json();
            _schemaGroups = data.datasources || [];
            // 数据源筛选下拉
            const dsSel = document.getElementById('filterDatasource');
            dsSel.innerHTML = '<option value="">全部数据源</option>';
            _schemaGroups.forEach(g => {
                const o = document.createElement('option');
                o.value = g.datasource_id;
                o.textContent = g.datasource_name || '未关联数据源';
                dsSel.appendChild(o);
            });
            buildSchemaOptions();
        }
    } catch(e) {}
}

// 按选中的数据源重建"数据库"下拉（未选数据源 = 全部，按数据源分组显示）
function buildSchemaOptions() {
    const dsId = document.getElementById('filterDatasource').value;
    const sel = document.getElementById('filterSchema');
    sel.innerHTML = '<option value="">全部</option>';
    _schemaGroups
        .filter(g => dsId === '' || String(g.datasource_id) === String(dsId))
        .forEach(g => {
            const schemas = (g.schemas || []).filter(Boolean);
            if (!schemas.length) return;
            const og = document.createElement('optgroup');
            og.label = g.datasource_name || '未关联数据源';
            schemas.forEach(s => {
                const o = document.createElement('option');
                o.value = s;
                o.textContent = s;
                og.appendChild(o);
            });
            sel.appendChild(og);
        });
}

function onDatasourceChange() {
    buildSchemaOptions();
    document.getElementById('filterSchema').value = '';
    const tableSelect = document.getElementById('filterTable');
    tableSelect.disabled = true;
    tableSelect.innerHTML = '<option value="">请先选择数据库</option>';
    currentPage = 1;
    loadSchemaList();
}

async function loadTableOptions(schemaName) {
    try {
        const resp = await apiRequest(`/api/schema/tables?schema_name=${encodeURIComponent(schemaName)}`);
        if (resp && resp.ok) {
            const data = await resp.json();
            const tableSelect = document.getElementById('filterTable');
            tableSelect.innerHTML = '<option value="">全部</option>';
            data.tables.forEach(t => {
                tableSelect.innerHTML += `<option value="${t.name}">${t.name}${t.description ? ' - ' + t.description : ''}</option>`;
            });
        }
    } catch (e) {
        console.error('加载表名列表失败:', e);
    }
}

function onSchemaChange() {
    const schema = document.getElementById('filterSchema').value;
    const tableSelect = document.getElementById('filterTable');

    if (schema) {
        tableSelect.disabled = false;
        loadTableOptions(schema);
    } else {
        tableSelect.disabled = true;
        tableSelect.innerHTML = '<option value="">请先选择数据库</option>';
    }

    currentPage = 1;
    loadSchemaList();
}

function onTableChange() {
    currentPage = 1;
    loadSchemaList();
}

function prevPage() { if (currentPage > 1) { currentPage--; loadSchemaList(); } }
function nextPage() { if (currentPage < totalPages) { currentPage++; loadSchemaList(); } }

function onSearchInput() {
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(() => { currentPage = 1; loadSchemaList(); }, 300);
}

// ═══════════════════════════════════════════════════════════
// 删除库 / 表 / 字段（仅管理员；后端 AdminUser 兜底）
// ═══════════════════════════════════════════════════════════
async function deleteSelectedSchema() {
    const schema = document.getElementById('filterSchema').value;
    if (!schema) { QF.toast('请先在「数据库」筛选中选择要删除的库', 'warning'); return; }
    // 该库若由数据源同步维护，提示可能被重新同步（避免"删了又回来"）
    const dsGroup = _schemaGroups.find(g => (g.schemas || []).includes(schema));
    let msg = `确定删除库「${schema}」？将同时删除其所有表和字段，且不可恢复。`;
    if (dsGroup && dsGroup.datasource_id !== null && dsGroup.datasource_id !== undefined) {
        msg += `\n\n⚠ 该库由数据源「${dsGroup.datasource_name || '未知'}」同步维护：` +
               `若对应同步任务仍启用，删除后可能被自动重新同步。` +
               `建议先在「数据源管理/同步任务」中停用或删除该任务。`;
    }
    if (!confirm(msg)) return;
    try {
        const resp = await apiRequest(`/api/schema/schema/${encodeURIComponent(schema)}`, { method: 'DELETE' });
        const data = await resp.json().catch(() => ({}));
        if (resp.ok) {
            QF.toast(data.message || '删除成功', 'success');
            loadSchemaNames();
            loadSchemaList();
        } else {
            QF.toast(data.detail || '删除失败', 'danger');
        }
    } catch (err) { QF.toast('删除失败：' + err.message, 'danger'); }
}

async function deleteSelectedTable() {
    const schema = document.getElementById('filterSchema').value;
    const table = document.getElementById('filterTable').value;
    if (!schema || !table) { QF.toast('请先在筛选中选择库和表', 'warning'); return; }
    if (!confirm(`确定删除表「${schema}.${table}」？将同时删除其所有字段，且不可恢复。`)) return;
    try {
        const resp = await apiRequest(`/api/schema/table?schema_name=${encodeURIComponent(schema)}&table_name=${encodeURIComponent(table)}`, { method: 'DELETE' });
        const data = await resp.json().catch(() => ({}));
        if (resp.ok) {
            QF.toast(data.message || '删除成功', 'success');
            document.getElementById('filterTable').value = '';
            loadSchemaList();
        } else {
            QF.toast(data.detail || '删除失败', 'danger');
        }
    } catch (err) { QF.toast('删除失败：' + err.message, 'danger'); }
}

async function deleteColumn(id, schemaName, tableName, columnName) {
    if (!confirm(`确定删除字段「${schemaName}.${tableName}.${columnName}」？`)) return;
    try {
        const resp = await apiRequest(`/api/schema/${id}`, { method: 'DELETE' });
        const data = await resp.json().catch(() => ({}));
        if (resp.ok) {
            QF.toast('字段已删除', 'success');
            loadSchemaList();
        } else {
            QF.toast(data.detail || '删除失败', 'danger');
        }
    } catch (err) { QF.toast('删除失败：' + err.message, 'danger'); }
}

// 维度/度量标记即时保存（仅管理员；后端 AdminUser 兜底）
async function saveColumnMeta(id) {
    const dimEl = document.getElementById('dim_' + id);
    const measEl = document.getElementById('meas_' + id);
    if (!dimEl || !measEl) return;
    const body = JSON.stringify({ is_dimension: dimEl.checked, is_measure: measEl.checked });
    try {
        const resp = await apiRequest(`/api/schema/column/${id}`, { method: 'PUT', body });
        if (!resp.ok) throw new Error((await resp.json()).detail || '保存失败');
        QF.toast('维度/度量已保存', 'success');
    } catch (err) {
        QF.toast('保存失败：' + err.message, 'danger');
        loadSchemaList(); // 失败回滚为服务端真实值
    }
}

// ═══════════════════════════════════════════════════════════
// CSV 模板下载 / 上传（仅 CSV；前端校验 + 后端管理员/格式/大小/数据源校验）
// ═══════════════════════════════════════════════════════════
function downloadCsvTemplate() {
    // 表头为中文（解析器支持中文别名），文件名中文
    const header = ['库名', '表名', '字段名', '字段类型', '字段描述',
                    '表描述', '可空', '默认值', '键类型', '外键', '示例值'];
    const sample = ['shop', 'users', 'id', 'INT', '用户ID', '用户表', '1', '', 'PRI', '', ''];
    const csv = '\uFEFF' + [header.join(','), sample.join(',')].join('\r\n') + '\r\n';   // BOM 兼容 Excel
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = '数据库结构导入模板.csv';
    document.body.appendChild(a);
    a.click();
    URL.revokeObjectURL(a.href);
    a.remove();
}

let _csvModal = null;
let _csvDatasources = [];

async function loadCsvDatasources() {
    const sel = document.getElementById('csvDatasource');
    try {
        const resp = await apiRequest('/api/sync/datasources');
        const data = await resp.json();
        _csvDatasources = data.items || [];
        sel.innerHTML = '<option value="">请选择数据源</option>' +
            _csvDatasources.map(d => `<option value="${d.id}">${e(d.name)}（${e(d.db_type || '-')}）</option>`).join('');
    } catch (err) {
        sel.innerHTML = '<option value="">数据源加载失败</option>';
        console.error(err);
    }
}

function onCsvDatasourceChange() {
    const id = document.getElementById('csvDatasource').value;
    const ds = _csvDatasources.find(d => String(d.id) === String(id));
    if (ds && ds.db_type) {
        const dt = document.getElementById('csvDbType');
        if (Array.from(dt.options).some(o => o.value === ds.db_type)) {
            dt.value = ds.db_type;
        }
    }
}

function openCsvUpload() {
    if (!_csvModal) _csvModal = new bootstrap.Modal(document.getElementById('csvUploadModal'));
    document.getElementById('csvUploadMsg').style.display = 'none';
    loadCsvDatasources();
    _csvModal.show();
}

function showCsvMsg(text, type) {
    const msg = document.getElementById('csvUploadMsg');
    msg.className = 'mt-2 alert alert-' + (type || 'info') + ' py-2';
    msg.style.fontSize = '12px';
    msg.style.marginBottom = '0';
    msg.textContent = text;
    msg.style.display = 'block';
}

async function uploadCsvFile() {
    const fileInput = document.getElementById('csvFile');
    const file = fileInput.files[0];
    const btn = document.getElementById('csvUploadBtn');
    const dsId = document.getElementById('csvDatasource').value;
    if (!dsId) { showCsvMsg('请选择数据源', 'danger'); return; }
    if (!file) { showCsvMsg('请选择 CSV 文件', 'danger'); return; }
    const name = (file.name || '').toLowerCase();
    if (!name.endsWith('.csv')) { showCsvMsg('仅支持 .csv 格式文件', 'danger'); fileInput.value = ''; return; }
    if (file.size > 5 * 1024 * 1024) { showCsvMsg('文件过大，仅支持 5MB 以内', 'danger'); return; }

    const fd = new FormData();
    fd.append('schema_name', document.getElementById('csvSchemaName').value.trim() || 'default');
    fd.append('db_type', document.getElementById('csvDbType').value);
    fd.append('datasource_id', dsId);
    fd.append('file', file);

    btn.disabled = true;
    btn.textContent = '导入中...';
    showCsvMsg('正在解析导入...', 'info');
    try {
        const resp = await apiRequest('/api/schema/upload', { method: 'POST', body: fd });
        const data = await resp.json().catch(() => ({}));
        if (resp.ok) {
            showCsvMsg(`导入成功：${data.total || 0} 个字段${data.message ? '，' + data.message : ''}`, 'success');
            fileInput.value = '';
            loadSchemaList();
            loadSchemaNames();
            setTimeout(() => { if (_csvModal) _csvModal.hide(); }, 1500);
        } else {
            showCsvMsg(data.detail || '导入失败', 'danger');
        }
    } catch (err) {
        showCsvMsg('导入失败：' + err.message, 'danger');
    } finally {
        btn.disabled = false;
        btn.textContent = '上传导入';
    }
}

document.addEventListener('DOMContentLoaded', () => {
    loadSchemaNames();
    loadSchemaList();
    document.getElementById('searchInput').addEventListener('input', onSearchInput);
    window.addEventListener('storage', event => {
        if (event.key === 'qf_schema_refresh') {
            currentPage = 1;
            loadSchemaNames();
            loadSchemaList();
        }
    });
    // 同步任务在其他 iframe 完成时刷新当前页面；定时刷新作为兜底。
    setInterval(() => {
        loadSchemaNames();
        loadSchemaList();
    }, 30000);
});
