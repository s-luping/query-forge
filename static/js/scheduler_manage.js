/* QueryForge 页面脚本 — 定时任务中心（自 scheduler_manage.html 拆出）
   参考 RuoYi / XXL-JOB 任务中心：任务增删改查 + 执行一次 + 暂停/恢复 + 执行日志
   公共 apiRequest / e / QF.toast / QF.confirm / QF.renderPager 见 app_common.js */

let jobList = [];
let handlerList = [];
let currentTab = 'jobs';
let logPage = 1;
const LOG_PS = 20;

const TRIGGER_LABELS = { scheduler: '调度触发', manual: '手动执行' };
const STATUS_LABELS = { success: '成功', failed: '失败', running: '运行中' };

function navTab(tab) {
    currentTab = tab;
    document.querySelectorAll('[id^="tab-"]').forEach(el => el.style.display = 'none');
    const el = document.getElementById('tab-' + tab);
    if (el) el.style.display = '';
    document.querySelectorAll('#pageTabs .nav-link').forEach(a =>
        a.classList.toggle('active', a.getAttribute('onclick') === `return navTab('${tab}')`));
    if (tab === 'jobs') loadJobs();
    else if (tab === 'logs') loadLogs();
    return false;
}

// ── 任务管理 ─────────────────────────────────────────────────
async function loadJobs() {
    try {
        const resp = await apiRequest('/api/scheduler/jobs');
        const data = await resp.json();
        const state = document.getElementById('schedulerState');
        state.innerHTML = `<span class="status-dot ${data.running ? 'on' : 'off'}"></span>调度器${data.running ? '运行中' : '未启动'} · 时区 ${e(data.timezone)}`;
        jobList = data.items || [];
        renderJobTable();
        renderLogJobFilter();
    } catch (error) {
        QF.toast('加载任务失败：' + error.message, 'danger');
    }
}

function renderJobTable() {
    const tbody = document.getElementById('jobTable');
    if (!jobList.length) { tbody.innerHTML = '<tr><td colspan="8" class="empty-state">暂无定时任务，点击右上角「新增任务」创建</td></tr>'; return; }
    tbody.innerHTML = jobList.map(job => {
        const lastBadge = job.last_run_status
            ? `<span class="badge badge-${job.last_run_status}">${STATUS_LABELS[job.last_run_status] || job.last_run_status}</span> ${QF.fmtTime(job.last_run_at)} · ${job.last_run_duration_ms || 0}ms`
            : '<span class="text-muted">从未执行</span>';
        const handlerWarn = job.handler_registered ? '' : '<span class="badge badge-failed" title="处理器已不在注册中心，执行会失败">处理器失效</span> ';
        return `<tr>
            <td>${job.id}</td>
            <td>${e(job.name)}<br><span class="text-muted" style="font-size:12px;">${e(job.description || '')}</span></td>
            <td>${handlerWarn}${e(job.handler_label)}</td>
            <td>${e(job.schedule_desc)}</td>
            <td><span class="badge badge-${job.status}">${job.status === 'enabled' ? '运行中' : '已暂停'}</span></td>
            <td style="font-size:12px;">${lastBadge}</td>
            <td>${e(job.next_run_time || '-')}</td>
            <td>
                <button class="btn btn-sm btn-outline-primary" onclick="runJob(${job.id})" title="执行一次"><i class="fas fa-play"></i></button>
                <button class="btn btn-sm btn-outline-secondary" onclick="showJobModal(${job.id})" title="修改"><i class="fas fa-edit"></i></button>
                ${job.status === 'enabled'
                    ? `<button class="btn btn-sm btn-outline-warning" onclick="pauseJob(${job.id})" title="暂停"><i class="fas fa-pause"></i></button>`
                    : `<button class="btn btn-sm btn-outline-success" onclick="resumeJob(${job.id})" title="恢复"><i class="fas fa-rotate-right"></i></button>`}
                <button class="btn btn-sm btn-outline-info" onclick="viewJobLogs(${job.id})" title="执行日志"><i class="fas fa-list"></i></button>
                ${job.is_system
                    ? `<button class="btn btn-sm btn-outline-danger" disabled title="系统内置任务不可删除"><i class="fas fa-trash"></i></button>`
                    : `<button class="btn btn-sm btn-outline-danger" onclick="deleteJob(${job.id})" title="删除"><i class="fas fa-trash"></i></button>`}
            </td>
        </tr>`;
    }).join('');
}

// ── 任务 新增/编辑 ───────────────────────────────────────────
async function loadHandlers() {
    if (handlerList.length) return;
    try {
        const resp = await apiRequest('/api/scheduler/handlers');
        handlerList = (await resp.json()).items || [];
        document.getElementById('jobHandler').innerHTML =
            handlerList.map(h => `<option value="${e(h.key)}">${e(h.label)}（${e(h.key)}）</option>`).join('');
    } catch (error) {
        QF.toast('加载处理器列表失败：' + error.message, 'danger');
    }
}

function currentHandler() {
    const key = document.getElementById('jobHandler').value;
    return handlerList.find(h => h.key === key);
}

function onHandlerChange() {
    const h = currentHandler();
    document.getElementById('handlerDesc').textContent = h ? h.description : '';
    const schema = h ? h.params : [];
    document.getElementById('paramHint').innerHTML = schema.length
        ? '支持参数：' + schema.map(p => `<code>${e(p.key)}</code>（${e(p.type)}${p.required ? '，必填' : ''}，默认 ${e(JSON.stringify(p.default))}）— ${e(p.desc)}`).join('；')
        : '该处理器无需参数，保持 {} 即可';
    // 编辑时切换处理器：若当前参数与选择器不兼容则重置为空对象
    let params = {};
    try { params = JSON.parse(document.getElementById('jobParams').value || '{}'); } catch (err) { /* 忽略 */ }
    const supported = schema.map(p => p.key);
    const cleaned = {};
    schema.forEach(p => { if (params[p.key] !== undefined) cleaned[p.key] = params[p.key]; });
    if (JSON.stringify(cleaned) !== JSON.stringify(params) || Object.keys(params).some(k => !supported.includes(k))) {
        document.getElementById('jobParams').value = JSON.stringify(cleaned);
    }
}

function onScheduleTypeChange() {
    const isCron = document.getElementById('typeCron').checked;
    document.getElementById('cronGroup').style.display = isCron ? '' : 'none';
    document.getElementById('intervalGroup').style.display = isCron ? 'none' : '';
}

function setCron(expr) { document.getElementById('jobCron').value = expr; previewCron(); }

async function previewCron() {
    const expr = document.getElementById('jobCron').value.trim();
    const out = document.getElementById('cronPreview');
    if (!expr) { out.innerHTML = '<span class="text-danger">请输入 cron 表达式</span>'; return; }
    try {
        const resp = await apiRequest('/api/scheduler/cron-preview', {
            method: 'POST', body: JSON.stringify({ cron_expr: expr })
        });
        const data = await resp.json();
        if (!resp.ok) { out.innerHTML = `<span class="text-danger">${e(data.detail || '表达式不合法')}</span>`; return; }
        out.innerHTML = '<span class="text-success">下次执行：</span>' + (data.next_run_times || []).map(t => e(t)).join(' → ');
    } catch (error) {
        out.innerHTML = '<span class="text-danger">预览失败：' + e(error.message) + '</span>';
    }
}

async function showJobModal(id) {
    await loadHandlers();
    const modalEl = document.getElementById('jobModal');
    const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
    document.getElementById('jobModalTitle').textContent = id ? '修改任务' : '新增任务';
    document.getElementById('cronPreview').innerHTML = '';
    if (id) {
        const job = jobList.find(j => j.id === id);
        if (!job) return;
        document.getElementById('jobId').value = job.id;
        document.getElementById('jobName').value = job.name;
        document.getElementById('jobHandler').value = job.handler;
        document.getElementById('typeCron').checked = job.schedule_type === 'cron';
        document.getElementById('typeInterval').checked = job.schedule_type === 'interval';
        document.getElementById('jobCron').value = job.cron_expr || '';
        document.getElementById('jobInterval').value = job.interval_seconds || 600;
        document.getElementById('jobParams').value = JSON.stringify(job.params || {});
        document.getElementById('jobMisfire').value = job.misfire_grace_time || 60;
        document.getElementById('jobMaxInstances').value = job.max_instances || 1;
        document.getElementById('jobDesc').value = job.description || '';
    } else {
        document.getElementById('jobId').value = '';
        document.getElementById('jobName').value = '';
        document.getElementById('typeCron').checked = true;
        document.getElementById('typeInterval').checked = false;
        document.getElementById('jobCron').value = '';
        document.getElementById('jobInterval').value = 600;
        document.getElementById('jobParams').value = '{}';
        document.getElementById('jobMisfire').value = 60;
        document.getElementById('jobMaxInstances').value = 1;
        document.getElementById('jobDesc').value = '';
    }
    onHandlerChange();
    onScheduleTypeChange();
    modal.show();
}

async function saveJob() {
    const id = document.getElementById('jobId').value;
    let params = {};
    const paramsRaw = document.getElementById('jobParams').value.trim() || '{}';
    try { params = JSON.parse(paramsRaw); } catch (err) { QF.toast('任务参数不是合法 JSON', 'danger'); return; }
    const body = {
        name: document.getElementById('jobName').value.trim(),
        handler: document.getElementById('jobHandler').value,
        schedule_type: document.getElementById('typeCron').checked ? 'cron' : 'interval',
        cron_expr: document.getElementById('jobCron').value.trim(),
        interval_seconds: parseInt(document.getElementById('jobInterval').value, 10) || 0,
        params: params,
        description: document.getElementById('jobDesc').value.trim(),
        misfire_grace_time: parseInt(document.getElementById('jobMisfire').value, 10) || 0,
        max_instances: parseInt(document.getElementById('jobMaxInstances').value, 10) || 1,
    };
    if (!body.name) { QF.toast('请输入任务名称', 'warning'); return; }
    if (body.schedule_type === 'cron' && !body.cron_expr) { QF.toast('请输入 cron 表达式', 'warning'); return; }
    try {
        const resp = await apiRequest(id ? `/api/scheduler/jobs/${id}` : '/api/scheduler/jobs', {
            method: id ? 'PUT' : 'POST',
            body: JSON.stringify(body),
        });
        const data = await resp.json();
        if (!resp.ok) { QF.toast(data.detail || '保存失败', 'danger'); return; }
        bootstrap.Modal.getInstance(document.getElementById('jobModal')).hide();
        QF.toast(data.message || '保存成功', 'success');
        loadJobs();
    } catch (error) {
        QF.toast('保存失败：' + error.message, 'danger');
    }
}

// ── 任务操作 ─────────────────────────────────────────────────
async function jobAction(id, action, confirmMsg) {
    if (confirmMsg && !await QF.confirm(confirmMsg)) return;
    try {
        const resp = await apiRequest(`/api/scheduler/jobs/${id}/${action}`, { method: 'POST' });
        const data = await resp.json();
        if (!resp.ok) { QF.toast(data.detail || '操作失败', 'danger'); return; }
        QF.toast(data.message || '操作成功', 'success');
        loadJobs();
    } catch (error) {
        QF.toast('操作失败：' + error.message, 'danger');
    }
}

function runJob(id) { jobAction(id, 'run'); }
function pauseJob(id) { jobAction(id, 'pause', '确定暂停该任务？暂停后不再自动执行。'); }
function resumeJob(id) { jobAction(id, 'resume'); }

async function deleteJob(id) {
    const job = jobList.find(j => j.id === id);
    if (!await QF.confirm(`确定删除任务「${job ? job.name : id}」？执行日志会保留。`)) return;
    try {
        const resp = await apiRequest(`/api/scheduler/jobs/${id}`, { method: 'DELETE' });
        const data = await resp.json();
        if (!resp.ok) { QF.toast(data.detail || '删除失败', 'danger'); return; }
        QF.toast(data.message || '已删除', 'success');
        loadJobs();
    } catch (error) {
        QF.toast('删除失败：' + error.message, 'danger');
    }
}

// ── 执行日志 ─────────────────────────────────────────────────
function renderLogJobFilter() {
    const sel = document.getElementById('logJobFilter');
    const current = sel.value;
    sel.innerHTML = '<option value="">全部任务</option>' +
        jobList.map(j => `<option value="${j.id}">${e(j.name)}</option>`).join('');
    if (current && jobList.some(j => String(j.id) === current)) sel.value = current;
}

function resetLogPage() { logPage = 1; loadLogs(); }

let _lastLogItems = [];
async function loadLogs() {
    const jobId = document.getElementById('logJobFilter').value;
    const status = document.getElementById('logStatusFilter').value;
    const tbody = document.getElementById('logTable');
    try {
        const qs = new URLSearchParams({ page: logPage, page_size: LOG_PS });
        if (jobId) qs.set('job_id', jobId);
        if (status) qs.set('status', status);
        const resp = await apiRequest(`/api/scheduler/logs?${qs}`);
        const data = await resp.json();
        const items = data.items || [];
        _lastLogItems = items;
        if (!items.length) { tbody.innerHTML = `<tr><td colspan="7" class="empty-state">暂无执行日志</td></tr>`; }
        else {
            tbody.innerHTML = items.map(r => {
                const brief = r.status === 'failed'
                    ? `<span class="text-danger">${e((r.error_message || '').split('\n')[0].slice(0, 80))}</span>`
                    : `<span class="text-muted" style="font-size:12px;">${e((r.result_summary || '').slice(0, 60)) || '-'}</span>`;
                return `<tr>
                    <td>${e(r.job_name)}</td>
                    <td><span class="badge badge-${r.trigger}">${TRIGGER_LABELS[r.trigger] || r.trigger}</span></td>
                    <td><span class="badge badge-${r.status}">${STATUS_LABELS[r.status] || r.status}</span></td>
                    <td>${e(r.started_at || '-')}</td>
                    <td>${r.duration_ms || 0}ms</td>
                    <td>${brief}</td>
                    <td><button class="btn btn-sm btn-outline-secondary" onclick="showLogDetail(${r.id})">详情</button></td>
                </tr>`;
            }).join('');
        }
        QF.renderPager('logPager', { total: data.total || 0, page: logPage, pageSize: LOG_PS, onPage: p => { logPage = p; loadLogs(); } });
    } catch (error) {
        tbody.innerHTML = `<tr><td colspan="7" class="empty-state">加载失败：${e(error.message)}</td></tr>`;
    }
}

function showLogDetail(id) {
    const row = _lastLogItems.find(r => r.id === id);
    if (!row) { QF.toast('日志记录不存在', 'warning'); return; }
    document.getElementById('logDetail').innerHTML = `
        <table class="table table-sm table-bordered">
            <tr><th style="width:120px;">任务</th><td>${e(row.job_name)}（ID: ${row.job_id}）</td></tr>
            <tr><th>处理器</th><td>${e(row.handler)}</td></tr>
            <tr><th>触发方式</th><td>${TRIGGER_LABELS[row.trigger] || e(row.trigger)}</td></tr>
            <tr><th>状态</th><td><span class="badge badge-${row.status}">${STATUS_LABELS[row.status] || e(row.status)}</span></td></tr>
            <tr><th>开始 / 结束</th><td>${e(row.started_at || '-')} → ${e(row.finished_at || '-')}（${row.duration_ms || 0}ms）</td></tr>
            <tr><th>参数</th><td><pre class="mb-0">${e(row.params || '{}')}</pre></td></tr>
            <tr><th>结果摘要</th><td><pre class="mb-0">${e(row.result_summary || '-')}</pre></td></tr>
            <tr><th>错误信息</th><td><pre class="mb-0">${e(row.error_message || '-')}</pre></td></tr>
        </table>`;
    bootstrap.Modal.getOrCreateInstance(document.getElementById('logModal')).show();
}

async function viewJobLogs(jobId) {
    document.getElementById('logJobFilter').value = String(jobId);
    document.getElementById('logStatusFilter').value = '';
    logPage = 1;
    navTab('logs');
}

async function clearLogs() {
    const jobId = document.getElementById('logJobFilter').value;
    if (!await QF.confirm(jobId ? '确定清空该任务的所有执行日志？' : '确定清空全部执行日志？此操作不可恢复。')) return;
    try {
        const resp = await apiRequest(`/api/scheduler/logs${jobId ? `?job_id=${jobId}` : ''}`, { method: 'DELETE' });
        const data = await resp.json();
        if (!resp.ok) { QF.toast(data.detail || '清空失败', 'danger'); return; }
        QF.toast(data.message || '已清空', 'success');
        resetLogPage();
    } catch (error) {
        QF.toast('清空失败：' + error.message, 'danger');
    }
}

loadJobs();
setInterval(() => { if (currentTab === 'jobs') loadJobs(); }, 15000);
