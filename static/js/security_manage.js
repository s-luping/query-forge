/* security_manage.html — 安全中心页交互逻辑 */
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function get(url, options) { const response = await apiRequest(url, options); return response.json(); }
async function loadStats() {
    const data = await get('/api/audit/stats');
    document.getElementById('stats').innerHTML = [['total_queries','总查询数','stat-total'],['blocked_queries','被拦截','stat-blocked'],['sensitive_hits','敏感命中','stat-sensitive'],['block_rate','拦截率','stat-rate']].map(([key, label, cls]) => `<div class="col-md-3"><div class="stat-card ${cls}"><div class="stat-value">${esc(data[key])}</div><div class="stat-label">${label}</div></div></div>`).join('');
    const logs = await get('/api/audit/logs?blocked_only=true&limit=10');
    document.getElementById('recent').innerHTML = logs.items.map(item => `<tr><td>${esc(item.created_at)}</td><td>${esc(item.username)}</td><td>${esc(item.query)}</td><td>${esc(item.block_reason)}</td></tr>`).join('') || '<tr><td colspan="4" class="text-center text-muted">暂无记录</td></tr>';
}
const LOGS_PS = 20;
let logsCur = 1, logsTotal = 0, logFilterTimer = null;
function logFilterDebounce() { clearTimeout(logFilterTimer); logFilterTimer = setTimeout(() => { logsCur = 1; loadLogs(); }, 400); }
async function loadLogs() {
    const offset = (logsCur - 1) * LOGS_PS;
    const params = new URLSearchParams({ limit: LOGS_PS, offset });
    const status = document.getElementById('logStatusFilter')?.value || '';
    const username = document.getElementById('logUserFilter')?.value.trim() || '';
    const search = document.getElementById('logSearch')?.value.trim() || '';
    if (status) params.set('status', status);
    if (username) params.set('username', username);
    if (search) params.set('search', search);
    const data = await get('/api/audit/logs?' + params.toString());
    logsTotal = data.total || 0;
    const maxPage = Math.max(1, Math.ceil(logsTotal / LOGS_PS));
    if (logsCur > maxPage) { logsCur = maxPage; return loadLogs(); }
    _logsCache = data.items;
    document.getElementById('logs').innerHTML = data.items.map(item => `<tr><td>${esc(item.created_at)}</td><td>${esc(item.username)}</td><td class="query-cell" title="${esc(item.query)}">${esc(item.query)}</td><td class="sql-cell" title="${esc(item.generated_sql)}">${esc(item.generated_sql)}</td><td>${item.was_blocked ? '已拦截' : '通过'}</td><td>${item.pipeline_log ? `<button class="btn btn-sm btn-outline-primary" onclick="showPipeline(${item.id})">查看</button>` : '<span class="text-muted">-</span>'}</td></tr>`).join('') || '<tr><td colspan="6" class="text-center text-muted">暂无记录</td></tr>';
    document.getElementById('logsCount').textContent = `共 ${logsTotal} 条`;
    document.getElementById('logsPageInfo').textContent = `${logsCur} / ${maxPage}`;
    document.getElementById('logsPrev').disabled = logsCur <= 1;
    document.getElementById('logsNext').disabled = logsCur >= maxPage;
}
function logsPage(delta) {
    const next = logsCur + delta;
    if (next < 1) return;
    logsCur = next;
    loadLogs();
}
// 链路追踪查看：从日志列表定位并解析 pipeline_log JSON
let _logsCache = [];
async function showPipeline(logId) {
    let item = _logsCache.find(x => x.id === logId);
    if (!item) {
        const data = await get('/api/audit/logs?limit=200');
        _logsCache = data.items;
        item = _logsCache.find(x => x.id === logId);
    }
    if (!item || !item.pipeline_log) { QF.toast('该记录无链路数据', 'info'); return; }
    let steps = [];
    try { steps = JSON.parse(item.pipeline_log); } catch (e) { steps = []; }
    const STEP_CN = {
        // 流程框架（无序号）
        'PIPELINE_START': '流程开始', 'PIPELINE_END': '流程结束',
        'VECTOR_LOAD': '向量索引加载', 'VECTOR_CHECK': '向量检查',
        // 前置步骤（路由层）
        'AUTH_SCHEMA_CHECK': '1. 数据库鉴权', 'LLM_CONFIG_LOAD': '2. 模型选择',
        'KNOWLEDGE_LOAD': '3. 知识库加载',
        // 召回与聚合
        'STEP1_KEYWORDS': '4. 关键词提取',
        'STEP2_VECTOR_RECALL': '5. 字段召回（向量）', 'STEP2_DB_RECALL': '5. 字段召回（数据库）',
        'STEP2_RECALL': '5. 字段召回',
        'STEP3_AGGREGATE': '6. 表聚合', 'STEP_CUMULATIVE_AGGREGATE': '6. 累积表聚合',
        'STEP_PERMISSION': '7. 权限裁剪统计（库/表/字段级）',
        'STEP_PERMISSION_ERROR': '7. 权限裁剪统计（异常）',
        // 知识与上下文
        'STEP_RECALL_KNOWLEDGE': '8. 知识召回', 'STEP_EXTEND_TABLES': '9. 知识扩表',
        'STEP4_CONTEXT': '10. 上下文构建',
        // 判断与生成
        'STEP_JUDGE_PROMPT': '11. 可否生成判断', 'STEP_JUDGE_RESULT': '11. 可否生成判断',
        'STEP_JUDGE_ERROR': '11. 可否生成判断（异常）',
        'STEP5_PROMPT': '12. 提示词构建', 'STEP5_RESULT': '13. LLM 生成',
        // 校验与网关
        'STEP6_VALIDATE': '14. SQL 校验', 'STEP7_GATEWAY': '15. 权限网关',
        'STEP7_GATEWAY_ERROR': '15. 权限网关（异常）',
        // 后置步骤（路由层）
        'PREFIX_REPAIR': '库前缀修复（全库模式）', 'SQL_EXECUTE': '16. SQL 执行',
        'MESSAGE_PERSIST': '17. 消息持久化',
        'STEP_RESPONSE': '响应返回',
    };
    // StepTrace 统一结构（docs/ChatSQL模块化与全链路留痕设计.md §5.2）：
    // ok=通过 error=失败(红) intercept=拦截(黄) skip=跳过(灰)；旧格式无 status 按"通过"兼容渲染
    const STATUS_META = {
        ok:        { label: '通过', cls: 'success' },
        error:     { label: '失败', cls: 'danger' },
        intercept: { label: '拦截', cls: 'warning' },
        skip:      { label: '跳过', cls: 'secondary' },
    };
    document.getElementById('pipelineDetail').innerHTML = steps.length ? steps.map((s, i) => {
        const meta = STATUS_META[s.status];
        const detail = s.detail !== undefined ? s.detail : s.data;   // 新结构 detail / 旧格式 data
        const ts = s.started_at || s.timestamp || '';
        const statusBadge = meta ? `<span class="badge bg-${meta.cls} ms-1">${meta.label}</span>` : '';
        const durBadge = (s.duration_ms != null)
            ? `<span class="badge bg-light text-dark ms-1">${s.duration_ms}ms</span>` : '';
        const sumHtml = s.summary
            ? `<div class="text-muted mb-1" style="font-size:12px;"><strong>${esc(s.summary)}</strong></div>` : '';
        const errHtml = s.error
            ? `<div class="alert ${s.status === 'error' ? 'alert-danger' : 'alert-warning'} py-1 px-2 my-1" style="font-size:12px;">${esc(s.error)}</div>` : '';
        return `
        <div class="card mb-2${meta && meta.cls === 'danger' ? ' border-danger' : ''}">
            <div class="card-header py-1 d-flex justify-content-between" style="font-size:13px;">
                <span><strong>${esc(STEP_CN[s.step] || s.step)}</strong>${statusBadge}${durBadge}</span>
                <span class="text-muted">${esc(ts)}</span>
            </div>
            <div class="card-body py-2" style="font-size:12px;">
                ${sumHtml}${errHtml}
                <pre class="mb-0" style="white-space:pre-wrap;word-break:break-all;background:#f8f9fa;padding:8px;border-radius:4px;">${esc(JSON.stringify(detail, null, 2))}</pre>
            </div>
        </div>`;
    }).join('') : '<div class="text-muted">链路数据为空</div>';
    bootstrap.Modal.getOrCreateInstance(document.getElementById('pipelineModal')).show();
}
const SENSITIVE_PAGE_SIZE = 50;
let sensitiveCur = 1, sensitiveTotal = 0;
const LEVEL_CN = { public: '公开', internal: '内部', sensitive: '敏感', confidential: '机密' };
const LEVELS = [
    ['public', '公开'], ['internal', '内部'], ['sensitive', '敏感'], ['confidential', '机密']
];
function levelSelect(item) {
    return `<select class="form-select form-select-sm" onchange="updateSensitive(${item.column_id}, this.value)">` +
        LEVELS.map(([v, label]) => `<option value="${v}" ${item.sensitive_level === v ? 'selected' : ''}>${label}</option>`).join('') + `</select>`;
}
async function loadSensitive() {
    const keyword = document.getElementById('sensitiveSearch').value.trim();
    const level = document.getElementById('sensitiveLevelFilter').value;
    const offset = (sensitiveCur - 1) * SENSITIVE_PAGE_SIZE;
    const params = new URLSearchParams({ limit: SENSITIVE_PAGE_SIZE, offset });
    if (keyword) params.set('search', keyword);
    if (level) params.set('sensitive_level', level);
    const data = await get('/api/audit/all-columns?' + params.toString());
    sensitiveTotal = data.total || 0;
    const maxPage = Math.max(1, Math.ceil(sensitiveTotal / SENSITIVE_PAGE_SIZE));
    if (sensitiveCur > maxPage) { sensitiveCur = maxPage; return loadSensitive(); }
    document.getElementById('sensitive').innerHTML = data.items.map(item => `<tr><td>${esc(item.schema_name)}</td><td>${esc(item.table_name)}</td><td>${esc(item.column_name)}</td><td style="max-width:260px;">${esc(item.description || '')}</td><td>${esc(LEVEL_CN[item.sensitive_level] || item.sensitive_level)}</td><td>${levelSelect(item)}</td></tr>`).join('') || '<tr><td colspan="6" class="text-center text-muted">无匹配字段</td></tr>';
    document.getElementById('sensitiveCount').textContent = `共 ${sensitiveTotal} 个字段`;
    document.getElementById('sensitivePageInfo').textContent = `${sensitiveCur} / ${maxPage}`;
    document.getElementById('sensitivePrev').disabled = sensitiveCur <= 1;
    document.getElementById('sensitiveNext').disabled = sensitiveCur >= maxPage;
}
function sensitivePage(delta) {
    const next = sensitiveCur + delta;
    if (next < 1) return;
    sensitiveCur = next;
    loadSensitive();
}
async function updateSensitive(columnId, level) { await get('/api/audit/sensitive-level', { method: 'PUT', body: JSON.stringify({column_id: columnId, sensitive_level: level}) }); }
document.querySelectorAll('[data-tab]').forEach(button => button.addEventListener('click', () => { document.querySelectorAll('[data-tab]').forEach(item => item.classList.remove('active')); button.classList.add('active'); ['overview','logs','sensitive'].forEach(tab => document.getElementById('tab-' + tab).hidden = tab !== button.dataset.tab); if (button.dataset.tab === 'logs') loadLogs(); if (button.dataset.tab === 'sensitive') loadSensitive(); }));
loadStats();
