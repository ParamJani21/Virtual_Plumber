"""
Overview Tab Module - Dashboard summary and key metrics
"""

import os
import json
import time as time_module
from datetime import datetime

LOGS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs', 'tool-output')
TMP_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'tmp')

_OVERVIEW_CACHE = {'data': None, 'time': 0, 'ttl': 5}

BULK_COOLDOWN = {
    'active': False,
    'current_repo': '',
    'repo_index': 0,
    'total_repos': 0,
    'remaining': 0,
    'updated_at': 0
}

SCAN_STEPS = [
    {'id': 1, 'name': 'cloning', 'label': '🦊 Cloning repository...', 'done': '✅ Cloned'},
    {'id': 2, 'name': 'opengrep', 'label': '🔍 Running OpenGrep scan...', 'done': '✅ OpenGrep done'},
    {'id': 3, 'name': 'trufflehog', 'label': '🔐 Running TruffleHog scan...', 'done': '✅ TruffleHog done'},
    {'id': 4, 'name': 'trivy', 'label': '🛡️ Running Trivy scan...', 'done': '✅ Trivy done'},
    {'id': 5, 'name': 'saving', 'label': '💾 Saving results...', 'done': '✅ Results saved'},
    {'id': 6, 'name': 'cleanup', 'label': '🧹 Cleaning up...', 'done': '✅ Cleanup done'}
]

def get_overview_data():
    """
    Fetches overview dashboard data including security metrics from tool-output
    """
    global _OVERVIEW_CACHE
    now = time_module.time()
    
    # Use cache for heavy data (recent_scans), refresh light data (active_scans, cooldown) every call
    if _OVERVIEW_CACHE['data'] is not None and now - _OVERVIEW_CACHE['time'] < _OVERVIEW_CACHE['ttl']:
        cached = _OVERVIEW_CACHE['data']
        recent_scans = cached['recent_scans']
        total_critical = cached['critical_issues']
        total_high = cached['high_issues']
        total_medium = cached['medium_issues']
        total_low = cached['low_issues']
    else:
        recent_scans = get_recent_scans(10)
        total_critical = 0
        total_high = 0
        total_medium = 0
        total_low = 0
        for scan in recent_scans:
            severity = scan.get('severity', {})
            total_critical += severity.get('CRITICAL', 0)
            total_high += severity.get('HIGH', 0)
            total_medium += severity.get('MEDIUM', 0)
            total_low += severity.get('LOW', 0)
    
    active_scans = get_active_scans()
    
    # Update cooldown remaining time
    cooldown = dict(BULK_COOLDOWN)
    if cooldown['active']:
        elapsed = time_module.time() - cooldown['updated_at']
        cooldown['remaining'] = max(0, int(10 - elapsed))
        if cooldown['remaining'] == 0:
            BULK_COOLDOWN['active'] = False
            cooldown['active'] = False
    
    result = {
        'total_repos': 0,
        'active_scans': len(active_scans),
        'critical_issues': total_critical,
        'high_issues': total_high,
        'medium_issues': total_medium,
        'low_issues': total_low,
        'compliance_score': calculate_security_score(total_critical, total_high, total_medium, total_low),
        'last_scan': recent_scans[0]['timestamp'] if recent_scans else None,
        'scan_status': 'idle' if len(active_scans) == 0 else 'scanning',
        'security_trends': {},
        'top_vulnerabilities': [],
        'recent_scans': recent_scans,
        'active_scans_list': active_scans,
        'bulk_cooldown': cooldown
    }
    
    _OVERVIEW_CACHE['data'] = result
    _OVERVIEW_CACHE['time'] = time_module.time()
    return result


def get_active_scans():
    """
    Get currently active scans from tmp directory only.
    Handles both structures:
      tmp/{owner}/{repo}/  (legacy)
      tmp/{scan_id}/{owner}/{repo}/  (scan-id-based)
    """
    active = []
    
    if not os.path.exists(TMP_DIR):
        return active
    
    try:
        for first_level in os.listdir(TMP_DIR):
            first_path = os.path.join(TMP_DIR, first_level)
            if not os.path.isdir(first_path):
                continue
            
            # Check if first_level looks like a scan_id (has subdirs that are owners)
            # or is itself an owner (has subdirs that are repos)
            for second_level in os.listdir(first_path):
                second_path = os.path.join(first_path, second_level)
                if not os.path.isdir(second_path):
                    continue
                
                # If second_path itself has subdirectories, it's a scan-id-based structure
                # where first_level=scan_id, second_level=owner, third_level=repo
                has_subdirs = False
                try:
                    for entry in os.listdir(second_path):
                        if os.path.isdir(os.path.join(second_path, entry)):
                            has_subdirs = True
                            break
                except:
                    pass
                
                if has_subdirs:
                    # scan-id-based: tmp/{scan_id}/{owner}/{repo}/
                    scan_id = first_level
                    owner = second_level
                    owner_path = second_path
                    for repo_name in os.listdir(owner_path):
                        repo_path = os.path.join(owner_path, repo_name)
                        if not os.path.isdir(repo_path):
                            continue
                        has_git = os.path.exists(os.path.join(repo_path, '.git'))
                        has_content = len(os.listdir(repo_path)) > 0
                        if has_git or has_content:
                            active.append({
                                'repo_name': repo_name,
                                'owner': owner,
                                'scan_id': scan_id,
                                'repo_path': repo_path,
                                'started_at': get_directory_time(repo_path)
                            })
                else:
                    # legacy: tmp/{owner}/{repo}/
                    owner = first_level
                    repo_name = second_level
                    repo_path = second_path
                    has_git = os.path.exists(os.path.join(repo_path, '.git'))
                    has_content = len(os.listdir(repo_path)) > 0
                    if has_git or has_content:
                        active.append({
                            'repo_name': repo_name,
                            'owner': owner,
                            'repo_path': repo_path,
                            'started_at': get_directory_time(repo_path)
                        })
    except Exception as e:
        print(f"Error detecting active scans from tmp: {e}")
    
    return active


def get_active_scans_from_logs():
    """Detect active scans from recent log activity"""
    scans = []
    logs_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs')
    app_log = os.path.join(logs_dir, 'app.log')
    
    if not os.path.exists(app_log):
        return scans
    
    try:
        with open(app_log, 'r') as f:
            lines = f.readlines()[-200:]
        
        # Check if any scan is in progress based on STEP markers
        step_markers = ['step 1', 'step 2', 'step 3', 'step 4', 'step 5', 'step 6']
        
        for line in lines[-30:]:  # Last 30 lines are most recent
            line_lower = line.lower()
            
            # If we see step markers in recent logs, scan is likely active
            has_step = any(step in line_lower for step in step_markers)
            if has_step:
                # Try to extract repo info from log line
                repo_info = extract_repo_from_log_line(line)
                if repo_info:
                    scans.append({
                        'repo_name': repo_info['repo_name'],
                        'owner': repo_info['owner'],
                        'repo_path': '',
                        'progress': determine_scan_progress_from_logs(lines),
                        'started_at': 'In Progress'
                    })
                break
                
    except Exception as e:
        print(f"Error detecting scans from logs: {e}")
    
    return scans


def extract_repo_from_log_line(line):
    """Extract owner/repo from log line"""
    try:
        # Look for patterns like "owner/repo" in logs
        import re
        # Match github.com/owner/repo or just owner/repo
        patterns = [
            r'github\.com[/:]([a-zA-Z0-9_-]+)/([a-zA-Z0-9_-]+)',
            r'(?:cloning|scanning|scanned)\s+([a-zA-Z0-9_-]+)/([a-zA-Z0-9_-]+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                return {'owner': match.group(1), 'repo_name': match.group(2)}
        
        return None
    except:
        return None


def get_scan_progress(repo_name, owner):
    """Get scan progress by reading recent logs"""
    if not repo_name or not owner:
        return [dict(SCAN_STEPS[0], status='current')]
    
    logs_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs')
    app_log = os.path.join(logs_dir, 'app.log')
    
    if not os.path.exists(app_log):
        return [dict(SCAN_STEPS[0], status='current')]
    
    try:
        with open(app_log, 'r') as f:
            lines = f.readlines()[-100:]
        
        # Look for this specific repo in logs
        repo_lower = repo_name.lower()
        owner_lower = owner.lower()
        repo_log_lines = [l for l in lines if repo_lower in l.lower() or owner_lower in l.lower()]
        
        if not repo_log_lines:
            return [dict(SCAN_STEPS[0], status='current')]
        
        return determine_scan_progress_from_logs(repo_log_lines)
        
    except Exception as e:
        print(f"Error reading log for progress: {e}")
        return [dict(SCAN_STEPS[0], status='current')]


def determine_scan_progress_from_logs(lines):
    """
    Determine scan progress from log lines
    """
    log_text = ''.join(lines).lower()
    steps = []
    
    # Check each step
    step_checks = [
        ('clone', 'cloning', 'STEP 1/6'),
        ('opengrep', 'STEP 2/6'),
        ('trufflehog', 'STEP 3/6'),
        ('trivy', 'STEP 4/6'),
        ('save', 'merge', 'STEP 5/6'),
        ('cleanup', 'STEP 6/6')
    ]
    
    current_step = 0
    completed_steps = set()
    
    for i, line in enumerate(lines):
        line_lower = line.lower()
        
        # Track completed steps
        if 'step 1' in line_lower or 'cloning' in line_lower:
            completed_steps.add(0)
            current_step = 1
        if 'step 2' in line_lower or 'opengrep' in line_lower:
            completed_steps.add(1)
            current_step = 2
        if 'step 3' in line_lower or 'trufflehog' in line_lower:
            completed_steps.add(2)
            current_step = 3
        if 'step 4' in line_lower or 'trivy' in line_lower:
            completed_steps.add(3)
            current_step = 4
        if 'step 5' in line_lower or 'save' in line_lower:
            completed_steps.add(4)
            current_step = 5
        if 'step 6' in line_lower or 'cleanup' in line_lower:
            completed_steps.add(5)
            current_step = 6
    
    # Build progress list
    for i, step in enumerate(SCAN_STEPS):
        if i in completed_steps:
            steps.append({'id': step['id'], 'name': step['name'], 'label': step['label'], 'status': 'completed'})
        elif i == current_step or (current_step == 0 and i == 0):
            steps.append({'id': step['id'], 'name': step['name'], 'label': step['label'], 'status': 'current'})
        else:
            steps.append({'id': step['id'], 'name': step['name'], 'label': step['label'], 'status': 'pending'})
    
    # If no steps found, show first step as current
    if not steps:
        steps = [dict(SCAN_STEPS[0], status='current')]
    
    return steps


def get_directory_time(dir_path):
    """Get directory creation/modification time"""
    try:
        stat = os.stat(dir_path)
        return datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
    except:
        return ''


def get_recent_scans(limit=10):
    """
    Get recent scans from tool-output directory
    """
    scans = []
    
    if not os.path.exists(LOGS_DIR):
        return scans
    
    scan_dirs = sorted(os.listdir(LOGS_DIR), reverse=True)[:limit]
    
    for scan_id in scan_dirs:
        scan_path = os.path.join(LOGS_DIR, scan_id)
        if not os.path.isdir(scan_path):
            continue
            
        merged_file = os.path.join(scan_path, 'merged.json')
        if os.path.exists(merged_file):
            try:
                with open(merged_file, 'r') as f:
                    data = json.load(f)
                    
                    # Get severity from summary
                    severity = {'CRITICAL': 0, 'HIGH': 0, 'MEDIUM': 0, 'LOW': 0}
                    summary = data.get('summary', {})
                    by_severity = summary.get('by_severity', {})
                    
                    for sev, count in by_severity.items():
                        if sev in severity:
                            severity[sev] = count
                    
                    # Get timestamp and scan_id
                    timestamp = data.get('timestamp', '')
                    
                    # Get findings count
                    findings = data.get('findings', [])
                    total = summary.get('total_unique', len(findings))
                    
                    # Extract repo name from scan_id (or use "Unknown")
                    repo_name = scan_id[:8] + '...'
                    
                    scans.append({
                        'scan_id': scan_id,
                        'repository': repo_name,
                        'timestamp': timestamp,
                        'total_findings': total,
                        'severity': severity
                    })
            except Exception as e:
                print(f"Error reading {merged_file}: {e}")
    
    return scans


def calculate_security_score(critical, high, medium, low):
    """
    Calculate overall security score based on issues
    """
    total = critical + high + medium + low
    if total == 0:
        return 100
    
    penalty = (critical * 10) + (high * 5) + (medium * 2) + (low * 1)
    score = max(0, 100 - penalty)
    return score


def get_security_status():
    """Determine overall security status"""
    return 'idle'