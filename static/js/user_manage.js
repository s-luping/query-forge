/* user_manage.html — 用户管理交互逻辑 */
let users = [];
let createModal = null, roleModal = null, resetModal = null;

// 统一关闭：优先走 Bootstrap 实例（含遮罩/动画清理），再兜底移除样式
function hideModal(id) {
    const el = document.getElementById(id);
    if (!el) return;
    const inst = bootstrap.Modal.getInstance(el);
    if (inst) inst.hide();
    el.classList.remove('show');
    el.style.display = 'none';
}

function fmtDate(s) { return s ? String(s).replace('T', ' ').slice(0, 19) : '-'; }

// 用户列表分页（20/页）+ 搜索
let userPage = 1, userSearch = '';
const USER_PS = 20;

async function loadUsers() {
    const resp = await apiRequest('/api/user/list');
    if (!resp.ok) { showErr('加载用户列表失败'); return; }
    users = await resp.json();
    userPage = 1;
    renderUserTable();
}

function renderUserTable() {
    const kw = userSearch.toLowerCase();
    const filtered = users.filter(u =>
        !kw || (u.username || '').toLowerCase().includes(kw) || ((u.email || '') || '').toLowerCase().includes(kw));
    const pageItems = filtered.slice((userPage - 1) * USER_PS, userPage * USER_PS);
    document.getElementById('userCount').textContent = `共 ${filtered.length} 个用户`;
    const tbody = document.getElementById('userTable');
    tbody.innerHTML = pageItems.length ? pageItems.map(u => `
        <tr>
            <td>${u.user_id}</td>
            <td>${e(u.username)}</td>
            <td>${e(u.email) || '-'}</td>
            <td><span class="badge ${u.role === 'admin' ? 'badge-admin' : 'badge-user'}">${u.role === 'admin' ? '管理员' : '普通用户'}</span></td>
            <td>${u.is_active === 1 ? '<span class="badge bg-success">启用</span>' : '<span class="badge badge-off">禁用</span>'}</td>
            <td>${fmtDate(u.register_date)}</td>
            <td>${fmtDate(u.last_login)}</td>
            <td class="text-nowrap">
                <button class="btn btn-outline-primary btn-sm" onclick="openRole(${u.user_id})">分配角色</button>
                <button class="btn btn-outline-warning btn-sm" onclick="openReset(${u.user_id})">重置密码</button>
                <button class="btn btn-outline-secondary btn-sm" onclick="toggleActive(${u.user_id})">${u.is_active === 1 ? '禁用' : '启用'}</button>
                <button class="btn btn-outline-danger btn-sm" onclick="delUser(${u.user_id})">删除</button>
            </td>
        </tr>`).join('')
        : '<tr><td colspan="8" class="text-center py-3 text-muted">暂无用户</td></tr>';
    QF.renderPager('userPager', {
        total: filtered.length, page: userPage, pageSize: USER_PS,
        onPage: p => { userPage = p; renderUserTable(); }
    });
}

function onUserSearch() {
    userSearch = document.getElementById('userSearch').value.trim();
    userPage = 1;
    renderUserTable();
}

// ── 新建 ──────────────────────────────────────────────
function openCreate() { createModal.show(); }

async function submitCreate() {
    const body = {
        username: document.getElementById('c-username').value.trim(),
        password: document.getElementById('c-password').value,
        email: document.getElementById('c-email').value.trim() || null,
        description: document.getElementById('c-desc').value.trim() || null,
        is_active: document.getElementById('c-active').checked ? 1 : 0,
    };
    if (body.username.length < 3) return QF.toast('用户名至少需要3个字符', 'warning');
    const resp = await apiRequest('/api/user/create', { method: 'POST', body: JSON.stringify(body) });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) return QF.toast(data.detail || '创建失败', 'danger');
    QF.toast(data.message || '用户创建成功', 'success');
    createModal.hide();
    loadUsers();
}

// ── 分配角色 ──────────────────────────────────────────
async function openRole(uid) {
    const u = users.find(x => x.user_id === uid);
    if (!u) return;
    document.getElementById('role-user-id').value = uid;
    document.getElementById('r-username-label2').textContent = u.username;
    await loadUserRoles(uid);
    roleModal.show();
}

async function submitRole() {
    const uid = document.getElementById('role-user-id').value;
    const roleIds = [...document.querySelectorAll('.role-check:checked')].map(item => +item.value);
    const resp = await apiRequest(`/api/permission/users/${uid}/roles`, {
        method: 'PUT', body: JSON.stringify({ role_ids: roleIds })
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) return QF.toast(data.detail || '角色保存失败', 'danger');
    QF.toast(data.message || '角色已更新', 'success');
    roleModal.hide();
    loadUsers();
}

async function loadUserRoles(uid) {
    const [rolesResp, assignedResp] = await Promise.all([
        apiRequest('/api/permission/roles'),
        apiRequest(`/api/permission/users/${uid}/roles`)
    ]);
    const roles = await rolesResp.json();
    const assigned = await assignedResp.json();
    const assignedIds = new Set(assigned.map(item => item.id));
    document.getElementById('role-list').innerHTML = roles.map(role =>
        `<label class="form-check form-check-inline"><input class="form-check-input role-check" type="checkbox" value="${role.id}" ${assignedIds.has(role.id) ? 'checked' : ''}><span class="form-check-label">${e(role.name)}</span></label>`
    ).join('') || '<span class="text-muted">暂无角色</span>';
}

// ── 启用/禁用 ────────────────────────────────────────
async function toggleActive(uid) {
    const u = users.find(x => x.user_id === uid);
    if (!u) return;
    const next = u.is_active === 1 ? 0 : 1;
    const resp = await apiRequest(`/api/user/${uid}`, {
        method: 'PUT', body: JSON.stringify({ is_active: next })
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) return QF.toast(data.detail || '操作失败', 'danger');
    loadUsers();
}

// ── 重置密码 ─────────────────────────────────────────
function openReset(uid) {
    const u = users.find(x => x.user_id === uid);
    if (!u) return;
    document.getElementById('r-user-id').value = uid;
    document.getElementById('r-username-label').textContent = u.username;
    document.getElementById('r-password').value = '';
    document.getElementById('r-password2').value = '';
    resetModal.show();
}

async function submitReset() {
    const uid = document.getElementById('r-user-id').value;
    const p1 = document.getElementById('r-password').value;
    const p2 = document.getElementById('r-password2').value;
    if (p1 !== p2) return QF.toast('两次输入的密码不一致', 'warning');
    const resp = await apiRequest(`/api/user/${uid}/reset-password`, {
        method: 'POST', body: JSON.stringify({ new_password: p1 })
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) return QF.toast(data.detail || '重置失败', 'danger');
    QF.toast(data.message || '密码已重置', 'success');
    resetModal.hide();
}

// ── 删除 ─────────────────────────────────────────────
async function delUser(uid) {
    const u = users.find(x => x.user_id === uid);
    if (!u) return;
    if (!confirm(`确定删除用户「${u.username}」？\n\n将同时清除其授权、对话、模型配置、知识库等关联数据，且不可恢复。\n（企业建议：不确定时请改用「禁用」）`)) return;
    const resp = await apiRequest(`/api/user/${uid}`, { method: 'DELETE' });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) return QF.toast(data.detail || '删除失败', 'danger');
    QF.toast(data.message || '已删除', 'success');
    loadUsers();
}

function showErr(msg) { document.getElementById('userTable').innerHTML = `<tr><td colspan="8" class="text-center py-3 text-danger">${e(msg)}</td></tr>`; }

// 兜底：data-bs-dismiss 之外再挂一层点击委托（幂等，防个别场景 Bootstrap 实例未初始化）
document.addEventListener('click', function (ev) {
    const btn = ev.target.closest('[data-bs-dismiss="modal"]');
    if (btn) {
        const m = btn.closest('.modal');
        if (m) hideModal(m.id);
    }
});

// 点击遮罩关闭
document.querySelectorAll('.modal').forEach(m => m.addEventListener('click', ev => {
    if (ev.target === m) hideModal(m.id);
}));

document.addEventListener('DOMContentLoaded', function () {
    createModal = new bootstrap.Modal(document.getElementById('createModal'));
    roleModal = new bootstrap.Modal(document.getElementById('roleModal'));
    resetModal = new bootstrap.Modal(document.getElementById('resetModal'));
    loadUsers();
});
