/* QueryForge 页面脚本 — 自 static/template/llm/llm_logs.html 拆出，公共 apiRequest/e/QF 见 app_common.js */

        let currentPage = 1;
        const pageSize = 20;

        // ---- 详情模态框：单例实例（避免每次 showDetail 都 new Modal 导致
        // “doesn't allow more than one instance per element” 报错）+ 无障碍修复
        // + 关闭后把焦点还给打开它的按钮 ----
        const detailModalEl = document.getElementById('detailModal');
        const detailModal = new bootstrap.Modal(detailModalEl);
        window.QF.modalA11y(detailModalEl);
        let detailTrigger = null;
        detailModalEl.addEventListener('hidden.bs.modal', function () {
            if (detailTrigger && detailTrigger.isConnected) {
                detailTrigger.focus();
            }
            detailTrigger = null;
        });

        async function loadStats() {
            // 后端按角色自动限定范围：管理员看全部，普通用户看自己的统计
            try {
                const response = await apiRequest('/api/llm/stats');
                const data = await response.json();

                document.getElementById('totalCalls').textContent = data.total_calls;
                document.getElementById('totalTokens').textContent = data.total_tokens.toLocaleString();
                document.getElementById('promptTokens').textContent = data.total_prompt_tokens.toLocaleString();
                document.getElementById('completionTokens').textContent = data.total_completion_tokens.toLocaleString();
                document.getElementById('totalCost').textContent = '$' + ((data.total_cost || 0).toFixed(4));
                document.getElementById('avgDuration').textContent = data.avg_duration_ms.toFixed(0);
                document.getElementById('successRate').textContent = data.success_rate + '%';
            } catch (e) {
                console.error('加载统计失败:', e);
            }
        }

        // 请求令牌：快速点击分页 / 切换筛选时，丢弃过期响应，避免旧数据覆盖新数据
        let loadToken = 0;

        async function loadLogs() {
            const token = ++loadToken;
            const status = document.getElementById('statusFilter').value;
            const offset = (currentPage - 1) * pageSize;

            try {
                let url = `/api/llm/list?limit=${pageSize}&offset=${offset}`;
                if (status) url += `&status=${status}`;

                const response = await apiRequest(url);
                const data = await response.json();
                if (token !== loadToken) return;

                renderLogs(data.items);
                renderPagination(data.total);
                document.getElementById('totalCount').textContent = data.total;
            } catch (e) {
                if (token !== loadToken) return;
                console.error('加载记录失败:', e);
                document.getElementById('logsTable').innerHTML =
                    '<tr><td colspan="12" class="text-center text-danger py-4">加载失败</td></tr>';
            }
        }

        // 用 DOM API + textContent 构建表格行（textContent 天然转义，且比拼接巨型
        // innerHTML 字符串更快）；title 只保留前 N 个字符，避免把大段 SQL/问题塞进属性。
        function renderLogs(items) {
            const tbody = document.getElementById('logsTable');
            tbody.innerHTML = '';

            if (!items || items.length === 0) {
                const tr = document.createElement('tr');
                const td = document.createElement('td');
                td.colSpan = 12;
                td.className = 'text-center text-muted py-4';
                td.textContent = '暂无记录';
                tr.appendChild(td);
                tbody.appendChild(tr);
                return;
            }

            const truncate = (s, n) => (s && s.length > n ? s.slice(0, n) + '…' : s);
            const frag = document.createDocumentFragment();

            for (const item of items) {
                const tr = document.createElement('tr');

                const tdId = document.createElement('td');
                tdId.textContent = item.id;
                tr.appendChild(tdId);

                const tdConv = document.createElement('td');
                if (item.conversation_id) {
                    const a = document.createElement('a');
                    a.href = 'javascript:void(0)';
                    a.className = 'badge bg-info text-decoration-none';
                    a.textContent = '对话 #' + item.conversation_id;
                    a.addEventListener('click', function () {
                        if (window.parent && typeof window.parent.openWindow === 'function') {
                            window.parent.openWindow('Chat SQL', '/static/template/chatSQL/chat.html');
                        }
                    });
                    tdConv.appendChild(a);
                } else {
                    const span = document.createElement('span');
                    span.className = 'text-muted';
                    span.textContent = '单次';
                    tdConv.appendChild(span);
                }
                tr.appendChild(tdConv);

                const tdProvider = document.createElement('td');
                const smallProvider = document.createElement('small');
                smallProvider.textContent = item.provider || '-';
                tdProvider.appendChild(smallProvider);
                tr.appendChild(tdProvider);

                const tdQ = document.createElement('td');
                tdQ.className = 'question-cell';
                tdQ.textContent = item.question || '';
                tdQ.title = truncate(item.question || '', 200);
                tr.appendChild(tdQ);

                const tdModel = document.createElement('td');
                tdModel.className = 'model-cell';
                tdModel.textContent = item.model || '';
                tdModel.title = truncate(item.model || '', 200);
                tr.appendChild(tdModel);

                const tdResult = document.createElement('td');
                tdResult.className = 'result-cell';
                tdResult.textContent = item.result || '-';
                tdResult.title = truncate(item.result || '', 300);
                tr.appendChild(tdResult);

                const tdDur = document.createElement('td');
                tdDur.textContent = item.duration_ms ? item.duration_ms.toFixed(0) : '-';
                tr.appendChild(tdDur);

                const tdTokens = document.createElement('td');
                const smallTokens = document.createElement('small');
                smallTokens.textContent = String(item.total_tokens || 0);
                const spanTokens = document.createElement('span');
                spanTokens.className = 'text-muted';
                spanTokens.textContent = `(${item.prompt_tokens || 0}/${item.completion_tokens || 0})`;
                smallTokens.appendChild(spanTokens);
                tdTokens.appendChild(smallTokens);
                tr.appendChild(tdTokens);

                const tdCost = document.createElement('td');
                const smallCost = document.createElement('small');
                smallCost.textContent = item.cost ? '$' + item.cost.toFixed(6) : '-';
                tdCost.appendChild(smallCost);
                tr.appendChild(tdCost);

                const tdStatus = document.createElement('td');
                const spanStatus = document.createElement('span');
                spanStatus.className = 'status-' + (item.status || '');
                spanStatus.textContent = getStatusText(item.status);
                tdStatus.appendChild(spanStatus);
                tr.appendChild(tdStatus);

                const tdTime = document.createElement('td');
                const smallTime = document.createElement('small');
                smallTime.textContent = formatTime(item.created_at);
                tdTime.appendChild(smallTime);
                tr.appendChild(tdTime);

                const tdOps = document.createElement('td');
                const btnDetail = document.createElement('button');
                btnDetail.type = 'button';
                btnDetail.className = 'btn btn-outline-primary btn-sm me-1';
                btnDetail.title = '查看详情';
                btnDetail.innerHTML = '<i class="fas fa-eye"></i>';
                btnDetail.addEventListener('click', function () { showDetail(item.id); });
                tdOps.appendChild(btnDetail);
                if (window.QF.isAdmin()) {
                    const btnDel = document.createElement('button');
                    btnDel.type = 'button';
                    btnDel.className = 'btn btn-outline-danger btn-sm';
                    btnDel.title = '删除';
                    btnDel.innerHTML = '<i class="fas fa-trash"></i>';
                    btnDel.addEventListener('click', function () { deleteLog(item.id); });
                    tdOps.appendChild(btnDel);
                }
                tr.appendChild(tdOps);

                frag.appendChild(tr);
            }
            tbody.appendChild(frag);
        }

        function renderPagination(total) {
            const totalPages = Math.ceil(total / pageSize);
            const pagination = document.getElementById('pagination');

            if (totalPages <= 1) {
                pagination.innerHTML = '';
                return;
            }

            let html = '';

            if (currentPage > 1) {
                html += `<li class="page-item"><a class="page-link" href="#" data-page="${currentPage - 1}">上一页</a></li>`;
            }

            for (let i = 1; i <= totalPages && i <= 5; i++) {
                html += `<li class="page-item ${i === currentPage ? 'active' : ''}">
                    <a class="page-link" href="#" data-page="${i}">${i}</a>
                </li>`;
            }

            if (totalPages > 5) {
                html += `<li class="page-item disabled"><span class="page-link">...</span></li>`;
                html += `<li class="page-item ${totalPages === currentPage ? 'active' : ''}">
                    <a class="page-link" href="#" data-page="${totalPages}">${totalPages}</a>
                </li>`;
            }

            if (currentPage < totalPages) {
                html += `<li class="page-item"><a class="page-link" href="#" data-page="${currentPage + 1}">下一页</a></li>`;
            }

            pagination.innerHTML = html;
        }

        // 分页事件委托（替代每个链接生成的 onclick="goToPage(n)" 内联脚本）
        document.getElementById('pagination').addEventListener('click', function (e) {
            if (!(e.target instanceof Element)) return;
            const link = e.target.closest('a[data-page]');
            if (!link) return;
            e.preventDefault();
            const page = parseInt(link.getAttribute('data-page'), 10);
            if (!isNaN(page) && page !== currentPage) {
                goToPage(page);
            }
        });

        function goToPage(page) {
            currentPage = page;
            loadLogs();
        }

        async function showDetail(id) {
            detailTrigger = document.activeElement;    // 记住打开者，关闭后还原焦点
            try {
                const response = await apiRequest(`/api/llm/${id}`);
                const item = await response.json();

                document.getElementById('detailContent').innerHTML = `
                    <div class="detail-item">
                        <div class="detail-label">问题</div>
                        <div class="detail-value">${escapeHtml(item.question)}</div>
                    </div>
                    <div class="row">
                        <div class="col-md-4 detail-item">
                            <div class="detail-label">供应商</div>
                            <div class="detail-value">${escapeHtml(item.provider || '-')}</div>
                        </div>
                        <div class="col-md-4 detail-item">
                            <div class="detail-label">来源</div>
                            <div class="detail-value">${item.conversation_id ? `对话 #${escapeHtml(item.conversation_id)}` : '单次生成'}</div>
                        </div>
                        <div class="col-md-4 detail-item">
                            <div class="detail-label">模型</div>
                            <div class="detail-value">${escapeHtml(item.model || '-')}</div>
                        </div>
                    </div>
                    <div class="row">
                        <div class="col-md-12 detail-item">
                            <div class="detail-label">条件</div>
                            <div class="detail-value">${escapeHtml(item.conditions || '-')}</div>
                        </div>
                    </div>
                    ${item.system_prompt ? `
                    <div class="detail-item">
                        <div class="detail-label">System Prompt（含表结构 + 领域知识）</div>
                        <details class="mt-1">
                            <summary class="text-primary" style="cursor:pointer;font-size:13px;">点击展开 / 折叠</summary>
                            <pre class="detail-value mt-2" style="max-height:400px;overflow:auto;white-space:pre-wrap;background:#f8f9fa;padding:10px;border-radius:6px;font-size:12px;">${escapeHtml(item.system_prompt)}</pre>
                        </details>
                    </div>
                    ` : ''}
                    <div class="row">
                        <div class="col-md-3 detail-item">
                            <div class="detail-label">耗时</div>
                            <div class="detail-value">${item.duration_ms ? item.duration_ms.toFixed(2) : '-'} ms</div>
                        </div>
                        <div class="col-md-2 detail-item">
                            <div class="detail-label">输入Token</div>
                            <div class="detail-value">${item.prompt_tokens || 0}</div>
                        </div>
                        <div class="col-md-2 detail-item">
                            <div class="detail-label">输出Token</div>
                            <div class="detail-value">${item.completion_tokens || 0}</div>
                        </div>
                        <div class="col-md-2 detail-item">
                            <div class="detail-label">总Token</div>
                            <div class="detail-value">${item.total_tokens || 0}</div>
                        </div>
                        <div class="col-md-3 detail-item">
                            <div class="detail-label">成本</div>
                            <div class="detail-value">${item.cost ? '$' + item.cost.toFixed(6) : '-'}</div>
                        </div>
                    </div>
                    <div class="detail-item">
                        <div class="detail-label">生成结果</div>
                        <div class="detail-value sql">${escapeHtml(item.result || '-')}</div>
                    </div>
                    ${item.error_message ? `
                    <div class="detail-item">
                        <div class="detail-label">错误信息</div>
                        <div class="detail-value text-danger">${escapeHtml(item.error_message)}</div>
                    </div>
                    ` : ''}
                    <div class="detail-item">
                        <div class="detail-label">调用时间</div>
                        <div class="detail-value">${formatTime(item.created_at)}</div>
                    </div>
                `;

                detailModal.show();
            } catch (e) {
                QF.toast('获取详情失败', 'danger');
            }
        }

        async function deleteLog(id) {
            // 非阻塞确认框（QF.confirm 见 app_common.js）：
            // 原生 confirm() 会同步阻塞事件循环，DevTools 会报 “'click' handler took xxx ms”
            if (!(await window.QF.confirm('确定要删除这条记录吗？'))) return;

            try {
                const response = await apiRequest(`/api/llm/${id}`, { method: 'DELETE' });
                const data = await response.json();

                if (data.message) {
                    loadLogs();
                    loadStats();
                }
            } catch (e) {
                QF.toast('删除失败', 'danger');
            }
        }

        function getStatusText(status) {
            const map = {
                'success': '成功',
                'warning': '警告',
                'error': '错误'
            };
            return map[status] || status || '-';
        }

        // escapeHtml / formatTime 由 app_common.js 提供

        // 等公共层认证就绪（QF.onReady 在 /api/user/profile 返回后触发），
        // 确保 QF.isAdmin() 可用后再渲染角色相关内容。
        // 必须无条件挂载 QF.onReady（否则角色未加载时 isAdmin()=false 会误删管理员功能）。
        function initPage() {
            if (window.QF.isAdmin()) loadStats();
            loadLogs();
        }
        window.QF.onReady = initPage;
