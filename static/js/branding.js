/* ============================================================
   QueryForge 站点品牌 — Logo / 站点名自定义
   - 读取公开接口 /api/system/site-branding（系统设置 SITE_LOGO / SITE_NAME）
   - 将 data-brand-logo 图片替换为自定义 Logo（未配置时保持默认）
   ============================================================ */
(function () {
    function applyBranding(cfg) {
        if (!cfg) return;
        if (cfg.logo) {
            document.querySelectorAll('img[data-brand-logo]').forEach(function (img) {
                img.src = cfg.logo;
            });
        }
        if (cfg.site_name) {
            document.querySelectorAll('[data-brand-name]').forEach(function (el) {
                el.textContent = cfg.site_name;
            });
        }
    }

    fetch('/api/system/site-branding', { credentials: 'same-origin' })
        .then(function (resp) { return resp.ok ? resp.json() : null; })
        .then(applyBranding)
        .catch(function () { /* 静默失败，保持默认品牌 */ });
})();
