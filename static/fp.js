/* ============================================
   VIRTUAL_PLUMBER False Positive Management JS
   ============================================ */

var FP_API = '/api/fp';
var currentFPView = 'my-requests';
var currentFPPage = 1;
var fpPollInterval = null;
var allRequestsCache = [];
var myRequestsCache = [];
var reviewQueueCache = [];
var currentRole = null;

// ============ Helpers ============
function escFP(str) {
    if (!str) return '';
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function toggleFindingMsg(id, link) {
    var shortEl = document.getElementById(id + '-short');
    var fullEl = document.getElementById(id + '-full');
    if (!shortEl || !fullEl) return;
    var showing = fullEl.style.display !== 'none';
    shortEl.style.display = showing ? '' : 'none';
    fullEl.style.display = showing ? 'none' : '';
    link.textContent = showing ? 'Show more' : 'Show less';
}

function formatScannerMsg(msg, baseId) {
    if (!msg) return '';
    var safe = String(msg).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
    var sectionRegex = /##\s+(.+?)\n([\s\S]*?)(?=\n##\s+|$)/g;
    var sections = [];
    var match;
    while ((match = sectionRegex.exec(msg)) !== null) {
        sections.push({ heading: match[1].trim(), body: match[2].trim() });
    }
    if (sections.length === 0) {
        if (safe.length <= 300) return safe;
        return '<span id="' + baseId + '-short">' + safe.substring(0, 300) + '...</span>' +
            '<span id="' + baseId + '-full" style="display:none;">' + safe + '</span>' +
            ' <a href="javascript:void(0)" onclick="toggleFindingMsg(\'' + baseId + '\', this)" style="color:#3b82f6;font-size:0.7rem;cursor:pointer;">Show more</a>';
    }
    var html = '';
    for (var i = 0; i < sections.length; i++) {
        var sec = sections[i];
        var secId = baseId + '-s' + i;
        var escHeading = String(sec.heading).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
        var escBody = String(sec.body).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
        var truncated = escBody.length > 200;
        html += '<div class="msg-section"><strong class="msg-section-heading">' + escHeading + '</strong>';
        if (truncated) {
            html += '<div class="msg-section-body" id="' + secId + '-short">' + escBody.substring(0, 200) + '...</div>' +
                '<div class="msg-section-body" id="' + secId + '-full" style="display:none;">' + escBody + '</div>' +
                ' <a href="javascript:void(0)" onclick="toggleFindingMsg(\'' + secId + '\', this)" style="color:#3b82f6;font-size:0.7rem;cursor:pointer;">Show more</a>';
        } else {
            html += '<div class="msg-section-body">' + escBody + '</div>';
        }
        html += '</div>';
    }
    return html;
}

function fpToast(msg, type) {
    var c = document.getElementById('fp-toast-container');
    if (!c) return;
    var t = document.createElement('div');
    t.className = 'fp-toast fp-toast-' + (type || 'info');
    t.textContent = msg;
    c.appendChild(t);
    setTimeout(function () { try { t.remove(); } catch (e) { } }, 5000);
}

function showFPStatus(el, msg, type) {
    if (!el) return;
    el.textContent = msg || '';
    el.className = 'fp-status-msg fp-status-' + (type || 'info');
    el.style.display = msg ? 'block' : 'none';
}

function formatDateFP(isoStr) {
    if (!isoStr) return 'N/A';
    var normalized = /[zZ]$|[+-]\d{2}:\d{2}$/.test(isoStr) ? isoStr : isoStr + 'Z';
    var d = new Date(normalized);
    return d.toLocaleString('en-US', { month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function timeAgoFP(isoStr) {
    if (!isoStr) return '';
    var normalized = /[zZ]$|[+-]\d{2}:\d{2}$/.test(isoStr) ? isoStr : isoStr + 'Z';
    var d = new Date(normalized);
    var now = new Date();
    var diffMs = now - d;
    var diffMin = Math.floor(diffMs / 60000);
    if (diffMin < 1) return 'just now';
    if (diffMin < 60) return diffMin + 'm ago';
    var diffHr = Math.floor(diffMin / 60);
    if (diffHr < 24) return diffHr + 'h ago';
    var diffDay = Math.floor(diffHr / 24);
    if (diffDay < 7) return diffDay + 'd ago';
    return formatDateFP(isoStr);
}

function getSeverityClass(sev) {
    return (sev || '').toLowerCase();
}

function getStatusLabel(status) {
    var labels = {
        'PENDING_OPERATOR': 'Pending Operator',
        'PENDING_ADMIN': 'Pending Admin',
        'APPROVED_FP': 'Approved FP',
        'OPERATOR_REJECTED': 'Rejected by Operator',
        'ADMIN_REJECTED': 'Rejected by Admin',
        'REVERTED_TO_TP': 'Reverted to TP'
    };
    return labels[status] || status || 'Unknown';
}

function getStatusClass(status) {
    var map = {
        'PENDING_OPERATOR': 'status-pending-operator',
        'PENDING_ADMIN': 'status-pending-admin',
        'APPROVED_FP': 'status-approved',
        'OPERATOR_REJECTED': 'status-rejected',
        'ADMIN_REJECTED': 'status-rejected',
        'REVERTED_TO_TP': 'status-reverted'
    };
    return map[status] || '';
}

function truncateFP(fp, maxLen) {
    if (!fp) return '';
    return fp.length > maxLen ? fp.substring(0, maxLen) + '...' : fp;
}

// ============ API ============
async function fpApiCall(url, options) {
    options = options || {};
    options.headers = options.headers || {};
    options.headers['Content-Type'] = options.headers['Content-Type'] || 'application/json';
    options.credentials = 'include';
    try {
        var resp = await fetch(url, options);
        var data = await resp.json();
        if (!resp.ok) {
            fpToast(data.error || 'Request failed (' + resp.status + ')', 'error');
            return null;
        }
        if (data.success === false) {
            fpToast(data.error || 'Request failed', 'error');
            return null;
        }
        return data;
    } catch (e) {
        fpToast('API request failed: ' + e.message, 'error');
        return null;
    }
}

// ============ Load Current User Role ============
async function loadCurrentRole() {
    var data = await fpApiCall('/api/me');
    if (data && data.user) {
        currentRole = data.user.role;
        applyRoleRestrictionsFP();
    }
}

function applyRoleRestrictionsFP() {
    var tabs = document.getElementById('fp-tabs');
    if (!tabs) return;
    var btns = tabs.querySelectorAll('.fp-tab-btn');
    var allowedViews = [];
    btns.forEach(function (b) {
        var v = b.getAttribute('data-fp-view');
        var hide = false;
        if (v === 'all-requests' && currentRole !== 'admin') {
            hide = true;
        }
        if (v === 'review-queue' && currentRole === 'viewer') {
            hide = true;
        }
        b.style.display = hide ? 'none' : '';
        if (!hide) allowedViews.push(v);
    });
    // If current view is not allowed, switch to first allowed view
    if (allowedViews.indexOf(currentFPView) === -1 && allowedViews.length > 0) {
        switchFPView(allowedViews[0]);
    }
    var statusFilter = document.getElementById('fp-status-filter');
    if (statusFilter && currentRole !== 'admin') {
        statusFilter.style.display = 'none';
    }
}

// ============ Tab Switching ============
function switchFPView(view) {
    currentFPView = view;
    localStorage.setItem('fpActiveView', view);
    document.querySelectorAll('.fp-view').forEach(function (v) { v.classList.remove('active'); });
    document.querySelectorAll('.fp-tab-btn').forEach(function (b) { b.classList.remove('active'); });
    var viewEl = document.getElementById('fp-view-' + view);
    if (viewEl) viewEl.classList.add('active');
    var btn = document.querySelector('.fp-tab-btn[data-fp-view="' + view + '"]');
    if (btn) btn.classList.add('active');

    if (view === 'my-requests') loadMyRequests();
    else if (view === 'review-queue') loadReviewQueue();
    else if (view === 'all-requests') loadAllRequests();
    stopFPPolling();
    startFPPolling();
}

// ============ Load Stats ============
async function loadFPStats() {
    var data = await fpApiCall(FP_API + '/requests?page=1&per_page=1000');
    if (!data || !data.requests) return;
    var requests = data.requests;
    var total = data.total || requests.length;
    var pendingOp = 0, pendingAd = 0, approved = 0, rejected = 0;
    requests.forEach(function(r) {
        if (r.status === 'PENDING_OPERATOR') pendingOp++;
        else if (r.status === 'PENDING_ADMIN') pendingAd++;
        else if (r.status === 'APPROVED_FP') approved++;
        else if (r.status === 'OPERATOR_REJECTED' || r.status === 'ADMIN_REJECTED') rejected++;
    });
    document.getElementById('stat-total').textContent = total;
    document.getElementById('stat-pending-operator').textContent = pendingOp;
    document.getElementById('stat-pending-admin').textContent = pendingAd;
    document.getElementById('stat-approved').textContent = approved;
    document.getElementById('stat-rejected').textContent = rejected;
}

// ============ Render Request Card ============
function renderRequestCard(r, context) {
    var sevClass = getSeverityClass(r.severity);
    var statusClass = getStatusClass(r.status);
    var statusLabel = getStatusLabel(r.status);
    var fp = truncateFP(r.fingerprint, 50);
    var fileLine = (r.file_path || '') + (r.line_number ? ':' + r.line_number : '');
    var created = timeAgoFP(r.created_at);
    var escFp = escFP(fp);
    var escFile = escFP(fileLine);
    var escTitle = escFP(r.title || '');
    var escSubmitter = escFP(r.submitter_username || 'Unknown');
    var escId = escFP(String(r.id));
    var escRepo = escFP(r.repo_name || '');
    var escTool = escFP(r.tool_name || '');
    var escCwe = escFP(r.cwe || '');

    var actionsHtml = '';

    var metaItems = '<span class="fp-meta-item">' + escFile + '</span>' +
        '<span class="fp-meta-item">by ' + escSubmitter + '</span>' +
        '<span class="fp-meta-item">' + created + '</span>';
    if (escRepo) metaItems += '<span class="fp-meta-item">' + escRepo + '</span>';
    if (escTool) metaItems += '<span class="fp-meta-item">' + escTool + '</span>';
    if (escCwe) metaItems += '<span class="fp-meta-item">CWE: ' + escCwe + '</span>';

    return '<div class="fp-request-card" data-fp-id="' + r.id + '" onclick="openFPDetail(' + r.id + ')">' +
        '<div class="fp-card-top">' +
        '<span class="fp-card-fingerprint" title="' + escFP(r.fingerprint) + '">' + escFp + '</span>' +
        '<span class="severity-badge ' + sevClass + '">' + escFP(r.severity || 'INFO') + '</span>' +
        '</div>' +
        '<div class="fp-card-title">' + escTitle + '</div>' +
        '<div class="fp-card-meta">' + metaItems + '</div>' +
        '<div class="fp-card-bottom">' +
        '<span class="fp-status-badge ' + statusClass + '">' + statusLabel + '</span>' +
        actionsHtml +
        '</div>' +
        '</div>';
}

function renderRequestList(requests, containerId, context) {
    var container = document.getElementById(containerId);
    if (!container) return;
    if (!requests || requests.length === 0) {
        container.innerHTML = '<div class="fp-empty">No requests found.</div>';
        return;
    }
    var html = '<div class="fp-card-grid">';
    requests.forEach(function (r) { html += renderRequestCard(r, context); });
    html += '</div>';
    container.innerHTML = html;
}

// ============ My Requests ============
async function loadMyRequests(silent) {
    var container = document.getElementById('fp-list-my-requests');
    if (!container) return;
    if (!silent) container.innerHTML = '<div class="fp-loading">Loading your requests...</div>';
    var data = await fpApiCall(FP_API + '/requests?page=1&per_page=100&status=my');
    if (!data) { if (!silent) container.innerHTML = '<div class="fp-empty">Failed to load requests.</div>'; return; }
    myRequestsCache = data.requests || [];
    renderRequestList(myRequestsCache, 'fp-list-my-requests', 'my');
}

function filterMyRequests(query) {
    var q = (query || '').toLowerCase();
    var filtered = myRequestsCache.filter(function (r) {
        return (r.fingerprint || '').toLowerCase().indexOf(q) !== -1 ||
            (r.title || '').toLowerCase().indexOf(q) !== -1 ||
            (r.file_path || '').toLowerCase().indexOf(q) !== -1;
    });
    renderRequestList(filtered, 'fp-list-my-requests', 'my');
}

// ============ Review Queue ============
async function loadReviewQueue(silent) {
    var container = document.getElementById('fp-list-review-queue');
    if (!container) return;
    if (!silent) container.innerHTML = '<div class="fp-loading">Loading review queue...</div>';
    var data = await fpApiCall(FP_API + '/queue');
    if (!data) { if (!silent) container.innerHTML = '<div class="fp-empty">Failed to load queue.</div>'; return; }
    reviewQueueCache = data.queue || [];
    renderRequestList(reviewQueueCache, 'fp-list-review-queue', 'review');
}

// ============ All Requests ============
async function loadAllRequests(silent) {
    var container = document.getElementById('fp-list-all-requests');
    if (!container) return;
    var statusInput = document.getElementById('fp-status-filter');
    var status = statusInput ? statusInput.value : '';
    if (!silent) container.innerHTML = '<div class="fp-loading">Loading all requests...</div>';
    var url = FP_API + '/requests?page=' + currentFPPage + '&per_page=50';
    if (status) url += '&status=' + status;
    var data = await fpApiCall(url);
    if (!data) { if (!silent) container.innerHTML = '<div class="fp-empty">Failed to load requests.</div>'; return; }
    allRequestsCache = data.requests || [];
    renderRequestList(allRequestsCache, 'fp-list-all-requests', 'all');
    renderPagination(data);
}

function filterAllRequests(query) {
    var q = (query || '').toLowerCase();
    var filtered = allRequestsCache.filter(function (r) {
        return (r.fingerprint || '').toLowerCase().indexOf(q) !== -1 ||
            (r.title || '').toLowerCase().indexOf(q) !== -1 ||
            (r.file_path || '').toLowerCase().indexOf(q) !== -1;
    });
    renderRequestList(filtered, 'fp-list-all-requests', 'all');
}

function renderPagination(data) {
    var container = document.getElementById('fp-pagination');
    if (!container) return;
    var total = data.total || 0;
    var pages = Math.ceil(total / (data.per_page || 50));
    if (pages <= 1) { container.innerHTML = ''; return; }
    var html = '';
    for (var i = 1; i <= pages; i++) {
        var active = i === currentFPPage ? ' class="active"' : '';
        html += '<button' + active + ' onclick="goToFPPage(' + i + ')">' + i + '</button>';
    }
    container.innerHTML = html;
}

function goToFPPage(page) {
    currentFPPage = page;
    loadAllRequests();
}

// ============ Detail Overlay ============
async function openFPDetail(requestId) {
    var overlay = document.getElementById('fp-detail-overlay');
    var body = document.getElementById('fp-detail-body');
    var footer = document.getElementById('fp-detail-footer');
    if (!overlay || !body) return;
    overlay.style.display = 'flex';
    body.innerHTML = '<div class="fp-loading">Loading detail...</div>';
    footer.innerHTML = '';

    var data = await fpApiCall(FP_API + '/requests/' + requestId);
    if (!data) { body.innerHTML = '<div class="fp-empty">Failed to load detail.</div>'; return; }
    var r = data.request || data;
    renderDetailContent(r, body, footer);
}

function renderDetailContent(r, body, footer) {
    var sevClass = getSeverityClass(r.severity);
    var statusClass = getStatusClass(r.status);
    var statusLabel = getStatusLabel(r.status);
    var escFp = escFP(r.fingerprint);
    var escFile = escFP(r.file_path || '');
    var escLine = escFP(String(r.line_number || ''));
    var escTitle = escFP(r.title || '');
    var escReason = escFP(r.viewer_reason || r.reason || '');
    var escSubmitter = escFP(r.submitter_username || 'Unknown');
    var escCreated = formatDateFP(r.created_at);
    var escUpdated = formatDateFP(r.updated_at);
    var escResolver = escFP(r.resolver_username || '');
    var escOperator = escFP(r.operator_username || '');
    var escRepo = escFP(r.repo_name || '');
    var escBranch = escFP(r.branch_name || '');
    var escCommit = escFP(r.commit_hash || '');
    var escTool = escFP(r.tool_name || '');
    var escCwe = escFP(r.cwe || '');
    var escScannerMsg = escFP(r.scanner_message || '');
    var escMatchedCode = escFP(r.matched_code || '');
    var escCodeContext = escFP(r.code_context || '');
    var escRemediation = escFP(r.remediation || '');
    var escOpMsg = escFP(r.operator_message || '');
    var escAdminMsg = escFP(r.admin_message || '');

    var html =
        '<div class="fp-detail-section">' +
        '<div class="fp-detail-row"><span class="detail-label">Status</span><span class="fp-status-badge ' + statusClass + '">' + statusLabel + '</span></div>' +
        '<div class="fp-detail-row"><span class="detail-label">Fingerprint</span><code class="detail-code">' + escFp + '</code></div>' +
        '<div class="fp-detail-row"><span class="detail-label">Title</span><span>' + escTitle + '</span></div>' +
        '<div class="fp-detail-row"><span class="detail-label">Severity</span><span class="severity-badge ' + sevClass + '">' + escFP(r.severity || 'INFO') + '</span></div>' +
        (escFile ? '<div class="fp-detail-row"><span class="detail-label">File</span><code class="detail-code">' + escFile + (escLine ? ':' + escLine : '') + '</code></div>' : '') +
        (escCwe ? '<div class="fp-detail-row"><span class="detail-label">CWE</span><span>' + escCwe + '</span></div>' : '') +
        (escTool ? '<div class="fp-detail-row"><span class="detail-label">Scanner</span><span>' + escTool + '</span></div>' : '') +
        (escRepo ? '<div class="fp-detail-row"><span class="detail-label">Repository</span><span>' + escRepo + (escBranch ? ' (' + escBranch + ')' : '') + '</span></div>' : '') +
        (escCommit ? '<div class="fp-detail-row"><span class="detail-label">Commit</span><code class="detail-code">' + escCommit + '</code></div>' : '') +
        '<div class="fp-detail-row"><span class="detail-label">Submitted by</span><span>' + escSubmitter + '</span></div>' +
        (escOperator ? '<div class="fp-detail-row"><span class="detail-label">Assigned Operator</span><span>' + escOperator + '</span></div>' : '') +
        '<div class="fp-detail-row"><span class="detail-label">Created</span><span>' + escCreated + '</span></div>' +
        (escUpdated && escUpdated !== escCreated ? '<div class="fp-detail-row"><span class="detail-label">Updated</span><span>' + escUpdated + '</span></div>' : '') +
        (escResolver ? '<div class="fp-detail-row"><span class="detail-label">Resolved by</span><span>' + escResolver + '</span></div>' : '') +
        '</div>';

    // Scanner message / finding description
    if (r.scanner_message) {
        var smId = 'fp-msg-' + r.id;
        html += '<div class="fp-detail-section"><h4>Scanner Message</h4>' + formatScannerMsg(r.scanner_message, smId) + '</div>';
    }

    // Matched code snippet
    if (escMatchedCode) {
        html += '<div class="fp-detail-section"><h4>Matched Code</h4><pre class="detail-code-block"><code>' + escMatchedCode + '</code></pre></div>';
    }

    // Code context
    if (escCodeContext) {
        html += '<div class="fp-detail-section"><h4>Code Context</h4><pre class="detail-code-block"><code>' + escCodeContext + '</code></pre></div>';
    }

    // Remediation
    if (escRemediation) {
        html += '<div class="fp-detail-section"><h4>Remediation</h4><p class="detail-reason">' + escRemediation + '</p></div>';
    }

    // Submitter reason
    if (escReason) {
        html += '<div class="fp-detail-section"><h4>Submitter Reason</h4><p class="detail-reason">' + escReason + '</p></div>';
    }

    // Operator message
    if (escOpMsg) {
        html += '<div class="fp-detail-section"><h4>Operator Notes</h4><p class="detail-reason">' + escOpMsg + '</p></div>';
    }

    // Admin message
    if (escAdminMsg) {
        html += '<div class="fp-detail-section"><h4>Admin Notes</h4><p class="detail-reason">' + escAdminMsg + '</p></div>';
    }

    // Resolution message (combined if single field used)
    if (r.resolution_message && !escOpMsg && !escAdminMsg) {
        html += '<div class="fp-detail-section"><h4>Resolution Message</h4><p class="detail-reason">' + escFP(r.resolution_message) + '</p></div>';
    }

    // Escalation history
    var history = r.history || r.escalation_history || [];
    if (history.length > 0) {
        html += '<div class="fp-detail-section"><h4>Escalation History</h4><div class="fp-escalation-chain">';
        history.forEach(function (h) {
            var hCreated = formatDateFP(h.created_at || h.timestamp || '');
            var hAction = escFP(h.action || h.new_status || h.from_role + ' → ' + h.to_role || 'Updated');
            var hUser = escFP(h.changed_by_username || h.user_id || 'System');
            var hMsg = escFP(h.message || '');
            html += '<div class="fp-escalation-step">' +
                '<span class="step-badge">' + hAction + '</span>' +
                '<span class="step-user">' + hUser + '</span>' +
                '<span class="step-time">' + hCreated + '</span>' +
                (hMsg ? '<span class="step-msg">' + hMsg + '</span>' : '') +
                '</div>';
        });
        html += '</div></div>';
    }

    body.innerHTML = html;

    // Footer actions
    var footerHtml = '<button class="btn-secondary" onclick="closeDetailOverlay()">Close</button>';
    if (r.status === 'PENDING_OPERATOR' || r.status === 'PENDING_ADMIN') {
        footerHtml +=
            '<div class="fp-detail-actions" style="display:flex;gap:0.5rem;align-items:center;margin-left:auto;">' +
            '<input type="text" id="fp-resolution-msg" class="form-input" style="width:200px;font-size:0.8rem;" placeholder="Optional message..." />' +
            '<button class="btn-sm btn-approve" onclick="approveFPRequest(' + r.id + ')">&#10003; Approve</button>' +
            '<button class="btn-sm btn-reject" onclick="rejectFPRequest(' + r.id + ')">&#10007; Reject</button>' +
            '</div>';
    } else if (r.status === 'APPROVED_FP' && currentRole === 'admin') {
        footerHtml +=
            '<div class="fp-detail-actions" style="display:flex;gap:0.5rem;align-items:center;margin-left:auto;">' +
            '<button class="btn-sm btn-revert" onclick="revertFPRequest(' + r.id + ')">&#x21A9; Revert</button>' +
            '</div>';
    }
    footer.innerHTML = footerHtml;
}

function closeDetailOverlay() {
    var el = document.getElementById('fp-detail-overlay');
    if (el) el.style.display = 'none';
}

// ============ Actions ============
async function approveFPRequest(requestId) {
    var msg = document.getElementById('fp-resolution-msg');
    var message = msg ? msg.value.trim() : '';
    var data = await fpApiCall(FP_API + '/requests/' + requestId + '/approve', {
        method: 'POST',
        body: JSON.stringify({ message: message })
    });
    if (!data) return;
    fpToast('Request approved', 'success');
    closeDetailOverlay();
    await refreshCurrentView();
}

async function rejectFPRequest(requestId) {
    var msg = document.getElementById('fp-resolution-msg');
    var message = msg ? msg.value.trim() : '';
    if (!message) {
        fpToast('Please provide a reason for rejection', 'warning');
        return;
    }
    var data = await fpApiCall(FP_API + '/requests/' + requestId + '/reject', {
        method: 'POST',
        body: JSON.stringify({ message: message })
    });
    if (!data) return;
    fpToast('Request rejected', 'info');
    closeDetailOverlay();
    await refreshCurrentView();
}

async function revertFPRequest(requestId) {
    if (!confirm('Revert this approved false positive? It will be treated as a valid finding again.')) return;
    var data = await fpApiCall(FP_API + '/requests/' + requestId + '/revert', {
        method: 'POST'
    });
    if (!data) return;
    fpToast('Request reverted', 'info');
    closeDetailOverlay();
    await refreshCurrentView();
}

async function refreshCurrentView() {
    await loadFPStats();
    await loadMyRequests();
    await loadReviewQueue();
    await loadAllRequests();
}

// ============ Polling ============
function startFPPolling() {
    stopFPPolling();
    fpPollInterval = setInterval(function () {
        loadFPStats();
        if (currentFPView === 'my-requests') loadMyRequests(true);
        else if (currentFPView === 'review-queue') loadReviewQueue(true);
        else if (currentFPView === 'all-requests') loadAllRequests(true);
    }, 5000);
}

function stopFPPolling() {
    if (fpPollInterval) {
        clearInterval(fpPollInterval);
        fpPollInterval = null;
    }
}

window.stopFPPolling = stopFPPolling;

// ============ Init ============
document.addEventListener('DOMContentLoaded', async function () {
    // Load role first so tab restrictions apply before view switch
    await loadCurrentRole();

    // Tab switching
    document.querySelectorAll('.fp-tab-btn').forEach(function (btn) {
        btn.addEventListener('click', function () {
            var view = this.getAttribute('data-fp-view');
            switchFPView(view);
        });
    });

    // Initial load
    loadFPStats();
    // Validate saved view against role restrictions
    var savedView = localStorage.getItem('fpActiveView') || 'my-requests';
    var allowedViews = [];
    document.querySelectorAll('.fp-tab-btn').forEach(function (b) {
        if (b.style.display !== 'none') allowedViews.push(b.getAttribute('data-fp-view'));
    });
    if (allowedViews.indexOf(savedView) === -1) savedView = allowedViews[0] || 'my-requests';
    switchFPView(savedView);
    startFPPolling();

    // Close overlay on Escape
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') closeDetailOverlay();
    });
});

// ============ Inline Init (called from dashboard.js when loaded inline) ============
window.initFPInline = async function () {
    // Attach tab click handlers (DOMContentLoaded already fired)
    document.querySelectorAll('.fp-tab-btn').forEach(function (btn) {
        btn.addEventListener('click', function () {
            var view = this.getAttribute('data-fp-view');
            switchFPView(view);
        });
    });
    // Load role first to apply restrictions before switching views
    await loadCurrentRole();
    loadFPStats();
    // Validate saved view against role restrictions
    var savedView = localStorage.getItem('fpActiveView') || 'my-requests';
    var allowedViews = [];
    document.querySelectorAll('.fp-tab-btn').forEach(function (b) {
        if (b.style.display !== 'none') allowedViews.push(b.getAttribute('data-fp-view'));
    });
    if (allowedViews.indexOf(savedView) === -1) savedView = allowedViews[0] || 'my-requests';
    switchFPView(savedView);
    startFPPolling();
};
