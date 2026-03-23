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
    document.getElementById('filter-country').addEventListener('change', onCountryChange);
    document.getElementById('filter-currency').addEventListener('change', renderTable);
    document.getElementById('filter-cat-recaudacion').addEventListener('change', renderTable);
    document.getElementById('filter-cat-dispersion').addEventListener('change', renderTable);
});

function onCountryChange() {
    // When country changes, update currency filter options to match
    const country = document.getElementById('filter-country').value;
    if (country) {
        const currencies = [...new Set(
            allData.filter(r => r.pais_destino === country).map(r => r.moneda_destino)
        )].sort();
        fillSelect('filter-currency', currencies);
    } else {
        const currencies = [...new Set(allData.map(r => r.moneda_destino))].sort();
        fillSelect('filter-currency', currencies);
    }
    renderTable();
}

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

        if (json.status === 'started') {
            showToast(json.message || 'Scraping en proceso', 'success');
        } else if (json.status === 'ok') {
            showToast(`${json.total_quotes} cotizaciones en ${json.duration}s`, 'success');
            await loadData();
        } else {
            showToast(json.message || 'Error al ejecutar', 'error');
        }
    } catch (e) {
        showToast('Error de conexión', 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg> Ejecutar Scraping';
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
    const catRecaudacion = [...new Set(allData.map(r => r.categoria_recaudacion).filter(Boolean))].sort();
    const catDispersion = [...new Set(allData.map(r => r.categoria_dispersion).filter(Boolean))].sort();

    fillSelect('filter-agent', agents);
    fillSelect('filter-country', countries);
    fillSelect('filter-currency', currencies);
    fillSelect('filter-cat-recaudacion', catRecaudacion);
    fillSelect('filter-cat-dispersion', catDispersion);
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
    const catRec = document.getElementById('filter-cat-recaudacion').value;
    const catDisp = document.getElementById('filter-cat-dispersion').value;

    return allData.filter(r =>
        r.metodo_recaudacion !== 'N/D' &&
        r.metodo_dispersion !== 'N/D' &&
        (!agent || r.agente === agent) &&
        (!country || r.pais_destino === country) &&
        (!currency || r.moneda_destino === currency) &&
        (!catRec || r.categoria_recaudacion === catRec) &&
        (!catDisp || r.categoria_dispersion === catDisp)
    );
}

// ===== Table Rendering =====
function renderTable() {
    const filtered = getFilteredData();
    const tbody = document.getElementById('table-body');
    const emptyState = document.getElementById('empty-state');
    const tableContainer = document.getElementById('table-container');
    const statsGrid = document.getElementById('stats-grid');

    // Show stats only when country filter is active
    const countryFilter = document.getElementById('filter-country').value;

    if (countryFilter) {
        statsGrid.style.display = '';
        updateStats(filtered, countryFilter);
    } else {
        statsGrid.style.display = 'none';
    }

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
            const keys = ['agente', 'pais_destino', 'moneda_origen', 'moneda_destino',
                'categoria_recaudacion', 'categoria_dispersion',
                'monto_enviado', 'monto_recibido', 'tasa_de_cambio', 'tasa_cambio_normalizada',
                'fee_base', 'fee_impuesto', 'total_cobrado', 'metodo_recaudacion', 'metodo_dispersion', 'timestamp'];
            const key = keys[sortCol];
            let va = a[key], vb = b[key];
            if (typeof va === 'number') return sortAsc ? va - vb : vb - va;
            return sortAsc ? String(va).localeCompare(String(vb)) : String(vb).localeCompare(String(va));
        });
    }

    tbody.innerHTML = data.map(r => `
        <tr>
            <td><span class="agent-badge ${agentClass(r.agente)}">${r.agente}</span></td>
            <td>${r.pais_destino}</td>
            <td>${r.moneda_origen}</td>
            <td>${r.moneda_destino}</td>
            <td><span class="cat-badge" data-tooltip="${getCatTooltip(r.categoria_recaudacion)}">${r.categoria_recaudacion || '-'}</span></td>
            <td><span class="cat-badge" data-tooltip="${getCatTooltip(r.categoria_dispersion)}">${r.categoria_dispersion || '-'}</span></td>
            <td class="num-clp">${fmt(r.monto_enviado)}</td>
            <td class="num-clp">${fmtDec(r.monto_recibido)}</td>
            <td class="num-rate">${fmtRate(r.tasa_de_cambio)}</td>
            <td class="num-rate">${fmtRate(r.tasa_cambio_normalizada)}</td>
            <td class="num-fee">${fmt(r.fee_base)}</td>
            <td class="num-fee">${fmt(r.fee_impuesto)}</td>
            <td class="num-total">${fmt(r.total_cobrado)}</td>
            <td>${r.metodo_recaudacion}</td>
            <td>${r.metodo_dispersion}</td>
            <td>${r.timestamp || ''}</td>
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

    document.querySelectorAll('th').forEach((th, i) => {
        th.classList.toggle('sorted', i === sortCol);
        const arrow = th.querySelector('.sort-arrow');
        if (arrow) arrow.textContent = i === sortCol ? (sortAsc ? '▲' : '▼') : '';
    });

    renderTable();
}

// ===== Stats =====
function updateStats(data, countryFilter) {
    const domTotal = document.getElementById('stat-total');
    const domBestTC = document.getElementById('stat-best-tc');
    const domBestTCUSD = document.getElementById('stat-best-tc-usd');
    const domTCSublabel = document.getElementById('stat-tc-sublabel');
    const cardUSD = document.getElementById('stat-card-usd');

    domTotal.textContent = data.length;

    if (!data.length) {
        domBestTC.innerHTML = '-';
        domBestTCUSD.innerHTML = '-';
        cardUSD.style.display = 'none';
        domTCSublabel.textContent = 'Moneda local';
        return;
    }

    // Get all non-USD currencies for this country (i.e. local currencies)
    const localQuotes = data.filter(r => r.moneda_destino !== 'USD' && r.tasa_cambio_final > 0);
    const usdQuotes = data.filter(r => r.moneda_destino === 'USD' && r.tasa_cambio_final > 0);

    // Mejor TC Final - Local currency (lowest tasa_cambio_final = best for the sender)
    if (localQuotes.length > 0) {
        const bestLocal = localQuotes.reduce((prev, curr) =>
            curr.tasa_cambio_final < prev.tasa_cambio_final ? curr : prev
        );
        const localCurrency = bestLocal.moneda_destino;
        domTCSublabel.textContent = `Dispersión en ${localCurrency}`;
        domBestTC.innerHTML = `<strong>${bestLocal.agente}</strong><br><span style="font-size:0.8rem;color:var(--accent-green)">${fmtRate(bestLocal.tasa_cambio_final)} CLP/${localCurrency}</span>`;
    } else {
        domTCSublabel.textContent = 'Moneda local';
        domBestTC.innerHTML = '<span style="color:var(--text-muted)">Sin datos</span>';
    }

    // Mejor TC Final - USD (conditional: only show if USD quotes exist for this country)
    if (usdQuotes.length > 0) {
        const bestUSD = usdQuotes.reduce((prev, curr) =>
            curr.tasa_cambio_final < prev.tasa_cambio_final ? curr : prev
        );
        cardUSD.style.display = '';
        domBestTCUSD.innerHTML = `<strong>${bestUSD.agente}</strong><br><span style="font-size:0.8rem;color:var(--accent-blue-light)">${fmtRate(bestUSD.tasa_cambio_final)} CLP/USD</span>`;
    } else {
        cardUSD.style.display = 'none';
        domBestTCUSD.innerHTML = '-';
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
function getCatTooltip(cat) {
    if (!cat || cat === '-' || cat === 'N/D') return 'Sin información específica';

    const tooltips = {
        'Tarjeta de Débito': 'Pago mediante tarjeta de débito bancaria vinculada a una cuenta\n(Incluye Webpay, Redcompra, Visa/MC Débito).',
        'Tarjeta de Crédito': 'Pago con tarjeta de crédito de cupo rotativo. Suele implicar comisiones más altas\n(Incluye Visa/MC Crédito).',
        'Efectivo': 'El cliente acude a una sucursal, ventanilla o agente físico\ncon dinero en efectivo para pagar el envío.',
        'Pago Online': 'Pago a través de un portal web de recaudación externa\n(Ej. Servipag, Sencillito, Multicaja).',
        'Transferencia Bancaria': 'El cliente transfiere dinero directamente desde su cuenta bancaria\na la cuenta de la empresa remesadora (Ej. Khipu).',
        'Billetera Digital': 'El dinero llega directo a una app móvil o e-wallet del destinatario\n(Ej. Yape, Nequi, Plin, Moncash).',
        'Depósito Bancario': 'El dinero se abona directamente en la cuenta bancaria\ntradicional del destinatario (Ej. Pix, CBU, Cuenta Rut).',
        'Retiro en Efectivo': 'El destinatario debe acudir físicamente a una agencia,\nsucursal o ventanilla en destino para recoger los billetes.'
    };

    return tooltips[cat] || 'Categoría de método de pago o retiro';
}

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

// ===== Table Drag-to-Scroll & Scroll Shadows =====
document.addEventListener('DOMContentLoaded', () => {
    const tableScroll = document.querySelector('.table-scroll');
    const tableContainer = document.getElementById('table-container');
    if (!tableScroll || !tableContainer) return;

    // Scroll shadow indicators
    function updateScrollShadows() {
        const { scrollLeft, scrollWidth, clientWidth } = tableScroll;
        tableContainer.classList.toggle('scroll-left', scrollLeft > 4);
        tableContainer.classList.toggle('scroll-right', scrollLeft < scrollWidth - clientWidth - 4);
    }

    tableScroll.addEventListener('scroll', updateScrollShadows);
    new ResizeObserver(updateScrollShadows).observe(tableScroll);
    setTimeout(updateScrollShadows, 200);

    // Drag to scroll
    let isDragging = false;
    let startX = 0;
    let scrollStart = 0;

    tableScroll.addEventListener('mousedown', (e) => {
        if (e.target.closest('th, a, button, select')) return;
        isDragging = true;
        startX = e.pageX;
        scrollStart = tableScroll.scrollLeft;
        tableScroll.style.userSelect = 'none';
    });

    window.addEventListener('mousemove', (e) => {
        if (!isDragging) return;
        const dx = e.pageX - startX;
        tableScroll.scrollLeft = scrollStart - dx;
    });

    window.addEventListener('mouseup', () => {
        isDragging = false;
        tableScroll.style.userSelect = '';
    });
});
