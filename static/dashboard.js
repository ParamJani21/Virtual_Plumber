/* ============================================
   VIRTUAL_PLUMBER Dashboard JavaScript
   Performance Optimized Edition
   ============================================ */

// ============ CACHING SYSTEM ============
// Cache for API responses with TTL (Time-To-Live in milliseconds)
const CACHE_TTL = 30000; // 30 seconds
const scanFindingsCache = {};

// Current user info
let currentUser = null;
let currentUserRole = null;

// Full repos list for client-side filtering
let allRepos = [];

// Full history list for client-side filtering
let allHistory = [];

// Debounce function for manual refresh
function debounce(func, delay) {
    let timeoutId;
    return function(...args) {
        clearTimeout(timeoutId);
        timeoutId = setTimeout(() => func(...args), delay);
    };
}

// Get cached data if fresh, otherwise return null
function getCachedFindings(scanId) {
    const cached = scanFindingsCache[scanId];
    if (!cached) return null;
    
    const now = Date.now();
    const age = now - cached.timestamp;
    
    if (age < CACHE_TTL) {
        return cached.data;
    }
    
    return null;
}

// Store findings in cache
function setCachedFindings(scanId, data) {
    scanFindingsCache[scanId] = {
        data: data,
        timestamp: Date.now()
    };
}

// Persist checkbox state to localStorage
function saveCheckboxState() {
    const checkedIds = Array.from(document.querySelectorAll('.scan-checkbox:checked'))
        .map(cb => cb.getAttribute('data-scan-id'));
    localStorage.setItem('checkedScans', JSON.stringify(checkedIds));
}

// Restore checkbox state from localStorage
function restoreCheckboxState() {
    try {
        const checkedIds = JSON.parse(localStorage.getItem('checkedScans') || '[]');
        checkedIds.forEach(id => {
            const cb = document.querySelector(`.scan-checkbox[data-scan-id="${id}"]`);
            if (cb) cb.checked = true;
        });
    } catch (e) {
        console.warn('Failed to restore checkbox state:', e);
    }
}

// Track expanded scans for this session
let expandedScanIds = new Set();

// ============ Simplified Retry Logic ============
const MAX_RETRIES = 2;
const RETRY_DELAY = 1000; // 1 second

// ============ Tab Management ============
document.addEventListener('DOMContentLoaded', function() {
    sendClientLog('page_domcontentloaded', { url: window.location.pathname, activeTab: localStorage.getItem('activeTab') || 'overview' });
    loadCurrentUser();
    initializeTabs();
    updateTimestamps();
    loadDynamicContent();
    initializeUserMenu();
    setInterval(updateTimestamps, 1000);

    // Restore scan detail overlay if it was open
    var savedScanId = localStorage.getItem('scanDetailId');
    if (savedScanId) {
        openScanDetail(savedScanId);
    }
});

function initializeTabs() {
    const tabButtons = document.querySelectorAll('.tab-button');
    const tabContents = document.querySelectorAll('.tab-content');

    sendClientLog('initializeTabs', { tabButtons: tabButtons.length, tabContents: tabContents.length });

    tabButtons.forEach(button => {
        button.addEventListener('click', function() {
            const tabName = this.getAttribute('data-tab');
            sendClientLog('tab_button_clicked', { tabName });
            switchTab(tabName);
        });
    });

    // Load last active tab from localStorage or default to 'overview'
    const lastActiveTab = localStorage.getItem('activeTab') || 'overview';
    switchTab(lastActiveTab);
}

// Load current user info
function loadCurrentUser() {
    fetch('/api/me', { credentials: 'include' })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success' && data.user) {
                currentUser = data.user;
                currentUserRole = data.user.role;
                applyRoleRestrictions();
            }
        })
        .catch(error => {
            console.error('Error loading current user:', error);
        });
}

// Check if user can start scans (operator or admin only)
function canStartScan() {
    return currentUserRole === 'operator' || currentUserRole === 'admin';
}

// Apply role-based UI restrictions
function applyRoleRestrictions() {
    console.log('Applying role restrictions for:', currentUserRole);

    // Show Users tab for admin and operator (operator can create viewers)
    const usersTab = document.querySelector('.tab-button[data-tab="users"]');
    if (usersTab) {
        usersTab.style.display = (currentUserRole !== 'viewer') ? '' : 'none';
    }

    // Show Settings tab for admin only
    const settingsTab = document.querySelector('.tab-button[data-tab="settings"]');
    if (settingsTab) {
        settingsTab.style.display = (currentUserRole === 'admin') ? '' : 'none';
    }

    // Disable scan buttons for viewer
    const scanButtons = document.querySelectorAll('.scan-btn, .scan-all-btn');
    scanButtons.forEach(btn => {
        btn.disabled = (currentUserRole === 'viewer');
        btn.style.opacity = (currentUserRole === 'viewer') ? '0.5' : '';
    });

    // Hide add user button for operator and viewer
    const addUserBtn = document.querySelector('.add-user-btn');
    if (addUserBtn) {
        addUserBtn.style.display = (currentUserRole === 'admin') ? '' : 'none';
    }

    // Update role dropdown in user modal based on current role
    const roleSelect = document.getElementById('user-role');
    if (roleSelect) {
        if (currentUserRole === 'admin') {
            roleSelect.innerHTML = '<option value="viewer">Viewer</option><option value="operator">Operator</option><option value="admin">Admin</option>';
        } else if (currentUserRole === 'operator') {
            roleSelect.innerHTML = '<option value="viewer">Viewer</option>';
        }
    }
}


function switchTab(tabName) {
    sendClientLog('switchTab_start', { tabName });
    // Hide all tabs
    document.querySelectorAll('.tab-content').forEach(tab => {
        tab.classList.remove('active');
    });

    // Remove active class from all buttons
    document.querySelectorAll('.tab-button').forEach(btn => {
        btn.classList.remove('active');
    });

    // Show selected tab
    const selectedTab = document.getElementById(tabName + '-tab');
    if (selectedTab) {
        selectedTab.classList.add('active');
    }

    // Add active class to corresponding button
    const tabButton = document.querySelector(`[data-tab="${tabName}"]`);
    if (tabButton) {
        tabButton.classList.add('active');
    }

    // Save active tab to localStorage
    localStorage.setItem('activeTab', tabName);

    // Load content if needed
    loadTabContent(tabName);
    sendClientLog('switchTab_complete', { tabName });
}

// ============ Dynamic Content Loading ============
// Client logging helper (global)
function sendClientLog(event, details = {}, level = 'info') {
    const payload = { event, details, level };
    const url = '/api/log';
    try {
        if (navigator && navigator.sendBeacon) {
            const blob = new Blob([JSON.stringify(payload)], { type: 'application/json' });
            navigator.sendBeacon(url, blob);
            return;
        }
    } catch (e) {
        // ignore and fallback to fetch
    }

    fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    }).catch(() => {});
}

function instrumentFetchLogging() {
    if (window.__fetchLoggingInstrumented) return;
    window.__fetchLoggingInstrumented = true;

    const originalFetch = window.fetch.bind(window);
    window.fetch = function(resource, init) {
        const url = typeof resource === 'string' ? resource : (resource && resource.url) ? resource.url : 'unknown';
        const method = (init && init.method) || (resource && resource.method) || 'GET';

        if (url !== '/api/log') {
            sendClientLog('fetch_start', { url, method }, 'debug');
        }

        return originalFetch(resource, init)
            .then(response => {
                if (url !== '/api/log') {
                    sendClientLog('fetch_complete', { url, method, status: response.status }, response.ok ? 'info' : 'warning');
                }
                return response;
            })
            .catch(error => {
                if (url !== '/api/log') {
                    sendClientLog('fetch_error', { url, method, message: error.message || String(error) }, 'error');
                }
                throw error;
            });
    };
}

function loadDynamicContent() {
    sendClientLog('loadDynamicContent_start');
    loadTabContent('overview');
    loadRepositories();
    renderScansChart();
    sendClientLog('loadDynamicContent_complete');
}

function loadTabContent(tabName) {
    sendClientLog('loadTabContent', { tabName });
    switch(tabName) {
        case 'repos':
            break;
        case 'history':
            loadHistory();
            break;
        case 'settings':
            loadSettings();
            break;
        case 'users':
            loadUsers();
            break;
        case 'false-positives':
            loadFPInlineContent();
            break;
        default:
            break;
    }
}

function loadFPInlineContent() {
    var container = document.getElementById('fp-inline-content');
    if (!container) return;
    fetch('/false-positives')
        .then(function(r) { return r.text(); })
        .then(function(html) {
            var match = html.match(/<main[^>]*>([\s\S]*?)<\/main>/);
            if (match) {
                container.innerHTML = match[1];
            } else {
                container.innerHTML = html;
            }
            if (window.initFPInline) {
                window.initFPInline();
            }
        })
        .catch(function(err) {
            container.innerHTML = '<div class="error">Failed to load FP Management</div>';
        });
}

function updateScanStatus() {
    fetch('/api/overview')
        .then(res => res.json())
        .then(data => {
            lastOverviewData = data;
            const container = document.getElementById('scan-status-container');
            if (!container) return;
            
            const activeScans = data.active_scans_list || [];
            const cooldown = data.bulk_cooldown || {};
            
            if (activeScans.length > 0) {
                const items = activeScans.map(s => {
                    let label = s.owner ? `${s.owner}/${s.repo_name}` : s.repo_name;
                    if (s.scan_id) label += ` [${s.scan_id.substring(0, 8)}]`;
                    return label;
                });
                container.innerHTML = `<span style="color: #22c55e;">● Scanning: ${items.join(', ')}</span>`;
            } else if (cooldown.active) {
                container.innerHTML = `<span style="color: #f59e0b;">● Cooling down ${cooldown.remaining}s — ${cooldown.current_repo} (${cooldown.repo_index}/${cooldown.total_repos})</span>`;
            } else {
                container.innerHTML = `<span style="color: #64748b;">✓ Ready to scan</span>`;
            }
        })
        .catch(() => {});
}

// Update scan status every 5 seconds
setInterval(updateScanStatus, 5000);
updateScanStatus();

function renderScansChart() {
    const ctx = document.getElementById('scansChart');
    if (!ctx) return;

    const useData = typeof lastOverviewData !== 'undefined' && lastOverviewData;
    const handler = (data) => {
        const scans = data.recent_scans || [];
        if (scans.length === 0) {
            ctx.parentElement.innerHTML = '<div style="color: #64748b; text-align: center; padding: 2rem; display: flex; flex-direction: column; justify-content: center; height: 200px;"><p>📊 No scans found yet</p><p style="font-size: 0.85rem; margin-top: 0.5rem;">Run a scan to see results</p></div>';
            return;
        }

        const labels = scans.map(s => {
            const repo = s.repository || 'Unknown';
            return repo.length > 15 ? repo.substring(0, 12) + '...' : repo;
        }).reverse();

        const criticalData = scans.map(s => s.severity.CRITICAL || 0).reverse();
        const highData = scans.map(s => s.severity.HIGH || 0).reverse();
        const mediumData = scans.map(s => s.severity.MEDIUM || 0).reverse();
        const lowData = scans.map(s => s.severity.LOW || 0).reverse();

        if (window.scansChartInstance) {
            window.scansChartInstance.destroy();
        }

        window.scansChartInstance = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [
                    { label: 'Critical', data: criticalData, backgroundColor: '#dc2626', borderRadius: 4 },
                    { label: 'High', data: highData, backgroundColor: '#ea580c', borderRadius: 4 },
                    { label: 'Medium', data: mediumData, backgroundColor: '#ca8a04', borderRadius: 4 },
                    { label: 'Low', data: lowData, backgroundColor: '#16a34a', borderRadius: 4 }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { position: 'top', labels: { color: '#94a3b8', font: { size: 11 } } },
                    title: { display: true, text: 'Recent Scan Results (Last 10)', color: '#f1f5f9', font: { size: 14 } }
                },
                scales: {
                    x: { stacked: true, ticks: { color: '#94a3b8', font: { size: 10 } }, grid: { color: '#334155' } },
                    y: { stacked: true, ticks: { color: '#94a3b8', font: { size: 10 } }, grid: { color: '#334155' }, beginAtZero: true }
                },
                barThickness: 35,
                categoryPercentage: 0.7,
                barPercentage: 0.95
            }
        });
    };

    if (useData) {
        handler(lastOverviewData);
    } else {
        fetch('/api/overview').then(r => r.json()).then(handler).catch(() => {});
    }
}

// Track selected branches per repo (repoId -> branch name)
const selectedBranches = new Map();

function loadRepositories() {
    const reposList = document.getElementById('repos-list');
    if (!reposList) return;
    sendClientLog('loadRepositories_start', { cached: !!localStorage.getItem('reposCache') });
    const cache = localStorage.getItem('reposCache');
    if (cache) {
        try {
            const cached = JSON.parse(cache);
            if (Array.isArray(cached) && cached.length > 0) {
                allRepos = cached;
                reposList.innerHTML = renderReposHtml(cached);
            }
        } catch (e) {
            console.warn('Invalid repos cache', e);
        }
    } else {
        reposList.innerHTML = '<div style="grid-column: 1 / -1; padding: 2rem 1rem; text-align: center; color: #64748b;">Loading repositories...</div>';
    }

    // Fetch fresh repos in background with timeout
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 10000);

    fetch('/api/repos', { signal: controller.signal })
        .then(response => response.json())
        .then(data => {
            clearTimeout(timeoutId);
            const repos = data.repositories || [];
            allRepos = repos;
            try { localStorage.setItem('reposCache', JSON.stringify(repos)); } catch (e) { /* ignore */ }
            reposList.innerHTML = repos.length > 0 ? renderReposHtml(repos) : '<div style="grid-column: 1 / -1; padding: 2rem; text-align: center; color: #64748b;">No repositories available</div>';
            sendClientLog('loadRepositories_success', { count: repos.length });
        })
        .catch(error => {
            clearTimeout(timeoutId);
            if (error.name === 'AbortError') {
                console.warn('Repo fetch aborted (timeout)');
                sendClientLog('loadRepositories_timeout', {}, 'warning');
            } else {
                console.error('Error loading repositories:', error);
                sendClientLog('loadRepositories_error', { message: error.message || String(error) }, 'error');
            }
        });
}

function renderReposHtml(repos) {
    let html = '';
    repos.forEach(repo => {
        let repoOwner = repo.owner || 'unknown';
        let repoUrl = repo.clone_url || repo.html_url || `https://github.com/${repoOwner}/${repo.name}.git`;
        let repoBranch = repo.branch || repo.default_branch || 'main';
        
        if (!selectedBranches.has(repo.id)) {
            selectedBranches.set(repo.id, repoBranch);
        }
        
        const escapedName = (repo.name || '').replace(/'/g, "\\'");
        const escapedOwner = (repoOwner || '').replace(/'/g, "\\'");
        const escapedUrl = (repoUrl || '').replace(/'/g, "\\'");
        
        html += `
            <div class="table-row">
                <div class="col-repo-name">${esc(repo.name || 'N/A')}</div>
                <div class="col-repo-id">${esc(repo.id || 'N/A')}</div>
                <div class="col-repo-branch">
                    <select id="branch-select-${repo.id}" class="branch-select" onchange="onBranchChange(${repo.id}, this.value)">
                        <option value="${esc(repoBranch)}">${esc(repoBranch)}</option>
                        <option value="loading" disabled>Loading branches...</option>
                    </select>
                </div>
                <div class="col-repo-action">
                    <button class="scan-btn" onclick="triggerManualScan('${repo.id}', '${escapedName}', '${escapedOwner}', '${escapedUrl}')">Scan</button>
                </div>
            </div>
        `;
    });
    
    setTimeout(() => {
        repos.forEach(repo => {
            fetchAndPopulateBranches(repo);
        });
    }, 100);
    
    return html;
}

// Filter repositories by search query
function filterRepos(query) {
    const reposList = document.getElementById('repos-list');
    if (!reposList) return;
    if (!query) {
        reposList.innerHTML = renderReposHtml(allRepos);
        return;
    }
    const q = query.toLowerCase();
    const filtered = allRepos.filter(repo =>
        (repo.name || '').toLowerCase().includes(q) ||
        (repo.owner || '').toLowerCase().includes(q) ||
        ((repo.name || '') + '/' + (repo.owner || '')).toLowerCase().includes(q)
    );
    reposList.innerHTML = filtered.length > 0
        ? renderReposHtml(filtered)
        : '<div style="grid-column: 1 / -1; padding: 2rem; text-align: center; color: #64748b;">No repositories match your search</div>';
}

// Filter history by search query
function filterHistory(query) {
    const historyList = document.getElementById('history-list');
    if (!historyList) return;
    if (!query) {
        renderFilteredHistory(allHistory);
        return;
    }
    const q = query.toLowerCase();
    const filtered = allHistory.filter(scan =>
        (scan.repository || '').toLowerCase().includes(q) ||
        (scan.branch || '').toLowerCase().includes(q) ||
        (scan.pr_number !== null && scan.pr_number !== undefined && String(scan.pr_number).includes(q))
    );
    renderFilteredHistory(filtered);
}

function fetchAndPopulateBranches(repo) {
    const selectElement = document.getElementById(`branch-select-${repo.id}`);
    if (!selectElement) return;
    
    const owner = repo.owner || 'unknown';
    const repoName = repo.name || '';
    
    fetch(`/api/branches/${owner}/${repoName}`)
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success' && data.branches && data.branches.length > 0) {
                const currentValue = selectElement.value;
                selectElement.innerHTML = '';
                
                data.branches.forEach(branch => {
                    const option = document.createElement('option');
                    option.value = branch;
                    option.textContent = branch;
                    option.selected = (branch === currentValue);
                    selectElement.appendChild(option);
                });
                
                if (!selectedBranches.has(repo.id)) {
                    selectedBranches.set(repo.id, data.branches[0]);
                }
            } else {
                console.warn(`Could not fetch branches for ${owner}/${repoName}`);
            }
        })
        .catch(error => {
            console.error(`Error fetching branches for ${owner}/${repoName}:`, error);
        });
}

function onBranchChange(repoId, selectedBranch) {
    selectedBranches.set(repoId, selectedBranch);

}

function showToast(message, type = 'info', timeout = 6000) {
    try {
        let container = document.getElementById('toast-container');
        if (!container) {
            container = document.createElement('div');
            container.id = 'toast-container';
            container.style.position = 'fixed';
            container.style.right = '1rem';
            container.style.bottom = '1rem';
            container.style.zIndex = 9999;
            document.body.appendChild(container);
        }

        const toast = document.createElement('div');
        toast.className = 'toast-notification toast-' + type;
        toast.style.background = type === 'error' ? '#ffdddd' : (type === 'success' ? '#e6ffed' : '#ffffff');
        toast.style.color = '#0f172a';
        toast.style.border = '1px solid #cbd5e1';
        toast.style.padding = '0.6rem 0.9rem';
        toast.style.marginTop = '0.5rem';
        toast.style.borderRadius = '6px';
        toast.style.boxShadow = '0 6px 18px rgba(2,6,23,0.08)';
        toast.style.maxWidth = '28rem';
        toast.style.fontSize = '0.95rem';
        toast.textContent = message;

        container.appendChild(toast);

        setTimeout(() => {
            try { toast.remove(); } catch (e) { /* ignore */ }
        }, timeout);
    } catch (e) {
        try { console.log('Toast:', message); } catch (e2) {}
    }
}

// ============ Scan Modal Functions ============
let pendingScanRepos = [];
let isScanAllMode = false;

function openScanModal(repos, isAll = false) {
    pendingScanRepos = repos;
    isScanAllMode = isAll;
    const modal = document.getElementById('scan-options-modal');
    if (modal) {
        modal.classList.add('show');
    }
}

function closeScanModal() {
    const modal = document.getElementById('scan-options-modal');
    if (modal) {
        modal.classList.remove('show');
    }
}

function getSelectedScanTypes() {
    const scanTypes = [];
    if (document.getElementById('scan-sats')?.checked) scanTypes.push('sats');
    if (document.getElementById('scan-sbom')?.checked) scanTypes.push('sbom');
    if (document.getElementById('scan-secret')?.checked) scanTypes.push('secret');
    return scanTypes;
}

function confirmScan() {
    const scanTypes = getSelectedScanTypes();
    
    if (scanTypes.length === 0) {
        showToast('Please select at least one scan type', 'error');
        return;
    }
    
    closeScanModal();
    
    if (isScanAllMode) {
        startScanAllRepos(scanTypes);
    } else if (pendingScanRepos.length > 0) {
        startSingleRepoScan(pendingScanRepos[0], scanTypes);
    }
    
    pendingScanRepos = [];
    isScanAllMode = false;
}

function startSingleRepoScan(repo, scanTypes) {
    sendClientLog('triggerManualScan_start', { repoId: repo.id, repoName: repo.name, scanTypes });
    
    fetch('/api/repos/scan', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ 
            repo_id: repo.id,
            repo_name: repo.name,
            repo_owner: repo.owner,
            repo_url: repo.url || `https://github.com/${repo.owner}/${repo.name}.git`,
            repo_branch: repo.branch || 'main',
            scan_types: scanTypes
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.status === 'success') {
            sendClientLog('triggerManualScan_success', { repoId: repo.id, repoName: repo.name, repo_path: data.repo_path });
            showToast(`✓ Scan completed for ${repo.owner}/${repo.name}`, 'success');
            updateScanStatus();
            loadHistory();
        } else {
            sendClientLog('triggerManualScan_error', { repoId: repo.id, message: data.message }, 'error');
            showToast(`✗ Scan failed: ${data.message}`, 'error');
        }
    })
    .catch(error => {
        console.error('Error triggering scan:', error);
        sendClientLog('triggerManualScan_error', { repoId: repo.id, message: error.message || String(error) }, 'error');
        showToast(`✗ Error: ${error.message || 'Failed to trigger scan'}`, 'error');
    });
}

function startScanAllRepos(scanTypes) {
    showToast(`Starting scan for all repositories... (${scanTypes.join(', ')})`, 'info');
    
    fetch('/api/repos')
        .then(response => response.json())
        .then(data => {
            const repos = data.repositories || [];
            const repoCount = repos.length;
            
            // Show success toast IMMEDIATELY (don't wait for scan to finish)
            showToast(`✓ Started scanning ${repoCount} repositories`, 'success');
            
            const reposWithBranches = repos.map(repo => ({
                repo_id: repo.id,
                repo_name: repo.name,
                repo_owner: repo.owner,
                repo_url: repo.clone_url || repo.html_url || `https://github.com/${repo.owner}/${repo.name}.git`,
                repo_branch: selectedBranches.get(repo.id) || repo.branch || 'main'
            }));
            
            fetch('/api/repos/scan-all', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ 
                    scan_types: scanTypes,
                    repos: reposWithBranches
                })
            })
            .then(response => response.json())
            .then(data => {
                if (data.status === 'success') {
                    loadHistory();
                    updateScanStatus();
                } else {
                    showToast(`✗ Scan error: ${data.message}`, 'error');
                }
            })
            .catch(error => {
                console.error('Error scanning all repos:', error);
                showToast(`✗ Error: ${error.message}`, 'error');
            });
        })
        .catch(error => {
            console.error('Error fetching repos:', error);
            showToast(`✗ Error fetching repositories: ${error.message}`, 'error');
        });
}

function scanAllRepos() {
    if (!canStartScan()) {
        showToast('Only operators and admins can start scans', 'error');
        return;
    }
    openScanModal([], true);
}

function triggerManualScan(repoId, repoName, repoOwner, repoUrl) {
    if (!canStartScan()) {
        showToast('Only operators and admins can start scans', 'error');
        return;
    }
    const selectedBranch = selectedBranches.get(parseInt(repoId)) || 'main';
    
    const repo = {
        id: repoId,
        name: repoName,
        owner: repoOwner,
        url: repoUrl,
        branch: selectedBranch
    };
    openScanModal([repo], false);
}

// ============ OPTIMIZED HISTORY LOADING - LAZY LOAD FINDINGS ============
function loadHistory() {
    const historyList = document.getElementById('history-list');
    if (!historyList) return;

    sendClientLog('loadHistory_start');
    
    syncDeleteButtonState();

    fetch('/api/history')
        .then(response => response.json())
        .then(data => {
            allHistory = data.history || [];
            
            // Apply any existing search filter
            const searchInput = document.getElementById('history-search-input');
            const query = searchInput ? searchInput.value : '';
            if (query) {
                filterHistory(query);
                return;
            }
            
            let html = '';
            if (allHistory.length > 0) {
                allHistory.forEach(scan => {
                    const severity = scan.severity || {};
                    const category = scan.category || {};
                    const multiSource = scan.multi_source || 0;
                    const branch = scan.branch || 'unknown';
                    
                    const critical = severity.CRITICAL || 0;
                    const high = severity.HIGH || 0;
                    const medium = severity.MEDIUM || 0;
                    const low = severity.LOW || 0;
                    const total = scan.total_findings || 0;
                    const prLabel = scan.is_pr_scan ? ' <span class="pr-label">PR</span>' : '';
                    
                    html += `
                        <div class="history-item" data-scan-id="${esc(scan.scan_id)}">
                            <div class="history-row" onclick="openScanDetail('${esc(scan.scan_id)}')">
                                <div class="col-checkbox">
                                    <input type="checkbox" class="scan-checkbox" data-scan-id="${esc(scan.scan_id)}" onclick="event.stopPropagation(); updateDeleteButton(); saveCheckboxState()">
                                </div>
                                <div class="col-time">${formatDate(scan.timestamp)}</div>
                                <div class="col-repo">${esc(scan.repository || 'Unknown')}${prLabel}</div>
                                <div class="col-branch">${esc(branch)}</div>
                                <div class="col-total">${total}</div>
                                <div class="col-severity">
                                    <span class="severity-badge critical">C${critical}</span>
                                    <span class="severity-badge high">H${high}</span>
                                    <span class="severity-badge medium">M${medium}</span>
                                    <span class="severity-badge low">L${low}</span>
                                </div>
                                 <div class="col-multi">${multiSource > 0 ? multiSource : '-'}</div>
                             </div>
                           </div>`;
                   });
            } else {
                html = '<div style="grid-column: 1 / -1; padding: 2rem; text-align: center; color: #64748b;">No scans found. Trigger a scan to see results here.</div>';
            }
            historyList.innerHTML = html;
            
            // Restore expanded state
            expandedScanIds.forEach(scanId => {
                const details = document.getElementById('details-' + scanId);
                const btn = document.querySelector(`[data-scan-id="${scanId}"] .view-detail-btn`);
                if (details) {
                    details.style.display = 'block';
                    if (btn) btn.innerHTML = '▼';
                } else {
                    expandedScanIds.delete(scanId);
                }
            });
            
            // Restore checkbox state from localStorage
            restoreCheckboxState();
            
            // Update stats
            document.getElementById('total-scans').textContent = data.stats.total_scans || 0;
            document.getElementById('total-findings').textContent = data.stats.total_findings || 0;
            document.getElementById('critical-issues').textContent = data.stats.critical_issues || 0;
            
            sendClientLog('loadHistory_success', { count: data.history ? data.history.length : 0 });
        })
        .catch(error => {
            console.error('Error loading history:', error);
            sendClientLog('loadHistory_error', { message: error.message || String(error) }, 'error');
        });
}

// ============ LAZY LOAD FINDINGS - CALLED WHEN USER EXPANDS ============
function loadScanFindings(scanId) {
    const container = document.getElementById('findings-' + scanId);
    if (!container) {
        console.error('❌ Container NOT found for:', 'findings-' + scanId);
        return;
    }
    
    
    const cachedData = getCachedFindings(scanId);
    if (cachedData) {
        renderFindings(scanId, cachedData, container);
        // Fetch fresh data in background
        fetchAndCacheFindings(scanId, container, true);
        return;
    }
    
    // Show loading message
    const loadingDiv = container.querySelector('.findings-loading');
    if (loadingDiv) {
        loadingDiv.style.display = 'block';
    }
    
    fetchAndCacheFindings(scanId, container, false);
}

// Fetch findings with simplified retry logic
function fetchAndCacheFindings(scanId, container, isBackground = false) {
    let attempts = 0;
    
    function retry() {
        attempts++;
        
        fetch('/api/history/' + scanId)
            .then(response => {
                
                if (response.status === 202) {
                    if (attempts < MAX_RETRIES) {
                        setTimeout(retry, RETRY_DELAY);
                    } else {
                        if (!isBackground) {
                            container.innerHTML = '<p style="color:#f87171;"><strong>Still loading findings...</strong> Results may still be being processed. Please try again in a few moments.</p>';
                        }
                    }
                    return null;
                }
                
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                }
                
                return response.json();
            })
            .then(data => {
                if (data === null) return;
                
                
                // Cache the data
                setCachedFindings(scanId, data);
                
                // Render findings
                renderFindings(scanId, data, container);
            })
            .catch(err => {
                console.error(`❌ Error loading findings for ${scanId}:`, err.message);
                
                if (attempts < MAX_RETRIES) {
                    setTimeout(retry, RETRY_DELAY);
                } else {
                    if (!isBackground) {
                        container.innerHTML = `<p style="color:#f87171;"><strong>Failed to load findings</strong><br><code style="font-size:12px;">${esc(err.message)}</code></p>`;
                    }
                }
            });
    }
    
    retry();
}

// Render findings to container, grouped by file
function renderFindings(scanId, data, container) {
    fpFindingIndex = 0;
    let findings = [];
    
    if (data.files && data.files.merged) {
        const merged = data.files.merged;
        if (Array.isArray(merged.findings)) {
            findings = merged.findings;
        } else if (merged.findings && typeof merged.findings === 'object') {
            findings = Object.values(merged.findings);
        }
    } else if (data.findings) {
        findings = Array.isArray(data.findings) ? data.findings : Object.values(data.findings);
    }
    
    if (!Array.isArray(findings)) {
        findings = [];
    }
    
    if (!findings || findings.length === 0) {
        container.innerHTML = '<h5>All Findings from merged.json</h5><p style="color:#94a3b8;font-style:italic;">No findings found</p>';
        return;
    }
    

    // Sort by severity: CRITICAL > HIGH > MEDIUM > LOW > others
    const severityOrder = { 'CRITICAL': 0, 'HIGH': 1, 'MEDIUM': 2, 'LOW': 3, 'WARNING': 4, 'INFO': 5 };
    findings.sort((a, b) => {
        const orderA = severityOrder[a.severity?.toUpperCase()] ?? 99;
        const orderB = severityOrder[b.severity?.toUpperCase()] ?? 99;
        return orderA - orderB;
    });

    // Group findings by file
    const fileGroups = new Map();
    findings.forEach(f => {
        const file = f.file || 'unknown';
        if (!fileGroups.has(file)) {
            fileGroups.set(file, []);
        }
        fileGroups.get(file).push(f);
    });

    let findingsHtml = '<h5>All Findings from merged.json (' + findings.length + ')</h5>';
    
    // Source filter buttons (show when 2+ unique sources)
    const allSources = new Set();
    findings.forEach(f => (f.sources || []).forEach(s => allSources.add(s)));
    const sourcesArr = Array.from(allSources).sort();
    if (sourcesArr.length >= 2) {
        findingsHtml += '<div class="source-filter-bar" style="margin:0.5rem 0 1rem 0;display:flex;gap:0.4rem;flex-wrap:wrap;">';
        findingsHtml += '<button class="source-filter-btn active" data-source="all" onclick="window.filterBySource(this,\'all\')">All</button>';
        sourcesArr.forEach(s => {
            findingsHtml += '<button class="source-filter-btn" data-source="' + esc(s) + '" onclick="window.filterBySource(this,\'' + esc(s) + '\')">' + esc(s) + '</button>';
        });
        findingsHtml += '</div>';
    }
    
    findingsHtml += '<div class="findings-file-groups">';

    fileGroups.forEach((fileFindings, file) => {
        const groupId = `file-group-${scanId}-${file.replace(/[^a-zA-Z0-9_-]/g, '-')}`;
        const fileEsc = esc(file);
        
        const allFileSuppressed = fileFindings.every(f => f.suppressed);
        
        // Collect all unique severities in this group, sorted worst-first
        const sevs = new Set();
        fileFindings.forEach(f => {
            const s = f.severity ? f.severity.toUpperCase() : '';
            if (s) sevs.add(s);
        });
        const severityBadges = Array.from(sevs)
            .sort((a, b) => (severityOrder[a] ?? 99) - (severityOrder[b] ?? 99))
            .map(s => `<span class="severity-badge ${s.toLowerCase()}">${esc(s)}</span>`)
            .join(' ');
        
        // Sub-group by tool within this file
        const toolGroups = new Map();
        fileFindings.forEach(f => {
            const tool = (f.sources && f.sources.length > 0) ? f.sources[0] : 'unknown';
            if (!toolGroups.has(tool)) {
                toolGroups.set(tool, []);
            }
            toolGroups.get(tool).push(f);
        });
        
        findingsHtml += `
            <div class="finding-file-group${allFileSuppressed ? ' all-suppressed' : ''}">
                <div class="finding-file-header" onclick="toggleFileGroup('${groupId}')">
                    <span class="file-group-toggle">▼</span>
                    <span class="file-group-name">${fileEsc}</span>
                    <span class="file-group-count">${fileFindings.length} finding${fileFindings.length > 1 ? 's' : ''}</span>
                    <span class="file-group-severities">${severityBadges}</span>
                </div>
                <div class="file-group-items" id="${groupId}">`;

        toolGroups.forEach((toolFindings, tool) => {
            const toolGroupId = `tool-group-${scanId}-${file.replace(/[^a-zA-Z0-9_-]/g, '-')}-${tool}`;
            const toolWorst = getWorstSeverity(toolFindings);
            const toolEsc = esc(tool);
            const allToolSuppressed = toolFindings.every(f => f.suppressed);
            
            findingsHtml += `
                <div class="finding-tool-group${allToolSuppressed ? ' all-suppressed' : ''}">
                    <div class="finding-tool-header" onclick="toggleToolGroup('${toolGroupId}', this)">
                        <span class="tool-group-toggle">▶</span>
                        <span class="tool-group-name">${toolEsc}</span>
                        <span class="file-group-count">${toolFindings.length} finding${toolFindings.length > 1 ? 's' : ''}</span>
                    </div>
                    <div class="tool-group-items" id="${toolGroupId}" style="display:none;">`;

            // Within each tool group, check if findings have package info (Trivy)
            const hasPackage = toolFindings.some(f => f.details && f.details.trivy && f.details.trivy.package);

            if (hasPackage) {
                // Sub-group by package
                const packageGroups = new Map();
                toolFindings.forEach(f => {
                    const pkg = (f.details && f.details.trivy && f.details.trivy.package) || '';
                    const key = pkg || '__no_package__';
                    if (!packageGroups.has(key)) {
                        packageGroups.set(key, []);
                    }
                    packageGroups.get(key).push(f);
                });

                packageGroups.forEach((pkgFindings, key) => {
                    const pkg = key === '__no_package__' ? 'Miscellaneous' : pkgFindings[0].details?.trivy?.package || 'Unknown';
                    const pkgGroupId = `pkg-group-${scanId}-${file.replace(/[^a-zA-Z0-9_-]/g, '-')}-${tool}-${key.replace(/[^a-zA-Z0-9_-]/g, '-')}`;
                    const pkgWorst = getWorstSeverity(pkgFindings);
                    const pkgEsc = esc(pkg);
                    const allPkgSuppressed = pkgFindings.every(f => f.suppressed);

                    findingsHtml += `
                        <div class="finding-package-group${allPkgSuppressed ? ' all-suppressed' : ''}">
                            <div class="finding-package-header" onclick="togglePackageGroup('${pkgGroupId}', this)">
                                <span class="package-group-toggle">▶</span>
                                <span class="package-group-name">${pkgEsc}</span>
                                <span class="file-group-count">${pkgFindings.length} finding${pkgFindings.length > 1 ? 's' : ''}</span>
                            </div>
                            <div class="package-group-items" id="${pkgGroupId}" style="display:none;">`;

                    pkgFindings.forEach(function (f) {
                        findingsHtml += renderFindingItem(f, fpFindingIndex++);
                    });

                    findingsHtml += `</div></div>`;
                });
            } else {
                // No package info, list findings directly
                toolFindings.forEach(function (f) {
                    findingsHtml += renderFindingItem(f, fpFindingIndex++);
                });
            }

            findingsHtml += `</div></div>`;
        });

        findingsHtml += `</div></div>`;
    });

    findingsHtml += '</div>';
    container.innerHTML = findingsHtml;
}

// Render a single finding item
var fpFindingIndex = 0;

function formatScannerMsg(msg, baseId) {
    if (!msg) return '';
    var safe = String(msg).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
    // Check for ## sections (markdown H2) — common in Trivy/Snyk advisories
    var sectionRegex = /##\s+(.+?)\n([\s\S]*?)(?=\n##\s+|$)/g;
    var sections = [];
    var match;
    while ((match = sectionRegex.exec(msg)) !== null) {
        sections.push({
            heading: match[1].trim(),
            body: match[2].trim()
        });
    }
    if (sections.length === 0) {
        if (safe.length <= 300) return safe;
        return '<span id="' + baseId + '-short">' + safe.substring(0, 300) + '...</span>' +
            '<span id="' + baseId + '-full" style="display:none;">' + safe + '</span>' +
            ' <a href="javascript:void(0)" onclick="toggleFindingMsg(\'' + baseId + '\', this)" style="color:#3b82f6;font-size:0.7rem;cursor:pointer;">Show more</a>';
    }
    // Render sections
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

function renderFindingItem(f, findingIdx) {
    const severityClass = (f.severity || '').toLowerCase();
    const cwe = (f.cwe || []).join(', ');
    const lineNum = f.line;
    const typeEsc = esc(f.type || 'unknown');
    const sevEsc = esc(f.severity || 'INFO');
    const titleEsc = esc(f.title || 'Untitled');
    const msgEsc = esc(f.message);
    const fileEsc2 = esc(f.file);
    const suppClass = f.suppressed ? ' fp-suppressed' : '';
    const suppBadge = f.suppressed ? ' <span class="fp-approved-badge">&#10003; FP Approved</span>' : '';

    let html = `
        <div class="finding-item${suppClass}" data-fp-index="${findingIdx}" data-source="${esc((f.sources || []).join(','))}">
            <div class="finding-header">
                <input type="checkbox" class="fp-finding-checkbox" data-fp-index="${findingIdx}" onchange="onFindingCheckboxChange()" style="margin-right:0.5rem;accent-color:#f59e0b;">
                <span class="finding-file">${lineNum > 0 ? fileEsc2 + ':' + lineNum : fileEsc2}</span>
                <span class="finding-type">${typeEsc}</span>
                <span class="severity-badge ${severityClass}">${sevEsc}</span>${suppBadge}
            </div>
            <div class="finding-title">${titleEsc}</div>`;
    if (msgEsc) {
        var msgId = 'msg-' + (findingIdx != null ? findingIdx : Math.random().toString(36).substr(2, 9));
        html += '<div class="finding-message">' + formatScannerMsg(f.message, msgId) + '</div>';
    }
    if (f.details && f.details.trivy) {
        html += `<div class="finding-version"><span class="version-installed">${esc(f.details.trivy.installed)}</span> → <span class="version-fixed">${esc(f.details.trivy.fixed)}</span></div>`;
    }
    if (cwe) {
        html += `<div class="finding-cwe">CWE: ${esc(cwe)}</div>`;
    }
    html += `<div class="source-badges">${(f.sources || []).map(s => `<span class="source-badge">${esc(s)}</span>`).join('')}</div>
        </div>`;
    return html;
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

function toggleSuppressedFindings() {
    var overlay = document.getElementById('scan-overlay-content');
    var toggle = document.getElementById('fp-show-toggle');
    if (overlay && toggle) {
        if (toggle.checked) {
            overlay.classList.add('show-suppressed-fp');
        } else {
            overlay.classList.remove('show-suppressed-fp');
        }
    }
}

window.filterBySource = function(btn, source) {
    document.querySelectorAll('.source-filter-btn').forEach(function(b) { b.classList.remove('active'); });
    btn.classList.add('active');
    document.querySelectorAll('.finding-item').forEach(function(item) {
        var primarySource = (item.getAttribute('data-source') || '').split(',')[0] || '';
        if (source === 'all') {
            item.style.display = '';
        } else {
            item.style.display = primarySource === source ? '' : 'none';
        }
    });
    document.querySelectorAll('.finding-file-group, .finding-tool-group, .finding-package-group').forEach(function(group) {
        var allItems = group.querySelectorAll('.finding-item');
        var hasVisible = false;
        allItems.forEach(function(item) {
            if (item.style.display !== 'none') hasVisible = true;
        });
        group.style.display = hasVisible ? '' : 'none';
    });
};

// Toggle package sub-sub-group expand/collapse
function togglePackageGroup(groupId, header) {
    const group = document.getElementById(groupId);
    if (!group) return;
    const toggle = header.querySelector('.package-group-toggle');
    if (group.style.display === 'none') {
        group.style.display = 'block';
        toggle.textContent = '▼';
    } else {
        group.style.display = 'none';
        toggle.textContent = '▶';
    }
}

// Toggle tool sub-group expand/collapse
function toggleToolGroup(groupId, header) {
    const group = document.getElementById(groupId);
    if (!group) return;
    const toggle = header.querySelector('.tool-group-toggle');
    if (group.style.display === 'none') {
        group.style.display = 'block';
        toggle.textContent = '▼';
    } else {
        group.style.display = 'none';
        toggle.textContent = '▶';
    }
}

// Toggle file group expand/collapse
function toggleFileGroup(groupId) {
    const group = document.getElementById(groupId);
    if (!group) return;
    const header = group.parentElement.querySelector('.finding-file-header');
    const toggle = header.querySelector('.file-group-toggle');
    if (group.style.display === 'none') {
        group.style.display = 'block';
        toggle.textContent = '▼';
    } else {
        group.style.display = 'none';
        toggle.textContent = '▶';
    }
}

// HTML-escape a string for safe innerHTML insertion
function esc(str) {
    if (str === null || str === undefined) {
        return '';
    }

    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

// Get worst severity from a list of findings
function getWorstSeverity(findings) {
    const order = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO'];
    for (const sev of order) {
        if (findings.some(f => (f.severity || '').toUpperCase() === sev)) {
            return sev.charAt(0) + sev.slice(1).toLowerCase();
        }
    }
    return 'INFO';
}

function toggleScanDetails(scanId) {
    const details = document.getElementById('details-' + scanId);
    const btn = document.querySelector(`[data-scan-id="${scanId}"] .view-detail-btn`);
    
    if (expandedScanIds.has(scanId)) {
        expandedScanIds.delete(scanId);
        details.style.display = 'none';
        if (btn) btn.innerHTML = '▶';
    } else {
        expandedScanIds.add(scanId);
        details.style.display = 'block';
        if (btn) btn.innerHTML = '▼';
        
        // Lazy load findings when user expands
        const findingsContainer = document.getElementById('findings-' + scanId);
        // Check if findings have actually been loaded (has finding-item divs, not just header)
        const hasLoadedFindings = findingsContainer && findingsContainer.querySelector('.finding-item');
        if (findingsContainer && !hasLoadedFindings) {
            loadScanFindings(scanId);
        }
    }
}

// ============ DEBOUNCED MANUAL REFRESH ============
function refreshAllData() {
    const btn = document.getElementById('refresh-btn');
    if (btn) btn.classList.add('spinning');
    sendClientLog('manual_refresh_all');
    showToast('Refreshing dashboard data...', 'info', 2000);
    updateScanStatus();
    loadDynamicContent();
    loadHistory();
    loadRepositories();
    loadSettings();
    loadActivityUsers();
    setTimeout(() => {
        if (btn) btn.classList.remove('spinning');
        showToast('Dashboard refreshed', 'success', 2000);
    }, 2000);
}

const debouncedRefreshHistory = debounce(() => {
    loadHistory();
}, 2000);

function manualRefreshHistory() {
    sendClientLog('manual_refresh_history');
    debouncedRefreshHistory();
}

function loadSettings() {
    const form = document.getElementById('github-credentials-form');
    const statusDiv = document.getElementById('settings-status');
    
    if (!form) return;

    sendClientLog('loadSettings_start');
    
    fetch('/api/settings/pr-scan')
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                const toggle = document.getElementById('pr-scan-toggle');
                if (toggle) {
                    toggle.checked = data.pr_scan_enabled;
                }
                const blockToggle = document.getElementById('pr-block-toggle');
                if (blockToggle) {
                    blockToggle.checked = data.pr_block_enabled;
                }
                const severitySelect = document.getElementById('pr-block-severity');
                if (severitySelect && data.pr_block_severity) {
                    severitySelect.value = data.pr_block_severity;
                }
            }
        })
        .catch(error => {
            console.error('Error loading PR scan settings:', error);
        });

    fetch('/api/settings/ngrok')
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                const subdomainInput = document.getElementById('ngrok_subdomain');
                if (subdomainInput) {
                    subdomainInput.value = data.ngrok_subdomain || '';
                }
            }
        })
        .catch(error => {
            console.error('Error loading ngrok settings:', error);
        });

    function saveAllPrSettings() {
        const prScanToggle = document.getElementById('pr-scan-toggle');
        const blockToggle = document.getElementById('pr-block-toggle');
        const severitySelect = document.getElementById('pr-block-severity');
        const payload = {
            pr_scan_enabled: prScanToggle ? prScanToggle.checked : true,
            pr_block_enabled: blockToggle ? blockToggle.checked : false,
            pr_block_severity: severitySelect ? severitySelect.value : 'HIGH'
        };
        fetch('/api/settings/pr-scan', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                showToast('PR settings saved', 'success');
            } else {
                showToast('Failed to save PR settings', 'error');
            }
        })
        .catch(error => {
            console.error('Error saving PR settings:', error);
            showToast('Error saving PR settings', 'error');
        });
    }

    const toggle = document.getElementById('pr-scan-toggle');
    if (toggle && !toggle.dataset.listenersAttached) {
        toggle.dataset.listenersAttached = 'true';
        toggle.addEventListener('change', saveAllPrSettings);
    }

    const blockToggle = document.getElementById('pr-block-toggle');
    if (blockToggle && !blockToggle.dataset.listenersAttached) {
        blockToggle.dataset.listenersAttached = 'true';
        blockToggle.addEventListener('change', saveAllPrSettings);
    }

    const severitySelect = document.getElementById('pr-block-severity');
    if (severitySelect && !severitySelect.dataset.listenersAttached) {
        severitySelect.dataset.listenersAttached = 'true';
        severitySelect.addEventListener('change', saveAllPrSettings);
    }

    const subdomainInput = document.getElementById('ngrok_subdomain');
    if (subdomainInput && !subdomainInput.dataset.listenersAttached) {
        subdomainInput.dataset.listenersAttached = 'true';
        subdomainInput.addEventListener('change', function() {
            const ngrokSubdomain = this.value.trim();
            
            fetch('/api/settings/ngrok', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ngrok_subdomain: ngrokSubdomain })
            })
            .then(response => response.json())
            .then(data => {
                if (data.status === 'success') {
                    showToast('Ngrok subdomain saved', 'success');
                } else {
                    showToast('Failed to save ngrok subdomain', 'error');
                }
            })
            .catch(error => {
                console.error('Error saving ngrok subdomain:', error);
                showToast('Error saving ngrok subdomain', 'error');
            });
        });
    }
    
    fetch('/api/settings/github')
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                const creds = data.credentials;
                document.getElementById('github_app_id').value = creds.github_app_id || '';
                document.getElementById('github_app_name').value = creds.github_app_name || '';
                const secretEl = document.getElementById('github_secret_key');
                if (secretEl) {
                    secretEl.value = '';
                    secretEl.placeholder = 'Private key is stored securely. Click "Replace Key" to provide a new one.';
                    secretEl.setAttribute('readonly', 'true');
                }
                
                // For ngrok token and webhook secret, clear the fields but show status
                const ngrokEl = document.getElementById('ngrok_oauth_token');
                const webhookEl = document.getElementById('github_webhook_secret');
                
                if (ngrokEl) {
                    ngrokEl.value = '';
                    if (creds.ngrok_oauth_token) {
                        ngrokEl.placeholder = '✓ Token saved (' + creds.ngrok_oauth_token_masked + ')';
                    } else {
                        ngrokEl.placeholder = 'Enter your Ngrok OAuth Token';
                    }
                }
                
                if (webhookEl) {
                    webhookEl.value = '';
                    if (creds.github_webhook_secret) {
                        webhookEl.placeholder = '✓ Secret saved (' + creds.github_webhook_secret_masked + ')';
                    } else {
                        webhookEl.placeholder = 'Enter your GitHub Webhook Secret';
                    }
                }
                
                sendClientLog('loadSettings_success', { github_app_id: !!creds.github_app_id });
            } else {
                sendClientLog('loadSettings_error', { message: data.message || 'unknown' }, 'error');
            }
        })
        .catch(error => { 
            console.error('Error loading GitHub credentials:', error); 
            sendClientLog('loadSettings_error', { message: error.message || String(error) }, 'error'); 
        });

    const replaceBtn = document.getElementById('replace-key-btn');
    const cancelReplaceBtn = document.getElementById('cancel-replace-btn');
    const secretEl = document.getElementById('github_secret_key');
    
    if (replaceBtn && secretEl) {
        replaceBtn.addEventListener('click', function() {
            secretEl.removeAttribute('readonly');
            secretEl.value = '';
            secretEl.placeholder = 'Paste your complete GitHub RSA Private Key here (-----BEGIN RSA PRIVATE KEY----- ... )';
            replaceBtn.style.display = 'none';
            if (cancelReplaceBtn) cancelReplaceBtn.style.display = 'inline-block';
            secretEl.focus();
            sendClientLog('replace_key_clicked');
        });
    }
    
    if (cancelReplaceBtn && secretEl) {
        cancelReplaceBtn.addEventListener('click', function() {
            secretEl.setAttribute('readonly', 'true');
            secretEl.value = '';
            secretEl.placeholder = 'Private key is stored securely. Click "Replace Key" to provide a new one.';
            cancelReplaceBtn.style.display = 'none';
            if (replaceBtn) replaceBtn.style.display = 'inline-block';
            sendClientLog('replace_key_cancelled');
        });
    }

    form.addEventListener('submit', function(e) {
        e.preventDefault();

        const formData = {
            github_app_id: document.getElementById('github_app_id').value.trim(),
            github_app_name: document.getElementById('github_app_name').value.trim(),
            github_secret_key: (document.getElementById('github_secret_key').value || '').trim(),
            ngrok_oauth_token: document.getElementById('ngrok_oauth_token').value.trim(),
            github_webhook_secret: document.getElementById('github_webhook_secret').value.trim()
        };

        if (!Object.values(formData).some(v => v !== '')) {
            showSettingsStatus('Please fill in at least one field', 'error');
            return;
        }

        showSettingsStatus('Saving credentials...', 'loading');
        sendClientLog('saveSettings_start', { github_app_id: formData.github_app_id ? true : false });

        fetch('/api/settings/github', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(formData)
        })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                showSettingsStatus('✓ Credentials saved successfully!', 'success');
                sendClientLog('saveSettings_success', { github_app_id: !!formData.github_app_id });
                setTimeout(() => {
                    // Reload settings from server to display saved values
                    loadSettings();
                    statusDiv.innerHTML = '';
                }, 1500);
            } else {
                showSettingsStatus('✗ ' + (data.message || 'Failed to save credentials'), 'error');
                sendClientLog('saveSettings_error', { message: data.message || 'unknown' }, 'error');
            }
        })
        .catch(error => {
            console.error('Error saving credentials:', error);
            showSettingsStatus('✗ Error saving credentials: ' + error.message, 'error');
            sendClientLog('saveSettings_error', { message: error.message || String(error) }, 'error');
        });
    });
}

function showSettingsStatus(message, type) {
    const statusDiv = document.getElementById('settings-status');
    if (statusDiv) {
        statusDiv.innerHTML = `<div class="status-message status-${type}">${esc(message)}</div>`;
        statusDiv.style.display = 'block';
    }
}

// ============ Utility Functions ============
function updateTimestamps() {
    const now = new Date();
    const formattedTime = now.toLocaleString('en-US', {
        weekday: 'short',
        month: 'short',
        day: 'numeric',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit'
    });
    
    const timestampEl = document.getElementById('timestamp');
    if (timestampEl) {
        timestampEl.textContent = formattedTime;
    }
}

function formatDate(dateString) {
    if (!dateString) return 'N/A';
    // If no timezone indicator, treat as UTC by appending Z
    const normalized = /[zZ]$|[+-]\d{2}:\d{2}$/.test(dateString) ? dateString : dateString + 'Z';
    const date = new Date(normalized);
    return date.toLocaleString('en-US', {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    });
}

// ============ Page Visibility ============
document.addEventListener('visibilitychange', function() {
    if (document.visibilityState === 'visible') {
        sendClientLog('page_visible');
        updateTimestamps();
    }
});

window.addEventListener('load', function() {
    instrumentFetchLogging();
    sendClientLog('page_load', { url: window.location.pathname, activeTab: localStorage.getItem('activeTab') || 'overview' });
});

window.addEventListener('beforeunload', function() {
    sendClientLog('page_beforeunload', { url: window.location.pathname });
});

// ============ Keyboard Navigation ============
document.addEventListener('keydown', function(event) {
    const tabButtons = document.querySelectorAll('.tab-button');
    const activeButton = document.querySelector('.tab-button.active');
    let currentIndex = Array.from(tabButtons).indexOf(activeButton);

    if (event.key === 'ArrowRight') {
        event.preventDefault();
        currentIndex = (currentIndex + 1) % tabButtons.length;
        tabButtons[currentIndex].click();
    } else if (event.key === 'ArrowLeft') {
        event.preventDefault();
        currentIndex = (currentIndex - 1 + tabButtons.length) % tabButtons.length;
        tabButtons[currentIndex].click();
    }
});

// ============ Initialize Security Score Animation ============
function animateSecurityScore() {
    const scoreValue = document.getElementById('score-value');
    if (!scoreValue) return;

    const finalScore = parseInt(scoreValue.textContent);
    let currentScore = 0;
    const increment = Math.ceil(finalScore / 30);

    const interval = setInterval(() => {
        currentScore += increment;
        if (currentScore >= finalScore) {
            currentScore = finalScore;
            clearInterval(interval);
        }
        scoreValue.textContent = currentScore;
    }, 30);
}

window.addEventListener('load', animateSecurityScore);

// ============ Bulk Delete Functions ============
function syncDeleteButtonState() {
    const checkboxes = document.querySelectorAll('.scan-checkbox');
    const deleteBtn = document.getElementById('delete-scans-btn');
    const selectedCount = document.getElementById('selected-count');
    const selectAllCheckbox = document.getElementById('select-all-scans');
    
    const checkedCheckboxes = document.querySelectorAll('.scan-checkbox:checked');
    const checkedCount = checkedCheckboxes.length;
    const totalCount = checkboxes.length;
    
    if (selectAllCheckbox) {
        selectAllCheckbox.checked = checkedCount > 0 && checkedCount === totalCount;
        selectAllCheckbox.indeterminate = checkedCount > 0 && checkedCount < totalCount;
    }
    
    if (deleteBtn && selectedCount) {
        selectedCount.textContent = checkedCount;
        deleteBtn.style.display = checkedCount > 0 ? 'inline-block' : 'none';
    }
}

function updateDeleteButton() {
    syncDeleteButtonState();
}

function toggleSelectAllScans() {
    const selectAllCheckbox = document.getElementById('select-all-scans');
    const checkboxes = document.querySelectorAll('.scan-checkbox');
    
    checkboxes.forEach(cb => {
        cb.checked = selectAllCheckbox.checked;
    });
    
    syncDeleteButtonState();
    saveCheckboxState();
}

function exportReport() {
    sendClientLog('export_report_start', {});
    window.location.href = '/api/export-report';
}

function deleteSelectedScans() {
    const checkboxes = document.querySelectorAll('.scan-checkbox:checked');
    const scanIds = Array.from(checkboxes).map(cb => cb.getAttribute('data-scan-id'));
    
    if (scanIds.length === 0) {
        return;
    }
    
    if (!confirm(`Are you sure you want to delete ${scanIds.length} scan(s)? This will remove all data from logs.`)) {
        return;
    }
    
    sendClientLog('delete_scans_start', { count: scanIds.length, scanIds: scanIds });
    
    fetch('/api/history/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scan_ids: scanIds })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            sendClientLog('delete_scans_success', { count: scanIds.length });
            loadHistory();
            const deleteBtn = document.getElementById('delete-scans-btn');
            if (deleteBtn) deleteBtn.style.display = 'none';
        } else {
            sendClientLog('delete_scans_error', { message: data.message || 'Unknown error' }, 'error');
            alert('Failed to delete scans: ' + (data.message || 'Unknown error'));
        }
    })
    .catch(error => {
        sendClientLog('delete_scans_error', { message: error.message || String(error) }, 'error');
        console.error('Error deleting scans:', error);
        alert('Error deleting scans: ' + error.message);
    });
}

// ============ User Menu Functions ============

function initializeUserMenu() {
    fetch('/api/auth/status')
        .then(response => response.json())
        .then(data => {
            if (data.username) {
                const usernameEl = document.getElementById('current-username');
                if (usernameEl) {
                    usernameEl.textContent = data.username;
                }
            }
        })
        .catch(error => {});
    
    const userMenuToggle = document.getElementById('user-menu-toggle');
    const userDropdown = document.getElementById('user-dropdown');
    
    if (userMenuToggle && userDropdown) {
        userMenuToggle.addEventListener('click', (e) => {
            e.stopPropagation();
            userDropdown.classList.toggle('active');
            userMenuToggle.classList.toggle('active');
        });
        
        document.addEventListener('click', () => {
            userDropdown.classList.remove('active');
            userMenuToggle.classList.remove('active');
        });
        
        userDropdown.addEventListener('click', (e) => {
            if (e.target.closest('a, button')) {
                userDropdown.classList.remove('active');
                userMenuToggle.classList.remove('active');
            }
        });
    }
}

function logout() {
    sendClientLog('logout_start', {});
    
    fetch('/auth/logout', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
    })
    .then(response => {
        if (response.ok) {
            sendClientLog('logout_success', {});
            window.location.href = '/auth/login';
        } else {
            sendClientLog('logout_error', { status: response.status }, 'error');
            alert('Logout failed. Please try again.');
        }
    })
    .catch(error => {
        sendClientLog('logout_error', { message: error.message }, 'error');
        console.error('Logout error:', error);
        alert('Logout error: ' + error.message);
    });
}

// ============ FINDINGS FILTER FUNCTIONS ============

var activeFilters = { severity: [], tool: [], category: [], search: '' };

function applyFilters() {
    const severityFilters = Array.from(document.querySelectorAll('.severity-filter:checked')).map(cb => cb.value);
    const toolFilters = Array.from(document.querySelectorAll('.tool-filter:checked')).map(cb => cb.value);
    const categoryFilters = Array.from(document.querySelectorAll('.category-filter:checked')).map(cb => cb.value);
    const searchQuery = document.getElementById('findingsSearch')?.value || '';
    
    activeFilters = { severity: severityFilters, tool: toolFilters, category: categoryFilters, search: searchQuery };

    const params = new URLSearchParams();
    if (severityFilters.length) params.set('severity', severityFilters.join(','));
    if (toolFilters.length) params.set('tool', toolFilters.join(','));
    if (categoryFilters.length) params.set('category', categoryFilters.join(','));
    if (searchQuery) params.set('search', searchQuery);
    
    const historyList = document.getElementById('history-list');
    if (historyList) historyList.innerHTML = '<div style="padding: 2rem; text-align: center; color: #64748b;">Filtering...</div>';
    
    // If no filters, just reload all history
    if (!severityFilters.length && !toolFilters.length && !categoryFilters.length && !searchQuery) {
        loadHistory();
        return;
    }
    
    fetch('/api/history/filter?' + params.toString())
        .then(response => response.json())
        .then(data => {
            if (data.history && data.history.length > 0) {
                renderFilteredHistory(data.history);
            } else {
                historyList.innerHTML = '<div style="padding: 2rem; text-align: center; color: #64748b;">No findings match your filters</div>';
            }
        })
        .catch(error => {
            console.error('Filter error:', error);
            loadHistory();
        });
}

function clearFilters() {
    activeFilters = { severity: [], tool: [], category: [], search: '' };
    document.querySelectorAll('.severity-filter, .tool-filter, .category-filter').forEach(cb => cb.checked = false);
    if (document.getElementById('findingsSearch')) {
        document.getElementById('findingsSearch').value = '';
    }
    loadHistory();
}

function renderFilteredHistory(filteredHistory) {
    const historyList = document.getElementById('history-list');
    if (!historyList) return;
    
    if (!filteredHistory || filteredHistory.length === 0) {
        historyList.innerHTML = '<div class="empty-state">No findings match your filters</div>';
        return;
    }
    
    // Save current checkbox state
    const checkedIds = Array.from(document.querySelectorAll('.scan-checkbox:checked')).map(cb => cb.getAttribute('data-scan-id'));
    
    let html = '';
    filteredHistory.forEach(scan => {
        html += renderHistoryItem(scan);
    });
    historyList.innerHTML = html;
    
    // For each scan with inline findings, render them immediately
    filteredHistory.forEach(scan => {
        const findingsContainer = document.getElementById('findings-' + scan.scan_id);
        if (findingsContainer && scan.findings && scan.findings.length > 0) {
            renderFindings(scan.scan_id, { findings: scan.findings }, findingsContainer);
        }
    });
    
    // Restore checkbox state
    checkedIds.forEach(id => {
        const cb = document.querySelector(`.scan-checkbox[data-scan-id="${id}"]`);
        if (cb) cb.checked = true;
    });
    updateDeleteButton();
}

function renderHistoryItem(scan) {
    // Get severity counts from findings
    const findings = scan.findings || [];
    const severity = { CRITICAL: 0, HIGH: 0, MEDIUM: 0, LOW: 0 };
    const sources = new Set();
    let multiSource = 0;
    
    findings.forEach(f => {
        const sev = f.severity || 'LOW';
        if (severity[sev] !== undefined) severity[sev]++;
        (f.sources || []).forEach(s => sources.add(s));
    });
    
    const total = findings.length;
    const branch = scan.repo_branch || 'main';
    const critical = severity.CRITICAL;
    const high = severity.HIGH;
    const medium = severity.MEDIUM;
    const low = severity.LOW;
    
    let html = '';
    const prLabel = scan.is_pr_scan ? ' <span class="pr-label">PR</span>' : '';
    const prInfo = scan.is_pr_scan && scan.pr_number ? ` #${scan.pr_number}` : '';
    html += `
            <div class="history-row" onclick="openScanDetail('${esc(scan.scan_id)}')">
                <div class="col-checkbox">
                    <input type="checkbox" class="scan-checkbox" data-scan-id="${esc(scan.scan_id)}" onclick="event.stopPropagation(); updateDeleteButton(); saveCheckboxState()">
                </div>
                <div class="col-time">${formatDate(scan.timestamp)}</div>
                <div class="col-repo">${esc(scan.repository || 'Unknown')}${prLabel}${prInfo}</div>
                <div class="col-branch">${esc(branch)}</div>
                <div class="col-total">${total}</div>
                <div class="col-severity">
                    <span class="severity-badge critical">C${critical}</span>
                    <span class="severity-badge high">H${high}</span>
                    <span class="severity-badge medium">M${medium}</span>
                    <span class="severity-badge low">L${low}</span>
                </div>
                <div class="col-multi">${multiSource > 0 ? multiSource : '-'}</div>
            </div>
        </div>
    `;
    return html;
}

// ============ USER MANAGEMENT FUNCTIONS ============

function loadUsers() {
     fetch('/api/users', { credentials: 'include' })
     .then(response => {
         if (response.status === 403) {
             response.json().then(err => {
                 showToast(err.error || 'Access denied', 'error');
             });
             return;
         }
         return response.json();
     })
     .then(data => {
         if (data && data.users) {
             displayUsers(data.users);
         }
     })
     .catch(error => {
         console.error('Error loading users:', error);
     });
}

function displayUsers(users) {
    const tbody = document.getElementById('users-list');
    if (!tbody) return;
    
    if (!users || users.length === 0) {
        tbody.innerHTML = '<tr><td colspan="9" style="text-align: center; padding: 20px; color: #64748b;">No users found</td></tr>';
        return;
    }
    
    tbody.innerHTML = users.map(user => `
         <tr>
             <td>${esc(user.username)}</td>
             <td>${esc(user.email || '-')}</td>
             <td>${esc(user.full_name || '-')}</td>
             <td>${esc(user.department || '-')}</td>
             <td><span class="user-role-badge ${esc(user.role)}">${esc(user.role)}</span></td>
             <td>${user.created_at ? user.created_at.split('T')[0] : '-'}</td>
             <td>${user.last_login ? user.last_login.split('T')[0] : 'Never'}</td>
             <td class="user-actions">
                 <button class="edit-btn" onclick="editUser(${user.id})">Edit</button>
                 <button class="delete-btn" onclick="deleteUser(${user.id})">Delete</button>
             </td>
         </tr>
    `).join('');
}

function showCreateUserModal() {
     document.getElementById('user-modal-title').textContent = 'Create User';
     document.getElementById('user-id').value = '';
     document.getElementById('user-form').reset();
     document.getElementById('password-group').style.display = 'block';
     document.getElementById('user-modal').style.display = 'block';
}

function closeUserModal() {
    document.getElementById('user-modal').style.display = 'none';
}

function editUser(userId) {
    fetch('/api/users', { credentials: 'include' })
    .then(response => response.json())
    .then(data => {
        const user = data.users.find(u => u.id === userId);
        if (!user) {
            alert('User not found');
            return;
        }
        
         document.getElementById('user-modal-title').textContent = 'Edit User';
         document.getElementById('user-id').value = user.id;
         document.getElementById('user-username').value = user.username;
         document.getElementById('user-email').value = user.email || '';
         document.getElementById('user-fullname').value = user.full_name || '';
         document.getElementById('user-department').value = user.department || '';
         document.getElementById('user-role').value = user.role;
         
         document.getElementById('password-group').style.display = 'none';
         document.getElementById('user-modal').style.display = 'block';
    });
}

function deleteUser(userId) {
     if (!confirm('Are you sure you want to delete this user?')) return;
     
     fetch('/api/users/' + userId, {
         method: 'DELETE',
         credentials: 'include'
     })
     .then(response => response.json())
     .then(data => {
         alert(data.message || data.status);
         loadUsers();
     })
     .catch(error => {
         console.error('Error:', error);
         alert('Failed to delete user');
    });
}

document.getElementById('user-form').addEventListener('submit', function(e) {
    e.preventDefault();
    
    const userId = document.getElementById('user-id').value;
    const isEdit = !!userId;
    
    const userData = {
        username: document.getElementById('user-username').value,
        email: document.getElementById('user-email').value,
        full_name: document.getElementById('user-fullname').value,
        department: document.getElementById('user-department').value,
        role: document.getElementById('user-role').value
    };
    
    if (!isEdit) {
        userData.password = document.getElementById('user-password').value;
    }
    
    const url = isEdit ? '/api/users/' + userId : '/api/users';
    const method = isEdit ? 'PUT' : 'POST';
    
    fetch(url, {
        method: method,
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(userData)
    })
    .then(response => {
        
        if (response.status === 200) {
            response.json().then(result => {
        if (result.status === 200 && result.body.status === 'success') {
            alert(result.body.message);
            closeUserModal();
            loadUsers();
        } else {
            alert(result.body.message || 'Error: ' + result.body.error);
        }
    })
    .catch(error => {
        console.error('Error:', error);
        alert('Failed to save user: ' + error.message);
    });
});

// Load users when users tab is shown
document.querySelector('[data-tab="users"]').addEventListener('click', function() {
    loadUsers();
});

// Also load users on page load if users tab is visible
document.addEventListener('DOMContentLoaded', function() {
    const usersTab = document.getElementById('users-tab');
    if (usersTab && usersTab.classList.contains('active')) {
        loadUsers();
    }
});

// ============ FILTER PANEL TOGGLE ============
function toggleFilterPanel() {
    const panel = document.getElementById('filter-panel');
    panel.classList.toggle('active');
}

// ============ EXPORT REPORT MODAL ============
function exportReport() {
    document.getElementById('export-modal').classList.add('active');
}
function closeExportModal() {
    document.getElementById('export-modal').classList.remove('active');
}
function confirmExport() {
    const params = new URLSearchParams();
    
    // Date filter (000 to 111 - bit 0)
    const dateFrom = document.getElementById('export-date-from').value;
    const dateTo = document.getElementById('export-date-to').value;
    if (dateFrom) params.set('date_from', dateFrom);
    if (dateTo) params.set('date_to', dateTo);
    
    // Severity filter (bit 1)
    const severity = [];
    if (document.getElementById('export-critical').checked) severity.push('CRITICAL');
    if (document.getElementById('export-high').checked) severity.push('HIGH');
    if (document.getElementById('export-medium').checked) severity.push('MEDIUM');
    if (document.getElementById('export-low').checked) severity.push('LOW');
    if (severity.length) params.set('severity', severity.join(','));
    
    // Tool filter (bit 2)
    const tool = [];
    if (document.getElementById('export-opengrep').checked) tool.push('opengrep');
    if (document.getElementById('export-truffle').checked) tool.push('truffle');
    if (document.getElementById('export-trivy').checked) tool.push('trivy');
    if (tool.length) params.set('tool', tool.join(','));
    
    closeExportModal();
    window.location.href = '/api/export-report' + (params.toString() ? '?' + params.toString() : '');
}

// Toggle password visibility
function togglePassword(inputId, btnElement) {
    var input = document.getElementById(inputId);
    if (!input) {
        return;
    }
    if (input.type === 'password') {
        input.type = 'text';
        if (btnElement) btnElement.innerHTML = '👁️‍🗨️';
    } else {
        input.type = 'password';
        if (btnElement) btnElement.innerHTML = '👁️';
    }
}

// ============ ACTIVITY LOG FUNCTIONS ============

// ============ USER CARDS VIEW ============

var inlinePollTimer = null;
var inlineLatestId = null;
var inlineUserId = null;
var inlineUsername = '';

function loadActivityUsers() {
    var container = document.getElementById('user-cards');
    if (!container) return;

    var days = document.getElementById('activity-days-filter')?.value || 30;

    container.innerHTML = '<div class="activity-loading">Loading users with activity...</div>';

    fetch('/api/activity/users?days=' + days, { credentials: 'include' })
        .then(function(r) {
            if (!r.ok) throw new Error('HTTP ' + r.status + ': ' + r.statusText);
            return r.json();
        })
        .then(function(data) {
            if (!data.users || data.users.length === 0) {
                container.innerHTML = '<div class="activity-empty">No user activity found for this period.</div>';
                return;
            }

            var html = '<div class="user-cards-grid">';
            data.users.forEach(function(user) {
                var initial = (user.username || '?')[0].toUpperCase();
                var timeAgo = formatInlineDate(user.last_activity);
                html += '<div class="user-card" onclick="openUserActivity(' + user.user_id + ',\'' + escAttr(user.username) + '\')">' +
                    '<div class="user-card-avatar">' + esc(initial) + '</div>' +
                    '<div class="user-card-info">' +
                        '<div class="user-card-name">' + esc(user.username) + '</div>' +
                        '<div class="user-card-role ' + esc(user.user_role) + '">' + esc(user.user_role) + '</div>' +
                    '</div>' +
                    '<div class="user-card-stats">' +
                        '<div class="user-card-count">' + user.log_count + '</div>' +
                        '<div class="user-card-label">entries</div>' +
                    '</div>' +
                    '<div class="user-card-time">' + timeAgo + '</div>' +
                    '<div class="user-card-arrow">→</div>' +
                '</div>';
            });
            html += '</div>';
            html += '<div class="activity-footer">' + data.total + ' user(s) with activity</div>';
            container.innerHTML = html;
        })
        .catch(function(err) {
            console.error('loadActivityUsers error:', err);
            container.innerHTML = '<div class="activity-empty">Error: ' + esc(err.message) + '</div>';
        });
}

function escAttr(str) {
    if (!str) return '';
    return String(str).replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/'/g,'&#39;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function openUserActivity(userId, username) {
    inlineUserId = userId;
    inlineUsername = username || 'User';
    inlineLatestId = null;
    localStorage.setItem('activityUserId', userId);
    localStorage.setItem('activityUsername', username || 'User');

    document.getElementById('user-cards-view').style.display = 'none';
    var inlineView = document.getElementById('user-activity-inline');
    inlineView.style.display = '';

    var initial = (inlineUsername || '?')[0].toUpperCase();
    document.getElementById('inline-activity-title').textContent = 'Activity Log';
    document.getElementById('inline-user-badge').innerHTML =
        '<div class="user-card-avatar" style="width:32px;height:32px;font-size:0.85rem;">' + esc(initial) + '</div>' +
        '<div class="user-card-info" style="flex:none;">' +
            '<div class="user-card-name">' + esc(inlineUsername) + '</div>' +
        '</div>';

    document.getElementById('inline-activity-list').innerHTML = '<div class="activity-loading">Loading activity...</div>';

    loadInlineUserLogs();
    startInlinePoll();
}

function backToUserCards() {
    stopInlinePoll();
    inlineUserId = null;
    inlineLatestId = null;
    localStorage.removeItem('activityUserId');
    localStorage.removeItem('activityUsername');
    var inlineView = document.getElementById('user-activity-inline');
    if (inlineView) inlineView.style.display = 'none';
    var cardsView = document.getElementById('user-cards-view');
    if (cardsView) cardsView.style.display = '';
    loadActivityUsers();
}

function formatInlineDate(isoStr) {
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
    var opts = { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' };
    return d.toLocaleDateString('en-US', opts);
}

function renderInlineActivityEntry(log) {
    var time = formatDate(log.created_at);
    var username = esc(log.username || 'System');
    var userRole = log.user_role || 'system';
    var roleBadge = '<span class="activity-role-badge ' + userRole + '">' + userRole + '</span>';
    var resourceLabel = formatResourceType(log.resource_type);
    var statusClass = log.status === 'failure' ? 'activity-failure' : 'activity-success';
    var details = formatInlineActivityDetails(log);
    var actorPart = username + ' ' + roleBadge;

    return '<div class="activity-entry ' + statusClass + '" data-id="' + log.id + '">' +
        '<div class="activity-entry-header">' +
        '<span class="activity-time">' + time + '</span>' +
        '<span class="activity-actor">' + actorPart + '</span>' +
        '<span class="activity-action-label">' + esc(resourceLabel) + '</span>' +
        '<span class="activity-status ' + log.status + '">' + esc(log.status) + '</span>' +
        '</div>' +
        (details ? '<div class="activity-details">' + details + '</div>' : '') +
        '</div>';
}

function formatInlineActivityDetails(log) {
    var parts = [];
    parts.push('<strong>' + esc(formatActionLabel(log.action)) + '</strong>');
    if (log.resource_type && log.resource_id) {
        parts.push(esc(log.resource_id));
    }
    if (log.new_value) {
        if (log.new_value.username) parts.push('User: ' + esc(log.new_value.username));
        if (log.new_value.role) parts.push('Role: ' + esc(log.new_value.role));
        if (log.new_value.repo_name) parts.push('Repo: ' + esc(log.new_value.repo_name));
        if (log.new_value.scan_types) parts.push('Types: ' + esc(JSON.stringify(log.new_value.scan_types)));
        if (log.new_value.total_repos !== undefined) parts.push('Scans: ' + log.new_value.triggered + '/' + log.new_value.total_repos);
        if (log.new_value.count !== undefined) parts.push('Deleted: ' + log.new_value.count + ' scan(s)');
        if (log.new_value.total_scans !== undefined) parts.push('Scans: ' + log.new_value.total_scans);
        if (log.new_value.total_findings !== undefined) parts.push('Findings: ' + log.new_value.total_findings);
        if (log.resource_type === 'false_positive') {
            if (log.new_value.file) parts.push('File: ' + esc(log.new_value.file));
            if (log.new_value.severity) parts.push('Severity: ' + esc(log.new_value.severity));
            if (log.new_value.title) parts.push('Type: ' + esc(log.new_value.title));
            if (log.new_value.finding_type && !log.new_value.title) parts.push('Type: ' + esc(log.new_value.finding_type));
            if (log.new_value.fingerprint) parts.push('FP: ' + esc(log.new_value.fingerprint.substring(0, 24)) + '...');
            if (log.new_value.reason) parts.push('Reason: ' + esc(log.new_value.reason.substring(0, 60)));
            if (log.new_value.submitter_role) parts.push('Submitter: ' + esc(log.new_value.submitter_role));
            if (log.new_value.tool_name) parts.push('Tool: ' + esc(log.new_value.tool_name));
            if (log.new_value.status) parts.push('Status: ' + esc(log.new_value.status));
            if (log.new_value.operator_message) parts.push('Op msg: ' + esc(log.new_value.operator_message.substring(0, 60)));
            if (log.new_value.admin_message) parts.push('Admin msg: ' + esc(log.new_value.admin_message.substring(0, 60)));
        }
    }
    if (log.new_value) {
        if (log.new_value.pr_scan_enabled !== undefined) {
            var parts_pr = [];
            parts_pr.push('auto-scan: ' + log.new_value.pr_scan_enabled);
            parts_pr.push('block: ' + log.new_value.pr_block_enabled);
            parts_pr.push('threshold: ' + log.new_value.pr_block_severity);
            if (log.old_value) {
                var changed_pr = [];
                if (log.old_value.pr_scan_enabled !== log.new_value.pr_scan_enabled) changed_pr.push('auto-scan ' + log.old_value.pr_scan_enabled + ' \u2192 ' + log.new_value.pr_scan_enabled);
                if (log.old_value.pr_block_enabled !== log.new_value.pr_block_enabled) changed_pr.push('block ' + log.old_value.pr_block_enabled + ' \u2192 ' + log.new_value.pr_block_enabled);
                if (log.old_value.pr_block_severity !== log.new_value.pr_block_severity) changed_pr.push('threshold ' + log.old_value.pr_block_severity + ' \u2192 ' + log.new_value.pr_block_severity);
                if (changed_pr.length) parts_pr.push('Changed: ' + changed_pr.join(', '));
            }
            parts.push(parts_pr.join(' | '));
        }
    }
    if (log.old_value && log.new_value) {
        var changed = [];
        if (log.old_value.role !== log.new_value.role) changed.push('role: ' + log.old_value.role + ' \u2192 ' + log.new_value.role);
        if (changed.length) parts.push('Changed: ' + changed.join(', '));
    }
    if (log.error_message) {
        parts.push('Error: ' + esc(log.error_message));
    }
    return parts.join(' | ');
}

function formatResourceType(rt) {
    var labels = {
        'authentication': 'Auth', 'repository': 'Repo', 'report': 'Report',
        'scan': 'Scan', 'settings': 'Settings', 'pull_request': 'PR', 'user': 'User',
        'false_positive': 'FP'
    };
    return labels[rt] || rt;
}

function formatActionLabel(action) {
    var labels = {
        'LOGIN_SUCCESS': 'Login', 'LOGIN_FAILED': 'Login Failed',
        'USER_CREATED': 'Created User', 'USER_UPDATED': 'Updated User',
        'USER_DELETED': 'Deleted User', 'SCAN_TRIGGERED': 'Triggered Scan',
        'SCAN_ALL_TRIGGERED': 'Triggered Scan All',
        'PR_SCAN_SETTINGS_UPDATED': 'Changed PR Settings',
        'GITHUB_CREDENTIALS_UPDATED': 'Updated GitHub Credentials',
        'REPORT_EXPORTED': 'Exported Report',
        'SCAN_HISTORY_DELETED': 'Deleted Scan History',
        'NGROK_SETTINGS_UPDATED': 'Updated Ngrok Settings',
        'PR_WEBHOOK_RECEIVED': 'PR Webhook Received',
        'PASSWORD_CHANGED': 'Password Changed',
        'LOGOUT': 'Logged Out', 'ADMIN_SETUP': 'Admin Setup',
        'FP_REQUEST_SUBMITTED': 'Submitted FP', 'FP_APPROVED_BY_OPERATOR': 'Approved FP (Op)',
        'FP_APPROVED_BY_ADMIN': 'Approved FP (Admin)', 'FP_REJECTED_BY_OPERATOR': 'Rejected FP (Op)',
        'FP_REJECTED_BY_ADMIN': 'Rejected FP (Admin)', 'FP_REVERTED_TO_TP': 'Reverted FP to TP'
    };
    return labels[action] || action;
}

function loadInlineUserLogs() {
    if (!inlineUserId) return;
    var container = document.getElementById('inline-activity-list');
    if (!container) return;

    var days = document.getElementById('activity-days-filter')?.value || 30;
    var action = document.getElementById('inline-action-filter')?.value || '';

    var url = '/api/activity?user_id=' + inlineUserId + '&days=' + days + '&limit=500';
    if (action) url += '&action=' + action;
    inlineLatestId = null;

    fetch(url, { credentials: 'include' })
        .then(function(r) {
            if (!r.ok) throw new Error('HTTP ' + r.status);
            return r.json();
        })
        .then(function(data) {
            if (!data.logs || data.logs.length === 0) {
                container.innerHTML = '<div class="activity-empty">No activity for this user.</div>';
                return;
            }

            var html = '<div class="activity-entries">';
            data.logs.forEach(function(log) {
                html += renderInlineActivityEntry(log);
            });
            html += '</div>';
            html += '<div class="activity-footer">Total: ' + data.total + ' entries</div>';
            container.innerHTML = html;

            if (data.logs.length > 0) inlineLatestId = data.logs[0].id;
        })
        .catch(function(err) {
            container.innerHTML = '<div class="activity-empty">Error: ' + esc(err.message) + '</div>';
        });
}

function pollInlineUserLogs() {
    if (!inlineUserId) return;
    var container = document.getElementById('inline-activity-list');
    var entriesEl = container?.querySelector('.activity-entries');
    if (!container || !entriesEl) return;

    var days = document.getElementById('activity-days-filter')?.value || 30;
    var action = document.getElementById('inline-action-filter')?.value || '';
    var url = '/api/activity?user_id=' + inlineUserId + '&days=' + days + '&limit=10';
    if (action) url += '&action=' + action;
    if (inlineLatestId) url += '&since_id=' + inlineLatestId;

    fetch(url, { credentials: 'include' })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (!data.logs || data.logs.length === 0) return;

            var seen = new Set();
            var existing = container.querySelectorAll('.activity-entry');
            existing.forEach(function(el) {
                var id = el.getAttribute('data-id');
                if (id) seen.add(parseInt(id));
            });

            var prependHtml = '';
            data.logs.forEach(function(log) {
                if (!seen.has(log.id)) {
                    prependHtml += renderInlineActivityEntry(log);
                }
                if (!inlineLatestId || log.id > inlineLatestId) {
                    inlineLatestId = log.id;
                }
            });

            if (prependHtml) {
                entriesEl.insertAdjacentHTML('afterbegin', prependHtml);
                var firstNew = entriesEl.firstElementChild;
                if (firstNew) {
                    firstNew.classList.add('activity-new');
                    setTimeout(function() { firstNew.classList.remove('activity-new'); }, 1000);
                }
            }

            var footer = container.querySelector('.activity-footer');
            if (footer) {
                var count = container.querySelectorAll('.activity-entry').length;
                footer.textContent = 'Total: ' + count + ' entries';
            }
        })
        .catch(function() {});
}

function startInlinePoll() {
    stopInlinePoll();
    inlinePollTimer = setInterval(pollInlineUserLogs, 5000);
}

function stopInlinePoll() {
    if (inlinePollTimer) {
        clearInterval(inlinePollTimer);
        inlinePollTimer = null;
    }
}

// ============ SCAN DETAIL OVERLAY ============

var selectedFPFindings = [];

function openScanDetail(scanId) {
    localStorage.setItem('scanDetailId', scanId);
    selectedFPFindings = [];
    document.getElementById('scan-overlay-title').textContent = 'Scan: ' + scanId;
    var content = document.getElementById('scan-overlay-content');
    content.innerHTML = '<div style="text-align:center;padding:3rem;color:#64748b;">Loading scan details...</div>';
    document.getElementById('scan-overlay').style.display = '';
    loadOverlayScanDetail(scanId);
}

function closeScanDetail() {
    localStorage.removeItem('scanDetailId');
    document.getElementById('scan-overlay').style.display = 'none';
}

function loadOverlayScanDetail(scanId) {
    var container = document.getElementById('scan-overlay-content');

    fetch('/api/history/' + scanId)
        .then(function(r) {
            if (r.status === 202) {
                container.innerHTML = '<div style="text-align:center;padding:3rem;color:#64748b;">Scan still processing...</div>';
                throw new Error('still processing');
            }
            if (!r.ok) throw new Error('HTTP ' + r.status);
            return r.json();
        })
        .then(function(data) {
            var merged = data.files && data.files.merged;
            if (!merged) {
                container.innerHTML = '<div style="text-align:center;padding:3rem;color:#64748b;">No scan data found.</div>';
                return;
            }

            var findings = [];
            if (Array.isArray(merged.findings)) {
                findings = merged.findings;
            } else if (merged.findings && typeof merged.findings === 'object') {
                findings = Object.values(merged.findings);
            }

            window._scanDetailFindings = findings;
            window._scanDetailScanMeta = {
                repo_name: merged.repo_name || '',
                repo_owner: merged.repo_owner || '',
                branch_name: merged.repo_branch || '',
                tool_name: '',
                scan_id: scanId
            };

            // Apply active filters
            var af = activeFilters;
            if (af.severity.length || af.tool.length || af.category.length || af.search) {
                findings = findings.filter(function(f) {
                    if (af.severity.length && af.severity.indexOf((f.severity || '').toUpperCase()) === -1) return false;
                    if (af.tool.length) {
                        var sources = f.sources || [];
                        var match = false;
                        for (var ti = 0; ti < af.tool.length; ti++) {
                            if (sources.indexOf(af.tool[ti]) !== -1) { match = true; break; }
                        }
                        if (!match) return false;
                    }
                    if (af.category.length && af.category.indexOf(f.category || '') === -1) return false;
                    if (af.search) {
                        var q = af.search.toLowerCase();
                        var fstr = ((f.file || '') + (f.title || '') + (f.message || '')).toLowerCase();
                        if (fstr.indexOf(q) === -1) return false;
                    }
                    return true;
                });
            }

            var bySev = {};
            findings.forEach(function(f) {
                var s = (f.severity || 'LOW').toUpperCase();
                bySev[s] = (bySev[s] || 0) + 1;
            });
            var severityCards = '';
            var sevOrder = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'];
            sevOrder.forEach(function(s) {
                severityCards += '<div class="detail-stat"><span class="stat-label">' + s + ':</span><span class="stat-value ' + s.toLowerCase() + '">' + (bySev[s] || 0) + '</span></div>';
            });

            var repoName = merged.repo_name || '';
            var repoOwner = merged.repo_owner || '';
            var repoBranch = merged.repo_branch || 'main';
            var timestamp = merged.timestamp || '';
            var repoFull = (repoOwner && repoName) ? repoOwner + '/' + repoName : scanId;

            var suppCount = findings.filter(function (f) { return f.suppressed; }).length;
            var suppToggleHtml = '';
            if (suppCount > 0) {
                suppToggleHtml = '<div class="fp-toggle-bar" style="margin:0 0 1rem 0;"><label class="fp-toggle-label"><input type="checkbox" id="fp-show-toggle" onchange="toggleSuppressedFindings()"> Show false positives (<span class="fp-supp-count">' + suppCount + '</span>)</label></div>';
            }

            var html = suppToggleHtml +
                '<div class="details-grid" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:1rem;margin-bottom:1.5rem;">' +
                    '<div class="detail-card" style="background:#1e293b;border:1px solid #334155;border-radius:6px;padding:1rem;">' +
                        '<h5 style="margin:0 0 0.75rem 0;font-size:0.75rem;text-transform:uppercase;letter-spacing:0.05em;color:#64748b;">Repository</h5>' +
                        '<div class="detail-stat" style="display:flex;justify-content:space-between;align-items:center;padding:0.25rem 0;font-size:0.85rem;"><span style="color:#94a3b8;">Name:</span><span style="font-weight:600;color:#e2e8f0;">' + esc(repoFull) + '</span></div>' +
                        '<div class="detail-stat" style="display:flex;justify-content:space-between;align-items:center;padding:0.25rem 0;font-size:0.85rem;"><span style="color:#94a3b8;">Branch:</span><span style="font-weight:600;color:#e2e8f0;">' + esc(repoBranch) + '</span></div>' +
                        '<div class="detail-stat" style="display:flex;justify-content:space-between;align-items:center;padding:0.25rem 0;font-size:0.85rem;"><span style="color:#94a3b8;">Time:</span><span style="font-weight:600;color:#e2e8f0;">' + esc(timestamp) + '</span></div>' +
                    '</div>' +
                    '<div class="detail-card" style="background:#1e293b;border:1px solid #334155;border-radius:6px;padding:1rem;">' +
                        '<h5 style="margin:0 0 0.75rem 0;font-size:0.75rem;text-transform:uppercase;letter-spacing:0.05em;color:#64748b;">Severity</h5>' + severityCards +
                    '</div>' +
                    '<div class="detail-card" style="background:#1e293b;border:1px solid #334155;border-radius:6px;padding:1rem;">' +
                        '<h5 style="margin:0 0 0.75rem 0;font-size:0.75rem;text-transform:uppercase;letter-spacing:0.05em;color:#64748b;">Total</h5>' +
                        '<div class="detail-stat highlight" style="display:flex;justify-content:space-between;align-items:center;padding:0.25rem 0;font-size:0.85rem;"><span class="stat-value" style="font-weight:600;color:#3b82f6;font-size:1.5rem;">' + findings.length + '</span></div>' +
                        '<div class="detail-stat" style="display:flex;justify-content:space-between;align-items:center;padding:0.25rem 0;font-size:0.85rem;"><span style="color:#94a3b8;">findings</span></div>' +
                    '</div>' +
                '</div>' +
                '<div id="bulk-fp-bar" style="display:none;background:#1e293b;border:1px solid #334155;border-radius:6px;padding:0.75rem 1rem;margin-bottom:1rem;align-items:center;gap:0.75rem;flex-wrap:wrap;">' +
                    '<span style="color:#e2e8f0;font-size:0.85rem;"><span id="bulk-fp-count">0</span> findings selected</span>' +
                    '<button onclick="showBulkFPModal()" style="background:#f59e0b;color:#0f172a;border:none;padding:0.4rem 0.75rem;border-radius:4px;font-size:0.8rem;font-weight:600;cursor:pointer;">Mark Selected as False Positive</button>' +
                    '<button onclick="clearFPSelections()" style="background:transparent;color:#64748b;border:1px solid #475569;padding:0.4rem 0.75rem;border-radius:4px;font-size:0.8rem;cursor:pointer;">Clear</button>' +
                '</div>' +
                '<div class="findings-list" id="overlay-findings-list">' +
                    '<div style="display:flex;align-items:center;gap:0.75rem;margin-bottom:0.75rem;">' +
                        '<h5 style="margin:0;color:#94a3b8;font-size:0.85rem;text-transform:uppercase;letter-spacing:0.05em;">' + (activeFilters.severity.length || activeFilters.tool.length || activeFilters.category.length || activeFilters.search ? 'Filtered Findings' : 'All Findings') + ' (' + findings.length + ')</h5>' +
                        '<label style="font-size:0.8rem;color:#64748b;display:flex;align-items:center;gap:0.3rem;cursor:pointer;"><input type="checkbox" id="select-all-findings" onchange="toggleSelectAllFindings(this)" style="accent-color:#f59e0b;"> Select All</label>' +
                    '</div>';

            if (findings.length === 0) {
                html += '<p style="color:#94a3b8;font-style:italic;">No findings</p>';
            }
            html += '</div>';

            container.innerHTML = html;

            if (findings.length > 0) {
                var fc = document.getElementById('overlay-findings-list');
                merged.findings = findings;
                renderFindings(scanId, data, fc);
            }
        })
        .catch(function(err) {
            if (err.message === 'still processing') return;
            container.innerHTML = '<div style="text-align:center;padding:3rem;color:#64748b;">Error: ' + esc(err.message) + '</div>';
        });
}

// ============ Bulk FP Selection ============
window.toggleSelectAllFindings = function (checkbox) {
    var checked = checkbox.checked;
    document.querySelectorAll('.fp-finding-checkbox').forEach(function (cb) {
        cb.checked = checked;
    });
    onFindingCheckboxChange();
};

window.onFindingCheckboxChange = function () {
    var checks = document.querySelectorAll('.fp-finding-checkbox:checked');
    selectedFPFindings = [];
    checks.forEach(function (cb) {
        var idx = parseInt(cb.getAttribute('data-fp-index'));
        if (!isNaN(idx)) selectedFPFindings.push(idx);
    });
    var bar = document.getElementById('bulk-fp-bar');
    var countEl = document.getElementById('bulk-fp-count');
    if (bar) {
        if (selectedFPFindings.length > 0) {
            bar.style.display = 'flex';
            countEl.textContent = selectedFPFindings.length;
        } else {
            bar.style.display = 'none';
        }
    }
};

window.clearFPSelections = function () {
    document.querySelectorAll('.fp-finding-checkbox:checked').forEach(function (cb) {
        cb.checked = false;
    });
    selectedFPFindings = [];
    var bar = document.getElementById('bulk-fp-bar');
    if (bar) {
        bar.style.setProperty('display', 'none', 'important');
    }
};

window.showBulkFPModal = function () {
    var existing = document.getElementById('bulk-fp-modal-overlay');
    if (existing) existing.remove();

    var overlay = document.createElement('div');
    overlay.id = 'bulk-fp-modal-overlay';
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.7);z-index:10000;display:flex;align-items:center;justify-content:center;';

    var modal = document.createElement('div');
    modal.style.cssText = 'background:#1e293b;border:1px solid #334155;border-radius:8px;padding:1.5rem;max-width:500px;width:90%;box-shadow:0 20px 60px rgba(0,0,0,0.5);';

    modal.innerHTML =
        '<h3 style="margin:0 0 0.5rem 0;color:#f59e0b;">Submit False Positive Request</h3>' +
        '<p style="color:#94a3b8;font-size:0.85rem;margin:0 0 1rem 0;">Marking <strong>' + selectedFPFindings.length + '</strong> finding(s) as false positive. These will be sent to an Operator for review.</p>' +
        '<label style="display:block;color:#cbd5e1;font-size:0.85rem;margin-bottom:0.4rem;">Reason for marking as FP (required)</label>' +
        '<textarea id="bulk-fp-reason" rows="4" style="width:100%;background:#0f172a;color:#e2e8f0;border:1px solid #334155;border-radius:4px;padding:0.6rem;font-size:0.85rem;resize:vertical;box-sizing:border-box;" placeholder="Explain why this is a false positive..."></textarea>' +
        '<div style="display:flex;gap:0.75rem;justify-content:flex-end;margin-top:1rem;">' +
            '<button onclick="this.closest(\'#bulk-fp-modal-overlay\').remove()" style="background:transparent;color:#64748b;border:1px solid #475569;padding:0.5rem 1rem;border-radius:4px;cursor:pointer;">Cancel</button>' +
            '<button id="bulk-fp-submit-btn" onclick="submitBulkFPRequest()" style="background:#f59e0b;color:#0f172a;border:none;padding:0.5rem 1rem;border-radius:4px;font-weight:600;cursor:pointer;">Submit ' + selectedFPFindings.length + ' Request(s)</button>' +
        '</div>';

    overlay.appendChild(modal);
    document.body.appendChild(overlay);

    overlay.addEventListener('click', function (e) {
        if (e.target === overlay) overlay.remove();
    });
};

window.submitBulkFPRequest = function () {
    var reason = document.getElementById('bulk-fp-reason').value.trim();
    if (!reason) {
        document.getElementById('bulk-fp-reason').style.borderColor = '#ef4444';
        return;
    }

    var btn = document.getElementById('bulk-fp-submit-btn');
    btn.disabled = true;
    btn.textContent = 'Submitting...';

    // Gather findings data
    var allFindings = window._scanDetailFindings || [];
    var selected = [];
    selectedFPFindings.forEach(function (idx) {
        var f = allFindings[idx];
        if (f) selected.push(f);
    });

    if (selected.length === 0) {
        showToast('No findings data available for selected items.', 'warning');
        return;
    }

    var scanMeta = window._scanDetailScanMeta || {};

    var promises = selected.map(function (f) {
        var payload = {
            finding: {
                file: f.file || '',
                line: f.line || 0,
                type: f.type || '',
                title: f.title || f.message || '',
                message: f.message || '',
                severity: f.severity || 'INFO',
                sources: f.sources || [],
                details: f.details || {}
            },
            viewer_reason: reason,
            scan_metadata: {
                repo_name: scanMeta.repo_name || '',
                repo_owner: scanMeta.repo_owner || '',
                branch_name: scanMeta.branch_name || '',
                tool_name: scanMeta.tool_name || '',
                scan_id: scanMeta.scan_id || ''
            }
        };
        return fetch('/api/fp/requests', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        }).then(function (r) { return r.json(); });
    });

    Promise.all(promises).then(function (results) {
        var success = results.filter(function (r) { return r.success === true; }).length;
        var failed = results.filter(function (r) { return r.success !== true; }).length;
        var overlay = document.getElementById('bulk-fp-modal-overlay');
        if (overlay) overlay.remove();

        // Visual feedback: mark successfully submitted findings with pending-review style
        if (success > 0) {
            selectedFPFindings.forEach(function (idx) {
                var item = document.querySelector('.finding-item[data-fp-index="' + idx + '"]');
                if (item) {
                    item.classList.add('fp-pending-review');
                    var badge = document.createElement('span');
                    badge.className = 'fp-pending-badge';
                    badge.textContent = 'Pending Review';
                    badge.style.cssText = 'display:inline-block;font-size:0.65rem;background:#f59e0b;color:#0f172a;padding:0.1rem 0.4rem;border-radius:3px;font-weight:600;margin-left:0.5rem;text-transform:uppercase;letter-spacing:0.03em;';
                    var header = item.querySelector('.finding-header');
                    if (header) header.appendChild(badge);
                }
            });
        }

        showToast(
            'Submitted ' + success + ' FP request(s)' + (failed > 0 ? ', ' + failed + ' failed' : '') + '.',
            failed === 0 ? 'success' : (success > 0 ? 'warning' : 'error')
        );

        selectedFPFindings = [];
        document.querySelectorAll('.fp-finding-checkbox').forEach(function (cb) { cb.checked = false; });
        var barEl = document.getElementById('bulk-fp-bar');
        if (barEl) {
            barEl.style.setProperty('display', 'none', 'important');
        }
        btn.disabled = false;
        btn.textContent = 'Submit ' + selectedFPFindings.length + ' Request(s)';
    }).catch(function (err) {
        showToast('Error submitting FP requests: ' + (err.message || err), 'error');
        btn.disabled = false;
        btn.textContent = 'Submit ' + selectedFPFindings.length + ' Request(s)';
    });
};

// ============ OVERRIDE SWITCH TAB ============

// Override switchTab to preserve inline view state
var origSwitchTab = window.switchTab;
if (origSwitchTab) {
    window.switchTab = function(tabName) {
        origSwitchTab(tabName);
        // Stop FP polling if leaving FP tab
        if (tabName !== 'false-positives') {
            if (window.stopFPPolling) window.stopFPPolling();
        }
        // Clear notification badge when visiting FP tab (fetch actual count to avoid re-triggering sound)
        if (tabName === 'false-positives') {
            updateNotifBadge(0);
            fetch('/api/fp/pending-count', { credentials: 'include' })
                .then(function(r) { return r.json(); })
                .then(function(data) { _lastPendingCount = data.count || 0; })
                .catch(function() { _lastPendingCount = 0; });
        }
        if (tabName === 'activity') {
            var savedUserId = inlineUserId || localStorage.getItem('activityUserId');
            if (savedUserId) {
                if (!inlineUserId) {
                    inlineUserId = parseInt(savedUserId);
                    inlineUsername = localStorage.getItem('activityUsername') || 'User';
                }
                resumeInlineView();
            } else {
                loadActivityUsers();
            }
        } else {
            stopInlinePoll();
        }
    };
}

// ============ NOTIFICATION SYSTEM (FP Review Queue) ============

var _lastPendingCount = 0;

function playNotifSound() {
    try {
        var audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        var osc = audioCtx.createOscillator();
        var gain = audioCtx.createGain();
        osc.connect(gain);
        gain.connect(audioCtx.destination);
        osc.type = 'sine';
        osc.frequency.setValueAtTime(880, audioCtx.currentTime);
        osc.frequency.setValueAtTime(660, audioCtx.currentTime + 0.12);
        gain.gain.setValueAtTime(0.3, audioCtx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + 0.4);
        osc.start(audioCtx.currentTime);
        osc.stop(audioCtx.currentTime + 0.4);
    } catch(e) {}
}

function updateNotifBadge(count) {
    var badge = document.getElementById('notif-badge');
    if (!badge) return;
    if (count > 0) {
        badge.textContent = count > 99 ? '99+' : count;
        badge.style.display = 'flex';
    } else {
        badge.style.display = 'none';
    }
}

function pollPendingCount() {
    fetch('/api/fp/pending-count', { credentials: 'include' })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var count = data.count || 0;
            if (count > 0 && _lastPendingCount === 0) {
                playNotifSound();
            }
            _lastPendingCount = count;
            updateNotifBadge(count);
        })
        .catch(function() {});
}

function startNotifPolling() {
    pollPendingCount();
    setInterval(pollPendingCount, 10000);
}

// Start notification polling after user role is known
if (currentUserRole === 'operator' || currentUserRole === 'admin') {
    startNotifPolling();
} else if (!currentUserRole) {
    // Retry until loadCurrentUser completes (max 50 tries = 10s)
    var _notifRetry = 0;
    var _notifTimer = setInterval(function() {
        _notifRetry++;
        if (_notifRetry > 50) { clearInterval(_notifTimer); return; }
        if (currentUserRole === 'operator' || currentUserRole === 'admin') {
            clearInterval(_notifTimer);
            startNotifPolling();
        }
    }, 200);
}

function resumeInlineView() {
    document.getElementById('user-cards-view').style.display = 'none';
    document.getElementById('user-activity-inline').style.display = '';
    loadInlineUserLogs();
    startInlinePoll();
}
