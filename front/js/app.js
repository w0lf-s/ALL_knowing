const state = {
    tab: 'dashboard',
    leads: [],
    company: { query: '', dossier: null, searching: false, progressPct: 0, progressStep: '' },
    linkedin: { name: '', company: '', role: '', location: '', email: '', phone: '', url: '', profiles: [], candidateUrls: [], candidates: [], searching: false, searched: false, matchesOpen: true, progressPct: 0, progressStep: '' },
    reports: [],
    bookmarks: [],
};

let activeLeadInvestigation = {
    leadId: null,
    controller: null,
};

let activeLinkedinScrape = {
    source: null,
    controller: null,
    stopped: false,
};

let activePeopleSearch = {
    controller: null,
    stopped: false,
};

function $(id) { return document.getElementById(id); }
function esc(v) {
    return String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function val(v, fallback = '-') {
    if (v === null || v === undefined || v === '') return fallback;
    return esc(v);
}
function currencySymbol(code) {
    const c = String(code || 'USD').toUpperCase();
    if (c === 'INR') return '₹';
    if (c === 'EUR') return '€';
    if (c === 'GBP') return '£';
    if (c === 'JPY' || c === 'CNY') return '¥';
    if (c === 'KRW') return '₩';
    if (c === 'AUD') return 'A$';
    if (c === 'CAD') return 'C$';
    if (c === 'HKD') return 'HK$';
    return '$';
}
function currencyCode(dossier) {
    const overview = (dossier && dossier.overview) || {};
    const resolved = (dossier && dossier.resolved) || {};
    if (overview.currency) return overview.currency;
    const t = String(resolved.ticker || '').toUpperCase();
    if (/\.(NS|BO|NSE|BSE)$/.test(t)) return 'INR';
    return 'USD';
}
function money(n, code) {
    const x = Number(n);
    const s = currencySymbol(code);
    if (!Number.isFinite(x)) return esc(n);
    if (x >= 1e12) return s + (x / 1e12).toFixed(1) + 'T';
    if (x >= 1e9) return s + (x / 1e9).toFixed(1) + 'B';
    if (x >= 1e6) return s + (x / 1e6).toFixed(1) + 'M';
    return s + Math.round(x).toLocaleString();
}
function price(n, code) {
    const x = Number(n);
    const s = currencySymbol(code);
    if (!Number.isFinite(x)) return esc(n);
    return s + x.toLocaleString(undefined, { maximumFractionDigits: 2 });
}
function fmtNum(n, digits) {
    const x = Number(n);
    if (!Number.isFinite(x)) return String(n ?? '');
    return x.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: 0 });
}
function showError(el, msg) {
    el.innerHTML = msg ? `<div class="error">${esc(msg)}</div>` : '';
}

function peopleSearchError(msg) {
    const raw = String(msg || '');
    const low = raw.toLowerCase();
    if (/navigating to|waiting until|timeout \d+ms exceeded|={5,}|net::err/.test(low)) {
        return 'LinkedIn took too long to load. Try again.';
    }
    return raw;
}
function showCompanyError(msg) {
    const el = $('company-error');
    if (!msg) { el.innerHTML = ''; return; }
    const marker = 'Did you mean ';
    const idx = msg.indexOf(marker);
    if (idx === -1) {
        showError(el, msg);
        return;
    }
    const names = [...msg.slice(idx + marker.length).matchAll(/"([^"]+)"/g)].map(m => m[1]);
    if (!names.length) {
        showError(el, msg);
        return;
    }
    const buttons = names.map(n => `<button type="button" class="suggest-link" data-q="${esc(n)}">"${esc(n)}"</button>`).join(',');
    el.innerHTML = `<div class="error">${esc(msg.slice(0, idx))}${esc(marker)}${buttons}</div>`;
    el.querySelectorAll('.suggest-link').forEach(btn => {
        btn.addEventListener('click', () => {
            $('company-query').value = btn.dataset.q;
            $('company-form').requestSubmit();
        });
    });
}
function setLoading(id, on, text) {
    const el = $(id);
    if (!el) return;
    el.classList.toggle('show', !!on);
    if (text) {
        const span = el.querySelector('span');
        if (span) span.textContent = text;
    }
}
function saveState() {
    try {
        const snapshot = {
            tab: state.tab,
            company: state.company,
            linkedin: {
                name: '',
                company: '',
                role: '',
                location: '',
                email: '',
                phone: '',
                url: '',
                profiles: [],
                candidateUrls: [],
                candidates: [],
                searched: false,
            },
            reports: state.reports,
            bookmarks: state.bookmarks || [],
            leads: state.leads.map(lead => ({
                id: lead.id,
                email: lead.email,
                parsed: lead.parsed,
                from_sample_cookie: lead.from_sample_cookie,
                result: lead.result,
                error: lead.error,
                viewOpen: !!lead.viewOpen,
                newsLookedUp: !!lead.newsLookedUp,
                investigating: false,
            })),
        };
        sessionStorage.setItem('zuntraFrontUi', JSON.stringify(snapshot));
        persistWorkspace(snapshot);
    } catch (_) {}
}
function persistWorkspace(snapshot) {
    if (persistWorkspace._timer) clearTimeout(persistWorkspace._timer);
    persistWorkspace._timer = setTimeout(() => {
        const li = snapshot.linkedin || {};
        fetch('/api/workspace', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                leads: snapshot.leads || [],
                bookmarks: snapshot.bookmarks || [],
                linkedin: {
                    name: li.name || '',
                    company: li.company || '',
                    role: li.role || '',
                    location: li.location || '',
                    email: li.email || '',
                    phone: li.phone || '',
                    url: li.url || '',
                    profiles: li.profiles || [],
                    candidateUrls: li.candidateUrls || [],
                    candidates: li.candidates || [],
                    searched: !!li.searched,
                },
            }),
        }).catch(() => {});
    }, 300);
}
function loadState() {
    try {
        const raw = sessionStorage.getItem('zuntraFrontUi');
        if (!raw) return;
        const parsed = JSON.parse(raw);
        if (parsed.leads) {
            state.leads = parsed.leads.map(lead => ({
                ...lead,
                investigating: false,
                newsLookedUp: !!lead.newsLookedUp,
                newsLoading: false,
                progressPct: 0,
                progressStep: '',
            }));
        }
        if (parsed.company) {
            state.company = parsed.company;
            state.company.searching = false;
            state.company.progressPct = 0;
            state.company.progressStep = '';
        }
        if (parsed.tab) state.tab = parsed.tab === 'linkedin' ? 'people' : parsed.tab;
        if (parsed.reports) state.reports = parsed.reports;
        if (Array.isArray(parsed.bookmarks)) state.bookmarks = parsed.bookmarks;
    } catch (_) {}
}
function applyWorkspace(data) {
    if (!data) return;
    if (Array.isArray(data.bookmarks) && data.bookmarks.length) state.bookmarks = data.bookmarks;
    if (Array.isArray(data.leads)) {
        state.leads = data.leads.map(lead => ({
            ...lead,
            investigating: false,
            newsLookedUp: !!lead.newsLookedUp,
            newsLoading: false,
            progressPct: 0,
            progressStep: '',
        }));
    }
}
async function loadWorkspace() {
    loadState();
    try {
        const res = await fetch('/api/workspace');
        const data = await res.json();
        if (!data || !data.ok) return;
        if (Array.isArray(data.bookmarks) && data.bookmarks.length) state.bookmarks = data.bookmarks;
        else if ((state.bookmarks || []).length) {
            (state.bookmarks || []).forEach(k => {
                fetch('/api/bookmarks', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ key: k }),
                }).catch(() => {});
            });
        }
        const remoteLeads = Array.isArray(data.leads) ? data.leads : [];
        if (remoteLeads.length) applyWorkspace({ ...data, bookmarks: state.bookmarks });
        queueSaveState();
    } catch (_) {
        queueSaveState();
    }
}
function queueSaveState() {
    if (queueSaveState._timer) clearTimeout(queueSaveState._timer);
    queueSaveState._timer = setTimeout(saveState, 0);
}
function uid() {
    return 'lead_' + Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
}

function syncCompanySearchUi() {
    if (!state.company.searching) return;
    setLoading('company-loading', true, state.company.progressStep || 'Fetching company data...');
    if ($('company-progress')) $('company-progress').style.display = 'block';
    if ($('company-progress-fill')) $('company-progress-fill').style.width = (state.company.progressPct || 0) + '%';
}

function setPeopleActionButton(searching) {
    const btn = $('people-btn');
    if (!btn) return;
    btn.disabled = false;
    btn.textContent = searching ? 'Cancel' : 'Search';
    btn.classList.toggle('people-btn-cancel', !!searching);
}

function syncLinkedinSearchUi() {
    if (!state.linkedin.searching) return;
    setPeopleActionButton(true);
    applyPeopleSearchProgress(state.linkedin.progressPct || 0, state.linkedin.progressStep || 'Searching people...');
}

function applyPeopleSearchProgress(pct, text) {
    const n = Number(pct) || 0;
    const step = String(text || '').trim();
    state.linkedin.progressPct = n;
    if (step) state.linkedin.progressStep = step;
    setLoading('people-loading', true, state.linkedin.progressStep || 'Searching people...');
    if ($('people-progress')) $('people-progress').style.display = 'block';
    if ($('people-progress-fill')) $('people-progress-fill').style.width = n + '%';
    if ($('people-step') && state.linkedin.progressStep) $('people-step').textContent = state.linkedin.progressStep;
}

function switchTab(tab) {
    state.tab = tab;
    document.querySelectorAll('nav.tabs button').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tab === tab);
    });
    document.querySelectorAll('.panel').forEach(panel => {
        panel.classList.toggle('active', panel.id === `panel-${tab}`);
    });
    if (!state.company.searching) {
        setLoading('company-loading', false);
        if ($('company-progress')) $('company-progress').style.display = 'none';
        if ($('company-progress-fill')) $('company-progress-fill').style.width = '0%';
    }
    if (!state.linkedin.searching) {
        setPeopleActionButton(false);
        setLoading('people-loading', false);
        if ($('people-progress')) $('people-progress').style.display = 'none';
        if ($('people-progress-fill')) $('people-progress-fill').style.width = '0%';
    }
    history.replaceState(null, '', `#${tab}`);
    saveState();
    renderAll();
    if (state.company.searching && tab === 'company') syncCompanySearchUi();
    if (state.linkedin.searching && tab === 'people') syncLinkedinSearchUi();
}

async function postJson(url, body, signal) {
    const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal,
    });
    const data = await res.json().catch(() => ({ ok: false, error: 'Invalid response' }));
    if (!res.ok || data.ok === false) throw new Error(data.error || `Request failed (${res.status})`);
    return data;
}

function companyKey(c) {
    return String((c && (c.query || ((c.resolved || {}).ticker) || ((c.resolved || {}).name))) || '').toLowerCase().trim();
}

function leadCompanyRecord(lead) {
    if (lead && lead.result && lead.result.company) return lead.result.company;
    const name = (lead && lead.parsed && lead.parsed.company) || '';
    if (!name) return null;
    return { query: name, resolved: { name }, overview: {}, financials: {}, filings: [] };
}

function leadCompanyKey(lead) {
    const rec = leadCompanyRecord(lead);
    return rec ? companyKey(rec) : '';
}

function isBookmarked(c) {
    const key = companyKey(c);
    return !!key && (state.bookmarks || []).includes(key);
}

function dashboardCompanies() {
    const byKey = new Map();
    (state.reports || []).forEach(r => {
        const k = companyKey(r);
        if (k) byKey.set(k, r);
    });
    (state.leads || []).forEach(lead => {
        const rec = leadCompanyRecord(lead);
        if (!rec || !isBookmarked(rec)) return;
        const k = companyKey(rec);
        if (!k) return;
        const existing = byKey.get(k);
        if (!existing || (hasFinancialData(rec.financials) && !hasFinancialData(existing.financials))) {
            byKey.set(k, rec);
        }
    });
    return [...byKey.values()];
}

function bookmarkButton(key, on) {
    return `<button type="button" class="bookmark-btn${on ? ' active' : ''}" data-key="${esc(key)}" aria-label="Bookmark">
                    <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
                        <path d="M6 3.75h12A1.25 1.25 0 0 1 19.25 5v16.1l-7.25-3.9-7.25 3.9V5A1.25 1.25 0 0 1 6 3.75z" fill="${on ? 'currentColor' : 'none'}" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/>
                    </svg>
                </button>`;
}

function bindBookmarkButtons(root) {
    if (!root) return;
    root.querySelectorAll('.bookmark-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            toggleBookmark(btn.dataset.key);
        });
    });
}

function toggleBookmark(key) {
    if (!key) return;
    const cur = state.bookmarks || [];
    const adding = !cur.includes(key);
    state.bookmarks = adding ? cur.concat(key) : cur.filter(k => k !== key);
    fetch('/api/bookmarks', {
        method: adding ? 'POST' : 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key }),
    }).then(async res => {
        const data = await res.json().catch(() => ({}));
        if (data && data.ok && Array.isArray(data.bookmarks)) {
            if (adding) {
                const merged = new Set([...(data.bookmarks || []), key]);
                state.bookmarks = [...merged];
            } else {
                state.bookmarks = (data.bookmarks || []).filter(k => k !== key);
            }
        }
        renderDashboard();
        renderLeadList();
        renderCompanyPanel();
        refreshStats();
    }).catch(() => {});
    saveState();
    renderDashboard();
    renderLeadList();
    renderCompanyPanel();
    if (adding) refreshBookmarkedCompanies();
}

function refreshStats() {
    if ($('statTotal')) $('statTotal').textContent = String(dashboardCompanies().length);
    if ($('statBookmarks')) $('statBookmarks').textContent = String((state.bookmarks || []).length);
}

function isErrorArticle(a) {
    const t = String(a.title || '').trim().toLowerCase();
    if (/^(?:\d{3}\s*(?:error|not found|forbidden|unauthorized)|access denied|just a moment|attention required|please wait|service unavailable|error|forbidden)$/.test(t)) return true;
    if (/^\d{3}\s+error\b/.test(t)) return true;
    const blob = `${a.title || ''} ${a.content || ''} ${a.summary || ''}`.toLowerCase();
    const hits = ['the request could not be satisfied', 'request blocked', 'generated by cloudfront', '403 error', '404 error']
        .filter(p => blob.includes(p)).length;
    return hits >= 2 || (hits >= 1 && blob.split(/\s+/).length < 90);
}

function hasFinancialData(financials) {
    const skip = new Set(['highlights', 'via', 'metrics_raw']);
    return Object.entries(financials || {}).some(([k, v]) => !skip.has(k) && v !== null && v !== undefined && v !== '');
}

function mergeReports(reports) {
    if (!Array.isArray(reports)) return;
    for (const rec of reports) {
        const k = companyKey(rec);
        if (!k) continue;
        const idx = (state.reports || []).findIndex(r => companyKey(r) === k);
        if (idx >= 0) state.reports[idx] = rec;
        else {
            state.reports = state.reports || [];
            state.reports.unshift(rec);
        }
    }
}

let bookmarkPollTimer = null;
function pollBookmarkRefresh(count) {
    if (bookmarkPollTimer) clearTimeout(bookmarkPollTimer);
    let tries = 0;
    const max = Math.min(12, 2 + Number(count || 1) * 3);
    function tick() {
        tries += 1;
        loadReports().then(() => {
            if (tries < max) bookmarkPollTimer = setTimeout(tick, 15000);
        });
    }
    bookmarkPollTimer = setTimeout(tick, 12000);
}

async function refreshBookmarkedCompanies() {
    const queries = (state.bookmarks || []).filter(Boolean);
    if (!queries.length) return;
    try {
        const data = await postJson('/api/company/refresh', { queries });
        if (data.ok && Array.isArray(data.reports) && data.reports.length) {
            mergeReports(data.reports);
            saveState();
            renderDashboard();
        }
        if (data.refreshing && data.refreshing.length) pollBookmarkRefresh(data.refreshing.length);
    } catch (_) {}
}

async function loadReports() {
    try {
        const res = await fetch('/api/reports');
        const data = await res.json();
        if (data.ok && Array.isArray(data.reports) && data.reports.length) {
            state.reports = data.reports;
            saveState();
        }
    } catch (_) {}
    renderDashboard();
}

async function loadStats() {
    refreshStats();
}

function dashboardCardHtml(c) {
    const resolved = c.resolved || {};
    const overview = c.overview || {};
    const financials = c.financials || {};
    const name = resolved.name || c.query || 'Unknown';
    const ticker = resolved.ticker || '';
    const industry = overview.industry || overview.sector || 'Unknown Industry';
    const desc = overview.short_description || overview.description || '';
    const summary = desc.length > 150 ? desc.slice(0, 150) + '...' : desc;
    const mc = financials.market_cap ? money(financials.market_cap, currencyCode(c)) : '—';
    const key = companyKey(c);
    const on = isBookmarked(c);
    const metrics = on ? `
            <div class="card-metrics">
                <div>Market Cap<span>${mc}</span></div>
                <div>Filings<span>${(c.filings || []).length}</span></div>
            </div>` : '';
    return `
        <div class="card clickable" data-key="${esc(key)}">
            <div class="card-header">
                <div>
                    <div class="card-title">${esc(name)}${ticker ? `<span class="ticker">${esc(ticker)}</span>` : ''}</div>
                    <div class="industry">${esc(industry)}</div>
                </div>
                ${bookmarkButton(key, on)}
            </div>
            <p class="card-summary">${esc(summary)}</p>
            ${metrics}
        </div>`;
}

function renderDashboard() {
    const grid = $('grid');
    const empty = $('emptyState');
    const q = (($('searchInput') && $('searchInput').value) || '').toLowerCase().trim();
    let list = dashboardCompanies();
    if (q) {
        list = list.filter(c => {
            const name = ((c.resolved || {}).name || c.query || '').toLowerCase();
            const ind = ((c.overview || {}).industry || '').toLowerCase();
            return name.includes(q) || ind.includes(q);
        });
    }
    refreshStats();
    if (!list.length) {
        grid.innerHTML = '';
        empty.style.display = 'block';
        return;
    }
    empty.style.display = 'none';
    const pinned = list.filter(isBookmarked);
    const rest = list.filter(c => !isBookmarked(c));
    let html = pinned.map(dashboardCardHtml).join('');
    if (pinned.length && rest.length) html += '<hr class="grid-split">';
    html += rest.map(dashboardCardHtml).join('');
    grid.innerHTML = html;
    bindBookmarkButtons(grid);
    grid.querySelectorAll('.card.clickable').forEach(card => {
        card.addEventListener('click', () => {
            const match = dashboardCompanies().find(r => companyKey(r) === card.dataset.key);
            if (match) openDetail(match);
        });
    });
}

function filterCards() {
    renderDashboard();
}

function factsFromText(text) {
    const t = String(text || '');
    const out = {};
    const hq = t.match(/headquartered in ([A-Z][A-Za-z .'-]+?)(?:\s+and\s|\s*,|\.|$)/i);
    if (hq) out.hq = hq[1].trim();
    const nations = [
        [/indian/i, 'India'],
        [/american/i, 'United States'],
        [/british/i, 'United Kingdom'],
        [/japanese/i, 'Japan'],
        [/chinese/i, 'China'],
        [/german/i, 'Germany'],
        [/french/i, 'France'],
        [/korean/i, 'South Korea'],
    ];
    for (const [re, name] of nations) {
        if (re.test(t)) { out.country = name; break; }
    }
    return out;
}

function openDetail(data) {
    const resolved = data.resolved || {};
    const overview = data.overview || {};
    const financials = data.financials || {};
    const cur = currencyCode(data);
    const facts = factsFromText(overview.description || overview.short_description || '');
    $('detailName').textContent = resolved.name || data.query || 'Unknown';
    $('detailTicker').textContent = resolved.ticker || '';
    $('detailSummary').textContent = overview.description || overview.short_description || 'No summary available.';
    $('detailIndustry').textContent = overview.industry || overview.sector || overview.short_description || 'N/A';
    $('detailMarketCap').textContent = financials.market_cap ? money(financials.market_cap, cur) : 'N/A';
    $('detailHigh').textContent = financials.week_52_high ? price(financials.week_52_high, cur) : 'N/A';
    $('detailLow').textContent = financials.week_52_low ? price(financials.week_52_low, cur) : 'N/A';
    $('detailEmployees').textContent = overview.employees || 'N/A';
    const hq = overview.headquarters || overview.city || facts.hq;
    const country = overview.country || facts.country;
    $('detailHQ').textContent = [hq, country].filter(Boolean).join(', ') || 'N/A';

    const webEl = $('detailWebsite');
    if (overview.website) {
        webEl.innerHTML = `<a class="link" href="${esc(overview.website)}" target="_blank">Visit</a>`;
    } else if (overview.wikipedia_url) {
        webEl.innerHTML = `<a class="link" href="${esc(overview.wikipedia_url)}" target="_blank">Wikipedia</a>`;
    } else {
        webEl.textContent = 'N/A';
    }

    const bars = [];
    if (hasFinancialData(financials)) {
        const pe = Number(financials.pe_ratio);
        if (Number.isFinite(pe) && pe !== 0) {
            bars.push({
                label: 'P/E Ratio',
                text: fmtNum(pe, 2),
                width: Math.min(100, Math.max(0, (Math.abs(pe) / 40) * 100)),
                hint: 'Price ÷ earnings',
                ticks: ['0 cheap', '20 typical', '40 expensive'],
            });
        }
        const beta = Number(financials.beta);
        if (Number.isFinite(beta) && beta !== 0) {
            bars.push({
                label: 'Beta',
                text: fmtNum(beta, 2),
                width: Math.min(100, Math.max(0, (Math.abs(beta) / 2) * 100)),
                hint: 'Vs market (1.0 = same as market)',
                ticks: ['0 calmer', '1.0 market', '2.0 jumpy'],
            });
        }
        const pm = Number(financials.profit_margin);
        if (Number.isFinite(pm) && pm !== 0) {
            const pct = Math.abs(pm) <= 1 ? Math.abs(pm) * 100 : Math.abs(pm);
            bars.push({
                label: 'Profit Margin',
                text: fmtNum(pct, 1) + '%',
                width: Math.min(100, pct),
                hint: 'Profit per $100 of sales',
                ticks: ['0%', '50%', '100%'],
            });
        }
    }
    $('scoreBars').innerHTML = bars.map(b => `
        <div class="score-bar-item">
            <div class="score-bar-label"><span>${esc(b.label)}</span><span>${esc(b.text)}</span></div>
            <div class="score-bar-hint">${esc(b.hint)}</div>
            <div class="score-bar-track"><div class="score-bar-fill" style="width:${b.width}%"></div></div>
            <div class="score-bar-ticks">${b.ticks.map(t => `<span>${esc(t)}</span>`).join('')}</div>
        </div>`).join('');

    $('detailModal').classList.add('active');
}

function closeModal(id) {
    $(id).classList.remove('active');
}

function submitAnalysis(e) {
    e.preventDefault();
    const name = $('companyName').value.trim();
    if (!name) return;

    closeModal('analyzeModal');
    $('loadingTitle').textContent = `Analyzing ${name}...`;
    $('loadingStep').textContent = 'Starting pipeline...';
    $('progressFill').style.width = '0%';
    $('loadingOverlay').classList.add('active');
    $('analyzeSubmit').disabled = true;

    const url = `/api/company/stream?query=${encodeURIComponent(name)}&fast=1`;
    const evtSource = new EventSource(url);
    let error = null;
    let done = false;

    evtSource.onmessage = function(ev) {
        try {
            const msg = JSON.parse(ev.data);
            $('progressFill').style.width = msg.pct + '%';
            $('loadingStep').textContent = msg.step || '';
            if (msg.done) {
                done = true;
                evtSource.close();
                if (msg.error) { error = msg.error; finish(); return; }
                fetchResult(name);
            }
        } catch (_) {}
    };

    evtSource.onerror = function() {
        evtSource.close();
        if (!done) { error = 'Connection lost'; finish(); }
    };

    async function fetchResult(query) {
        try {
            const res = await fetch('/api/reports');
            const data = await res.json();
            if (data.ok && data.reports) {
                const match = data.reports.find(r => (r.query || '').toLowerCase() === query.toLowerCase());
                if (match) {
                    const exists = state.reports.findIndex(r => (r.query || '').toLowerCase() === query.toLowerCase());
                    if (exists >= 0) state.reports[exists] = match;
                    else state.reports.unshift(match);
                    saveState();
                    renderDashboard();
                    loadStats();
                    openDetail(match);
                }
            }
        } catch (err) {
            error = err.message;
        }
        finish();
    }

    function finish() {
        if (error) alert(`Analysis failed: ${error}`);
        $('progressFill').style.width = '0%';
        $('loadingOverlay').classList.remove('active');
        $('analyzeSubmit').disabled = false;
        $('analyzeForm').reset();
    }
}

function row(label, valueHtml) {
    if (!valueHtml || valueHtml === '-') return '';
    return `<tr><th>${esc(label)}</th><td>${valueHtml}</td></tr>`;
}

function companyErrorText(msg) {
    let s = String(msg || '').trim();
    const cut = s.indexOf('AmbiguousCompanyError:');
    if (cut !== -1) return s.slice(cut + 'AmbiguousCompanyError:'.length).trim();
    return s.replace(/^(?:[A-Za-z_][\w.]*Error|RuntimeError):\s*/, '');
}

function renderCompanyDossier(dossier, titlePrefix, opts) {
    const options = opts || {};
    if (!dossier) {
        const err = companyErrorText(options.emptyError || '');
        if (err) return `<div class="card"><p class="muted">${esc(err)}</p></div>`;
        return '<div class="card"><p class="muted">No company data yet. Investigate a lead, or search here.</p></div>';
    }
    const resolved = dossier.resolved || {};
    const overview = dossier.overview || {};
    const financials = dossier.financials || {};
    const sources = dossier.sources_status || {};
    const news = ((dossier.news && dossier.news.articles) || []).filter(a => !isErrorArticle(a));
    const filings = dossier.filings || [];
    const name = resolved.name || dossier.query || 'Company';
    const ticker = resolved.ticker ? ` <span class="ticker">${esc(resolved.ticker)}</span>` : '';
    const bmKey = companyKey(dossier);
    const bm = bmKey ? bookmarkButton(bmKey, isBookmarked(dossier)) : '';
    let html = `
    <div class="card">
        <div class="card-header">
            <h3>${esc(titlePrefix || 'Company')} — ${esc(name)}${ticker}</h3>
            ${bm}
        </div>
        <table>
            ${row('Description', val(overview.description || overview.short_description))}
            ${row('Industry', val(overview.industry))}
            ${row('Sector', val(overview.sector))}
            ${row('Headquarters', val(overview.headquarters))}
            ${row('Country', val(overview.country))}
            ${overview.website ? row('Website', `<a class="link" href="${esc(overview.website)}" target="_blank">${esc(overview.website)}</a>`) : ''}
            ${row('Employees', val(overview.employees))}
            ${resolved.exchanges && resolved.exchanges.length ? row('Exchange', esc(resolved.exchanges.join(', '))) : ''}
        </table>
    </div>`;
    if (options.leadId) {
        html += `<div class="card">
            <div class="card-actions" style="margin-top:0">
                <button type="button" class="btn btn-secondary lookup-news-btn" data-id="${esc(options.leadId)}" ${options.newsLoading ? 'disabled' : ''}>
                    ${options.newsLoading ? 'Looking up news...' : 'Look up news'}
                </button>
            </div>
        </div>`;
        if (options.newsLoading) {
            html += `<div class="loading-inline show" style="margin-bottom:1rem"><div class="spinner-sm"></div><span>Fetching news articles...</span></div>`;
        } else if (options.newsReady) {
            if (news.length) {
                html += `<div class="card"><h3>Recent News (${news.length})</h3>`;
                news.slice(0, 10).forEach(a => {
                    const title = a.url
                        ? `<a href="${esc(a.url)}" target="_blank">${esc(a.title || 'Untitled')}</a>`
                        : esc(a.title || 'Untitled');
                    html += `<div class="news-item"><h4>${title}</h4><div class="meta">${esc(a.source_name || '')} · ${esc(a.published_at || '')}</div>`;
                    if (a.summary) html += `<p>${esc(String(a.summary).slice(0, 200))}</p>`;
                    html += `</div>`;
                });
                html += `</div>`;
            } else {
                html += `<div class="card"><h3>Recent News</h3><p class="muted">No recent news found.</p></div>`;
            }
        }
    }
    if (hasFinancialData(financials)) {
        const cur = currencyCode(dossier);
        html += `
        <div class="card">
            <h3>Financials</h3>
            <table>
                ${financials.market_cap ? row('Market Cap', money(financials.market_cap, cur)) : ''}
                ${financials.revenue ? row('Revenue', money(financials.revenue, cur)) : ''}
                ${row('EPS', financials.eps != null && financials.eps !== '' ? price(financials.eps, cur) : '')}
                ${row('P/E Ratio', val(financials.pe_ratio))}
                ${row('Beta', val(financials.beta))}
                ${financials.week_52_high ? row('52W High', `<span class="fin-high">↑ ${price(financials.week_52_high, cur)}</span>`) : ''}
                ${financials.week_52_low ? row('52W Low', `<span class="fin-low">↓ ${price(financials.week_52_low, cur)}</span>`) : ''}
            </table>
        </div>`;
    } else if (sources.yahoo || sources.finnhub || sources.alpha_vantage) {
        const reason = (sources.yahoo && sources.yahoo.error) || (sources.finnhub && sources.finnhub.error) || (sources.alpha_vantage && sources.alpha_vantage.error) || 'unavailable';
        html += `<div class="card"><h3>Financials</h3><p class="muted">Not available (${esc(reason)}). Try the parent company or stock ticker.</p></div>`;
    }
    if (!options.leadId && news.length) {
        html += `<div class="card"><h3>Recent News (${news.length})</h3>`;
        news.slice(0, 10).forEach(a => {
            const title = a.url
                ? `<a href="${esc(a.url)}" target="_blank">${esc(a.title || 'Untitled')}</a>`
                : esc(a.title || 'Untitled');
            html += `<div class="news-item"><h4>${title}</h4><div class="meta">${esc(a.source_name || '')} · ${esc(a.published_at || '')}</div>`;
            if (a.summary) html += `<p>${esc(String(a.summary).slice(0, 200))}</p>`;
            html += `</div>`;
        });
        html += `</div>`;
    }
    if (filings.length) {
        const india = (filings[0].via || []).includes('nse') || /india_listing|\.NS|\.BO/i.test((resolved.ticker || '') + (sources.sec_edgar && sources.sec_edgar.error || ''));
        const heading = india ? `Filings (${filings.length})` : `SEC Filings (${filings.length})`;
        html += `<div class="card"><h3>${heading}</h3><table class="filings-table">`;
        filings.slice(0, 20).forEach(f => {
            const label = f.title || f.form || '';
            const when = String(f.filed_at || '').trim();
            const dateHtml = when
                ? when.split(/\s+/).map(p => esc(p)).join('<br>')
                : '-';
            const link = f.url ? `<a class="link" href="${esc(f.url)}" target="_blank">View</a>` : '-';
            html += `<tr><td>${esc(f.form || '')}</td><td>${dateHtml}</td><td>${esc(label)}</td><td>${link}</td></tr>`;
        });
        html += `</table></div>`;
    } else if (sources.nse && sources.nse.error && sources.nse.error !== 'us_listing' && sources.nse.error !== 'not_india_listing') {
        html += `<div class="card"><h3>Filings</h3><p class="muted">NSE announcements not available (${esc(sources.nse.error)}).</p></div>`;
    } else if (sources.sec_edgar) {
        const reason = (sources.sec_edgar && sources.sec_edgar.error) || 'unavailable';
        const india = reason === 'india_listing';
        html += `<div class="card"><h3>${india ? 'Filings' : 'SEC Filings'}</h3><p class="muted">${india ? 'No NSE announcements found for this listing.' : `Not available (${esc(reason)}). US filings need a resolved ticker/CIK.`}</p></div>`;
    }
    return html;
}

function nameFromLinkedInUrl(url) {
    const slug = (url || '').split('/in/')[1]?.replace(/\/$/, '').split('?')[0] || '';
    if (!slug) return '';
    return slug.split('-').map(w => w ? w[0].toUpperCase() + w.slice(1).toLowerCase() : '').join(' ');
}

function candidateDisplayName(url, profiles, candidates) {
    const norm = (u) => (u || '').split('?')[0].replace(/\/$/, '').toLowerCase();
    const key = norm(url);
    if (candidates && candidates.length) {
        const c = candidates.find(x => norm(x.url || x) === key);
        if (c && c.name) return c.name;
    }
    if (profiles && profiles.length) {
        const p = profiles.find(x => norm(x.linkedin_profile_url || x.url) === key);
        if (p && p.name) return p.name;
    }
    return nameFromLinkedInUrl(url) || '-';
}

function contactSourceLabel(src) {
    const map = {
        linkedin: 'LinkedIn',
        saved: 'Saved',
        entered: 'Entered',
        company_site: 'Company site',
        profile_link: 'Profile link',
        github: 'GitHub',
    };
    const key = String(src || '').trim();
    return map[key] || key.replace(/_/g, ' ');
}

function contactEntries(profile, primary, listKey, entriesKey, kind, allowCompany) {
    const out = [];
    const seen = new Set();
    const add = (value, source) => {
        let text = String(value || '').trim().replace(/\\+$/g, '');
        if (!text) return;
        const src = String(source || '').trim().toLowerCase();
        if (src === 'guessed' || src === 'guess') return;
        if (kind === 'phone' && src === 'company_site' && !allowCompany) return;
        if (kind === 'email' && /^(info|hello|support|press|media|contact|sales|admin|webmaster|ir)@/.test(text) && src !== 'entered' && !allowCompany) return;
        if (kind === 'phone') {
            if ((text.match(/\./g) || []).length > 1 || /[A-Za-z]/.test(text)) return;
            const digits = text.replace(/\D/g, '');
            if (digits.length < 10 || digits.length > 15) return;
        }
        const key = kind === 'phone' ? text.replace(/\D/g, '') : text.toLowerCase();
        if (!key || seen.has(key)) return;
        seen.add(key);
        out.push({ value: text, source: src || (allowCompany ? 'company_site' : '') });
    };
    (profile[entriesKey] || []).forEach(item => {
        if (item && typeof item === 'object') add(item.value, item.source);
        else add(item, '');
    });
    add(primary, '');
    (profile[listKey] || []).forEach(item => add(item, ''));
    return out;
}

function contactChip(text, href, kind, source) {
    const inner = href
        ? `<a href="${esc(href)}"${/^https?:/i.test(href) ? ' target="_blank" rel="noopener"' : ''}>${esc(text)}</a>`
        : esc(text);
    const label = contactSourceLabel(source);
    const src = label ? `<span class="contact-chip-src">${esc(label)}</span>` : '';
    return `<span class="contact-chip ${kind || ''}">${inner}${src}</span>`;
}

function contactGroup(label, chips) {
    if (!chips) return '';
    return `<div class="contact-group"><span class="contact-label">${esc(label)}</span><div class="contact-chips">${chips}</div></div>`;
}

function renderProfileContact(p) {
    const emails = contactEntries(p, p.email, 'emails', 'email_entries', 'email');
    const phones = contactEntries(p, p.phone, 'phones', 'phone_entries', 'phone');
    const companyEmails = contactEntries(p, '', 'company_emails', 'company_email_entries', 'email', true);
    const companyPhones = contactEntries(p, '', 'company_phones', 'company_phone_entries', 'phone', true);
    const emailChips = emails.map(e => contactChip(e.value, `mailto:${e.value}`, '', e.source)).join('');
    const phoneChips = phones.map(n => contactChip(n.value, `tel:${n.value.replace(/[^\d+]/g, '')}`, 'phone', n.source)).join('');
    const companyChips = [
        ...companyEmails.map(e => contactChip(e.value, `mailto:${e.value}`, 'company', e.source || 'company_site')),
        ...companyPhones.map(n => contactChip(n.value, `tel:${n.value.replace(/[^\d+]/g, '')}`, 'company', n.source || 'company_site')),
    ].join('');
    if (!emailChips && !phoneChips && !companyChips) {
        return `<p class="contact-empty">No public contact found</p>`;
    }
    return `<div class="contact-block">
        ${emailChips ? contactGroup('Email', emailChips) : ''}
        ${phoneChips ? contactGroup('Phone', phoneChips) : ''}
        ${companyChips ? contactGroup('Company contact', companyChips) : ''}
    </div>`;
}

function isPeopleJunkLine(text) {
    const s = String(text || '').toLowerCase().replace(/\s+/g, ' ').trim();
    if (!s) return true;
    if (/\bmutual\b/.test(s)) return true;
    if (/(?:and|&)\s*\d+\s+other/.test(s)) return true;
    if (/^connections?$/.test(s)) return true;
    if (/\d+\s+connections?\b/.test(s)) return true;
    return false;
}

function peopleJobField(value, headline) {
    const v = val(value);
    const h = val(headline);
    if (!v) return '';
    if (h && v === h) return '';
    if (h && v.length >= 12 && h.includes(v) && /\|/.test(h)) return '';
    if ((v.match(/\|/g) || []).length >= 1 && v.length > 40) return '';
    return v;
}

function matchInitials(name) {
    const parts = String(name || '').trim().split(/\s+/).filter(Boolean);
    if (!parts.length) return '?';
    if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
    return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

function peopleVisualFields(item) {
    const src = item && typeof item === 'object' ? item : {};
    return {
        photo: String(src.photo || '').trim(),
        banner: String(src.banner || '').trim(),
        shot: String(src.shot || '').trim(),
    };
}

function renderPeoplePhotoHtml(name, photo) {
    return photo
        ? `<img class="people-match-photo" src="${esc(photo)}" alt="">`
        : `<div class="people-match-photo people-match-photo-fallback">${esc(matchInitials(name))}</div>`;
}

function renderPeopleBannerPhoto(name, photo, banner) {
    const cover = String(banner || '').trim();
    const photoHtml = renderPeoplePhotoHtml(name, photo);
    if (!cover) {
        return `<div class="people-match-body people-match-body-visual people-match-body-flat">${photoHtml}</div>`;
    }
    return `<div class="people-match-banner people-match-banner-has-img"><img class="people-match-banner-img" src="${esc(cover)}" alt=""></div>
        <div class="people-match-body people-match-body-visual">${photoHtml}</div>`;
}

function renderPeopleVisual(name, item) {
    const { photo, banner } = peopleVisualFields(item);
    return renderPeopleBannerPhoto(name, photo, banner);
}

function candidateVisualForUrl(url) {
    const want = normalizeProfileUrl(url);
    if (!want) return {};
    const hit = (state.linkedin.candidates || []).find(c => normalizeProfileUrl(c.url) === want);
    return hit ? peopleVisualFields(hit) : {};
}

function profileVisual(p) {
    const own = peopleVisualFields(p);
    if (own.photo || own.banner || own.shot) return own;
    return candidateVisualForUrl(p.linkedin_profile_url || p.url);
}

function renderMatchPreview(item, index, profiles, cands, allowScrape, scraping) {
    const url = item.url || item;
    const name = candidateDisplayName(url, profiles, cands);
    const headline = isPeopleJunkLine(item.headline) ? '' : String(item.headline || '').trim();
    const location = isPeopleJunkLine(item.location) ? '' : String(item.location || '').trim();
    const companies = Array.isArray(item.companies) ? item.companies.filter(Boolean) : [];
    const vis = peopleVisualFields(item);
    const photoHtml = renderPeoplePhotoHtml(name, vis.photo);
    const look = allowScrape
        ? `<button type="button" class="btn btn-secondary scrape-one-btn" data-url="${esc(url)}" ${scraping ? 'disabled' : ''}>Look up</button>`
        : '';
    const coHtml = companies.length
        ? `<div class="people-match-cos">${companies.map(c => `<span class="people-match-co">${esc(c)}</span>`).join('')}</div>`
        : '';
    return `<article class="people-match people-match-flat">
        <div class="people-match-body people-match-body-flat">
            ${photoHtml}
            <div class="people-match-info">
                <h4>${esc(name)}</h4>
                ${headline ? `<p class="people-match-headline">${esc(headline)}</p>` : ''}
                ${location ? `<p class="people-match-location">${esc(location)}</p>` : ''}
                ${coHtml}
                <a class="link people-match-url" href="${esc(url)}" target="_blank" rel="noopener">${esc(url)}</a>
            </div>
            <div class="people-match-actions">${look}</div>
        </div>
    </article>`;
}

function renderProfiles(profiles, candidateUrls, candidates, opts) {
    const options = opts || {};
    let html = '';
    const urls = candidateUrls || [];
    const cands = candidates && candidates.length ? candidates : urls.map(u => ({ url: u, name: '' }));
    if (cands.length) {
        const scrapeBtn = options.allowScrape
            ? `<div class="card-actions" style="margin:0.75rem 0">
                <button type="button" class="btn btn-primary scrape-candidates-btn" ${options.scraping ? 'disabled' : ''}>
                    ${options.scraping ? 'Looking up people...' : 'Look up people'}
                </button>
                ${options.scraping ? '<button type="button" class="btn btn-ghost scrape-stop-btn">Stop</button>' : ''}
               </div>
               ${options.scraping ? `<div class="loading-inline show"><div class="spinner-sm"></div><span class="linkedin-scrape-step">${esc(options.scrapeStep || 'Looking up people...')}</span></div>
               <div class="progress-bar" style="margin-top:0.5rem"><div class="progress-fill linkedin-scrape-fill" style="width:${options.scrapePct || 8}%"></div></div>` : ''}`
            : '';
        html += `<div class="card">
            <div class="card-header people-matches-header">
                <h3>Matches (${cands.length})</h3>
                <button type="button" class="btn btn-secondary matches-toggle-btn">${options.matchesOpen === false ? 'Expand ▼' : 'Collapse ▲'}</button>
            </div>
            <div class="people-matches-body"${options.matchesOpen === false ? ' hidden' : ''}>
            ${scrapeBtn}<div class="people-match-list">`;
        cands.forEach((item, i) => {
            html += renderMatchPreview(item, i, profiles, cands, options.allowScrape, options.scraping);
        });
        html += `</div></div></div>`;
    }
    if (!profiles || !profiles.length) {
        if (!html) {
            if (options.searching) return '';
            if (options.searched) html = '<div class="card"><p class="muted">No person found</p></div>';
            else html = '<div class="card"><p class="muted">Enter a name, email, company, or profile URL</p></div>';
        }
        return html;
    }
    profiles.forEach((p) => {
        const name = p.name || 'Unknown';
        const vis = profileVisual(p);
        html += `
        <div class="card people-profile-card">
            ${renderPeopleVisual(name, vis)}
            <div class="people-profile-main">
                <h3>${esc(name)}</h3>
                <table>
                    ${row('Headline', val(p.headline))}
                    ${row('Role', peopleJobField(p.current_role, p.headline))}
                    ${row('Company', peopleJobField(p.current_company, p.headline))}
                    ${p.error ? `<tr><th>Error</th><td style="color:#fca5a5">${esc(p.error)}</td></tr>` : ''}
                </table>
                ${renderProfileContact(p)}
            </div>
        </div>`;
    });
    return html;
}

function renderLeadLinkedInAction(lead) {
    const p = (lead && lead.parsed) || {};
    if (!p.name && !p.email) return '<div class="card"><p class="muted">No person found</p></div>';
    return `<div class="card">
        <h3>People Lookup</h3>
        <div class="card-actions" style="margin-top:0">
            <button type="button" class="btn btn-primary linkedin-lookup-btn" data-id="${esc(lead.id)}">Look up person</button>
        </div>
    </div>`;
}

function isLinkedInProfileUrl(value) {
    return /linkedin\.com\/in\//i.test(String(value || ''));
}

function normalizeProfileUrl(value) {
    const text = String(value || '').trim();
    if (!isLinkedInProfileUrl(text)) return '';
    return text.split('?')[0].replace(/\/$/, '');
}

function personNameTokens(text) {
    const stop = new Set(['the', 'and', 'for', 'with', 'from', '3rd', '2nd', '1st']);
    return (String(text || '').toLowerCase().match(/[a-z0-9]+/g) || []).filter(t => t.length > 1 && !stop.has(t));
}

function slugParts(url) {
    const slug = (String(url || '').split('/in/')[1] || '').split('?')[0].replace(/\/$/, '').toLowerCase();
    return slug ? slug.split(/[-_]+/).filter(Boolean) : [];
}

function tokenMatches(token, display, parts) {
    const re = new RegExp(`\\b${token.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\b`, 'i');
    if (re.test(display || '')) return true;
    return parts.some(p => p === token || p.startsWith(`${token}-`));
}

function personMatchesQuery(candidate, name, profileUrl) {
    const url = String((candidate && candidate.url) || candidate || '').trim();
    const display = String((candidate && candidate.name) || '').trim();
    const want = normalizeProfileUrl(profileUrl);
    if (want) return normalizeProfileUrl(url).toLowerCase() === want.toLowerCase();
    const q = String(name || '').trim();
    if (!q || q.includes('@')) return true;
    const tokens = personNameTokens(q);
    if (!tokens.length) return true;
    const parts = slugParts(url);
    return tokens.every(t => tokenMatches(t, display, parts));
}

function filterPeopleCandidates(candidates, name, profileUrl) {
    const list = (candidates || []).map(c => {
        if (!c) return null;
        if (typeof c === 'string') return { url: c, name: '', headline: '', location: '', photo: '', banner: '', shot: '', companies: [] };
        const companies = Array.isArray(c.companies)
            ? c.companies.map(x => String(x || '').trim()).filter(Boolean).slice(0, 4)
            : [];
        return {
            url: String(c.url || '').trim(),
            name: String(c.name || '').trim(),
            headline: isPeopleJunkLine(c.headline) ? '' : String(c.headline || '').trim(),
            location: isPeopleJunkLine(c.location) ? '' : String(c.location || '').trim(),
            photo: String(c.photo || '').trim(),
            banner: '',
            shot: String(c.shot || '').trim(),
            companies,
        };
    }).filter(c => c && c.url);
    if (normalizeProfileUrl(profileUrl)) {
        const matched = list.filter(c => personMatchesQuery(c, name, profileUrl));
        if (!matched.length) {
            return [{ url: normalizeProfileUrl(profileUrl), name: name || '' }];
        }
        return matched;
    }
    return list;
}

function normalizePeopleState(raw) {
    const li = raw && typeof raw === 'object' ? raw : {};
    let url = String(li.url || '').trim();
    let name = String(li.name || '').trim();
    if (url && !isLinkedInProfileUrl(url) && !name) {
        name = url;
        url = '';
    }
    const candidates = filterPeopleCandidates(li.candidates, name, url);
    return {
        name,
        company: String(li.company || '').trim(),
        role: String(li.role || '').trim(),
        location: String(li.location || '').trim(),
        email: String(li.email || '').trim(),
        phone: String(li.phone || '').trim(),
        url,
        profiles: Array.isArray(li.profiles) ? li.profiles : [],
        candidateUrls: candidates.map(c => c.url),
        candidates,
        searching: false,
        searched: !!li.searched,
        matchesOpen: li.matchesOpen !== false,
        scraping: false,
        progressPct: 0,
        progressStep: '',
        scrapePct: 0,
        scrapeStep: '',
    };
}

function peopleHints() {
    const li = state.linkedin || {};
    return {
        name: li.name || '',
        company: li.company || '',
        role: li.role || '',
        location: li.location || '',
        email: li.email || '',
        phone: li.phone || '',
    };
}

function readPeopleForm() {
    return {
        name: ($('people-name') && $('people-name').value.trim()) || '',
        company: ($('people-company') && $('people-company').value.trim()) || '',
        role: ($('people-role') && $('people-role').value.trim()) || '',
        location: ($('people-location') && $('people-location').value.trim()) || '',
        email: ($('people-email') && $('people-email').value.trim()) || '',
        phone: ($('people-phone') && $('people-phone').value.trim()) || '',
        url: ($('people-url') && $('people-url').value.trim()) || '',
    };
}

function fillPeopleForm() {
    const li = state.linkedin || {};
    if ($('people-name')) $('people-name').value = li.name || '';
    if ($('people-company')) $('people-company').value = li.company || '';
    if ($('people-role')) $('people-role').value = li.role || '';
    if ($('people-location')) $('people-location').value = li.location || '';
    if ($('people-email')) $('people-email').value = li.email || '';
    if ($('people-phone')) $('people-phone').value = li.phone || '';
    if ($('people-url')) $('people-url').value = li.url || '';
}

function applyPeopleForm(fields) {
    state.linkedin.name = fields.name || '';
    state.linkedin.company = fields.company || '';
    state.linkedin.role = fields.role || '';
    state.linkedin.location = fields.location || '';
    state.linkedin.email = fields.email || '';
    state.linkedin.phone = fields.phone || '';
    state.linkedin.url = fields.url || '';
}

function openLinkedInFromLead(id) {
    const lead = state.leads.find(l => l.id === id);
    if (!lead) return;
    const p = lead.parsed || {};
    const name = String(p.name || '').trim();
    const email = String(p.email || lead.email || '').trim();
    if (!name && !email) return;
    const company = p.is_corporate && p.company ? String(p.company).trim() : '';
    applyPeopleForm({
        name,
        company,
        role: '',
        location: '',
        email,
        phone: '',
        url: '',
    });
    state.linkedin.profiles = [];
    state.linkedin.candidates = [];
    state.linkedin.candidateUrls = [];
    state.linkedin.searching = true;
    state.linkedin.searched = false;
    state.linkedin.matchesOpen = true;
    saveState();
    fillPeopleForm();
    switchTab('people');
    $('people-form').requestSubmit();
}

function renderLeadList() {
    const list = $('lead-list');
    if (!state.leads.length) {
        list.innerHTML = '<div class="card"><p class="muted">No leads yet. Add an email above.</p></div>';
        return;
    }
    list.innerHTML = state.leads.map(lead => {
        const p = lead.parsed || {};
        const source = lead.from_sample_cookie ? 'cookie snapshot' : 'manual';
        const progressPct = lead.progressPct || 0;
        const progressStep = lead.progressStep || 'Investigating...';
        const busy = lead.investigating
            ? `<div class="loading-inline show"><div class="spinner-sm"></div><span class="lead-step-text" data-id="${esc(lead.id)}">${esc(progressStep)}</span></div>
               <div class="progress-bar" style="margin-top:0.5rem"><div class="progress-fill lead-progress-fill" data-id="${esc(lead.id)}" style="width:${progressPct}%"></div></div>`
            : '';
        const hasResult = !!(lead.result && !lead.investigating);
        const viewBtn = hasResult
            ? `<button type="button" class="btn btn-secondary view-btn" data-id="${esc(lead.id)}">${lead.viewOpen ? 'Collapse ▲' : 'View ▼'}</button>`
            : '';
        const detailsHtml = (hasResult && lead.viewOpen) ? `
            <div class="lead-details" data-lead-details="${esc(lead.id)}" style="margin-top:1rem">
                ${renderCompanyDossier(lead.result.company, 'Lead Company', {
                    leadId: lead.id,
                    newsLoading: !!lead.newsLoading,
                    newsReady: !!lead.newsLookedUp,
                    emptyError: lead.result.company_error || '',
                })}
                ${renderLeadLinkedInAction(lead)}
            </div>
        ` : '';
        const err = lead.error ? `<div class="error">${esc(lead.error)}</div>` : '';
        const stopBtn = lead.investigating
            ? `<button type="button" class="btn btn-ghost stop-btn" data-id="${esc(lead.id)}">Stop</button>`
            : '';
        const ckey = leadCompanyKey(lead);
        const bm = ckey ? `<span class="lead-bookmark">${bookmarkButton(ckey, (state.bookmarks || []).includes(ckey))}</span>` : '';
        return `
        <div class="card" data-lead-id="${esc(lead.id)}">
            ${bm}
            <table>
                ${row('Name', val(p.name))}
                ${row('Email', val(p.email))}
                ${row('Company', val(p.company))}
                ${row('Source', esc(source))}
            </table>
            <div class="card-actions">
                <button type="button" class="btn btn-primary investigate-btn" data-id="${esc(lead.id)}" ${lead.investigating ? 'disabled' : ''}>
                    ${lead.investigating ? 'Investigating...' : (lead.result ? 'Re-investigate' : 'Investigate')}
                </button>
                <button type="button" class="btn btn-secondary remove-btn" data-id="${esc(lead.id)}" ${lead.investigating ? 'disabled' : ''}>Remove</button>
                ${stopBtn}
                ${viewBtn}
            </div>
            ${busy}
            ${err}
            ${detailsHtml}
        </div>`;
    }).join('');

    list.querySelectorAll('.investigate-btn').forEach(btn => {
        btn.addEventListener('click', () => investigateLead(btn.dataset.id));
    });
    list.querySelectorAll('.remove-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            state.leads = state.leads.filter(l => l.id !== btn.dataset.id);
            saveState();
            renderLeadList();
            renderDashboard();
        });
    });
    bindBookmarkButtons(list);

    list.querySelectorAll('.view-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const lead = state.leads.find(l => l.id === btn.dataset.id);
            if (!lead) return;
            lead.viewOpen = !lead.viewOpen;
            renderLeadList();
            queueSaveState();
        });
    });

    list.querySelectorAll('.stop-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const id = btn.dataset.id;
            const lead = state.leads.find(l => l.id === id);
            if (!lead || activeLeadInvestigation.leadId !== id) return;
            fetch('/api/lead/investigate/stop', { method: 'POST' }).catch(() => {});
            if (activeLeadInvestigation.controller) activeLeadInvestigation.controller.abort();
            lead.investigating = false;
            lead.progressPct = 0;
            lead.progressStep = '';
            activeLeadInvestigation.leadId = null;
            activeLeadInvestigation.controller = null;
            renderLeadList();
        });
    });

    list.querySelectorAll('.linkedin-lookup-btn').forEach(btn => {
        btn.addEventListener('click', () => openLinkedInFromLead(btn.dataset.id));
    });

    list.querySelectorAll('.lookup-news-btn').forEach(btn => {
        btn.addEventListener('click', () => lookupLeadNews(btn.dataset.id));
    });
}

function renderCompanyPanel() {
    if (state.company.query) $('company-query').value = state.company.query;
    $('company-results').innerHTML = renderCompanyDossier(state.company.dossier);
    bindBookmarkButtons($('company-results'));
}

function renderLinkedinPanel() {
    fillPeopleForm();
    $('people-results').innerHTML = renderProfiles(
        state.linkedin.profiles,
        state.linkedin.candidateUrls,
        state.linkedin.candidates,
        { allowScrape: true, scraping: !!state.linkedin.scraping, scrapePct: state.linkedin.scrapePct || 0, scrapeStep: state.linkedin.scrapeStep || '', searching: !!state.linkedin.searching, searched: !!state.linkedin.searched, matchesOpen: state.linkedin.matchesOpen !== false }
    );
    const results = $('people-results');
    if (results) {
        results.querySelectorAll('.scrape-candidates-btn').forEach(btn => {
            btn.addEventListener('click', () => scrapeLinkedInCandidates());
        });
        results.querySelectorAll('.scrape-one-btn').forEach(btn => {
            btn.addEventListener('click', () => scrapeLinkedInCandidates(btn.dataset.url));
        });
        results.querySelectorAll('.scrape-stop-btn').forEach(btn => {
            btn.addEventListener('click', () => stopLinkedInScrape());
        });
        results.querySelectorAll('.matches-toggle-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                state.linkedin.matchesOpen = state.linkedin.matchesOpen === false;
                renderLinkedinPanel();
            });
        });
    }
}

function renderAll() {
    renderDashboard();
    renderLeadList();
    renderCompanyPanel();
    renderLinkedinPanel();
}

function applyInvestigateToShared(result) {
    if (result.company) {
        state.company.dossier = result.company;
        state.company.query = (result.parsed && result.parsed.company) || state.company.query || '';
    }
}

function newsQueryForLead(lead) {
    const company = (lead.result && lead.result.company) || {};
    const resolved = company.resolved || {};
    const parsed = lead.parsed || {};
    return resolved.name || company.query || parsed.company || '';
}

async function lookupLeadNews(id) {
    const lead = state.leads.find(l => l.id === id);
    if (!lead || !lead.result || lead.newsLoading) return;
    const query = newsQueryForLead(lead);
    if (!query) {
        lead.error = 'No company name available for news lookup.';
        renderLeadList();
        return;
    }
    lead.newsLoading = true;
    lead.newsLookedUp = false;
    lead.viewOpen = true;
    lead.error = null;
    renderLeadList();
    try {
        const data = await postJson('/api/company/news', { query });
        if (!lead.result.company) lead.result.company = {};
        lead.result.company.news = {
            digest_summary: null,
            lookback_days: data.lookback_days || 3,
            articles: data.articles || [],
            fetched_at: data.fetched_at || null,
        };
        lead.newsLookedUp = true;
    } catch (err) {
        lead.error = err.message || String(err);
        lead.newsLookedUp = false;
    } finally {
        lead.newsLoading = false;
        renderLeadList();
        queueSaveState();
    }
}

async function scrapeLinkedInCandidates(onlyUrl) {
    if (state.linkedin.scraping) return;
    const all = (state.linkedin.candidateUrls && state.linkedin.candidateUrls.length)
        ? state.linkedin.candidateUrls
        : (state.linkedin.candidates || []).map(c => c.url || c).filter(Boolean);
    const urls = (onlyUrl ? [onlyUrl] : all).filter(Boolean).slice(0, 5);
    if (!urls.length) return;
    const total = urls.length;
    state.linkedin.scraping = true;
    state.linkedin.scrapePct = 4;
    state.linkedin.scrapeStep = total > 1 ? `Looking up profile 1 of ${total}` : 'Looking up profile...';
    if (!onlyUrl) state.linkedin.profiles = [];
    showError($('people-error'), '');
    renderLinkedinPanel();

    let finished = false;
    const controller = new AbortController();
    activeLinkedinScrape.controller = controller;
    activeLinkedinScrape.source = null;
    activeLinkedinScrape.stopped = false;

    function applyProgress(pct, text) {
        state.linkedin.scrapePct = pct;
        state.linkedin.scrapeStep = text;
        const fill = document.querySelector('.linkedin-scrape-fill');
        const stepEl = document.querySelector('.linkedin-scrape-step');
        if (fill) fill.style.width = pct + '%';
        if (stepEl) stepEl.textContent = text;
    }

    function mergeProfile(row) {
        if (!row) return;
        const vis = candidateVisualForUrl(row.linkedin_profile_url || row.url);
        if (!row.photo && vis.photo) row.photo = vis.photo;
        if (!row.banner && vis.banner) row.banner = vis.banner;
        const key = String(row.linkedin_profile_url || row.url || '').split('?')[0].replace(/\/$/, '').toLowerCase();
        if (!key) {
            state.linkedin.profiles = (state.linkedin.profiles || []).concat([row]);
            return;
        }
        const idx = (state.linkedin.profiles || []).findIndex(p => {
            const k = String(p.linkedin_profile_url || p.url || '').split('?')[0].replace(/\/$/, '').toLowerCase();
            return k === key;
        });
        if (idx >= 0) state.linkedin.profiles[idx] = row;
        else state.linkedin.profiles = (state.linkedin.profiles || []).concat([row]);
    }

    function handleMsg(msg) {
        if (!msg || typeof msg !== 'object') return;
        if (msg.error && msg.done) {
            finish(activeLinkedinScrape.stopped ? '' : msg.error);
            return;
        }
        if (activeLinkedinScrape.stopped) return;
        if (msg.step) {
            applyProgress(Number(msg.pct) || state.linkedin.scrapePct || 0, msg.step);
        }
        if (msg.profile) {
            mergeProfile(msg.profile);
            renderLinkedinPanel();
        }
        if (msg.done) {
            if (Array.isArray(msg.profiles) && msg.profiles.length) {
                msg.profiles.forEach(mergeProfile);
            }
            applyProgress(100, 'Complete');
            finish();
        }
    }

    function finish(err) {
        if (finished) return;
        finished = true;
        try { controller.abort(); } catch (_) {}
        activeLinkedinScrape.controller = null;
        activeLinkedinScrape.source = null;
        activeLinkedinScrape.finish = null;
        if (err && !activeLinkedinScrape.stopped) showError($('people-error'), err);
        state.linkedin.scraping = false;
        state.linkedin.scrapePct = 0;
        state.linkedin.scrapeStep = '';
        saveState();
        renderLinkedinPanel();
    }

    activeLinkedinScrape.finish = finish;

    try {
        const res = await fetch('/api/linkedin/stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Accept': 'text/event-stream' },
            body: JSON.stringify({ urls, hints: peopleHints() }),
            signal: controller.signal,
        });
        if (!res.ok) {
            let err = 'Lookup did not finish';
            try {
                const payload = await res.json();
                if (payload && payload.error) err = payload.error;
            } catch (_) {}
            finish(err);
            return;
        }
        const reader = res.body && res.body.getReader();
        if (!reader) {
            finish('Lookup did not finish');
            return;
        }
        const dec = new TextDecoder();
        let buf = '';
        while (!finished) {
            const chunk = await reader.read();
            if (chunk.done) break;
            buf += dec.decode(chunk.value, { stream: true });
            let sep;
            while ((sep = buf.indexOf('\n\n')) >= 0) {
                const block = buf.slice(0, sep);
                buf = buf.slice(sep + 2);
                block.split('\n').forEach(line => {
                    if (!line.startsWith('data:')) return;
                    try { handleMsg(JSON.parse(line.slice(5).trim())); } catch (_) {}
                });
            }
        }
        if (!finished) {
            if (activeLinkedinScrape.stopped || (state.linkedin.profiles || []).length) finish();
            else finish('Lookup did not finish');
        }
    } catch (err) {
        if (finished) return;
        if (err && err.name === 'AbortError') {
            if (activeLinkedinScrape.stopped || (state.linkedin.profiles || []).length) finish();
            else finish();
            return;
        }
        finish(err && err.message ? err.message : 'Lookup did not finish');
    }
}

function stopLinkedInScrape() {
    activeLinkedinScrape.stopped = true;
    if (activeLinkedinScrape.controller) {
        try { activeLinkedinScrape.controller.abort(); } catch (_) {}
    }
    if (activeLinkedinScrape.source) {
        try { activeLinkedinScrape.source.close(); } catch (_) {}
    }
    fetch('/api/linkedin/scrape/stop', { method: 'POST' }).catch(() => {});
    if (typeof activeLinkedinScrape.finish === 'function') activeLinkedinScrape.finish();
    else {
        state.linkedin.scraping = false;
        state.linkedin.scrapePct = 0;
        state.linkedin.scrapeStep = '';
        activeLinkedinScrape.source = null;
        activeLinkedinScrape.controller = null;
    }
}

async function investigateLead(id) {
    const lead = state.leads.find(l => l.id === id);
    if (!lead || lead.investigating) return;

    if (activeLeadInvestigation.leadId && activeLeadInvestigation.leadId !== id) {
        const prev = state.leads.find(l => l.id === activeLeadInvestigation.leadId);
        if (prev) prev.investigating = false;
        if (activeLeadInvestigation.controller) activeLeadInvestigation.controller.abort();
        activeLeadInvestigation.leadId = null;
        activeLeadInvestigation.controller = null;
        saveState();
        renderLeadList();
        try { await fetch('/api/lead/investigate/stop', { method: 'POST' }); } catch (_) {}
    }

    lead.investigating = true;
    lead.error = null;
    lead.viewOpen = false;
    lead.newsLookedUp = false;
    lead.newsLoading = false;
    lead.progressPct = 0;
    lead.progressStep = 'Starting...';
    renderLeadList();

    const controller = new AbortController();
    activeLeadInvestigation.leadId = id;
    activeLeadInvestigation.controller = controller;
    const hardTimeout = setTimeout(() => {
        fetch('/api/lead/investigate/stop', { method: 'POST' }).catch(() => {});
        try { controller.abort(); } catch (_) {}
    }, 120000);

    const steps = [
        [8, 'Parsing email...'],
        [28, 'Running company pipeline...'],
        [52, 'Fetching financial data...'],
        [78, 'Wrapping up...'],
    ];
    const waitMsgs = ['Still working...', 'Processing results...', 'Almost there...'];
    let stepIdx = 0;
    let waitTick = 0;

    function setLeadProgress(pct, text, rerender) {
        lead.progressPct = pct;
        lead.progressStep = text;
        const fill = document.querySelector(`.lead-progress-fill[data-id="${id}"]`);
        const stepEl = document.querySelector(`.lead-step-text[data-id="${id}"]`);
        if (fill) fill.style.width = pct + '%';
        if (stepEl) stepEl.textContent = text;
        if (rerender) renderLeadList();
    }

    const interval = setInterval(() => {
        if (stepIdx < steps.length) {
            setLeadProgress(steps[stepIdx][0], steps[stepIdx][1], false);
            stepIdx++;
            return;
        }
        const current = lead.progressPct || 85;
        const next = current < 96 ? current + 1 : current;
        setLeadProgress(next, waitMsgs[waitTick % waitMsgs.length], false);
        waitTick++;
    }, 6000);

    try {
        const data = await postJson('/api/lead/investigate', {
            email: lead.email,
            use_sample: false,
            max_profiles: 2,
        }, controller.signal);
        lead.result = data.result;
        lead.parsed = (data.result && data.result.parsed) || lead.parsed;
        if (lead.result && lead.result.company && lead.result.company.news) {
            lead.result.company.news.articles = [];
        }
        lead.newsLookedUp = false;
        const liErr = (data.result && (data.result.search_error || data.result.scrape_error)) || '';
        if (liErr) lead.error = String(liErr);
        setLeadProgress(100, 'Complete', false);
    } catch (err) {
        if (err && err.name === 'AbortError') {
            lead.error = null;
        } else {
            const msg = err.message || String(err);
            if (/timed out|stopped|failed/i.test(msg) && activeLeadInvestigation.leadId !== id) {
                lead.error = null;
            } else {
                lead.error = msg;
            }
        }
    } finally {
        clearTimeout(hardTimeout);
        clearInterval(interval);
        lead.investigating = false;
        lead.progressPct = 0;
        lead.progressStep = '';
        if (activeLeadInvestigation.leadId === id) {
            activeLeadInvestigation.leadId = null;
            activeLeadInvestigation.controller = null;
        }
        renderLeadList();
        renderDashboard();
        queueSaveState();
    }
}

async function loadSampleLeads() {
    try {
        const res = await fetch('/api/lead/samples');
        const data = await res.json();
        if (!data.ok || !Array.isArray(data.samples)) return;
        for (const s of data.samples) {
            const exists = state.leads.find(l => l.id === s.id);
            if (exists) {
                exists.parsed = s.parsed || exists.parsed;
                exists.email = s.email || exists.email;
                exists.from_sample_cookie = true;
                continue;
            }
            state.leads.push({
                id: s.id,
                email: s.email,
                parsed: s.parsed,
                from_sample_cookie: true,
                result: null,
                investigating: false,
                error: null,
            });
        }
        saveState();
    } catch (_) {}
}

document.querySelectorAll('nav.tabs button').forEach(btn => {
    btn.addEventListener('click', () => switchTab(btn.dataset.tab));
});

$('searchInput').addEventListener('input', filterCards);

const analyzeBtnEl = $('analyzeBtn');
if (analyzeBtnEl) {
    analyzeBtnEl.addEventListener('click', () => {
        $('analyzeModal').classList.add('active');
    });
}
$('analyzeClose').addEventListener('click', () => closeModal('analyzeModal'));
$('analyzeCancel').addEventListener('click', () => closeModal('analyzeModal'));
$('detailClose').addEventListener('click', () => closeModal('detailModal'));
$('analyzeForm').addEventListener('submit', submitAnalysis);

$('detailModal').addEventListener('click', e => {
    if (e.target.id === 'detailModal') closeModal('detailModal');
});
$('analyzeModal').addEventListener('click', e => {
    if (e.target.id === 'analyzeModal') closeModal('analyzeModal');
});

$('lead-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const email = $('lead-email').value.trim();
    if (!email) { showError($('lead-error'), 'Enter an email'); return; }
    showError($('lead-error'), '');
    const btn = $('lead-add-btn');
    btn.disabled = true;
    setLoading('lead-loading', true, 'Adding lead...');
    try {
        const data = await postJson('/api/lead/parse', { email, use_sample: false });
        const exists = state.leads.find(l => (l.email || '').toLowerCase() === (data.email || '').toLowerCase());
        if (exists) {
            exists.parsed = data.parsed;
            exists.email = data.email;
        } else {
            state.leads.unshift({
                id: uid(),
                email: data.email,
                parsed: data.parsed,
                result: null,
                investigating: false,
                error: null,
            });
        }
        $('lead-email').value = '';
        saveState();
        renderLeadList();
    } catch (err) {
        showError($('lead-error'), err.message || String(err));
    } finally {
        btn.disabled = false;
        setLoading('lead-loading', false);
    }
});

$('company-form').addEventListener('submit', (e) => {
    e.preventDefault();
    const query = $('company-query').value.trim();
    if (!query) return;
    state.company.query = query;
    state.company.dossier = null;
    state.company.searching = true;
    state.company.progressPct = 0;
    state.company.progressStep = 'Starting pipeline...';
    renderCompanyPanel();
    showError($('company-error'), '');
    const btn = $('company-btn');
    btn.disabled = true;
    syncCompanySearchUi();

    const url = `/api/company/stream?query=${encodeURIComponent(query)}&fast=0`;
    const evtSource = new EventSource(url);
    let done = false;

    evtSource.onmessage = function(ev) {
        try {
            const msg = JSON.parse(ev.data);
            state.company.progressPct = msg.pct || 0;
            state.company.progressStep = msg.step || '';
            $('company-progress-fill').style.width = state.company.progressPct + '%';
            $('company-step').textContent = state.company.progressStep;
            if (msg.done) {
                done = true;
                evtSource.close();
                if (msg.error) {
                    state.company.dossier = null;
                    renderCompanyPanel();
                    showCompanyError(msg.error);
                    finishCompany();
                } else {
                    fetchCompanyResult(query);
                }
            }
        } catch (_) {}
    };

    evtSource.onerror = function() {
        evtSource.close();
        if (!done) { showError($('company-error'), 'Connection lost'); finishCompany(); }
    };

    async function fetchCompanyResult(q) {
        try {
            const res = await fetch('/api/reports');
            const data = await res.json();
            if (data.ok && data.reports) {
                const match = data.reports.find(r => (r.query || '').toLowerCase() === q.toLowerCase());
                const desc = ((match && match.overview) || {}).description || '';
                const short = (((match && match.overview) || {}).short_description || '').toLowerCase();
                if (match && (/may refer to/i.test(desc) || short.includes('same term') || short.includes('disambiguation'))) {
                    state.company.dossier = null;
                    showCompanyError('The name is too vague. Try a full company name or stock ticker.');
                } else if (match) {
                    state.company.dossier = match;
                }
            }
            saveState();
            renderCompanyPanel();
        } catch (err) {
            showError($('company-error'), err.message || String(err));
        }
        finishCompany();
    }

    function finishCompany() {
        state.company.searching = false;
        state.company.progressPct = 0;
        state.company.progressStep = '';
        btn.disabled = false;
        setLoading('company-loading', false);
        $('company-progress').style.display = 'none';
        $('company-progress-fill').style.width = '0%';
    }
});

function stopPeopleSearch() {
    activePeopleSearch.stopped = true;
    if (activePeopleSearch.controller) {
        try { activePeopleSearch.controller.abort(); } catch (_) {}
    }
    fetch('/api/linkedin/search/stop', { method: 'POST' }).catch(() => {});
}

async function streamPeopleSearch(body, signal) {
    const res = await fetch('/api/linkedin/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Accept': 'text/event-stream' },
        body: JSON.stringify(body),
        signal,
    });
    if (!res.ok) {
        let err = 'LinkedIn search failed';
        try {
            const payload = await res.json();
            if (payload && payload.error) err = payload.error;
        } catch (_) {}
        throw new Error(err);
    }
    const reader = res.body && res.body.getReader();
    if (!reader) throw new Error('LinkedIn search failed');
    const dec = new TextDecoder();
    let buf = '';
    let candidates = [];
    let profiles = [];
    let error = '';
    let cancelled = false;
    while (true) {
        const chunk = await reader.read();
        if (chunk.done) break;
        buf += dec.decode(chunk.value, { stream: true });
        let sep;
        while ((sep = buf.indexOf('\n\n')) >= 0) {
            const block = buf.slice(0, sep);
            buf = buf.slice(sep + 2);
            block.split('\n').forEach(line => {
                if (!line.startsWith('data:')) return;
                let msg;
                try { msg = JSON.parse(line.slice(5).trim()); } catch (_) { return; }
                if (!msg || typeof msg !== 'object') return;
                if (msg.step) applyPeopleSearchProgress(Number(msg.pct) || state.linkedin.progressPct || 0, msg.step);
                if (Array.isArray(msg.candidates)) candidates = msg.candidates;
                if (Array.isArray(msg.profiles)) profiles = msg.profiles;
                if (msg.cancelled) cancelled = true;
                if (msg.done) {
                    if (msg.error) error = String(msg.error);
                    if (Array.isArray(msg.candidates)) candidates = msg.candidates;
                    if (Array.isArray(msg.profiles)) profiles = msg.profiles;
                }
            });
        }
    }
    if (cancelled) {
        const err = new Error('cancelled');
        err.name = 'AbortError';
        throw err;
    }
    if (error) throw new Error(error);
    return { candidates, profiles };
}

$('people-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    if (state.linkedin.searching) {
        stopPeopleSearch();
        return;
    }
    const fields = readPeopleForm();
    const profileUrl = isLinkedInProfileUrl(fields.url) ? fields.url : (isLinkedInProfileUrl(fields.name) ? fields.name : '');
    if (profileUrl && isLinkedInProfileUrl(fields.name)) fields.name = '';
    if (!fields.name && !fields.email && !profileUrl) {
        showError($('people-error'), 'Enter a name, email, or profile URL');
        return;
    }
    if (state.linkedin.scraping || activeLinkedinScrape.source || activeLinkedinScrape.controller) stopLinkedInScrape();
    applyPeopleForm({ ...fields, url: profileUrl || fields.url });
    state.linkedin.searching = true;
    state.linkedin.progressPct = 0;
    state.linkedin.progressStep = profileUrl ? 'Looking up profile...' : 'Searching people...';
    state.linkedin.searched = false;
    state.linkedin.matchesOpen = true;
    state.linkedin.profiles = [];
    state.linkedin.candidates = [];
    state.linkedin.candidateUrls = [];
    showError($('people-error'), '');
    setPeopleActionButton(true);
    renderLinkedinPanel();
    activePeopleSearch.stopped = false;
    const controller = new AbortController();
    activePeopleSearch.controller = controller;
    syncLinkedinSearchUi();

    const steps = profileUrl
        ? [
            [15, 'Looking up profile...'],
            [35, 'Opening profile...'],
            [55, 'Waiting for page load...'],
            [70, 'Reading role and company...'],
            [85, 'Checking public contact pages...'],
        ]
        : [];
    let stepIdx = 0;
    const interval = profileUrl ? setInterval(() => {
        if (stepIdx < steps.length) {
            applyPeopleSearchProgress(steps[stepIdx][0], steps[stepIdx][1]);
            stepIdx++;
        }
    }, 4000) : null;

    try {
        const hints = peopleHints();
        if (profileUrl) {
            const data = await postJson('/api/linkedin', { url: profileUrl, hints }, controller.signal);
            if (activePeopleSearch.stopped) return;
            state.linkedin.profiles = data.profiles || (data.profile ? [data.profile] : []);
            state.linkedin.candidateUrls = [];
            state.linkedin.candidates = [];
        } else {
            applyPeopleSearchProgress(4, 'Opening LinkedIn...');
            const found = await streamPeopleSearch({
                name: fields.name || fields.email,
                company: fields.company,
                title: fields.role,
                location: fields.location,
                email: fields.email,
                max_profiles: 10,
            }, controller.signal);
            if (activePeopleSearch.stopped) return;
            if (found.profiles && found.profiles.length) {
                state.linkedin.profiles = found.profiles;
                state.linkedin.candidates = [];
                state.linkedin.candidateUrls = [];
            } else {
                state.linkedin.candidates = filterPeopleCandidates(
                    found.candidates || [],
                    fields.name || fields.email,
                    profileUrl
                );
                state.linkedin.candidateUrls = state.linkedin.candidates.map(c => c.url);
                state.linkedin.profiles = [];
                if (!state.linkedin.candidates.length && (fields.email || fields.phone || fields.company)) {
                    applyPeopleSearchProgress(90, 'Checking public contact pages...');
                    const enriched = await postJson('/api/people/enrich', hints, controller.signal);
                    if (activePeopleSearch.stopped) return;
                    if (enriched.profile) state.linkedin.profiles = [enriched.profile];
                }
            }
        }
        if (activePeopleSearch.stopped) return;
        state.linkedin.searched = true;
        state.linkedin.searching = false;
        saveState();
        if ($('people-progress-fill')) $('people-progress-fill').style.width = '100%';
        if ($('people-step')) $('people-step').textContent = 'Complete';
        renderLinkedinPanel();
    } catch (err) {
        if (activePeopleSearch.stopped || (err && err.name === 'AbortError')) {
            state.linkedin.searched = false;
            state.linkedin.searching = false;
            showError($('people-error'), '');
            renderLinkedinPanel();
        } else {
            state.linkedin.searched = true;
            state.linkedin.searching = false;
            showError($('people-error'), peopleSearchError(err.message || String(err)));
            renderLinkedinPanel();
        }
    } finally {
        if (interval) clearInterval(interval);
        activePeopleSearch.controller = null;
        state.linkedin.searching = false;
        state.linkedin.progressPct = 0;
        state.linkedin.progressStep = '';
        setPeopleActionButton(false);
        setLoading('people-loading', false);
        if ($('people-progress')) $('people-progress').style.display = 'none';
        if ($('people-progress-fill')) $('people-progress-fill').style.width = '0%';
    }
});

loadWorkspace().then(() => {
    if (!state.leads) state.leads = [];
    loadSampleLeads().then(() => {
        const hash = (location.hash || '#dashboard').replace('#', '');
        const mapped = hash === 'linkedin' ? 'people' : hash;
        const valid = ['dashboard', 'lead', 'company', 'people'];
        const initial = valid.includes(mapped) ? mapped : (state.tab === 'linkedin' ? 'people' : (state.tab || 'dashboard'));
        switchTab(initial);
    });
    loadReports().then(() => refreshBookmarkedCompanies());
    loadStats();
});
