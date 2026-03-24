// ===== State =====
let allData = [];
let sortCol = null;
let sortAsc = true;

// ===== Init =====
document.addEventListener('DOMContentLoaded', () => {
    loadData();
    document.getElementById('btn-scrape').addEventListener('click', triggerScrape);
    document.getElementById('btn-download').addEventListener('click', downloadExcel);
    document.getElementById('filter-country').addEventListener('change', onCountryChange);
    document.getElementById('filter-currency').addEventListener('change', renderTable);
    window._isReady = true;
});

// ===== Navigation (Tabs) =====
function switchTab(tabId) {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.style.display = 'none');
    
    if (event && event.currentTarget) {
        event.currentTarget.classList.add('active');
    }
    const tab = document.getElementById('tab-' + tabId);
    if (tab) tab.style.display = 'block';

    const groupAgent = document.getElementById('group-filter-agent');
    if (groupAgent) {
        groupAgent.style.display = tabId === 'history' ? 'none' : 'flex';
    }

    if (tabId === 'history') {
        fetchHistory();
    }
}

let historyChartInstance = null;
async function fetchHistory() {
    const country = document.getElementById('filter-country').value;
    const days = document.getElementById('filter-history-days').value;
    const agent = getMsValues('agent').map(v => encodeURIComponent(v)).join(',');
    const catRec = getMsValues('cat-rec').map(v => encodeURIComponent(v)).join(',');
    const catDisp = getMsValues('cat-disp').map(v => encodeURIComponent(v)).join(',');
    
    const emptyState = document.getElementById('history-empty');
    
    if (!country) {
        emptyState.style.display = 'block';
        if (historyChartInstance) { historyChartInstance.destroy(); historyChartInstance = null; }
        return;
    }
    
    emptyState.style.display = 'none';
    document.getElementById('history-loading').style.display = 'block';
    
    try {
        let url = `/api/history?country=${encodeURIComponent(country)}&days=${days}`;
        if (currency) url += `&currency=${encodeURIComponent(currency)}`;
        if (catRec) url += `&catRec=${catRec}`;
        if (catDisp) url += `&catDisp=${catDisp}`;
        // Note: Agent filter is ignored for History per user request (legend is the filter)
        
        const res = await fetch(url);
        if (!res.ok) throw new Error("Fallo la red o Supabase");
        const data = await res.json();
        
        renderHistoryChart(data);
    } catch (err) {
        console.error("Error fetching history:", err);
    } finally {
        document.getElementById('history-loading').style.display = 'none';
    }
}

function renderHistoryChart(data) {
    const ctx = document.getElementById('historyChart').getContext('2d');
    if (historyChartInstance) { historyChartInstance.destroy(); }
    
    if (!data || data.length === 0) {
        // Nada que graficar
        return;
    }
    
    // Agrupar por fecha ("YYYY-MM-DD") y agente
    // Para simplificar, tomaremos el mejor TC (máximo) por agente por día
    const aggregated = {};
    const datesSet = new Set();
    
    data.forEach(r => {
        if (!r.timestamp || !r.agente || !r.tasa_cambio_final) return;
        const dateStr = r.timestamp.split('T')[0];
        datesSet.add(dateStr);
        
        if (!aggregated[dateStr]) aggregated[dateStr] = {};
        if (!aggregated[dateStr][r.agente]) {
            aggregated[dateStr][r.agente] = r.tasa_cambio_final;
        } else {
            // Quedarse con el mejor (más alto) del día para ese proveedor
            if (r.tasa_cambio_final > aggregated[dateStr][r.agente]) {
                aggregated[dateStr][r.agente] = r.tasa_cambio_final;
            }
        }
    });
    
    const labels = Array.from(datesSet).sort();
    
    // Colores y series
    const agCol = {
        'AFEX': '#1F4E79',
        'Western Union': '#FFCC00',
        'RIA': '#f37021'
    };
    
    const agents = Array.from(new Set(data.map(d => d.agente)));
    const datasets = agents.map(ag => {
        const mappedData = labels.map(day => aggregated[day][ag] || null); // null rompe la linea si falta
        return {
            label: ag,
            data: mappedData,
            borderColor: agCol[ag] || '#999',
            backgroundColor: agCol[ag] || '#999',
            borderWidth: 3,
            tension: 0.1,
            pointRadius: 4,
            spanGaps: true // Conectar puntos si falta data en medio
        };
    });
    
    historyChartInstance = new Chart(ctx, {
        type: 'line',
        data: { labels: labels, datasets: datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: { position: 'top' },
                tooltip: { 
                    callbacks: {
                        label: function(context) {
                            let label = context.dataset.label || '';
                            if (label) { label += ': '; }
                            if (context.parsed.y !== null) {
                                label += new Intl.NumberFormat('es-CL', { style: 'currency', currency: 'CLP' }).format(context.parsed.y);
                            }
                            return label;
                        }
                    }
                }
            },
            scales: {
                y: {
                    title: { display: true, text: 'Tasa de Cambio Final (CLP)' },
                    ticks: { callback: function(value) { return value.toLocaleString('es-CL'); } }
                }
            }
        }
    });
}

function onCountryChange() {
    // When country changes, update currency filter options to match
    const country = document.getElementById('filter-country').value;
    if (country) {
        const currencies = [...new Set(
            allData.filter(r => r.pais_destino === country).map(r => r.moneda_destino)
        )].sort();
        fillSelect('filter-currency', currencies);
        
        // Auto-select foreign currency (prefer not USD if available)
        const nonUsd = currencies.filter(c => c !== 'USD');
        if (nonUsd.length > 0) {
            document.getElementById('filter-currency').value = nonUsd[0];
        } else if (currencies.length > 0) {
            document.getElementById('filter-currency').value = currencies[0];
        }
    } else {
        const currencies = [...new Set(allData.map(r => r.moneda_destino))].sort();
        fillSelect('filter-currency', currencies);
        document.getElementById('filter-currency').value = '';
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

    fillSelect('filter-country', countries);
    fillSelect('filter-currency', currencies);
    
    populateMultiFilter('agent', agents);
    populateMultiFilter('cat-rec', catRecaudacion);
    populateMultiFilter('cat-disp', catDispersion);
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
    const agent = getMsValues('agent');
    const country = document.getElementById('filter-country').value;
    const currency = document.getElementById('filter-currency').value;
    const catRec = getMsValues('cat-rec');
    const catDisp = getMsValues('cat-disp');

    return allData.filter(r =>
        r.metodo_recaudacion !== 'N/D' &&
        r.metodo_dispersion !== 'N/D' &&
        (agent.length === 0 || agent.includes(r.agente)) &&
        (!country || r.pais_destino === country) &&
        (!currency || r.moneda_destino === currency) &&
        (catRec.length === 0 || catRec.includes(r.categoria_recaudacion)) &&
        (catDisp.length === 0 || catDisp.includes(r.categoria_dispersion))
    );
}

// ===== Table Rendering =====
function renderTable() {
    const filtered = getFilteredData();
    const tbody = document.getElementById('table-body');
    const emptyState = document.getElementById('empty-state');
    const tableContainer = document.getElementById('table-container');
    const statsGrid = document.getElementById('stats-grid');
    const globalSummary = document.getElementById('global-summary');

    // Show stats only when country filter is active
    const countryFilter = document.getElementById('filter-country').value;

    if (countryFilter) {
        statsGrid.style.display = '';
        if (globalSummary) globalSummary.style.display = 'none';
        updateStats(filtered, countryFilter);
        
        // Auto-refresh history if currently viewing history tab
        const histBtn = document.querySelector('.tab-btn[onclick*="history"]');
        if (histBtn && histBtn.classList.contains('active')) {
            fetchHistory();
        }
    } else {
        statsGrid.style.display = 'none';
        if (globalSummary) globalSummary.style.display = 'block';
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
                'monto_enviado', 'monto_recibido', 'tasa_cambio_normalizada', 'tasa_cambio_final',
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
            <td class="num-rate">${fmtRate(r.tasa_cambio_normalizada)}</td>
            <td class="num-rate">${fmtRate(r.tasa_cambio_final)}</td>
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

// ===== Competitive Stats =====
function updateStats(data, countryFilter) {
    const domTotal = document.getElementById('val-total-quotes');
    domTotal.textContent = data.length;

    const ids = [
        'val-best-tc', 'val-best-norm', 'val-best-fee',
        'sub-best-tc', 'sub-best-norm', 'sub-best-fee',
        'val-afex-tc', 'val-afex-norm', 'val-afex-fee',
        'sub-afex-tc', 'sub-afex-norm', 'sub-afex-fee',
        'val-diff-tc', 'val-diff-norm', 'val-diff-fee'
    ];

    if (!data.length) {
        ids.forEach(id => {
            const el = document.getElementById(id);
            if (el) el.innerHTML = id.startsWith('sub-') ? 'Sin datos' : '-';
        });
        return;
    }

    // Identificar moneda destino principal para comparar
    // Si hay USD, no mezclarlos con PE etc, preferimos filtrar todos a la misma moneda
    // Tomamos la moneda destino del primer registro que no sea USD, o la que haya.
    let targetCurrency = 'USD';
    const nonUsd = data.filter(r => r.moneda_destino !== 'USD');
    if (nonUsd.length > 0) targetCurrency = nonUsd[0].moneda_destino;
    
    // Filtramos para asegurar que comparamos la misma moneda (peras con peras)
    const validData = data.filter(r => r.moneda_destino === targetCurrency);

    if (!validData.length) return;

    // Helper para formatear
    const fRate = (v, c) => `${fmtRate(v)} CLP/${c}`;
    const fFee = (v) => `${fmtDecTwo(v)} CLP`;
    const fMethod = (r, showExtraAgent = true) => {
        if (!r) return 'Sin datos';
        let text = `<span style="color:var(--text-muted)">Recaudación:</span> ${r.categoria_recaudacion || 'N/D'}<br>`;
        text += `<span style="color:var(--text-muted)">Dispersión:</span> ${r.categoria_dispersion || 'N/D'}`;
        
        if (showExtraAgent && r.agente === 'AFEX' && r.metodo_dispersion) {
            const match = r.metodo_dispersion.match(/\((.*?)\)/);
            if (match) {
                text += `<br><span style="color:var(--accent-blue);font-weight:600">Agente: ${match[1]}</span>`;
            }
        }
        return text;
    };
    const getFee = (r) => (r.fee_base || 0) + (r.fee_impuesto || 0);

    // 1. Global Bests
    const bestTc = validData.filter(r => r.tasa_cambio_final > 0).reduce((prev, curr) => curr.tasa_cambio_final < prev.tasa_cambio_final ? curr : prev, {tasa_cambio_final: Infinity});
    const bestNorm = validData.filter(r => r.tasa_cambio_normalizada > 0).reduce((prev, curr) => curr.tasa_cambio_normalizada < prev.tasa_cambio_normalizada ? curr : prev, {tasa_cambio_normalizada: Infinity});
    const bestFee = validData.filter(r => getFee(r) >= 0).reduce((prev, curr) => getFee(curr) < getFee(prev) ? curr : prev, {__fake: true, fee_base: Infinity, fee_impuesto: Infinity});

    // 2. AFEX Bests
    const afexData = validData.filter(r => r.agente.toUpperCase() === 'AFEX' || r.agente.toUpperCase().includes('AFEX'));
    
    const afexTc = afexData.filter(r => r.tasa_cambio_final > 0).reduce((prev, curr) => curr.tasa_cambio_final < prev.tasa_cambio_final ? curr : prev, {tasa_cambio_final: Infinity});
    const afexNorm = afexData.filter(r => r.tasa_cambio_normalizada > 0).reduce((prev, curr) => curr.tasa_cambio_normalizada < prev.tasa_cambio_normalizada ? curr : prev, {tasa_cambio_normalizada: Infinity});
    const afexFee = afexData.filter(r => getFee(r) >= 0).reduce((prev, curr) => getFee(curr) < getFee(prev) ? curr : prev, {__fake: true, fee_base: Infinity, fee_impuesto: Infinity});

    // Populate Global Bests
    document.getElementById('val-best-tc').innerHTML = bestTc.tasa_cambio_final !== Infinity ? fRate(bestTc.tasa_cambio_final, targetCurrency) : '-';
    document.getElementById('sub-best-tc').innerHTML = bestTc.tasa_cambio_final !== Infinity ? `Ofrecido por <strong>${bestTc.agente}</strong><br>` + fMethod(bestTc, false) : '';

    document.getElementById('val-best-norm').innerHTML = bestNorm.tasa_cambio_normalizada !== Infinity ? fRate(bestNorm.tasa_cambio_normalizada, targetCurrency) : '-';
    document.getElementById('sub-best-norm').innerHTML = bestNorm.tasa_cambio_normalizada !== Infinity ? `Ofrecido por <strong>${bestNorm.agente}</strong><br>` + fMethod(bestNorm, false) : '';

    document.getElementById('val-best-fee').innerHTML = !bestFee.__fake ? fFee(getFee(bestFee)) : '-';
    document.getElementById('sub-best-fee').innerHTML = !bestFee.__fake ? `Ofrecido por <strong>${bestFee.agente}</strong><br>` + fMethod(bestFee, false) : '';

    // Populate AFEX Bests
    document.getElementById('val-afex-tc').innerHTML = afexTc.tasa_cambio_final !== Infinity ? fRate(afexTc.tasa_cambio_final, targetCurrency) : '<span style="color:#aaa">N/A</span>';
    document.getElementById('sub-afex-tc').innerHTML = afexTc.tasa_cambio_final !== Infinity ? `Ofrecido por <strong>${afexTc.agente}</strong><br>` + fMethod(afexTc, true) : '';

    document.getElementById('val-afex-norm').innerHTML = afexNorm.tasa_cambio_normalizada !== Infinity ? fRate(afexNorm.tasa_cambio_normalizada, targetCurrency) : '<span style="color:#aaa">N/A</span>';
    document.getElementById('sub-afex-norm').innerHTML = afexNorm.tasa_cambio_normalizada !== Infinity ? `Ofrecido por <strong>${afexNorm.agente}</strong><br>` + fMethod(afexNorm, true) : '';

    document.getElementById('val-afex-fee').innerHTML = !afexFee.__fake ? fFee(getFee(afexFee)) : '<span style="color:#aaa">N/A</span>';
    document.getElementById('sub-afex-fee').innerHTML = !afexFee.__fake ? `Ofrecido por <strong>${afexFee.agente}</strong><br>` + fMethod(afexFee, true) : '';

    // Calculate Differences
    const domDiffTc = document.getElementById('val-diff-tc');
    const domDiffNorm = document.getElementById('val-diff-norm');
    const domDiffFee = document.getElementById('val-diff-fee');

    function renderDiff(dom, afexVal, globalVal, suffix, bestAgentName) {
        const subLabelDom = dom.nextElementSibling;
        
        if (afexVal === Infinity || globalVal === Infinity || isNaN(afexVal) || isNaN(globalVal)) {
            dom.innerHTML = '<span class="val-neutral">-</span>';
            dom.removeAttribute('title');
            if (subLabelDom) subLabelDom.innerText = 'Sin datos';
            return;
        }
        
        const diff = afexVal - globalVal;
        const tt = "Significa respecto al cliente:\n(+) MÁS CARO: AFEX cobra más pesos por la misma divisa.\n(-) MÁS BARATO: AFEX cobra menos pesos por la misma divisa.";
        dom.setAttribute('title', tt);
        
        let valHtml;
        if (Math.abs(diff) < 0.001) {
            valHtml = `<span class="val-negative">0.00 ${suffix}</span>`;
            if (subLabelDom) subLabelDom.innerText = `Somos el mejor mercado`;
        } else if (diff > 0) {
            // AFEX is worse (more expensive) -> Red
            valHtml = `<span class="val-positive">+ ${fmtRate(diff)} ${suffix}</span>`;
            if (subLabelDom) subLabelDom.innerText = `AFEX vs ${bestAgentName}`;
        } else {
            // AFEX is better (cheaper) -> Green
            valHtml = `<span class="val-negative">- ${fmtRate(Math.abs(diff))} ${suffix}</span>`;
            if (subLabelDom) subLabelDom.innerText = `AFEX vs ${bestAgentName}`;
        }
        dom.innerHTML = valHtml;
    }

    renderDiff(domDiffTc, afexTc.tasa_cambio_final, bestTc.tasa_cambio_final, `CLP/${targetCurrency}`, bestTc.agente);
    renderDiff(domDiffNorm, afexNorm.tasa_cambio_normalizada, bestNorm.tasa_cambio_normalizada, `CLP/${targetCurrency}`, bestNorm.agente);
    
    // Fee Diff (Zero decimals)
    const feeAfex = getFee(afexFee);
    const feeBest = getFee(bestFee);
    if (afexFee.__fake || bestFee.__fake) {
        domDiffFee.innerHTML = '-';
        domDiffFee.className = 'comp-value';
    } else {
        const d = feeAfex - feeBest;
        // Positive if AFEX is more expensive (worse), negative if AFEX is cheaper (better)
        const signStr = d > 0 ? '+ ' : (d < 0 ? '- ' : '');
        const cClass = d === 0 ? 'val-neutral' : (d < 0 ? 'val-negative' : 'val-positive');
        domDiffFee.innerHTML = `<span class="${cClass}">${signStr}${fmt(Math.abs(d))} CLP</span><div style="font-size:0.7rem;color:var(--text-muted);margin-top:2px;">vs ${bestFee.agente}</div>`;
    }
}

function updateMeta(meta) {
    if (!meta) return;
    
    // Header timestamp
    document.getElementById('meta-info').textContent = `Actualizado: ${meta.timestamp} (${meta.total_quotes} cot.)`;

    // Global Summary Empty State Variables
    const domQuot = document.getElementById('global-total-quotes');
    const domCoun = document.getElementById('global-total-countries');
    const domAg = document.getElementById('global-total-agents');
    const domUpd = document.getElementById('global-last-update');
    
    if (domQuot) domQuot.innerText = meta.total_quotes || allData.length;
    if (domCoun) {
        const countries = new Set(allData.map(r => r.pais_destino)).size;
        domCoun.innerText = countries;
    }
    if (domAg) {
        const agents = new Set(allData.map(r => r.agente)).size;
        domAg.innerText = agents;
    }
    if (domUpd) {
        try {
            const dt = new Date(meta.timestamp);
            domUpd.innerText = dt.toLocaleString() !== 'Invalid Date' ? dt.toLocaleString() : meta.timestamp;
        } catch(e) {
            domUpd.innerText = meta.timestamp;
        }
    }
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

function fmtDecTwo(val) {
    if (val === undefined || val === null) return '-';
    return Number(val).toLocaleString('es-CL', { minimumFractionDigits: 0, maximumFractionDigits: 2 });
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

// ===== Custom Multi Select Logic =====
window.toggleMs = function(id) {
    document.querySelectorAll('.ms-dropdown').forEach(d => {
        if (d.id !== `dropdown-${id}`) d.classList.remove('show');
    });
    document.getElementById(`dropdown-${id}`).classList.toggle('show');
}

document.addEventListener('click', (e) => {
    if (!e.target.closest('.ms-container')) {
        document.querySelectorAll('.ms-dropdown').forEach(d => d.classList.remove('show'));
    }
});

window.updateMsText = function(id, trigger = true) {
    const container = document.getElementById(`dropdown-${id}`);
    if (!container) return;
    const checked = Array.from(container.querySelectorAll('input:checked')).length;
    const btn = document.querySelector(`#ms-${id} .ms-text`);
    if (checked === 0) {
        btn.innerText = 'Todos';
    } else {
        btn.innerText = `${checked} seleccionado${checked>1?'s':''}`;
    }
    if (trigger && window._isReady) renderTable(); 
}

function getMsValues(id) {
    const container = document.getElementById(`dropdown-${id}`);
    if (!container) return [];
    return Array.from(container.querySelectorAll('input:checked')).map(cb => cb.value);
}

function populateMultiFilter(containerId, dataList) {
    const container = document.getElementById(`dropdown-${containerId}`);
    if (!container) return;
    const options = [...new Set(dataList.filter(v => v !== '-' && v !== '' && v !== 'N/D' && v != null))].sort();
    let html = '';
    options.forEach(opt => {
        html += `<label class="ms-option"><input type="checkbox" value="${opt}" onchange="updateMsText('${containerId}')"> ${opt}</label>`;
    });
    container.innerHTML = html;
    updateMsText(containerId, false);
}
