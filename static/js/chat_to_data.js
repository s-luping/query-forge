// 获取DOM元素
const userQueryEl = document.getElementById('userQuery');
const executeBtn = document.getElementById('executeBtn');
const executeBtnText = document.getElementById('executeBtnText');
const executeSpinner = document.getElementById('executeSpinner');
const generatedSqlEl = document.getElementById('generatedSql');
const resultContainer = document.getElementById('resultContainer');
const errorModal = new bootstrap.Modal(document.getElementById('errorModal'));
const errorMessageEl = document.getElementById('errorMessage');

// 历史记录相关元素
const historyBtn = document.getElementById('historyBtn');
const historyModal = new bootstrap.Modal(document.getElementById('historyModal'));
const historyLoading = document.getElementById('historyLoading');
const historyContent = document.getElementById('historyContent');
const historyEmpty = document.getElementById('historyEmpty');
const historyList = document.getElementById('historyList');
const refreshHistoryBtn = document.getElementById('refreshHistoryBtn');
const prevHistoryBtn = document.getElementById('prevHistoryBtn');
const nextHistoryBtn = document.getElementById('nextHistoryBtn');
const historyPageInfo = document.getElementById('historyPageInfo');

// 评分相关元素
const ratingModal = new bootstrap.Modal(document.getElementById('ratingModal'));
const starBtns = document.querySelectorAll('.star-btn');
const submitRatingBtn = document.getElementById('submitRatingBtn');

// 补充知识相关元素
const knowledgeBtn = document.getElementById('knowledgeBtn');
const knowledgeModal = new bootstrap.Modal(document.getElementById('knowledgeModal'));
const knowledgeLoading = document.getElementById('knowledgeLoading');
const knowledgeContent = document.getElementById('knowledgeContent');
const knowledgeEmpty = document.getElementById('knowledgeEmpty');
const knowledgeList = document.getElementById('knowledgeList');
const prevKnowledgeBtn = document.getElementById('prevKnowledgeBtn');
const nextKnowledgeBtn = document.getElementById('nextKnowledgeBtn');
const knowledgePageInfo = document.getElementById('knowledgePageInfo');
const knowledgeForm = document.getElementById('knowledgeForm');
const viewKnowledgeModal = new bootstrap.Modal(document.getElementById('viewKnowledgeModal'));

let lastResult = null;
let currentPage = 1;
let totalPages = 1;
let selectedRating = 0;
let currentHistoryId = null;
let hasSchema = false;
let knowledgeCurrentPage = 1;
let knowledgeTotalPages = 1;
let editingKnowledgeId = null;
let selectedKnowledgeId = null;


function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(';').shift();
}

function getToken() {
    return getCookie('token') || '';
}

async function checkSchemaStatus() {
    try {
        const response = await fetch('/api/chat-to-sql/check-schema', {
            method: 'GET',
            headers: {
                'Authorization': `Bearer ${getToken()}`
            }
        });
        
        if (response.status === 401) {
            alert('登录已过期，请重新登录');
            parent.window.location.href = '/login';
            return;
        }
        
        if (response.ok) {
            const data = await response.json();
            hasSchema = data.has_schema;
            
            if (!hasSchema) {
                showSchemaWarning();
            } else {
                showSchemaInfo(data);
            }
        }
    } catch (error) {
        console.error('检查Schema状态失败:', error);
    }
}

function showSchemaWarning() {
    const warningHtml = `
        <div class="alert alert-warning alert-dismissible fade show" role="alert">
            <strong>提示：</strong>您还没有维护Schema，请先在【Schema管理】中上传DDL解析表结构，才能使用数据查询功能。
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
    `;
    
    const container = document.querySelector('.container-fluid');
    const firstCard = container.querySelector('.card');
    if (firstCard) {
        firstCard.insertAdjacentHTML('beforebegin', warningHtml);
    }
    
    executeBtn.disabled = true;
    executeBtn.title = '请先维护Schema';
}

function showSchemaInfo(data) {
    const infoHtml = `
        <div class="alert alert-info alert-dismissible fade show" role="alert">
            <strong>Schema状态：</strong>已解析 ${data.table_count} 个表，共 ${data.schema_count} 个字段。
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
    `;
    
    const container = document.querySelector('.container-fluid');
    const firstCard = container.querySelector('.card');
    if (firstCard) {
        firstCard.insertAdjacentHTML('beforebegin', infoHtml);
    }
}


executeBtn.addEventListener('click', async function () {
    if (!hasSchema) {
        showError('您还没有维护Schema，请先在【Schema管理】中上传DDL解析表结构');
        return;
    }
    
    const query = userQueryEl.value.trim();
    if (!query) {
        showError('请输入查询需求');
        return;
    }

    toggleLoadingState(true);

    try {
        const requestBody = {
            query: query
        };
        
        if (selectedKnowledgeId) {
            requestBody.knowledge_id = selectedKnowledgeId;
        }

        const validateResp = await fetch('/api/chat-to-sql/validate', {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${getToken()}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(requestBody)
        });
        
        if (validateResp.status === 401) {
            alert('登录已过期，请重新登录');
            parent.window.location.href = '/login';
            return;
        }

        if (!validateResp.ok) {
            const err = await validateResp.json();
            throw new Error(err.detail || '验证请求失败');
        }

        const validation = await validateResp.json();
        if (!validation.is_valid) {
            showError(validation.error_message || '生成的SQL无效');
            generatedSqlEl.textContent = validation.sql_query || '';
            resultContainer.innerHTML = '';
            toggleExportButton(false);
            toggleLoadingState(false);
            return;
        }

        generatedSqlEl.textContent = validation.sql_query;

        const response = await fetch('/api/chat-to-sql/execute', {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${getToken()}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(requestBody)
        });

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.detail || '执行请求失败');
        }

        const result = await response.json();
        lastResult = result;

        displayResults(result);
    } catch (error) {
        console.error('执行查询失败:', error);
        showError(`执行查询失败: ${error.message}`);
    } finally {
        toggleLoadingState(false);
    }
});

historyBtn.addEventListener('click', function () {
    currentPage = 1;
    loadHistory();
    historyModal.show();
});

refreshHistoryBtn.addEventListener('click', function () {
    loadHistory();
});

prevHistoryBtn.addEventListener('click', function () {
    if (currentPage > 1) {
        currentPage--;
        loadHistory();
    }
});

nextHistoryBtn.addEventListener('click', function () {
    if (currentPage < totalPages) {
        currentPage++;
        loadHistory();
    }
});

starBtns.forEach(btn => {
    btn.addEventListener('click', function () {
        const rating = parseInt(this.getAttribute('data-rating'));
        selectedRating = rating;

        starBtns.forEach((star, index) => {
            if (index < rating) {
                star.classList.remove('btn-outline-warning');
                star.classList.add('btn-warning');
            } else {
                star.classList.remove('btn-warning');
                star.classList.add('btn-outline-warning');
            }
        });

        submitRatingBtn.disabled = false;
    });
});

submitRatingBtn.addEventListener('click', async function () {
    if (selectedRating === 0 || currentHistoryId === null) {
        showError('请选择评分');
        return;
    }

    try {
        const response = await fetch('/api/chat-to-sql/history/rate', {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${getToken()}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                history_id: currentHistoryId,
                rating: selectedRating
            })
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || '评分失败');
        }

        ratingModal.hide();
        loadHistory();

        selectedRating = 0;
        currentHistoryId = null;
        starBtns.forEach(star => {
            star.classList.remove('btn-warning');
            star.classList.add('btn-outline-warning');
        });
        submitRatingBtn.disabled = true;

    } catch (error) {
        console.error('评分失败:', error);
        showError(`评分失败: ${error.message}`);
    }
});

async function loadHistory() {
    historyLoading.classList.remove('d-none');
    historyContent.classList.add('d-none');
    historyEmpty.classList.add('d-none');

    try {
        const limit = 10;
        const offset = (currentPage - 1) * limit;

        const response = await fetch(`/api/chat-to-sql/history?limit=${limit}&offset=${offset}`, {
            method: 'GET',
            headers: {
                'Authorization': `Bearer ${getToken()}`
            }
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || '获取历史记录失败');
        }

        const data = await response.json();

        if (data.total === 0) {
            historyLoading.classList.add('d-none');
            historyEmpty.classList.remove('d-none');
            return;
        }

        totalPages = Math.ceil(data.total / limit);

        historyPageInfo.textContent = `第 ${currentPage} 页，共 ${totalPages} 页`;
        prevHistoryBtn.disabled = currentPage === 1;
        nextHistoryBtn.disabled = currentPage === totalPages;

        displayHistory(data.items);

        historyLoading.classList.add('d-none');
        historyContent.classList.remove('d-none');

    } catch (error) {
        console.error('加载历史记录失败:', error);
        showError(`加载历史记录失败: ${error.message}`);
        historyLoading.classList.add('d-none');
        historyEmpty.classList.remove('d-none');
    }
}

function displayHistory(items) {
    historyList.innerHTML = '';

    items.forEach(item => {
        const historyItem = document.createElement('div');
        historyItem.className = 'list-group-item list-group-item-action';

        const formattedDate = new Date(item.created_at).toLocaleString();

        historyItem.innerHTML = `
            <div class="d-flex justify-content-between">
                <div class="flex-grow-1">
                    <h6 class="mb-1">${item.query}</h6>
                    <p class="mb-1 text-muted small">${item.sql_query.substring(0, 100)}${item.sql_query.length > 100 ? '...' : ''}</p>
                    <div class="d-flex justify-content-between align-items-center">
                        <span class="text-xs text-muted">${formattedDate}</span>
                        <span class="badge ${item.is_valid ? 'bg-success' : 'bg-danger'}">${item.is_valid ? '有效' : '无效'}</span>
                    </div>
                </div>
                <div class="d-flex flex-column align-items-end ms-3">
                    ${item.rating ? `
                        <div class="rating mb-2">
                            ${Array.from({ length: 5 }, (_, i) => `
                                <i class="fas fa-star ${i < item.rating ? 'text-warning' : 'text-muted'}"></i>
                            `).join('')}
                        </div>
                    ` : ''}
                    <div class="btn-group">
                        <button class="btn btn-sm btn-outline-primary use-history-btn" data-query="${item.query}" data-sql="${item.sql_query}">
                            <i class="fas fa-reply me-1"></i>使用
                        </button>
                        ${!item.rating && item.is_valid ? `
                            <button class="btn btn-sm btn-outline-warning rate-history-btn" data-id="${item.id}">
                                <i class="fas fa-star me-1"></i>评分
                            </button>
                        ` : ''}
                    </div>
                </div>
            </div>
        `;

        historyList.appendChild(historyItem);
    });

    document.querySelectorAll('.use-history-btn').forEach(btn => {
        btn.addEventListener('click', function () {
            const query = this.getAttribute('data-query');
            const sql = this.getAttribute('data-sql');

            userQueryEl.value = query;
            generatedSqlEl.textContent = sql;
            historyModal.hide();
        });
    });

    document.querySelectorAll('.rate-history-btn').forEach(btn => {
        btn.addEventListener('click', function () {
            currentHistoryId = parseInt(this.getAttribute('data-id'));
            selectedRating = 0;
            starBtns.forEach(star => {
                star.classList.remove('btn-warning');
                star.classList.add('btn-outline-warning');
            });
            submitRatingBtn.disabled = true;
            ratingModal.show();
        });
    });
}

// 补充知识相关功能
knowledgeBtn.addEventListener('click', function () {
    knowledgeCurrentPage = 1;
    loadKnowledge();
    knowledgeModal.show();
});

prevKnowledgeBtn.addEventListener('click', function () {
    if (knowledgeCurrentPage > 1) {
        knowledgeCurrentPage--;
        loadKnowledge();
    }
});

nextKnowledgeBtn.addEventListener('click', function () {
    if (knowledgeCurrentPage < knowledgeTotalPages) {
        knowledgeCurrentPage++;
        loadKnowledge();
    }
});

async function loadKnowledge() {
    knowledgeLoading.classList.remove('d-none');
    knowledgeContent.classList.add('d-none');
    knowledgeEmpty.classList.add('d-none');

    try {
        const limit = 6;
        const offset = (knowledgeCurrentPage - 1) * limit;

        const response = await fetch(`/api/extra-knowledge?limit=${limit}&offset=${offset}`, {
            method: 'GET',
            headers: {
                'Authorization': `Bearer ${getToken()}`
            }
        });

        if (response.status === 401) {
            alert('登录已过期，请重新登录');
            parent.window.location.href = '/login';
            return;
        }

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || '获取补充知识失败');
        }

        const data = await response.json();

        if (data.total === 0) {
            knowledgeLoading.classList.add('d-none');
            knowledgeEmpty.classList.remove('d-none');
            return;
        }

        knowledgeTotalPages = Math.ceil(data.total / limit);

        knowledgePageInfo.textContent = `第 ${knowledgeCurrentPage} 页，共 ${knowledgeTotalPages} 页`;
        prevKnowledgeBtn.disabled = knowledgeCurrentPage === 1;
        nextKnowledgeBtn.disabled = knowledgeCurrentPage === knowledgeTotalPages;

        displayKnowledge(data.items);

        knowledgeLoading.classList.add('d-none');
        knowledgeContent.classList.remove('d-none');

    } catch (error) {
        console.error('加载补充知识失败:', error);
        showError(`加载补充知识失败: ${error.message}`);
        knowledgeLoading.classList.add('d-none');
        knowledgeEmpty.classList.remove('d-none');
    }
}

function displayKnowledge(items) {
    knowledgeList.innerHTML = '';

    items.forEach(item => {
        const card = document.createElement('div');
        card.className = 'col-md-6 col-lg-4 mb-3';
        
        const title = item.title || '未命名知识';
        const preview = (item.domain_knowledge_section || item.sample_values_section || '').substring(0, 100);
        const isSelected = selectedKnowledgeId === item.id;
        
        card.innerHTML = `
            <div class="card knowledge-card h-100 ${isSelected ? 'selected' : ''}" data-id="${item.id}">
                <div class="card-body">
                    <h6 class="card-title">${title}</h6>
                    <p class="card-text text-muted small">${preview}...</p>
                    <div class="d-flex justify-content-between align-items-center">
                        <small class="text-muted">${item.updated_at || ''}</small>
                        <div class="btn-group">
                            <button class="btn btn-sm ${isSelected ? 'btn-success' : 'btn-outline-success'} use-knowledge-btn" data-id="${item.id}" data-title="${title}">
                                <i class="fas fa-check"></i>
                            </button>
                            <button class="btn btn-sm btn-outline-info view-knowledge-btn" data-id="${item.id}">
                                <i class="fas fa-eye"></i>
                            </button>
                            <button class="btn btn-sm btn-outline-primary edit-knowledge-btn" data-id="${item.id}">
                                <i class="fas fa-edit"></i>
                            </button>
                            <button class="btn btn-sm btn-outline-danger delete-knowledge-btn" data-id="${item.id}">
                                <i class="fas fa-trash"></i>
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        `;

        knowledgeList.appendChild(card);
    });

    document.querySelectorAll('.use-knowledge-btn').forEach(btn => {
        btn.addEventListener('click', function (e) {
            e.stopPropagation();
            const id = parseInt(this.getAttribute('data-id'));
            const title = this.getAttribute('data-title');
            selectKnowledge(id, title);
        });
    });

    document.querySelectorAll('.view-knowledge-btn').forEach(btn => {
        btn.addEventListener('click', function (e) {
            e.stopPropagation();
            const id = parseInt(this.getAttribute('data-id'));
            viewKnowledge(id);
        });
    });

    document.querySelectorAll('.edit-knowledge-btn').forEach(btn => {
        btn.addEventListener('click', function (e) {
            e.stopPropagation();
            const id = parseInt(this.getAttribute('data-id'));
            editKnowledge(id);
        });
    });

    document.querySelectorAll('.delete-knowledge-btn').forEach(btn => {
        btn.addEventListener('click', async function (e) {
            e.stopPropagation();
            const id = parseInt(this.getAttribute('data-id'));
            if (confirm('确定要删除这条知识吗？')) {
                await deleteKnowledge(id);
            }
        });
    });
}

async function viewKnowledge(id) {
    try {
        const response = await fetch(`/api/extra-knowledge/${id}`, {
            method: 'GET',
            headers: {
                'Authorization': `Bearer ${getToken()}`
            }
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || '获取知识详情失败');
        }

        const data = await response.json();

        document.getElementById('viewKnowledgeTitle').textContent = data.title || '未命名知识';
        document.getElementById('viewSampleValues').textContent = data.sample_values_section || '无';
        document.getElementById('viewTableRelations').textContent = data.table_relations_section || '无';
        document.getElementById('viewDomainKnowledge').textContent = data.domain_knowledge_section || '无';
        document.getElementById('viewKnowledgeTime').textContent = `创建时间: ${data.created_at || ''} | 更新时间: ${data.updated_at || ''}`;

        viewKnowledgeModal.show();

    } catch (error) {
        console.error('查看知识详情失败:', error);
        showError(`查看知识详情失败: ${error.message}`);
    }
}

async function editKnowledge(id) {
    try {
        const response = await fetch(`/api/extra-knowledge/${id}`, {
            method: 'GET',
            headers: {
                'Authorization': `Bearer ${getToken()}`
            }
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || '获取知识详情失败');
        }

        const data = await response.json();

        editingKnowledgeId = id;
        document.getElementById('knowledgeId').value = id;
        document.getElementById('knowledgeTitle').value = data.title || '';
        document.getElementById('sampleValuesSection').value = data.sample_values_section || '';
        document.getElementById('tableRelationsSection').value = data.table_relations_section || '';
        document.getElementById('domainKnowledgeSection').value = data.domain_knowledge_section || '';

        document.getElementById('add-tab').click();

    } catch (error) {
        console.error('编辑知识失败:', error);
        showError(`编辑知识失败: ${error.message}`);
    }
}

async function deleteKnowledge(id) {
    try {
        const response = await fetch(`/api/extra-knowledge/${id}`, {
            method: 'DELETE',
            headers: {
                'Authorization': `Bearer ${getToken()}`
            }
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || '删除知识失败');
        }

        loadKnowledge();

    } catch (error) {
        console.error('删除知识失败:', error);
        showError(`删除知识失败: ${error.message}`);
    }
}

function resetKnowledgeForm() {
    editingKnowledgeId = null;
    document.getElementById('knowledgeId').value = '';
    document.getElementById('knowledgeTitle').value = '';
    document.getElementById('sampleValuesSection').value = '';
    document.getElementById('tableRelationsSection').value = '';
    document.getElementById('domainKnowledgeSection').value = '';
}

function selectKnowledge(id, title) {
    selectedKnowledgeId = id;
    document.getElementById('selectedKnowledgeTitle').textContent = title;
    document.getElementById('selectedKnowledgeInfo').classList.remove('d-none');
    knowledgeModal.hide();
    loadKnowledge();
}

function clearSelectedKnowledge() {
    selectedKnowledgeId = null;
    document.getElementById('selectedKnowledgeInfo').classList.add('d-none');
    document.getElementById('selectedKnowledgeTitle').textContent = '';
}

knowledgeForm.addEventListener('submit', async function (e) {
    e.preventDefault();

    const data = {
        title: document.getElementById('knowledgeTitle').value,
        sample_values_section: document.getElementById('sampleValuesSection').value,
        table_relations_section: document.getElementById('tableRelationsSection').value,
        domain_knowledge_section: document.getElementById('domainKnowledgeSection').value
    };

    try {
        let response;
        if (editingKnowledgeId) {
            response = await fetch(`/api/extra-knowledge/${editingKnowledgeId}`, {
                method: 'PUT',
                headers: {
                    'Authorization': `Bearer ${getToken()}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(data)
            });
        } else {
            response = await fetch('/api/extra-knowledge', {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${getToken()}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(data)
            });
        }

        if (response.status === 401) {
            alert('登录已过期，请重新登录');
            parent.window.location.href = '/login';
            return;
        }

        const result = await response.json();

        if (response.ok && result.success) {
            alert(editingKnowledgeId ? '更新成功！' : '创建成功！');
            resetKnowledgeForm();
            document.getElementById('list-tab').click();
            loadKnowledge();
        } else {
            alert('操作失败: ' + (result.detail || result.message || '未知错误'));
        }
    } catch (error) {
        console.error('保存知识失败:', error);
        showError(`保存知识失败: ${error.message}`);
    }
});

function exportToCSV() {
    if (!lastResult || !lastResult.data || lastResult.data.length === 0) {
        showError('没有可导出的数据');
        return;
    }

    const data = lastResult.data;
    const headers = Object.keys(data[0]);

    let csvContent = headers.join(',') + '\n';

    data.forEach(row => {
        const rowValues = headers.map(header => {
            let value = row[header];
            if (typeof value === 'object') {
                value = JSON.stringify(value);
            }
            if (value && (value.toString().includes(',') || value.toString().includes('"') || value.toString().includes('\n'))) {
                value = `"${value.toString().replace(/"/g, '""')}"`;
            }
            return value;
        });
        csvContent += rowValues.join(',') + '\n';
    });

    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `query_results_${new Date().toISOString().slice(0, 10)}.csv`;
    link.style.display = 'none';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
}

function displayResults(data) {
    if (data.total_rows === 0) {
        resultContainer.innerHTML = `
            <div class="alert alert-info text-center">
                <i class="fas fa-info-circle fa-2x mb-2"></i>
                <p class="mb-0">查询未返回任何数据</p>
            </div>
        `;
        toggleExportButton(false);
        return;
    }

    let tableHtml = `
        <div class="data-summary mb-3">
            <div class="d-flex justify-content-between">
                <div class="summary-item">查询结果: <span class="summary-value">${data.total_rows} 条记录</span></div>
                <div class="summary-item">SQL语句: <span class="summary-value">${data.sql_query.substring(0, 50)}...</span></div>
            </div>
        </div>
    `;

    tableHtml += `<div class="table-responsive"><table class="table table-striped table-hover result-table">`;
    if (data.data.length > 0) {
        tableHtml += '<thead><tr>';
        Object.keys(data.data[0]).forEach(key => {
            tableHtml += `<th>${key}</th>`;
        });
        tableHtml += '</tr></thead>';

        tableHtml += '<tbody>';
        data.data.forEach(row => {
            tableHtml += '<tr>';
            Object.values(row).forEach(value => {
                const displayValue = typeof value === 'object' ? JSON.stringify(value) : value;
                tableHtml += `<td>${displayValue}</td>`;
            });
            tableHtml += '</tr>';
        });
        tableHtml += '</tbody>';
    }
    tableHtml += '</table></div>';
    resultContainer.innerHTML = tableHtml;

    toggleExportButton(true);
}

function toggleExportButton(show) {
    const exportBtn = document.getElementById('exportBtn');
    if (exportBtn) {
        exportBtn.style.display = show ? 'inline-block' : 'none';
    }
}

function copySql() {
    const sqlElement = document.getElementById('generatedSql');
    const sqlText = sqlElement.innerText || sqlElement.textContent;

    navigator.clipboard.writeText(sqlText).then(function () {
        const originalText = document.querySelector('.copy-btn').innerText;
        document.querySelector('.copy-btn').innerText = '已复制!';

        setTimeout(() => {
            document.querySelector('.copy-btn').innerText = originalText;
        }, 2000);
    }).catch(function (err) {
        console.error('复制失败: ', err);
        showError('复制失败，请手动选择复制');
    });
}

function exportTable() {
    const table = document.querySelector('#resultContainer .result-table');
    if (!table) {
        showError('当前没有可导出的表格数据');
        return;
    }

    let csv = [];
    const rows = table.querySelectorAll('tr');

    for (let i = 0; i < rows.length; i++) {
        const row = [], cols = rows[i].querySelectorAll('th, td');

        for (let j = 0; j < cols.length; j++) {
            let data = cols[j].innerText;
            data = data.replace(/"/g, '""');
            if (data.includes(',') || data.includes('\n') || data.includes('"')) {
                data = '"' + data + '"';
            }
            row.push(data);
        }

        csv.push(row.join(','));
    }

    const csvString = csv.join('\n');
    const blob = new Blob([csvString], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.setAttribute('href', url);
    link.setAttribute('download', 'query_result_' + new Date().getTime() + '.csv');
    link.style.visibility = 'hidden';

    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

function showError(message) {
    errorMessageEl.textContent = message;
    errorModal.show();
}

function toggleLoadingState(isLoading) {
    if (isLoading) {
        executeBtn.disabled = true;
        executeBtnText.classList.add('d-none');
        executeSpinner.classList.remove('d-none');
    } else {
        executeBtn.disabled = false;
        executeBtnText.classList.remove('d-none');
        executeSpinner.classList.add('d-none');
    }
}

window.addEventListener('load', checkSchemaStatus);
