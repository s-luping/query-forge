/* ============================================================
   QueryForge 前端公共层 — 合并各页面重复的 API 封装 / 转义 / 认证守卫
   - 统一 apiRequest（401 → 跳登录）
   - 统一 e() HTML 转义
   - 启动时加载当前用户，body 增加 qf-authed / qf-admin 标记
   - 非管理员自动移除 [data-admin-only] 元素（角色差异化展示）
   - 页面初始化逻辑挂到 window.QF.onReady(user)
   ============================================================ */
(function () {
    window.QF = window.QF || {};

    // HTML 转义（防 XSS）
    window.e = function (s) {
        const d = document.createElement('div');
        d.textContent = s == null ? '' : String(s);
        return d.innerHTML;
    };
    // 兼容历史命名（chat/llm_config/llm_logs 曾各自定义 escapeHtml）
    window.escapeHtml = window.e;

    // JS 字符串上下文转义——用于「HTML 属性内内联 JS 的单引号字符串」插值，
    // 如 onclick="fn('${escapeAttr(title)}')"。注意：e()/escapeHtml() 不转义
    // 引号，绝不能用于此场景（属性值会被 HTML 解析器实体解码后交给 JS 引擎）。
    window.escapeAttr = function (text) {
        return String(text == null ? '' : text)
            .replace(/\\/g, '\\\\')
            .replace(/'/g, "\\'")
            .replace(/"/g, '&quot;');
    };

    // 时间格式化（合并 llm_logs.formatTime / security_manage.fmtTime / sync_manage.fmt）
    window.QF.fmtTime = function (s, fallback) {
        if (s == null || s === '') return fallback === undefined ? '-' : fallback;
        const d = new Date(s);
        if (!isNaN(d.getTime())) return d.toLocaleString('zh-CN');
        return String(s).replace('T', ' ').slice(0, 19);
    };
    window.formatTime = window.QF.fmtTime;
    window.fmtTime = window.QF.fmtTime;
    window.fmt = window.QF.fmtTime;

    // 全局浮动提示（右上角 toast，自动消失）：
    //   QF.toast('保存成功', 'success' | 'danger' | 'warning' | 'info')
    // 不依赖 Bootstrap 组件，任何页面引用 app_common.js 后即可使用。
    window.QF.toast = function (message, type) {
        type = type || 'info';
        const colors = { success: '#28a745', danger: '#dc3545', warning: '#ffc107', info: '#0d6efd' };
        const color = colors[type] || colors.info;
        const container = document.getElementById('qf-toast-container');
        const host = container || (function () {
            const el = document.createElement('div');
            el.id = 'qf-toast-container';
            el.style.cssText = 'position:fixed;top:16px;right:16px;z-index:9999;display:flex;flex-direction:column;gap:8px;max-width:360px;';
            document.body.appendChild(el);
            return el;
        })();
        const toast = document.createElement('div');
        toast.style.cssText =
            'background:#fff;border-left:4px solid ' + color + ';border-radius:6px;' +
            'box-shadow:0 2px 12px rgba(0,0,0,.15);padding:10px 14px;font-size:13px;color:#333;' +
            'display:flex;align-items:center;gap:8px;word-break:break-all;' +
            'animation:qfToastIn .2s ease;';
        toast.innerHTML =
            '<span style="width:8px;height:8px;border-radius:50%;background:' + color + ';flex:none;"></span>' +
            '<span>' + window.e(message) + '</span>';
        if (!document.getElementById('qf-toast-style')) {
            const style = document.createElement('style');
            style.id = 'qf-toast-style';
            style.textContent =
                '@keyframes qfToastIn{from{opacity:0;transform:translateX(20px)}to{opacity:1;transform:none}}' +
                '@keyframes qfToastOut{from{opacity:1}to{opacity:0;transform:translateX(20px)}}';
            document.head.appendChild(style);
        }
        host.appendChild(toast);
        setTimeout(function () {
            toast.style.animation = 'qfToastOut .2s ease';
            setTimeout(function () { toast.remove(); }, 220);
        }, 2600);
    };
    // 兼容历史命名
    window.showToast = window.QF.toast;

    // 统一 API 请求：兼容主界面 iframe（window.apiRequest 由 index.html 注入）
    // 与独立打开（token 为 HttpOnly cookie，fetch 同源自动携带）
    // FormData（文件上传）由浏览器自动设置 multipart 边界，不能强制 JSON Content-Type
    window.apiRequest = window.apiRequest || async function (url, options = {}) {
        const headers = {};
        if (!(options.body instanceof FormData)) {
            headers['Content-Type'] = 'application/json';
        }
        const resp = await fetch(url, { ...options, headers, credentials: 'same-origin' });
        if (resp.status === 401) {
            const data = await resp.json().catch(() => ({}));
            const msg = data.detail || '登录已过期，请重新登录';
            window.top.location.href = '/login';   // 嵌套 iframe 也跳到顶层登录页
            throw new Error(msg);
        }
        return resp;
    };

    // 模态框无障碍修复：Bootstrap 隐藏模态框时会给框体写 aria-hidden="true"，
    // 若此刻框内仍有焦点元素（例如被点击过的 .btn-close），Chrome 会阻断该 aria-hidden
    // 并报警（“descendant retained focus”）。规范建议改用 inert 属性。
    // - hide.bs.modal   ：先把焦点移出框体（该事件在 Bootstrap 写入 aria-hidden 之前触发）
    // - hidden.bs.modal ：补上 inert，彻底阻止焦点/点击进入已隐藏的模态框
    // - show.bs.modal   ：显示前移除 inert，避免影响 Bootstrap 自身的焦点管理
    window.QF.modalA11y = function (modalEl) {
        if (!modalEl) return;
        modalEl.addEventListener('hide.bs.modal', function () {
            if (modalEl.contains(document.activeElement)) {
                document.activeElement.blur();
            }
        });
        modalEl.addEventListener('hidden.bs.modal', function () {
            modalEl.setAttribute('inert', '');
        });
        modalEl.addEventListener('show.bs.modal', function () {
            modalEl.removeAttribute('inert');
        });
    };

    // 非阻塞确认框，替代原生 confirm()：confirm() 会同步阻塞事件循环，
    // 导致 DevTools 报 “[Violation] 'click' handler took xxx ms”，且样式与页面割裂。
    // 返回 Promise<boolean>；环境里没有 Bootstrap 时降级为原生 confirm。
    window.QF.confirm = function (message, options) {
        options = options || {};
        if (typeof bootstrap === 'undefined' || typeof bootstrap.Modal !== 'function') {
            return Promise.resolve(window.confirm(message));
        }
        const title = options.title || '确认操作';
        const okText = options.okText || '确定';
        const cancelText = options.cancelText || '取消';
        const okClass = options.okClass || 'btn-danger';
        const titleId = 'qf-confirm-title-' + Date.now();
        const trigger = document.activeElement;   // 关闭后把焦点还给触发按钮

        return new Promise(function (resolve) {
            const host = document.createElement('div');
            host.innerHTML =
                '<div class="modal fade" tabindex="-1" role="dialog" aria-labelledby="' + titleId + '">' +
                '  <div class="modal-dialog modal-dialog-centered modal-sm">' +
                '    <div class="modal-content">' +
                '      <div class="modal-header">' +
                '        <h6 class="modal-title" id="' + titleId + '"></h6>' +
                '        <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="关闭"></button>' +
                '      </div>' +
                '      <div class="modal-body"></div>' +
                '      <div class="modal-footer">' +
                '        <button type="button" class="btn btn-secondary"></button>' +
                '        <button type="button" class="btn ' + okClass + '"></button>' +
                '      </div>' +
                '    </div>' +
                '  </div>' +
                '</div>';
            const modalEl = host.firstElementChild;
            modalEl.querySelector('.modal-title').textContent = title;
            modalEl.querySelector('.modal-body').textContent = String(message == null ? '' : message);
            const [cancelBtn, okBtn] = modalEl.querySelectorAll('.modal-footer .btn');
            cancelBtn.textContent = cancelText;
            okBtn.textContent = okText;
            document.body.appendChild(modalEl);

            const modal = new bootstrap.Modal(modalEl);
            window.QF.modalA11y(modalEl);

            let result = false;
            okBtn.addEventListener('click', function () { result = true; modal.hide(); });
            cancelBtn.addEventListener('click', function () { modal.hide(); });
            // X / 点击遮罩 / Esc 均走 modal.hide() → hidden → resolve(false)
            modalEl.addEventListener('hidden.bs.modal', function () {
                modal.dispose();
                modalEl.remove();
                if (trigger && trigger.isConnected) trigger.focus();
                resolve(result);
            });
            modalEl.addEventListener('shown.bs.modal', function () {
                cancelBtn.focus();   // 默认焦点放在“取消”，避免误操作
            });
            modal.show();
        });
    };

    // 当前用户与角色（token 为 HttpOnly cookie，前端必须走后端接口获取）
    window.QF.user = null;
    window.QF.isAuthed = function () { return !!window.QF.user; };
    window.QF.isAdmin = function () { return !!(window.QF.user && window.QF.user.role === 'admin'); };

    // 敏感等级中文映射（数据库存英文，前端展示中文）
    window.QF.LEVEL_LABELS = {
        public: '公开',
        internal: '内部',
        sensitive: '敏感',
        confidential: '机密',
    };
    window.QF.levelLabel = function (lv) {
        return window.QF.LEVEL_LABELS[lv] || lv || '-';
    };

    // ── 通用分页条 ──────────────────────────────────────────────
    // QF.renderPager(containerId, {total, page, pageSize, onPage})
    //   onPage(newPage) 由调用方重新加载数据；总数 ≤ pageSize 时不渲染。
    window.QF._pagerHandlers = window.QF._pagerHandlers || {};
    window.QF.renderPager = function (containerId, opts) {
        const el = document.getElementById(containerId);
        if (!el) return;
        const total = opts.total || 0;
        const page = opts.page || 1;
        const pageSize = opts.pageSize || 50;
        const totalPages = Math.max(1, Math.ceil(total / pageSize));
        window.QF._pagerHandlers[containerId] = opts.onPage;
        if (totalPages <= 1) { el.innerHTML = ''; return; }

        // 页码窗口：最多显示 5 个数字页（当前页居中）
        const pages = [];
        let start = Math.max(1, page - 2), end = Math.min(totalPages, start + 4);
        start = Math.max(1, end - 4);
        for (let i = start; i <= end; i++) pages.push(i);

        const link = function (label, p, extra, disabled) {
            return '<li class="page-item ' + (extra || '') + (disabled ? ' disabled' : '') + '">' +
                '<a class="page-link" href="#" data-p="' + p + '" ' +
                (disabled ? 'tabindex="-1"' : '') + '>' + label + '</a></li>';
        };
        const numbered = pages.map(function (p) {
            return link(p, p, p === page ? 'active' : '');
        }).join('');

        el.innerHTML =
            '<div class="d-flex align-items-center justify-content-between">' +
            '<span class="text-muted" style="font-size:12px;">共 ' + total + ' 条</span>' +
            '<ul class="pagination pagination-sm mb-0">' +
            link('上一页', page - 1, '', page <= 1) +
            numbered +
            link('下一页', page + 1, '', page >= totalPages) +
            '</ul></div>';

        el.querySelectorAll('a[data-p]').forEach(function (a) {
            a.addEventListener('click', function (ev) {
                ev.preventDefault();
                const p = parseInt(a.getAttribute('data-p'), 10);
                if (!isNaN(p) && p !== page && !a.parentElement.classList.contains('disabled')) {
                    opts.onPage(p);
                }
            });
        });
    };

    // 角色差异化展示：body 打标；非管理员移除 data-admin-only 元素
    function applyRole() {
        document.body.classList.add('qf-authed');
        if (window.QF.isAdmin()) {
            document.body.classList.add('qf-admin');
        } else {
            document.querySelectorAll('[data-admin-only]').forEach(el => el.remove());
        }
    }

    // 认证守卫：未登录跳登录页；成功后回调页面自身初始化
    async function guard() {
        try {
            const resp = await fetch('/api/user/profile', { credentials: 'same-origin' });
            if (!resp.ok) throw new Error('unauthorized');
            window.QF.user = await resp.json();
            applyRole();
            if (typeof window.QF.onReady === 'function') {
                window.QF.onReady(window.QF.user);
            }
        } catch (e) {
            window.top.location.href = '/login';   // 未登录 → 顶层登录页
        }
    }

    window.QF.guard = guard;

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', guard);
    } else {
        guard();
    }
})();
