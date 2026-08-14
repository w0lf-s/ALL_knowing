const state = {
    tab: 'dashboard',
    leads: [],
    company: { query: '', dossier: null, searching: false, progressPct: 0, progressStep: '' },
    linkedin: { url: '', company: '', profiles: [], candidateUrls: [], candidates: [], searching: false, searched: false, progressPct: 0, progressStep: '' },
    reports: [],
    bookmarks: [],
};

let activeLeadInvestigation = {
    leadId: null,
    controller: null,
};

let activeLinkedinScrape = {
    source: null,
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
            linkedin: state.linkedin,
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
                linkedin: {
                    url: li.url || '',
                    company: li.company || '',
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
        if (parsed.linkedin) {
            state.linkedin = parsed.linkedin;
            state.linkedin.searching = false;
            state.linkedin.scraping = false;
            state.linkedin.progressPct = 0;
            state.linkedin.progressStep = '';
            state.linkedin.scrapePct = 0;
            state.linkedin.scrapeStep = '';
        }
        if (parsed.tab) state.tab = parsed.tab;
        if (parsed.reports) state.reports = parsed.reports;
        if (Array.isArray(parsed.bookmarks)) state.bookmarks = parsed.bookmarks;
    } catch (_) {}
}
function applyWorkspace(data) {
    if (!data) return;
    if (Array.isArray(data.bookmarks)) state.bookmarks = data.bookmarks;
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
    if (data.linkedin && typeof data.linkedin === 'object') {
        state.linkedin = data.linkedin;
        state.linkedin.searching = false;
        state.linkedin.scraping = false;
        state.linkedin.progressPct = 0;
        state.linkedin.progressStep = '';
        state.linkedin.scrapePct = 0;
        state.linkedin.scrapeStep = '';
    }
}
async function loadWorkspace() {
    loadState();
    try {
        const res = await fetch('/api/workspace');
        const data = await res.json();
        if (!data || !data.ok) return;
        if (Array.isArray(data.bookmarks)) state.bookmarks = data.bookmarks;
        const remoteLeads = Array.isArray(data.leads) ? data.leads : [];
        const remoteLi = data.linkedin && typeof data.linkedin === 'object' ? data.linkedin : {};
        const liHas = !!(remoteLi.url || remoteLi.company || (remoteLi.profiles || []).length || (remoteLi.candidates || []).length);
        const hasRemote = remoteLeads.length || liHas;
        if (hasRemote) applyWorkspace({ ...data, bookmarks: state.bookmarks });
        else queueSaveState();
    } catch (_) {}
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

function syncLinkedinSearchUi() {
    if (!state.linkedin.searching) return;
    setLoading('linkedin-loading', true, state.linkedin.progressStep || 'Searching LinkedIn...');
    if ($('linkedin-progress')) $('linkedin-progress').style.display = 'block';
    if ($('linkedin-progress-fill')) $('linkedin-progress-fill').style.width = (state.linkedin.progressPct || 0) + '%';
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
        setLoading('linkedin-loading', false);
        if ($('linkedin-progress')) $('linkedin-progress').style.display = 'none';
        if ($('linkedin-progress-fill')) $('linkedin-progress-fill').style.width = '0%';
    }
    history.replaceState(null, '', `#${tab}`);
    saveState();
    renderAll();
    if (state.company.searching && tab === 'company') syncCompanySearchUi();
    if (state.linkedin.searching && tab === 'linkedin') syncLinkedinSearchUi();
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
        if (data && Array.isArray(data.bookmarks)) state.bookmarks = data.bookmarks;
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
        if (data.ok && Array.isArray(data.reports)) {
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

function renderProfiles(profiles, candidateUrls, candidates, opts) {
    const options = opts || {};
    let html = '';
    const urls = candidateUrls || [];
    const cands = candidates && candidates.length ? candidates : urls.map(u => ({ url: u, name: '' }));
    if (cands.length) {
        const scrapeBtn = options.allowScrape
            ? `<div class="card-actions" style="margin:0.75rem 0">
                <button type="button" class="btn btn-primary scrape-candidates-btn" ${options.scraping ? 'disabled' : ''}>
                    ${options.scraping ? 'Scraping profiles...' : 'Scrape profiles'}
                </button>
                ${options.scraping ? '<button type="button" class="btn btn-ghost scrape-stop-btn">Stop</button>' : ''}
               </div>
               ${options.scraping ? `<div class="loading-inline show"><div class="spinner-sm"></div><span class="linkedin-scrape-step">${esc(options.scrapeStep || 'Scraping LinkedIn profiles...')}</span></div>
               <div class="progress-bar" style="margin-top:0.5rem"><div class="progress-fill linkedin-scrape-fill" style="width:${options.scrapePct || 8}%"></div></div>` : ''}`
            : '';
        html += `<div class="card"><h3>LinkedIn candidates (${cands.length})</h3>${scrapeBtn}<table class="candidates-table">`;
        cands.forEach((item, i) => {
            const url = item.url || item;
            const name = candidateDisplayName(url, profiles, cands);
            html += `<tr><th>${i + 1}</th><td>${esc(name)}</td><td><a class="link" href="${esc(url)}" target="_blank">${esc(url)}</a></td>${options.allowScrape ? `<td><button type="button" class="btn btn-secondary scrape-one-btn" data-url="${esc(url)}" ${options.scraping ? 'disabled' : ''}>Scrape</button></td>` : ''}</tr>`;
        });
        html += `</table></div>`;
    }
    if (!profiles || !profiles.length) {
        if (!html) {
            if (options.searching) return '';
            if (options.searched) html = '<div class="card"><p class="muted">No linkedin profile found</p></div>';
            else html = '<div class="card"><p class="muted">Enter a name or LinkedIn URL</p></div>';
        }
        return html;
    }
    profiles.forEach((p, i) => {
        const profileUrl = p.linkedin_profile_url || p.url;
        html += `
        <div class="card">
            <h3>LinkedIn profile ${i + 1} — ${esc(p.name || 'Unknown')}</h3>
            <table>
                ${row('Headline', val(p.headline))}
                ${row('Role', val(p.current_role))}
                ${row('Company', val(p.current_company))}
                ${row('Location', val(p.location))}
                ${row('Email', val(p.email))}
                ${row('Phone', val(p.phone))}
                ${profileUrl ? row('Profile', `<a class="link" href="${esc(profileUrl)}" target="_blank">${esc(profileUrl)}</a>`) : ''}
                ${row('About', val(p.about))}
                ${p.error ? `<tr><th>Error</th><td style="color:#fca5a5">${esc(p.error)}</td></tr>` : ''}
            </table>
        </div>`;
    });
    return html;
}

function renderLeadLinkedInAction(lead) {
    const p = (lead && lead.parsed) || {};
    if (!p.name) return '<div class="card"><p class="muted">No linkedin profile found</p></div>';
    return `<div class="card">
        <h3>LinkedIn</h3>
        <div class="card-actions" style="margin-top:0">
            <button type="button" class="btn btn-primary linkedin-lookup-btn" data-id="${esc(lead.id)}">Look up on LinkedIn</button>
        </div>
    </div>`;
}

function isLinkedInProfileUrl(value) {
    return /linkedin\.com\/in\//i.test(String(value || ''));
}

function openLinkedInFromLead(id) {
    const lead = state.leads.find(l => l.id === id);
    if (!lead) return;
    const p = lead.parsed || {};
    const name = String(p.name || '').trim();
    if (!name) return;
    const company = p.is_corporate && p.company ? String(p.company).trim() : '';
    state.linkedin.url = name;
    state.linkedin.company = company;
    state.linkedin.profiles = [];
    state.linkedin.candidates = [];
    state.linkedin.candidateUrls = [];
    state.linkedin.searching = true;
    state.linkedin.searched = false;
    saveState();
    switchTab('linkedin');
    $('linkedin-form').requestSubmit();
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
    if (state.linkedin.url) $('linkedin-url').value = state.linkedin.url;
    if ($('linkedin-company')) $('linkedin-company').value = state.linkedin.company || '';
    $('linkedin-results').innerHTML = renderProfiles(
        state.linkedin.profiles,
        state.linkedin.candidateUrls,
        state.linkedin.candidates,
        { allowScrape: true, scraping: !!state.linkedin.scraping, scrapePct: state.linkedin.scrapePct || 0, scrapeStep: state.linkedin.scrapeStep || '', searching: !!state.linkedin.searching, searched: !!state.linkedin.searched }
    );
    const results = $('linkedin-results');
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
    state.linkedin.scrapeStep = total > 1 ? `Scraping profile 1 of ${total}` : 'Scraping profile...';
    if (!onlyUrl) state.linkedin.profiles = [];
    showError($('linkedin-error'), '');
    renderLinkedinPanel();

    const streamUrl = `/api/linkedin/stream?urls=${encodeURIComponent(JSON.stringify(urls))}`;
    const evtSource = new EventSource(streamUrl);
    let finished = false;
    activeLinkedinScrape.source = evtSource;
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

    function finish(err) {
        if (finished) return;
        finished = true;
        evtSource.close();
        activeLinkedinScrape.source = null;
        activeLinkedinScrape.finish = null;
        if (err && !activeLinkedinScrape.stopped) showError($('linkedin-error'), err);
        state.linkedin.scraping = false;
        state.linkedin.scrapePct = 0;
        state.linkedin.scrapeStep = '';
        saveState();
        renderLinkedinPanel();
    }

    activeLinkedinScrape.finish = finish;

    evtSource.onmessage = function(ev) {
        let msg = {};
        try { msg = JSON.parse(ev.data); } catch (_) { return; }
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
            if (state.linkedin.profiles.length) {
                const first = state.linkedin.profiles[0];
                state.linkedin.url = first.linkedin_profile_url || first.url || state.linkedin.url || '';
            }
            applyProgress(100, 'Complete');
            finish();
        }
    };
    evtSource.onerror = function() {
        if (!finished) finish(activeLinkedinScrape.stopped ? '' : 'Connection lost');
    };
}

function stopLinkedInScrape() {
    if (!state.linkedin.scraping) return;
    activeLinkedinScrape.stopped = true;
    fetch('/api/linkedin/scrape/stop', { method: 'POST' }).catch(() => {});
    if (typeof activeLinkedinScrape.finish === 'function') activeLinkedinScrape.finish();
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

$('linkedin-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const raw = $('linkedin-url').value.trim();
    if (!raw) return;
    const company = ($('linkedin-company') && $('linkedin-company').value.trim()) || '';
    state.linkedin.url = raw;
    state.linkedin.company = company;
    state.linkedin.searching = true;
    state.linkedin.progressPct = 0;
    state.linkedin.progressStep = isLinkedInProfileUrl(raw) ? 'Launching browser...' : 'Searching LinkedIn...';
    state.linkedin.searched = false;
    state.linkedin.profiles = [];
    state.linkedin.candidates = [];
    state.linkedin.candidateUrls = [];
    showError($('linkedin-error'), '');
    renderLinkedinPanel();
    const btn = $('linkedin-btn');
    btn.disabled = true;
    const asUrl = isLinkedInProfileUrl(raw);
    syncLinkedinSearchUi();

    const steps = asUrl
        ? [
            [15, 'Launching browser...'],
            [35, 'Navigating to profile...'],
            [55, 'Waiting for page load...'],
            [70, 'Extracting profile data...'],
            [85, 'Processing...'],
        ]
        : [
            [20, 'Opening LinkedIn search...'],
            [45, 'Reading people results...'],
            [70, 'Collecting profile links...'],
            [88, 'Finishing search...'],
        ];
    let stepIdx = 0;
    const interval = setInterval(() => {
        if (stepIdx < steps.length) {
            state.linkedin.progressPct = steps[stepIdx][0];
            state.linkedin.progressStep = steps[stepIdx][1];
            $('linkedin-progress-fill').style.width = state.linkedin.progressPct + '%';
            $('linkedin-step').textContent = state.linkedin.progressStep;
            stepIdx++;
        }
    }, 4000);

    try {
        if (asUrl) {
            const data = await postJson('/api/linkedin', { url: raw });
            state.linkedin.profiles = data.profiles || (data.profile ? [data.profile] : []);
            state.linkedin.candidateUrls = [];
            state.linkedin.candidates = [];
        } else {
            const data = await postJson('/api/linkedin/search', { name: raw, company, max_profiles: 5 });
            state.linkedin.candidates = data.candidates || [];
            state.linkedin.candidateUrls = data.candidate_urls || [];
            state.linkedin.profiles = [];
        }
        state.linkedin.searched = true;
        state.linkedin.searching = false;
        saveState();
        $('linkedin-progress-fill').style.width = '100%';
        $('linkedin-step').textContent = 'Complete';
        renderLinkedinPanel();
    } catch (err) {
        state.linkedin.searched = true;
        state.linkedin.searching = false;
        showError($('linkedin-error'), err.message || String(err));
        renderLinkedinPanel();
    } finally {
        clearInterval(interval);
        state.linkedin.searching = false;
        state.linkedin.progressPct = 0;
        state.linkedin.progressStep = '';
        btn.disabled = false;
        setLoading('linkedin-loading', false);
        $('linkedin-progress').style.display = 'none';
        $('linkedin-progress-fill').style.width = '0%';
    }
});

loadWorkspace().then(() => {
    if (!state.leads) state.leads = [];
    loadSampleLeads().then(() => {
        const hash = (location.hash || '#dashboard').replace('#', '');
        const valid = ['dashboard', 'lead', 'company', 'linkedin'];
        const initial = valid.includes(hash) ? hash : (state.tab || 'dashboard');
        switchTab(initial);
    });
    loadReports().then(() => refreshBookmarkedCompanies());
    loadStats();
});
