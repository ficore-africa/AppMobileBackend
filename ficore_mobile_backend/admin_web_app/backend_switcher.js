/**
 * Backend Switcher - Shared JavaScript
 * Add this script to any admin page to enable backend switching
 */

// Initialize backend switcher on page load
function initializeBackendSwitcher() {
    // Create backend switcher HTML
    const switcherHTML = `
        <div class="backend-switcher">
            <label>Backend:</label>
            <div class="backend-toggle">
                <button id="prodBtn" onclick="switchBackend('production')">
                    <span class="backend-indicator production"></span>
                    Production
                </button>
                <button id="devBtn" onclick="switchBackend('dev')">
                    <span class="backend-indicator dev"></span>
                    Dev
                </button>
            </div>
        </div>
    `;
    
    // Append to body
    document.body.insertAdjacentHTML('beforeend', switcherHTML);
    
    // Update UI to show current backend
    updateBackendSwitcherUI();
}

// Update backend switcher UI to show active backend
function updateBackendSwitcherUI() {
    const currentBackend = getCurrentBackend();
    const prodBtn = document.getElementById('prodBtn');
    const devBtn = document.getElementById('devBtn');
    
    if (prodBtn && devBtn) {
        prodBtn.classList.toggle('active', currentBackend === 'production');
        devBtn.classList.toggle('active', currentBackend === 'dev');
    }
}

// Auto-initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initializeBackendSwitcher);
} else {
    initializeBackendSwitcher();
}
