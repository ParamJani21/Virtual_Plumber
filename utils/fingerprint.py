import hashlib

def generate_fingerprint(tool_name, rule_id, file_path, code_line):
    """
    Generate a stable SHA256 fingerprint for a finding.
    
    This fingerprint survives line shifts, commit changes, PR rebases,
    and repository evolution because it's based on:
    - tool name (opengrep/trufflehog/trivy)
    - rule/detector ID
    - relative file path
    - actual matched code line content
    
    Args:
        tool_name: Source tool name (e.g., 'opengrep', 'trufflehog')
        rule_id: Rule/detector ID or finding type
        file_path: Relative file path
        code_line: The raw code line that matched
    
    Returns:
        SHA256 hex digest string
    """
    raw = f"{tool_name}::{rule_id}::{file_path}::{code_line}"
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def fp_fingerprint_from_finding(finding, source=None):
    """
    Generate fingerprint from a merged finding dict.
    
    The finding dict has the structure from merge_findings():
    {
        'id': str,
        'file': path,
        'line': line_number,
        'type': issue_type,
        'title': ...,
        'message': ...,
        'severity': ...,
        'sources': ['opengrep', ...],
        'details': {...}
    }
    
    Args:
        finding: Finding dict from merged.json
        source: Force a specific source tool. If None, uses finding['sources'][0]
    
    Returns:
        SHA256 hex digest string
    """
    src = source or (finding.get('sources', ['unknown'])[0] if finding.get('sources') else 'unknown')
    rule_id = finding.get('type', 'unknown')
    file_path = finding.get('file', 'unknown')
    code_line = str(finding.get('line', '0'))
    
    # Use first line of message as additional signal for the fingerprint
    msg = (finding.get('message', '') or '')[:100]
    raw = f"{src}::{rule_id}::{file_path}::{code_line}::{msg}"
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()
