/* QueryForge 页面脚本 — 自 static/template/system/sync_manage.html 拆出，公共 apiRequest/e/QF 见 app_common.js */
// 子页面在 iframe 中运行，父窗口的 window.apiRequest 不可见，须自带兜底实现

let currentTab = 'overview';
let dsList = [];
let jobList = [];

// 分页状态（同步历史 / 变更记录）
let runsPage = 1, changesPage = 1;
const RUNS_PS = 50, CHANGES_PS = 50;

// 变更记录中文映射
const CHG_STATUS_LABELS = { auto_applied: '自动应用', pending: '待审批', approved: '已通过', rejected: '已拒绝', ignored: '已忽略' };
const CHG_TYPE_LABELS = { add: '新增', modify: '修改', remove: '删除' };
const CHG_OBJ_LABELS = { table: '表', column: '字段' };

function switchTab(tab) {
    currentTab = tab;
    document.querySelectorAll('[id^="tab-"]').forEach(el => el.style.display = 'none');
    const el = document.getElementById('tab-' + tab);
    if (el) el.style.display = '';
    // 页内 tab 导航条高亮同步
    document.querySelectorAll('#pageTabs .nav-link').forEach(a => {
        a.classList.toggle('active', a.getAttribute('onclick') === `return navTab('${tab}')`);
    });
    // 保持 URL hash 同步（#tab），左侧菜单与页内导航共用
    if (location.hash !== '#' + tab) history.replaceState(null, '', '#' + tab);

    if (tab === 'overview') loadOverview();
    else if (tab === 'datasources') loadDatasources();
    else if (tab === 'jobs') loadJobs();
    else if (tab === 'runs') loadRuns();
    else if (tab === 'changes') loadChanges();
}

function navTab(tab) {
    switchTab(tab);
    return false;
}

// ── 概览 ──────────────────────────────────────────────────
async function loadOverview() {
    try {
        const resp = await apiRequest('/api/sync/stats');
        const s = await resp.json();
        document.getElementById('st-ds-total').textContent = s.datasources?.total ?? 0;
        document.getElementById('st-jobs-enabled').textContent = s.jobs?.enabled ?? 0;
        document.getElementById('st-changes-pending').textContent = s.changes?.pending ?? 0;
        document.getElementById('st-runs-failed').textContent = s.runs?.failed ?? 0;
    } catch (e) { console.error(e); }

    try {
        const resp = await apiRequest('/api/sync/runs?limit=10');
        const data = await resp.json();
        const tbody = document.getElementById('recentRuns');
        const items = data.items || [];
        if (!items.length) { tbody.innerHTML = '<tr><td colspan="8" class="empty-state">暂无同步记录</td></tr>'; return; }
        tbody.innerHTML = items.map(r => `<tr>
            <td>${fmt(r.started_at)}</td>
            <td>${r.summary ? (JSON.parse(r.summary).schema || '-') : '-'}</td>
            <td>${r.triggered_by || '-'}</td>
            <td><span class="badge badge-${r.status}">${r.status}</span></td>
            <td>${r.columns_added || 0}</td>
            <td>${r.columns_modified || 0}</td>
            <td>${r.columns_removed || 0}</td>
            <td>${r.duration_ms || 0}ms</td>
        </tr>`).join('');
    } catch (e) { console.error(e); }
}

// ── 数据源 ─────────────────────────────────────────────────
async function loadDatasources() {
    try {
        const resp = await apiRequest('/api/sync/datasources');
        const data = await resp.json();
        dsList = data.items || [];
        const tbody = document.getElementById('dsTable');
        if (!dsList.length) { tbody.innerHTML = '<tr><td colspan="8" class="empty-state">暂无数据源</td></tr>'; return; }
        tbody.innerHTML = dsList.map(ds => `<tr>
            <td>${ds.name}</td>
            <td><span class="badge bg-secondary">${ds.db_type}</span></td>
            <td>${ds.host}:${ds.port}</td>
            <td>${ds.database || '-'}</td>
            <td>${ds.username || '-'}</td>
            <td>${ds.password_masked || '****'}</td>
            <td><span class="badge badge-${ds.status}">${ds.status}</span></td>
            <td>
                <button class="btn btn-sm btn-outline-success" onclick="testDs(${ds.id})" title="测试连接"><i class="fas fa-plug"></i></button>
                <button class="btn btn-sm btn-outline-primary" onclick="showDsModal(${ds.id})" title="编辑"><i class="fas fa-edit"></i></button>
                <button class="btn btn-sm btn-outline-danger" onclick="deleteDs(${ds.id})" title="删除"><i class="fas fa-trash"></i></button>
            </td>
        </tr>`).join('');
    } catch (e) { console.error(e); }
}

function showDsModal(id) {
    const m = new bootstrap.Modal(document.getElementById('dsModal'));
    document.getElementById('dsId').value = id || '';
    if (id) {
        const ds = dsList.find(d => d.id === id);
        if (ds) {
            document.getElementById('dsName').value = ds.name;
            document.getElementById('dsDbType').value = ds.db_type;
            document.getElementById('dsHost').value = ds.host;
            document.getElementById('dsPort').value = ds.port;
            document.getElementById('dsDatabase').value = ds.database;
            document.getElementById('dsUsername').value = ds.username;
            document.getElementById('dsPassword').value = '';
        }
    } else {
        ['dsName','dsDatabase','dsUsername','dsPassword'].forEach(id => document.getElementById(id).value = '');
        document.getElementById('dsDbType').value = 'mysql';
        document.getElementById('dsHost').value = 'localhost';
        document.getElementById('dsPort').value = '3306';
    }
    m.show();
}

async function saveDs() {
    const id = document.getElementById('dsId').value;
    const name = document.getElementById('dsName').value.trim();
    const database = document.getElementById('dsDatabase').value.trim();
    if (!name) { QF.toast('数据源名称必填', 'warning'); return; }
    if (!database) { QF.toast('数据库名必填', 'warning'); return; }
    const body = {
        name,
        db_type: document.getElementById('dsDbType').value,
        host: document.getElementById('dsHost').value,
        port: parseInt(document.getElementById('dsPort').value),
        database,
        username: document.getElementById('dsUsername').value,
    };
    const pwd = document.getElementById('dsPassword').value;
    if (pwd) body.password = pwd;

    try {
        const resp = await apiRequest(id ? `/api/sync/datasources/${id}` : '/api/sync/datasources', {
            method: id ? 'PUT' : 'POST',
            body: JSON.stringify(body),
        });
        if (resp.ok) {
            bootstrap.Modal.getInstance(document.getElementById('dsModal')).hide();
            loadDatasources();
        } else {
            const err = await resp.json();
            QF.toast(err.detail || '保存失败', 'danger');
        }
    } catch (e) { QF.toast('请求失败: ' + e.message, 'danger'); }
}

async function testDs(id) {
    try {
        const resp = await apiRequest(`/api/sync/datasources/${id}/test`, { method: 'POST' });
        const data = await resp.json();
        QF.toast(data.success ? '连接成功' : '连接失败: ' + data.message, data.success ? 'success' : 'danger');
        loadDatasources();
    } catch (e) { QF.toast('请求失败: ' + e.message, 'danger'); }
}

async function deleteDs(id) {
    if (!confirm('确认删除此数据源？关联的同步任务将被禁用。')) return;
    try {
        await apiRequest(`/api/sync/datasources/${id}`, { method: 'DELETE' });
        loadDatasources();
    } catch (e) { QF.toast('删除失败: ' + e.message, 'danger'); }
}

// ── 同步任务 ─────────────────────────────────────────────────
async function loadJobs() {
    try {
        const resp = await apiRequest('/api/sync/jobs');
        const data = await resp.json();
        jobList = data.items || [];
        const tbody = document.getElementById('jobTable');
        if (!jobList.length) { tbody.innerHTML = '<tr><td colspan="8" class="empty-state">暂无同步任务</td></tr>'; return; }
        tbody.innerHTML = jobList.map(j => `<tr>
            <td>${j.datasource_name || '-'}</td>
            <td>${e(j.database || '-')}</td>
            <td>${j.schedule_type === 'interval' ? '每' + j.schedule_value + '分钟' : j.schedule_type}</td>
            <td>${j.auto_classify ? '<i class="fas fa-check text-success"></i>' : '<i class="fas fa-times text-muted"></i>'}</td>
            <td>${j.is_enabled ? '<span class="badge badge-active">启用</span>' : '<span class="badge badge-inactive">禁用</span>'}</td>
            <td>${fmt(j.last_synced_at)}</td>
            <td>${j.last_sync_status ? '<span class="badge badge-'+j.last_sync_status+'">'+j.last_sync_status+'</span>' : '-'}</td>
            <td>
                <button class="btn btn-sm ${j.is_enabled ? 'btn-outline-warning' : 'btn-outline-success'}" onclick="toggleJob(${j.id})" title="${j.is_enabled ? '停用（暂停调度）' : '启用'}" ${j.is_enabled ? '' : 'style="background:#28a745;color:#fff;"'}>
                    <i class="fas ${j.is_enabled ? 'fa-pause' : 'fa-play-circle'}"></i> ${j.is_enabled ? '停用' : '启用'}
                </button>
                <button class="btn btn-sm btn-outline-success" onclick="triggerSync(${j.id})" title="立即同步"><i class="fas fa-play"></i></button>
                <button class="btn btn-sm btn-outline-primary" onclick="showJobModal(${j.id})" title="编辑"><i class="fas fa-edit"></i></button>
                <button class="btn btn-sm btn-outline-danger" onclick="deleteJob(${j.id})" title="删除"><i class="fas fa-trash"></i></button>
            </td>
        </tr>`).join('');
    } catch (e) { console.error(e); }
}

async function showJobModal(id) {
    // 先加载数据源列表到下拉
    if (!dsList.length) {
        const resp = await apiRequest('/api/sync/datasources');
        const data = await resp.json();
        dsList = data.items || [];
    }
    const sel = document.getElementById('jobDsId');
    sel.innerHTML = dsList.map(d => `<option value="${d.id}">${d.name} (${d.db_type})</option>`).join('');

    const m = new bootstrap.Modal(document.getElementById('jobModal'));
    document.getElementById('jobId').value = id || '';
    if (id) {
        const j = jobList.find(x => x.id === id);
        if (j) {
            sel.value = j.datasource_id;
            document.getElementById('jobSchedType').value = j.schedule_type;
            document.getElementById('jobSchedValue').value = j.schedule_value;
            document.getElementById('jobAutoClassify').checked = j.auto_classify;
            document.getElementById('jobInclude').value = j.include_tables || '';
            document.getElementById('jobExclude').value = j.exclude_tables || '';
        }
    } else {
        document.getElementById('jobSchedType').value = 'interval';
        document.getElementById('jobSchedValue').value = '360';
        document.getElementById('jobAutoClassify').checked = true;
        document.getElementById('jobInclude').value = '';
        document.getElementById('jobExclude').value = '';
    }
    syncTargetPreview();
    toggleSchedInput();
    m.show();
}

// 目标库名自动取数据源「数据库名」（不再手动填 Schema 名称）
function syncTargetPreview() {
    const sel = document.getElementById('jobDsId');
    const ds = dsList.find(d => d.id === parseInt(sel.value));
    document.getElementById('jobSchema').value = (ds && ds.database) ? ds.database : '';
}

function toggleSchedInput() {
    const type = document.getElementById('jobSchedType').value;
    document.getElementById('schedValueWrap').style.display = type === 'interval' ? '' : 'none';
}

async function saveJob() {
    const id = document.getElementById('jobId').value;
    const dsId = parseInt(document.getElementById('jobDsId').value);
    const ds = dsList.find(d => d.id === dsId);
    if (!ds || !ds.database) { QF.toast('请先在数据源中填写数据库名', 'warning'); return; }
    const body = {
        datasource_id: dsId,
        schedule_type: document.getElementById('jobSchedType').value,
        schedule_value: document.getElementById('jobSchedValue').value || '0',
        auto_classify: document.getElementById('jobAutoClassify').checked,
        include_tables: document.getElementById('jobInclude').value,
        exclude_tables: document.getElementById('jobExclude').value,
    };
    try {
        const resp = await apiRequest(id ? `/api/sync/jobs/${id}` : '/api/sync/jobs', {
            method: id ? 'PUT' : 'POST',
            body: JSON.stringify(body),
        });
        if (resp.ok) {
            bootstrap.Modal.getInstance(document.getElementById('jobModal')).hide();
            loadJobs();
        } else {
            const err = await resp.json();
            QF.toast(err.detail || '保存失败', 'danger');
        }
    } catch (e) { QF.toast('请求失败: ' + e.message, 'danger'); }
}

async function triggerSync(id) {
    try {
        const before = jobList.find(item => item.id === id);
        const beforeSyncedAt = before ? before.last_synced_at : null;
        const resp = await apiRequest(`/api/sync/jobs/${id}/run`, { method: 'POST' });
        const data = await resp.json();
        QF.toast(data.message || '同步已触发', 'info');
        waitForSyncCompletion(id, beforeSyncedAt);
    } catch (e) { QF.toast('请求失败: ' + e.message, 'danger'); }
}

async function waitForSyncCompletion(id, beforeSyncedAt, attempt = 0) {
    if (attempt >= 30) return;
    setTimeout(async () => {
        try {
            const resp = await apiRequest('/api/sync/jobs');
            const data = await resp.json();
            const job = (data.items || []).find(item => item.id === id);
            loadJobs();
            if (job && job.last_sync_status && job.last_sync_status !== 'running' &&
                job.last_synced_at !== beforeSyncedAt) {
                notifySchemaRefresh();
                return;
            }
        } catch (e) { /* 下一轮继续尝试 */ }
        waitForSyncCompletion(id, beforeSyncedAt, attempt + 1);
    }, 2000);
}

function notifySchemaRefresh() {
    localStorage.setItem('qf_schema_refresh', String(Date.now()));
}

async function deleteJob(id) {
    if (!confirm('确认删除此同步任务？')) return;
    try {
        await apiRequest(`/api/sync/jobs/${id}`, { method: 'DELETE' });
        loadJobs();
    } catch (e) { QF.toast('删除失败: ' + e.message, 'danger'); }
}

// ── 启用/停用同步任务（暂停/恢复调度） ─────────────────────────
async function toggleJob(id) {
    const job = jobList.find(x => x.id === id);
    if (!job) return;
    const next = job.is_enabled ? 0 : 1;
    try {
        const resp = await apiRequest(`/api/sync/jobs/${id}`, {
            method: 'PUT',
            body: JSON.stringify({ is_enabled: next })
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) { QF.toast(data.detail || '操作失败', 'danger'); return; }
        QF.toast(next ? '同步任务已启用' : '同步任务已停用（不再自动同步）', 'info');
        loadJobs();
    } catch (e) { QF.toast('操作失败: ' + e.message, 'danger'); }
}

// ── 清空同步历史与变更记录（仅管理员） ─────────────────────────
async function clearSyncHistory() {
    if (!confirm('确认清空全部同步执行历史与变更记录？此操作不可恢复。\n\n（不影响数据源/同步任务/库表结构）')) return;
    try {
        const resp = await apiRequest('/api/sync/history/clear', { method: 'POST' });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) { QF.toast(data.detail || '清空失败', 'danger'); return; }
        QF.toast(data.message || '已清空', 'success');
        runsPage = 1; changesPage = 1;
        loadOverview();
        loadRuns();
        loadChanges();
    } catch (e) { QF.toast('清空失败: ' + e.message, 'danger'); }
}

// ── 同步历史 ─────────────────────────────────────────────────
// 执行记录的目标库名：后端已返回 schema_name；旧记录回退到 summary JSON
function runSchemaName(r) {
    if (r.schema_name) return r.schema_name;
    if (!r.summary) return '-';
    try {
        const s = JSON.parse(r.summary);
        return s.schema || '-';
    } catch (e) { return '-'; }
}

async function loadRuns() {
    try {
        const offset = (runsPage - 1) * RUNS_PS;
        const resp = await apiRequest(`/api/sync/runs?limit=${RUNS_PS}&offset=${offset}`);
        const data = await resp.json();
        const tbody = document.getElementById('runsTable');
        const items = data.items || [];
        if (!items.length) { tbody.innerHTML = '<tr><td colspan="11" class="empty-state">暂无同步记录</td></tr>'; }
        else {
            tbody.innerHTML = items.map(r => `<tr>
                <td>${fmt(r.started_at)}</td>
                <td><span class="table-badge">${e(runSchemaName(r))}</span></td>
                <td>${r.triggered_by || '-'}</td>
                <td><span class="badge badge-${r.status}">${r.status}</span></td>
                <td>${r.tables_synced || 0}/${r.tables_total || 0}</td>
                <td>${r.columns_added || 0}</td>
                <td>${r.columns_modified || 0}</td>
                <td>${r.columns_removed || 0}</td>
                <td>${r.changes_auto || 0}/${r.changes_pending || 0}</td>
                <td>${r.duration_ms || 0}ms</td>
                <td><button class="btn btn-sm btn-outline-info" onclick="showRunDetail(${r.id})"><i class="fas fa-eye"></i></button></td>
            </tr>`).join('');
        }
        QF.renderPager('runsPager', {
            total: data.total || 0, page: runsPage, pageSize: RUNS_PS,
            onPage: p => { runsPage = p; loadRuns(); }
        });
    } catch (e) { console.error(e); }
}

async function showRunDetail(runId) {
    try {
        const resp = await apiRequest(`/api/sync/runs/${runId}`);
        const r = await resp.json();
        const changes = r.changes || [];
        const detail = document.getElementById('changeDetail');
        detail.innerHTML = `
            <h6>执行信息</h6>
            <table class="table table-sm">
                <tr><td>状态</td><td><span class="badge badge-${r.status}">${r.status}</span></td>
                    <td>耗时</td><td>${r.duration_ms || 0}ms</td></tr>
                <tr><td>新增字段</td><td>${r.columns_added || 0}</td>
                    <td>修改字段</td><td>${r.columns_modified || 0}</td></tr>
                <tr><td>删除字段</td><td>${r.columns_removed || 0}</td>
                    <td>自动应用/待审批</td><td>${r.changes_auto || 0} / ${r.changes_pending || 0}</td></tr>
                ${r.error_message ? `<tr><td colspan="4" class="text-danger">错误: ${r.error_message}</td></tr>` : ''}
            </table>
            <h6 class="mt-3">变更明细（${changes.length} 条）</h6>
            <pre>${JSON.stringify(changes, null, 2)}</pre>`;
        new bootstrap.Modal(document.getElementById('changeModal')).show();
    } catch (e) { QF.toast('加载失败: ' + e.message, 'danger'); }
}

// ── 变更记录 ─────────────────────────────────────────────────
async function loadChanges() {
    const filter = document.getElementById('chgFilter')?.value || '';
    const offset = (changesPage - 1) * CHANGES_PS;
    let qs = `?limit=${CHANGES_PS}&offset=${offset}`;
    if (filter) qs += `&approval_status=${filter}`;
    try {
        const resp = await apiRequest('/api/sync/changes' + qs);
        const data = await resp.json();
        const tbody = document.getElementById('chgTable');
        const items = data.items || [];
        if (!items.length) { tbody.innerHTML = '<tr><td colspan="7" class="empty-state">暂无变更记录</td></tr>'; }
        else {
            tbody.innerHTML = items.map(c => {
                const changeIcon = c.change_type === 'add' ? '<i class="fas fa-plus text-success"></i>' :
                                   c.change_type === 'modify' ? '<i class="fas fa-edit text-warning"></i>' :
                                   '<i class="fas fa-minus text-danger"></i>';
                const levelLabel = window.QF && QF.levelLabel ? QF.levelLabel(c.auto_classified_level) : (c.auto_classified_level || '');
                return `<tr>
                    <td>${fmt(c.created_at)}</td>
                    <td>${changeIcon} ${CHG_TYPE_LABELS[c.change_type] || c.change_type}</td>
                    <td class="text-monospace">${c.object_name}</td>
                    <td>${CHG_OBJ_LABELS[c.object_type] || c.object_type}</td>
                    <td>${c.auto_classified_level ? `<span class="badge badge-${c.auto_classified_level}">${levelLabel}</span>` : '-'}</td>
                    <td><span class="badge badge-${c.approval_status}">${CHG_STATUS_LABELS[c.approval_status] || c.approval_status}</span></td>
                    <td>${c.approval_status === 'pending' ? `
                        <button class="btn btn-sm btn-outline-success" onclick="approveChange(${c.id})" title="通过"><i class="fas fa-check"></i></button>
                        <button class="btn btn-sm btn-outline-danger" onclick="rejectChange(${c.id})" title="拒绝"><i class="fas fa-times"></i></button>
                        <button class="btn btn-sm btn-outline-info" onclick="showChangeDetail(${c.id})" title="详情"><i class="fas fa-eye"></i></button>
                    ` : `<button class="btn btn-sm btn-outline-info" onclick="showChangeDetail(${c.id})" title="详情"><i class="fas fa-eye"></i></button>`}</td>
                </tr>`;
            }).join('');
        }
        QF.renderPager('changesPager', {
            total: data.total || 0, page: changesPage, pageSize: CHANGES_PS,
            onPage: p => { changesPage = p; loadChanges(); }
        });
    } catch (e) { console.error(e); }
}

function showChangeDetail(id) {
    // 从当前列表中查找
    // 由于没有全局缓存changes列表，这里简单 alert
    // 实际场景中可以调用 API 获取详情
    QF.toast('请在同步历史中查看变更详情', 'info');
}

async function approveChange(id) {
    if (!confirm('确认通过此变更？将执行删除操作。')) return;
    try {
        const resp = await apiRequest(`/api/sync/changes/${id}/approve`, { method: 'POST' });
        const data = await resp.json();
        if (resp.ok) { QF.toast(data.message, 'success'); loadChanges(); }
        else { QF.toast(data.detail || '操作失败', 'danger'); }
    } catch (e) { QF.toast('请求失败: ' + e.message, 'danger'); }
}

async function rejectChange(id) {
    if (!confirm('确认拒绝此变更？元数据将保留不变。')) return;
    try {
        const resp = await apiRequest(`/api/sync/changes/${id}/reject`, { method: 'POST' });
        const data = await resp.json();
        if (resp.ok) { QF.toast(data.message, 'success'); loadChanges(); }
        else { QF.toast(data.detail || '操作失败', 'danger'); }
    } catch (e) { QF.toast('请求失败: ' + e.message, 'danger'); }
}

// ── 工具 ──────────────────────────────────────────────────
// fmt 由 app_common.js 提供（window.fmt）

// 初始化：优先按 URL hash（#datasources/#jobs/#runs/#changes）直达子页签，默认概览
const _TABS = ['overview', 'datasources', 'jobs', 'runs', 'changes'];
(function init() {
    const h = location.hash.replace('#', '');
    switchTab(_TABS.includes(h) ? h : 'overview');
})();
