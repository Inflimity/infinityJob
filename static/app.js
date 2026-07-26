/**
 * ginNews Dashboard — Client Application
 *
 * Handles WebSocket live feed, REST API interactions,
 * alert rendering, filtering, actions, and real-time stats.
 */

(() => {
    'use strict';

    // ── State ───────────────────────────────────────────────────
    const state = {
        alerts: [],
        activeFilter: 'all',
        ws: null,
        wsRetryCount: 0,
        wsMaxRetries: 50,
        wsRetryDelay: 2000,
        statusPollInterval: null,
    };

    // ── DOM References ──────────────────────────────────────────
    const $ = (sel) => document.querySelector(sel);
    const $$ = (sel) => document.querySelectorAll(sel);

    const dom = {
        alertFeed: $('#alert-feed'),
        emptyState: $('#empty-state'),
        filterBar: $('#filter-bar'),
        monitorList: $('#monitor-list'),
        coinWatchlist: $('#coin-watchlist'),
        keywordWatchlist: $('#keyword-watchlist'),
        statusText: $('#status-text'),
        wsText: $('#ws-text'),
        wsClients: $('#ws-clients'),
        uptimeDisplay: $('#uptime-display'),
        statReceived: $('#stat-received'),
        statMatched: $('#stat-matched'),
        statDeduped: $('#stat-deduped'),
        statDispatched: $('#stat-dispatched'),
        toastContainer: $('#toast-container'),
    };

    // ── Platform Config ─────────────────────────────────────────
    const PLATFORM_META = {
        telegram: { icon: '📱', label: 'Telegram', color: '#0088cc' },
        discord:  { icon: '🎮', label: 'Discord',  color: '#5865f2' },
        twitter:  { icon: '🐦', label: 'X',        color: '#1da1f2' },
        reddit:   { icon: '🔴', label: 'Reddit',   color: '#ff4500' },
    };

    // ── WebSocket Connection ────────────────────────────────────

    function connectWebSocket() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws`;

        state.ws = new WebSocket(wsUrl);

        state.ws.onopen = () => {
            state.wsRetryCount = 0;
            updateWsStatus('connected');
            showToast('⚡ Live feed connected', 'success');
        };

        state.ws.onmessage = (event) => {
            try {
                const msg = JSON.parse(event.data);
                if (msg.type === 'alert') {
                    handleNewAlert(msg.data);
                } else if (msg.type === 'status') {
                    updateStats(msg.data);
                }
            } catch (e) {
                console.error('Failed to parse WebSocket message:', e);
            }
        };

        state.ws.onclose = () => {
            updateWsStatus('disconnected');
            attemptReconnect();
        };

        state.ws.onerror = () => {
            updateWsStatus('error');
        };

        // Heartbeat ping every 30s
        setInterval(() => {
            if (state.ws && state.ws.readyState === WebSocket.OPEN) {
                state.ws.send('ping');
            }
        }, 30000);
    }

    function attemptReconnect() {
        if (state.wsRetryCount >= state.wsMaxRetries) {
            updateWsStatus('failed');
            return;
        }

        state.wsRetryCount++;
        const delay = Math.min(state.wsRetryDelay * Math.pow(1.5, state.wsRetryCount - 1), 30000);
        updateWsStatus('reconnecting');

        setTimeout(() => connectWebSocket(), delay);
    }

    function updateWsStatus(status) {
        const statusMap = {
            connected:    { text: 'WebSocket: live', color: '#34d399' },
            disconnected: { text: 'WebSocket: disconnected', color: '#fb7185' },
            reconnecting: { text: `WebSocket: reconnecting (${state.wsRetryCount})...`, color: '#fbbf24' },
            error:        { text: 'WebSocket: error', color: '#fb7185' },
            failed:       { text: 'WebSocket: failed', color: '#fb7185' },
        };

        const info = statusMap[status] || statusMap.disconnected;
        dom.wsText.textContent = info.text;
        dom.wsText.style.color = info.color;
    }

    // ── Alert Handling ──────────────────────────────────────────

    function handleNewAlert(data) {
        // Add to state (newest first)
        state.alerts.unshift(data);

        // Cap at 200 alerts in memory
        if (state.alerts.length > 200) {
            state.alerts = state.alerts.slice(0, 200);
        }

        // Render if passes current filter
        if (state.activeFilter === 'all' || state.activeFilter === data.platform) {
            prependAlertCard(data, true);
            hideEmptyState();
        }
    }

    function prependAlertCard(alert, isNew = false) {
        const card = createAlertCard(alert, isNew);
        dom.alertFeed.insertBefore(card, dom.alertFeed.firstChild);

        // Remove excess cards from DOM (keep max 100)
        const cards = dom.alertFeed.querySelectorAll('.alert-card');
        if (cards.length > 100) {
            for (let i = 100; i < cards.length; i++) {
                cards[i].remove();
            }
        }
    }

    function createAlertCard(alert, isNew = false) {
        const meta = PLATFORM_META[alert.platform] || PLATFORM_META.telegram;
        const severity = alert.severity >= 4 ? 'high' : alert.severity >= 3 ? 'medium' : 'low';
        const timeStr = formatTime(alert.timestamp);
        const truncatedText = alert.text.length > 280
            ? alert.text.substring(0, 280) + '...'
            : alert.text;

        const card = document.createElement('div');
        card.className = `alert-card${isNew ? ' new' : ''}`;
        card.dataset.platform = alert.platform;
        card.dataset.alertId = alert.id || '';

        // Build tags
        const coinTags = (alert.matched_coins || [])
            .map(c => `<span class="tag coin">${c.toUpperCase()}</span>`)
            .join('');
        const keywordTags = (alert.matched_keywords || [])
            .map(k => `<span class="tag keyword">${k}</span>`)
            .join('');

        // Build link
        const linkHtml = alert.link
            ? `<a href="${escapeHtml(alert.link)}" target="_blank" rel="noopener" class="action-btn" title="Open source">🔗 Open</a>`
            : '';

        card.innerHTML = `
            <div class="alert-header">
                <div class="alert-platform">
                    <div class="platform-icon ${alert.platform}">${meta.icon}</div>
                    <div>
                        <div class="platform-name">${meta.label}</div>
                        <div class="alert-source">${escapeHtml(alert.source_name)} · ${escapeHtml(alert.author)}</div>
                    </div>
                </div>
                <span class="alert-severity severity-${severity}">⚡ ${alert.severity}</span>
            </div>
            <div class="alert-body">${escapeHtml(truncatedText)}</div>
            <div class="alert-tags">${coinTags}${keywordTags}</div>
            <div class="alert-footer">
                <span class="alert-time">${timeStr}</span>
                <div class="alert-actions">
                    ${linkHtml}
                    <button class="action-btn dismiss" onclick="ginNews.dismissAlert(this, ${alert.id || 0})" title="Dismiss">✅ Dismiss</button>
                    <button class="action-btn mute" onclick="ginNews.muteSource(this, ${alert.id || 0})" title="Mute source for 1h">🔇 Mute</button>
                    <button class="action-btn save" onclick="ginNews.saveAlert(this, ${alert.id || 0})" title="Bookmark">📌 Save</button>
                </div>
            </div>
        `;

        // Remove 'new' class after animation
        if (isNew) {
            setTimeout(() => card.classList.remove('new'), 600);
        }

        return card;
    }

    // ── Alert Actions ───────────────────────────────────────────

    async function dismissAlert(btn, alertId) {
        if (!alertId) return;
        btn.classList.add('done');
        btn.textContent = '✅ Done';
        try {
            await fetch(`/api/alerts/${alertId}/dismiss`, { method: 'POST' });
            showToast('✅ Alert dismissed', 'success');
        } catch (e) {
            showToast('⚠️ Failed to dismiss', 'error');
            btn.classList.remove('done');
        }
    }

    async function muteSource(btn, alertId) {
        if (!alertId) return;
        btn.classList.add('done');
        btn.textContent = '🔇 Muted';
        try {
            await fetch(`/api/alerts/${alertId}/mute?hours=1`, { method: 'POST' });
            showToast('🔇 Source muted for 1 hour', 'success');
        } catch (e) {
            showToast('⚠️ Failed to mute', 'error');
            btn.classList.remove('done');
        }
    }

    async function saveAlert(btn, alertId) {
        if (!alertId) return;
        btn.classList.add('done');
        btn.textContent = '📌 Saved';
        try {
            await fetch(`/api/alerts/${alertId}/save`, { method: 'POST' });
            showToast('📌 Alert bookmarked', 'success');
        } catch (e) {
            showToast('⚠️ Failed to save', 'error');
            btn.classList.remove('done');
        }
    }

    // ── Filtering ───────────────────────────────────────────────

    function initFilters() {
        dom.filterBar.addEventListener('click', (e) => {
            const btn = e.target.closest('.filter-btn');
            if (!btn) return;

            // Update active state
            dom.filterBar.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');

            state.activeFilter = btn.dataset.filter;
            renderAlertFeed();
        });
    }

    function renderAlertFeed() {
        // Clear existing cards
        dom.alertFeed.querySelectorAll('.alert-card').forEach(c => c.remove());

        const filtered = state.activeFilter === 'all'
            ? state.alerts
            : state.alerts.filter(a => a.platform === state.activeFilter);

        if (filtered.length === 0) {
            showEmptyState();
            return;
        }

        hideEmptyState();
        // Render in batches with staggered animation
        filtered.slice(0, 50).forEach((alert, i) => {
            const card = createAlertCard(alert);
            card.style.animationDelay = `${i * 0.03}s`;
            dom.alertFeed.appendChild(card);
        });
    }

    function showEmptyState() {
        dom.emptyState.style.display = 'flex';
    }

    function hideEmptyState() {
        dom.emptyState.style.display = 'none';
    }

    // ── Data Fetching ───────────────────────────────────────────

    async function fetchInitialAlerts() {
        try {
            const res = await fetch('/api/alerts?limit=50');
            if (!res.ok) return;
            const alerts = await res.json();
            state.alerts = alerts.map(a => ({
                ...a,
                timestamp: a.created_at,
            }));
            renderAlertFeed();
        } catch (e) {
            console.warn('Failed to fetch initial alerts:', e);
        }
    }

    async function fetchStatus() {
        try {
            const res = await fetch('/api/status');
            if (!res.ok) return;
            const status = await res.json();
            updateStats(status);
            updateMonitors(status.monitors);
            dom.statusText.textContent = status.status === 'running' ? 'System Active' : status.status;
        } catch (e) {
            dom.statusText.textContent = 'Offline';
        }
    }

    async function fetchConfig() {
        try {
            const res = await fetch('/api/config');
            if (!res.ok) return;
            const config = await res.json();
            renderWatchlist(config);
        } catch (e) {
            console.warn('Failed to fetch config:', e);
        }
    }

    // ── UI Updates ──────────────────────────────────────────────

    function updateStats(data) {
        const stats = data.stats || data;
        if (stats.received !== undefined) dom.statReceived.textContent = formatNumber(stats.received);
        if (stats.matched !== undefined) dom.statMatched.textContent = formatNumber(stats.matched);
        if (stats.deduplicated !== undefined) dom.statDeduped.textContent = formatNumber(stats.deduplicated);
        if (stats.dispatched !== undefined) dom.statDispatched.textContent = formatNumber(stats.dispatched);

        if (data.uptime_seconds !== undefined) {
            dom.uptimeDisplay.textContent = formatUptime(data.uptime_seconds);
        }
        if (data.websocket_clients !== undefined) {
            dom.wsClients.textContent = data.websocket_clients;
        }
    }

    function updateMonitors(monitors) {
        if (!monitors || !monitors.length) return;

        const monitorIcons = {
            telegram: '📱',
            discord: '🎮',
            twitter: '🐦',
        };

        dom.monitorList.innerHTML = monitors.map(m => {
            const name = m.charAt(0).toUpperCase() + m.slice(1);
            const icon = m.startsWith('reddit') ? '🔴' : (monitorIcons[m] || '📡');
            return `
                <div class="monitor-item">
                    <div class="monitor-info">
                        <span class="monitor-icon">${icon}</span>
                        <span class="monitor-name">${escapeHtml(name)}</span>
                    </div>
                    <span class="monitor-status active">Active</span>
                </div>
            `;
        }).join('');
    }

    function renderWatchlist(config) {
        if (config.coins) {
            dom.coinWatchlist.innerHTML = config.coins
                .map(c => `<span class="watch-tag">${escapeHtml(c.toUpperCase())}</span>`)
                .join('');
        }
        if (config.keywords) {
            dom.keywordWatchlist.innerHTML = config.keywords
                .map(k => `<span class="watch-tag">${escapeHtml(k)}</span>`)
                .join('');
        }
    }

    // ── Toast Notifications ─────────────────────────────────────

    function showToast(message, type = 'info') {
        const icons = { success: '✅', error: '❌', info: 'ℹ️' };
        const toast = document.createElement('div');
        toast.className = 'toast';
        toast.innerHTML = `<span>${icons[type] || ''}</span><span>${escapeHtml(message)}</span>`;
        dom.toastContainer.appendChild(toast);

        setTimeout(() => {
            toast.classList.add('leaving');
            setTimeout(() => toast.remove(), 300);
        }, 3000);
    }

    // ── Utilities ───────────────────────────────────────────────

    function escapeHtml(str) {
        if (!str) return '';
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    function formatTime(isoString) {
        if (!isoString) return '';
        try {
            const date = new Date(isoString);
            const now = new Date();
            const diffMs = now - date;
            const diffMin = Math.floor(diffMs / 60000);

            if (diffMin < 1) return 'just now';
            if (diffMin < 60) return `${diffMin}m ago`;
            if (diffMin < 1440) return `${Math.floor(diffMin / 60)}h ago`;
            return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
        } catch {
            return isoString;
        }
    }

    function formatNumber(n) {
        if (n === undefined || n === null) return '—';
        if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
        if (n >= 1000) return (n / 1000).toFixed(1) + 'K';
        return n.toLocaleString();
    }

    function formatUptime(seconds) {
        const h = Math.floor(seconds / 3600);
        const m = Math.floor((seconds % 3600) / 60);
        if (h > 0) return `${h}h ${m}m`;
        return `${m}m`;
    }

    // ── Initialization ──────────────────────────────────────────

    function init() {
        initFilters();
        fetchInitialAlerts();
        fetchStatus();
        fetchConfig();
        connectWebSocket();

        // Poll status every 15 seconds
        state.statusPollInterval = setInterval(fetchStatus, 15000);
    }

    // Expose action functions globally for inline onclick handlers
    window.ginNews = { dismissAlert, muteSource, saveAlert };

    // Boot
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
