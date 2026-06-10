// VIRTUAL_PLUMBER Dashboard JavaScript

// Initialize vulnerability chart
const ctx = document.getElementById('vulnerabilityChart').getContext('2d');
const vulnerabilityChart = new Chart(ctx, {
    type: 'bar',
    data: {
        labels: [], // Scan labels (e.g., dates or scan IDs)
        datasets: [{
            label: 'Vulnerabilities Found',
            data: [], // Vulnerability counts
            backgroundColor: 'rgba(255, 99, 132, 0.2)',
            borderColor: 'rgba(255, 99, 132, 1)',
            borderWidth: 1
        }]
    },
    options: {
        scales: {
            y: {
                beginAtZero: true
            }
        }
    }
});

// Function to update chart data (to be called when data is available)
function updateVulnerabilityChart(labels, data) {
    vulnerabilityChart.data.labels = labels;
    vulnerabilityChart.data.datasets[0].data = data;
    vulnerabilityChart.update();
}

// Function to add active scan (placeholder)
function addActiveScan(scanName, progress) {
    const activeScans = document.getElementById('activeScans');
    const scanElement = document.createElement('div');
    scanElement.className = 'mb-2';
    scanElement.innerHTML = `
        <div class="d-flex justify-content-between">
            <span>${scanName}</span>
            <span>${progress}%</span>
        </div>
        <div class="progress">
            <div class="progress-bar" role="progressbar" style="width: ${progress}%" aria-valuenow="${progress}" aria-valuemin="0" aria-valuemax="100"></div>
        </div>
    `;
    activeScans.appendChild(scanElement);
}