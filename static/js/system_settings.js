/* system_settings.html — 系统设置页交互逻辑 */
async function checkAll() {
    await checkEmbedding();
    await loadSettings();
}

async function checkEmbedding() {
    try {
        const resp = await apiRequest('/api/system/embedding-status');
        const data = await resp.json();
        const container = document.getElementById('embeddingInfo');

        // status
        let readyHtml;
        if (data.ready) {
            readyHtml = '<span class="status-dot ok"></span>就绪 (true)';
            document.getElementById('btnDownload').style.display = 'none';
        } else if (data.downloaded) {
            readyHtml = '<span class="status-dot warn"></span>已下载待加载 (false)';
            document.getElementById('btnDownload').style.display = 'none';
        } else {
            readyHtml = '<span class="status-dot warn"></span>未下载 (false)';
            document.getElementById('btnDownload').style.display = '';
        }

        // path
        const path = data.model_path || '-';
        const pathDisplay = path !== '-' ? `<small>${escapeHtml(path)}</small>` : '<span class="text-muted">-</span>';

        container.innerHTML = `
            <div class="setting-row">
                <div><span class="setting-key">EMBEDDING_MODEL_READY</span><br><span class="setting-desc">模型就绪状态</span></div>
                <span class="setting-value">${readyHtml}</span>
            </div>
            <div class="setting-row">
                <div><span class="setting-key">EMBEDDING_MODEL_PATH</span><br><span class="setting-desc">本地模型路径</span></div>
                <span class="setting-value">${pathDisplay}</span>
            </div>
        `;
    } catch (e) {
        document.getElementById('embeddingInfo').innerHTML = '<div class="text-danger">检查失败: ' + e.message + '</div>';
    }
}

async function loadSettings() {
    try {
        const resp = await apiRequest('/api/system/settings');
        const items = await resp.json();

        // JWT 配置
        const jwtKeys = ['SECRET_KEY', 'ACCESS_TOKEN_EXPIRE_MINUTES'];
        const jwtItems = items.filter(s => jwtKeys.includes(s.key));
        document.getElementById('jwtSettings').innerHTML = jwtItems.map(s => renderSettingRow(s, {
            'SECRET_KEY': { desc: 'JWT 签名密钥', disabled: true },
            'ACCESS_TOKEN_EXPIRE_MINUTES': { desc: 'Token 有效时长（分钟）' }
        })).join('');

        // 向量索引参数
        const vecKeys = ['VECTOR_INDEX_THRESHOLD', 'FIELD_RECALL_TOP_K', 'MAX_TABLES'];
        const vecItems = items.filter(s => vecKeys.includes(s.key));
        document.getElementById('vectorConfig').innerHTML = vecItems.map(s => renderSettingRow(s, {
            'VECTOR_INDEX_THRESHOLD': { desc: '字段数达到此值自动构建索引', width: '80px' },
            'FIELD_RECALL_TOP_K': { desc: '向量检索时召回的最大字段数', width: '80px' },
            'MAX_TABLES': { desc: '按表聚合时包含的最大表数', width: '80px' }
        })).join('');

        // 站点品牌（Logo / 站点名）
        const brandKeys = ['SITE_LOGO', 'SITE_NAME'];
        const brandItems = items.filter(s => brandKeys.includes(s.key));
        document.getElementById('brandingConfig').innerHTML = brandItems.map(s => renderSettingRow(s, {
            'SITE_LOGO': { desc: '自定义 Logo 图片地址（留空使用默认）', width: '240px' },
            'SITE_NAME': { desc: '站点名称（登录页/顶栏品牌显示）', width: '140px' }
        })).join('');
    } catch (e) {
        document.getElementById('jwtSettings').textContent = '加载失败（仅管理员可查看）';
    }
}

function renderSettingRow(s, meta) {
    const m = (meta && meta[s.key]) || {};
    const desc = m.desc || '';
    const disabled = m.disabled || false;
    const width = m.width || '120px';
    return `
    <div class="setting-row">
        <div>
            <span class="setting-key">${s.key}</span>
            <br><span class="setting-desc">${desc}</span>
        </div>
        <div style="display:flex;align-items:center;gap:8px;">
            <input type="text" class="form-control form-control-sm2"
                   id="val-${s.key}" value="${escapeHtml(s.value)}"
                   style="width:${width};"
                   ${disabled ? 'disabled' : ''}>
            ${!disabled ? `<button class="btn btn-outline-primary btn-sm2" onclick="saveSetting('${s.key}')">保存</button>` : ''}
        </div>
    </div>`;
}

async function saveSetting(key) {
    const input = document.getElementById('val-' + key);
    try {
        const resp = await apiRequest('/api/system/settings', {
            method: 'PUT',
            body: JSON.stringify({ key, value: input.value })
        });
        const data = await resp.json().catch(() => ({}));
        if (resp.ok) {
            QF.toast(data.message ? data.message + '（重启服务后生效）' : '保存成功', 'success');
        } else {
            QF.toast(data.detail || '保存失败', 'danger');
        }
    } catch (e) {
        QF.toast('保存失败: ' + e.message, 'danger');
    }
}

async function downloadEmbedding() {
    const btn = document.getElementById('btnDownload');
    btn.disabled = true; btn.textContent = '⏳ 正在启动下载...';
    try {
        const resp = await apiRequest('/api/system/download-embedding', { method: 'POST' });
        const data = await resp.json().catch(() => ({}));
        QF.toast(data.message || '下载已启动', data.success ? 'info' : 'danger');
    } catch (e) {
        QF.toast('下载失败: ' + e.message, 'danger');
    }
    btn.disabled = false; btn.textContent = '📥 下载 Embedding 模型';
}

// escapeHtml 由 app_common.js 提供

document.addEventListener('DOMContentLoaded', checkAll);
