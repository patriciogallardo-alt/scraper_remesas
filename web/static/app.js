// ===== State =====
let allData = [];
let sortCol = null;
let sortAsc = true;

// ===== Init =====
document.addEventListener('DOMContentLoaded', () => {
    loadData();
    document.getElementById('btn-scrape').addEventListener('click', triggerScrape);
    document.getElementById('btn-download').addEventListener('click', downloadExcel);
    document.getElementById('filter-agent').addEventListener('change', renderTable);
    document.getElementById('filter-country').addEventListener('change', renderTable);
    document.getElementById('filter-currency').addEventListener('change', renderTable);
});

// ===== API Calls =====
async function loadData() {
    try {
        const resp = await fetch('/api/data');
        const json = await resp.json();
        allData = json.results || [];
        updateMeta(json.metadata);
        populateFilters();
        renderTable();
    } catch (e) {
        console.error('Error cargando datos:', e);
    }
}

async function triggerScrape() {
    const btn = document.getElementById('btn-scrape');
    btn.disabled = true;
    btn.innerHTML = '<span class="loading-spinner" style="width:14px;height:14px;border-width:2px;display:inline-block"></span> Ejecutando...';

    showLoading(true);

    try {
        const resp = await fetch('/api/scrape', { method: 'POST' });
        const json = await resp.json();

        if (json.status === 'ok') {
            showToast(`${json.total_quotes} cotizaciones en ${json.duration}s`, 'success');
            await loadData();
        } else {
            showToast(json.message || 'Error al ejecutar', 'error');
        }
    } catch (e) {
        showToast('Error de conexión', 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '⚡ Ejecutar Scraping';
        showLoading(false);
    }
}

function downloadExcel() {
    window.location.href = '/api/data/download';
}

// ===== Filters =====
function populateFilters() {
    const agents = [...new Set(allData.map(r => r.agente))].sort();
    const countries = [...new Set(allData.map(r => r.pais_destino))].sort();
    const currencies = [...new Set(allData.map(r => r.moneda_destino))].sort();

    fillSelect('filter-agent', agents);
    fillSelect('filter-country', countries);
    fillSelect('filter-currency', currencies);
}

function fillSelect(id, options) {
    const sel = document.getElementById(id);
    const current = sel.value;
    sel.innerHTML = '<option value="">Todos</option>';
    options.forEach(opt => {
        sel.innerHTML += `<option value="${opt}">${opt}</option>`;
    });
    sel.value = current;
}

function getFilteredData() {
    const agent = document.getElementById('filter-agent').value;
    const country = document.getElementById('filter-country').value;
    const currency = document.getElementById('filter-currency').value;

    return allData.filter(r =>
        (!agent || r.agente === agent) &&
        (!country || r.pais_destino === country) &&
        (!currency || r.moneda_destino === currency)
    );
}

// ===== Table Rendering =====
function renderTable() {
    const filtered = getFilteredData();
    const tbody = document.getElementById('table-body');
    const emptyState = document.getElementById('empty-state');
    const tableContainer = document.getElementById('table-container');

    // Update stats
    updateStats(filtered);

    if (!filtered.length) {
        tableContainer.style.display = 'none';
        emptyState.style.display = 'block';
        return;
    }

    tableContainer.style.display = 'block';
    emptyState.style.display = 'none';

    // Sort
    let data = [...filtered];
    if (sortCol !== null) {
        data.sort((a, b) => {
            const keys = ['timestamp', 'agente', 'pais_destino', 'moneda_origen', 'moneda_destino',
                'monto_enviado', 'monto_recibido', 'tasa_de_cambio', 'fee_base', 'fee_impuesto',
                'total_cobrado', 'metodo_recaudacion', 'metodo_dispersion'];
            const key = keys[sortCol];
            let va = a[key], vb = b[key];
            if (typeof va === 'number') return sortAsc ? va - vb : vb - va;
            return sortAsc ? String(va).localeCompare(String(vb)) : String(vb).localeCompare(String(va));
        });
    }

    tbody.innerHTML = data.map(r => `
        <tr>
            <td>${r.timestamp || ''}</td>
            <td><span class="agent-badge ${agentClass(r.agente)}">${r.agente}</span></td>
            <td>${r.pais_destino}</td>
            <td>${r.moneda_origen}</td>
            <td>${r.moneda_destino}</td>
            <td class="num-clp">${fmt(r.monto_enviado)}</td>
            <td class="num-clp">${fmtDec(r.monto_recibido)}</td>
            <td class="num-rate">${fmtRate(r.tasa_de_cambio)}</td>
            <td class="num-fee">${fmt(r.fee_base)}</td>
            <td class="num-fee">${fmt(r.fee_impuesto)}</td>
            <td class="num-total">${fmt(r.total_cobrado)}</td>
            <td>${r.metodo_recaudacion}</td>
            <td>${r.metodo_dispersion}</td>
        </tr>
    `).join('');
}

function sortTable(colIndex) {
    if (sortCol === colIndex) {
        sortAsc = !sortAsc;
    } else {
        sortCol = colIndex;
        sortAsc = true;
    }

    // Update header arrows
    document.querySelectorAll('th').forEach((th, i) => {
        th.classList.toggle('sorted', i === sortCol);
        const arrow = th.querySelector('.sort-arrow');
        if (arrow) arrow.textContent = i === sortCol ? (sortAsc ? '▲' : '▼') : '';
    });

    renderTable();
}

// ===== Stats =====
function updateStats(data) {
    document.getElementById('stat-total').textContent = data.length;

    const agents = new Set(data.map(r => r.agente));
    document.getElementById('stat-agents').textContent = agents.size;

    const countries = new Set(data.map(r => r.pais_destino));
    document.getElementById('stat-countries').textContent = countries.size;

    if (data.length) {
        const bestRate = Math.max(...data.filter(r => r.tasa_de_cambio > 0).map(r => r.tasa_de_cambio));
        document.getElementById('stat-best-rate').textContent = fmtRate(bestRate);
    } else {
        document.getElementById('stat-best-rate').textContent = '-';
    }
}

function updateMeta(meta) {
    const el = document.getElementById('meta-info');
    if (!meta) {
        el.textContent = 'Sin datos';
        return;
    }
    el.textContent = `${meta.timestamp} · ${meta.total_quotes} quotes · ${meta.duration_seconds}s`;
}

// ===== Helpers =====
function agentClass(name) {
    if (name.includes('RIA')) return 'ria';
    if (name.includes('Western') || name.includes('WU')) return 'wu';
    if (name.includes('AFEX')) return 'afex';
    return '';
}

function fmt(n) {
    if (n == null || isNaN(n)) return '-';
    return Math.round(n).toLocaleString('es-CL');
}

function fmtDec(n) {
    if (n == null || isNaN(n)) return '-';
    return Number(n).toLocaleString('es-CL', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtRate(n) {
    if (n == null || isNaN(n) || n === 0) return '-';
    return Number(n).toLocaleString('es-CL', { minimumFractionDigits: 4, maximumFractionDigits: 4 });
}

function showLoading(show) {
    document.getElementById('loading-overlay').style.display = show ? 'flex' : 'none';
}

function showToast(msg, type = 'success') {
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = msg;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 4000);
}
