/* dashboard.html — 仪表盘页交互逻辑 */
function jump(url) {
    // 在父窗口（管理后台框架）中打开对应页面
    if (window.parent && window.parent.openWindow) {
        const map = {
            '/static/template/schema/schema_view.html': '数据浏览',
            '/static/template/schema/vector_index.html': '向量索引',
            '/static/template/system/sync_manage.html': '同步管理',
            '/static/template/system/sync_manage.html#runs': '同步历史',
            '/static/template/llm/llm_config.html': '模型配置',
            '/static/template/system/security_manage.html#overview': '审计概览',
            '/static/template/system/security_manage.html#logs': '审计日志',
            '/static/template/system/user_manage.html': '用户管理',
            '/static/template/knowledge.html': '知识库',
            '/static/template/system/system_settings.html': '系统设置',
        };
        window.parent.openWindow(map[url] || url, url);
    } else {
        window.location.href = url;
    }
}

async function loadAll() {
    const greeting = document.getElementById('greeting');
    const sub = document.getElementById('greetingSub');
    if (window.QF && window.QF.user) {
        const u = window.QF.user;
        const hour = new Date().getHours();
        const period = hour < 6 ? '凌晨好' : hour < 12 ? '上午好' : hour < 14 ? '中午好' : hour < 18 ? '下午好' : '晚上好';
        greeting.textContent = `${period}，${u.username}`;
    }
    sub.textContent = '系统运行概览 · 更新于 ' + new Date().toLocaleString('zh-CN');

    // 用户数
    try {
        const resp = await apiRequest('/api/permission/users');
        const users = await resp.json();
        const active = users.filter(u => u.is_active).length;
        document.getElementById('st-users').textContent = `${active}/${users.length}`;
    } catch (e) { document.getElementById('st-users').textContent = '-'; }

    // Schema 统计
    try {
        const resp = await apiRequest('/api/schema/stats');
        const s = await resp.json();
        document.getElementById('st-schemas').textContent = `${s.schema_count || 0} / ${s.table_count || 0} / ${s.column_count || 0}`;
    } catch (e) { document.getElementById('st-schemas').textContent = '-'; }

    // 知识库
    try {
        const resp = await apiRequest('/api/knowledge?limit=1');
        const k = await resp.json();
        document.getElementById('st-knowledge').textContent = k.total || 0;
    } catch (e) { document.getElementById('st-knowledge').textContent = '-'; }

    // LLM 用量
    try {
        const resp = await apiRequest('/api/llm/stats');
        const l = await resp.json();
        document.getElementById('st-llm').textContent = (l.total_calls || 0).toLocaleString();
    } catch (e) { document.getElementById('st-llm').textContent = '-'; }

    // 审计统计
    try {
        const resp = await apiRequest('/api/audit/stats');
        const a = await resp.json();
        document.getElementById('st-blocked').textContent = `${a.blocked_queries || 0} / ${a.block_rate || '0%'}`;
    } catch (e) { document.getElementById('st-blocked').textContent = '-'; }

    // 同步统计
    try {
        const resp = await apiRequest('/api/sync/stats');
        const s = await resp.json();
        document.getElementById('st-sync-failed').textContent = s.runs?.failed || 0;
        document.getElementById('st-datasources').textContent = `${s.datasources?.active || 0}/${s.datasources?.total || 0}`;
        document.getElementById('st-jobs').textContent = `${s.jobs?.enabled || 0}/${s.jobs?.total || 0}`;
    } catch (e) { document.getElementById('st-sync-failed').textContent = '-'; }

    // 最近同步
    try {
        const resp = await apiRequest('/api/sync/runs?limit=5');
        const data = await resp.json();
        const tbody = document.getElementById('recentRuns');
        const items = data.items || [];
        if (!items.length) { tbody.innerHTML = '<tr><td colspan="4" class="empty-state">暂无同步记录</td></tr>'; }
        else {
            tbody.innerHTML = items.map(r => `<tr>
                <td>${fmtTime(r.started_at)}</td>
                <td>${r.summary ? (JSON.parse(r.summary).schema || '-') : '-'}</td>
                <td><span class="badge badge-${r.status}">${r.status}</span></td>
                <td>${r.columns_added || 0}/${r.columns_modified || 0}/${r.columns_removed || 0}</td>
            </tr>`).join('');
        }
    } catch (e) { /* 静默 */ }

    // 最近拦截
    try {
        const resp = await apiRequest('/api/audit/logs?limit=5&blocked_only=true');
        const data = await resp.json();
        const tbody = document.getElementById('recentBlocked');
        const items = data.items || [];
        if (!items.length) { tbody.innerHTML = '<tr><td colspan="4" class="empty-state">暂无拦截记录</td></tr>'; }
        else {
            tbody.innerHTML = items.map(r => `<tr>
                <td>${fmtTime(r.created_at)}</td>
                <td>${e(r.username)}</td>
                <td style="max-width:180px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" title="${e(r.query)}">${e(r.query)}</td>
                <td style="max-width:140px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" title="${e(r.block_reason)}">${e(r.block_reason)}</td>
            </tr>`).join('');
        }
    } catch (e) { /* 静默 */ }
}

// LLM 用量趋势（读主库聚合表 llm_usage_stats，每小时刷新，当天最多滞后 1 小时）
async function loadUsageTrend() {
    const chart = document.getElementById('trendChart');
    try {
        const resp = await apiRequest('/api/llm/usage-trend?days=7');
        const data = await resp.json();
        const items = data.items || [];
        const totalCalls = items.reduce((s, i) => s + i.call_count, 0);
        const totalTokens = items.reduce((s, i) => s + i.total_tokens, 0);
        document.getElementById('trendSummary').textContent =
            `合计调用 ${totalCalls.toLocaleString()} 次 · Token ${totalTokens.toLocaleString()}（每小时聚合刷新）`;
        if (!totalCalls) { chart.innerHTML = '<div class="empty-state w-100">近 7 天暂无调用</div>'; return; }
        const max = Math.max(...items.map(i => i.call_count));
        chart.innerHTML = items.map(i => {
            const d = new Date(i.stat_date + 'T00:00:00');
            const tip = `${i.stat_date}｜调用 ${i.call_count} 次（成功 ${i.success_count}）｜Token ${i.total_tokens.toLocaleString()}`;
            return `<div class="trend-col">
                <div class="trend-plot" title="${tip}">
                    <div class="trend-bar" style="height:${Math.max(Math.round(i.call_count / max * 100), 2)}%"></div>
                </div>
                <div class="trend-val">${i.call_count || ''}</div>
                <div class="trend-day">${d.getMonth() + 1}/${d.getDate()}</div>
            </div>`;
        }).join('');
    } catch (e) {
        chart.innerHTML = '<div class="empty-state w-100">趋势加载失败</div>';
    }
}

window.QF.onReady = function () { loadAll(); loadUsageTrend(); };
window.addEventListener('storage', event => {
    if (event.key === 'qf_schema_refresh') loadAll();
});
setInterval(loadAll, 30000);
