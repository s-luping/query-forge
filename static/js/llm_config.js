/* QueryForge 页面脚本 — 自 static/template/llm/llm_config.html 拆出，公共 apiRequest/e/QF 见 app_common.js */

        function toggleApiKey() {
            const input = document.getElementById('apiKey');
            const icon = document.getElementById('apiKeyToggleIcon');
            if (input.type === 'password') {
                input.type = 'text';
                icon.classList.replace('fa-eye', 'fa-eye-slash');
            } else {
                input.type = 'password';
                icon.classList.replace('fa-eye-slash', 'fa-eye');
            }
        }

        async function testConnection() {
            const provider = document.getElementById('providerInput').value;
            const apiKey = document.getElementById('apiKey').value;
            const model = document.getElementById('modelInput').value;
            const baseUrl = document.getElementById('baseUrl').value;
            const maxTokens = parseInt(document.getElementById('maxTokens').value) || 8192;
            const temperature = parseFloat(document.getElementById('temperature').value) || 0.0;
            const configId = document.getElementById('configId').value;

            if (!provider) {
                QF.toast('请输入模型供应商', 'warning');
                return;
            }
            if (!model) {
                QF.toast('请输入模型名称', 'warning');
                return;
            }
            if (!apiKey && !configId) {
                QF.toast('请输入API密钥', 'warning');
                return;
            }
            if (!baseUrl) {
                QF.toast('请输入API地址', 'warning');
                return;
            }

            const btn = document.querySelector('.btn-test');
            const originalText = btn.innerHTML;
            btn.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i>测试中...';
            btn.disabled = true;

            try {
                const requestData = {
                    provider: provider,
                    model: model,
                    base_url: baseUrl || null,
                    max_tokens: maxTokens,
                    temperature: temperature
                };

                if (apiKey) {
                    requestData.api_key = apiKey;
                }
                if (configId) {
                    requestData.config_id = parseInt(configId);
                }

                const response = await apiRequest('/api/llm-config/test', {
                    method: 'POST',
                    body: JSON.stringify(requestData)
                });
                const result = await response.json();

                if (result.success) {
                    QF.toast('✅ ' + result.message, 'success');
                } else {
                    QF.toast('❌ ' + result.message, 'danger');
                }
            } catch (e) {
                QF.toast('测试失败: ' + e.message, 'danger');
            } finally {
                btn.innerHTML = originalText;
                btn.disabled = false;
            }
        }

        document.getElementById('configForm').addEventListener('submit', async function(e) {
            e.preventDefault();

            const configId = document.getElementById('configId').value;
            const provider = document.getElementById('providerInput').value;
            const model = document.getElementById('modelInput').value;
            const apiKeyValue = document.getElementById('apiKey').value;
            const baseUrl = document.getElementById('baseUrl').value;

            if (!provider) {
                QF.toast('请输入模型供应商', 'warning');
                return;
            }
            if (!model) {
                QF.toast('请输入模型名称', 'warning');
                return;
            }
            if (!baseUrl) {
                QF.toast('请输入API地址', 'warning');
                return;
            }

            const data = {
                provider: provider,
                model: model,
                base_url: baseUrl || null,
                max_tokens: parseInt(document.getElementById('maxTokens').value) || 8192,
                temperature: parseFloat(document.getElementById('temperature').value) || 0.0,
                thinking_mode: document.getElementById('thinkingMode').value || 'auto',
                timeout: parseInt(document.getElementById('timeout').value) || 300,
                is_default: document.getElementById('isDefault').checked,
                is_public: document.getElementById('isPublic').checked,
                description: document.getElementById('description').value || null
            };

            if (apiKeyValue) {
                data.api_key = apiKeyValue;
            }

            try {
                let response;
                if (configId) {
                    response = await apiRequest(`/api/llm-config/${configId}`, {
                        method: 'PUT',
                        body: JSON.stringify(data)
                    });
                } else {
                    if (!apiKeyValue) {
                        QF.toast('请输入API密钥', 'warning');
                        return;
                    }
                    response = await apiRequest('/api/llm-config/create', {
                        method: 'POST',
                        body: JSON.stringify(data)
                    });
                }

                const result = await response.json();

                if (result.message) {
                    QF.toast('✅ ' + result.message, 'success');
                    loadConfigs();
                    resetForm();
                } else {
                    QF.toast('❌ 保存失败', 'danger');
                }
            } catch (e) {
                const error = await e.json?.() || { detail: e.message };
                QF.toast('保存失败: ' + (error.detail || e.message), 'danger');
            }
        });

        async function loadConfigs() {
            try {
                const response = await apiRequest('/api/llm-config/list');
                const data = await response.json();
                renderConfigs(data.items);
            } catch (e) {
                document.getElementById('configList').innerHTML =
                    '<div class="text-center text-danger py-4">加载失败</div>';
            }
        }

        function renderConfigs(items) {
            const container = document.getElementById('configList');

            if (!items || items.length === 0) {
                container.innerHTML = '<div class="text-center text-muted py-4">暂无配置</div>';
                return;
            }

            container.innerHTML = items.map(item => `
                <div class="config-item ${item.is_default ? 'default' : ''}">
                    <div class="d-flex justify-content-between align-items-start">
                        <div>
                            <div class="fw-bold">
                                🤖 ${escapeHtml(item.provider)} / ${escapeHtml(item.model)}
                                ${item.is_public ? '<span class="status-badge bg-info text-white ms-2">公共</span>' : '<span class="status-badge bg-light text-dark ms-2">私有</span>'}
                                ${item.is_default ? '<span class="status-badge bg-success text-white ms-2">默认</span>' : ''}
                                ${!item.is_active ? '<span class="status-badge bg-secondary text-white ms-2">已禁用</span>' : ''}
                            </div>
                            <small class="text-muted">
                                API Key: ${escapeHtml(item.api_key_masked)}
                                ${item.base_url ? `<br>API地址: ${escapeHtml(item.base_url)}` : ''}
                                <br>Max Tokens: ${item.max_tokens} | Temperature: ${item.temperature} | Timeout: ${item.timeout}s
                                ${item.thinking_mode && item.thinking_mode !== 'auto' ? ` | 思考: ${item.thinking_mode === 'enabled' ? '开' : '关'}` : ''}
                            </small>
                            ${item.description ? `<div class="mt-1"><small>${escapeHtml(item.description)}</small></div>` : ''}
                        </div>
                        <div class="btn-group btn-group-sm">
                            <button class="btn btn-outline-primary" onclick="editConfig(${item.id})" title="编辑">
                                <i class="fas fa-edit"></i>
                            </button>
                            ${!item.is_default ? `
                            <button class="btn btn-outline-success" onclick="setDefault(${item.id})" title="设为默认">
                                <i class="fas fa-star"></i>
                            </button>
                            ` : ''}
                            <button class="btn btn-outline-danger" onclick="deleteConfig(${item.id})" title="删除">
                                <i class="fas fa-trash"></i>
                            </button>
                        </div>
                    </div>
                </div>
            `).join('');
        }

        async function editConfig(id) {
            try {
                const response = await apiRequest(`/api/llm-config/list`);
                const data = await response.json();
                const config = data.items.find(c => c.id === id);

                if (!config) {
                    QF.toast('配置不存在', 'danger');
                    return;
                }

                document.getElementById('configId').value = config.id;
                document.getElementById('providerInput').value = config.provider;
                document.getElementById('modelInput').value = config.model;
                document.getElementById('apiKey').value = '';
                document.getElementById('apiKey').placeholder = '****** (不修改请留空)';
                document.getElementById('apiKeyHint').textContent = '当前已保存API密钥，留空则保持原值不变';
                if (config.base_url) {
                    document.getElementById('baseUrl').value = config.base_url;
                }
                document.getElementById('maxTokens').value = config.max_tokens ?? 8192;
                document.getElementById('temperature').value = config.temperature ?? 0.0;
                document.getElementById('thinkingMode').value = config.thinking_mode || 'auto';
                document.getElementById('timeout').value = config.timeout || 300;
                document.getElementById('isDefault').checked = config.is_default;
                document.getElementById('isPublic').checked = config.is_public || false;
                if (config.description) {
                    document.getElementById('description').value = config.description;
                }
            } catch (e) {
                QF.toast('获取配置失败', 'danger');
            }
        }

        async function setDefault(id) {
            try {
                const response = await apiRequest(`/api/llm-config/set-default/${id}`, {
                    method: 'POST'
                });
                const result = await response.json();

                if (result.message) {
                    loadConfigs();
                }
            } catch (e) {
                QF.toast('设置失败', 'danger');
            }
        }

        async function deleteConfig(id) {
            if (!confirm('确定要删除这个配置吗？')) return;

            try {
                const response = await apiRequest(`/api/llm-config/${id}`, {
                    method: 'DELETE'
                });
                const result = await response.json();

                if (result.message) {
                    loadConfigs();
                }
            } catch (e) {
                QF.toast('删除失败', 'danger');
            }
        }

        function resetForm() {
            document.getElementById('configId').value = '';
            document.getElementById('providerInput').value = '';
            document.getElementById('modelInput').value = '';
            document.getElementById('apiKey').value = '';
            document.getElementById('apiKey').placeholder = '请输入API密钥';
            document.getElementById('apiKeyHint').textContent = '新建配置时必填，编辑时留空则保持原值';
            document.getElementById('baseUrl').value = '';
            document.getElementById('maxTokens').value = 8192;
            document.getElementById('temperature').value = 0.0;
            document.getElementById('thinkingMode').value = 'auto';
            document.getElementById('timeout').value = 300;
            document.getElementById('description').value = '';
            document.getElementById('isDefault').checked = false;
            document.getElementById('isPublic').checked = false;
        }

        // escapeHtml / e 由 app_common.js 提供

        document.addEventListener('DOMContentLoaded', function () {
            loadConfigs();
        });
