// ===== UTILITY FUNCTIONS FOR ADMIN WEB APP =====

// Configuration
const API_BASE_URL = 'https://mobilebackend.ficoreafrica.com';

// Get admin token from localStorage
function getAdminToken() {
    return localStorage.getItem('admin_token');
}

// Get admin permissions from localStorage
function getAdminPermissions() {
    try {
        const permissions = localStorage.getItem('admin_permissions');
        return permissions ? JSON.parse(permissions) : [];
    } catch (error) {
        console.error('Error parsing admin permissions:', error);
        return [];
    }
}

// Check if admin has specific permission
function hasPermission(permission) {
    try {
        const permissions = getAdminPermissions();
        return permissions.includes(permission) || permissions.includes('admin:*');
    } catch (error) {
        console.error('Error checking permission:', error);
        return false;
    }
}

// Show success message
function showSuccess(message) {
    // Create success toast/alert
    const alertDiv = document.createElement('div');
    alertDiv.className = 'alert alert-success';
    alertDiv.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        z-index: 9999;
        padding: 15px 20px;
        background-color: #28a745;
        color: white;
        border-radius: 5px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        animation: slideIn 0.3s ease-out;
    `;
    alertDiv.innerHTML = `
        <i class="fas fa-check-circle"></i> ${message}
    `;
    
    document.body.appendChild(alertDiv);
    
    // Auto-remove after 3 seconds
    setTimeout(() => {
        alertDiv.style.animation = 'slideOut 0.3s ease-out';
        setTimeout(() => alertDiv.remove(), 300);
    }, 3000);
}

// Show error message
function showError(message) {
    // Create error toast/alert
    const alertDiv = document.createElement('div');
    alertDiv.className = 'alert alert-danger';
    alertDiv.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        z-index: 9999;
        padding: 15px 20px;
        background-color: #dc3545;
        color: white;
        border-radius: 5px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        animation: slideIn 0.3s ease-out;
    `;
    alertDiv.innerHTML = `
        <i class="fas fa-exclamation-circle"></i> ${message}
    `;
    
    document.body.appendChild(alertDiv);
    
    // Auto-remove after 5 seconds
    setTimeout(() => {
        alertDiv.style.animation = 'slideOut 0.3s ease-out';
        setTimeout(() => alertDiv.remove(), 300);
    }, 5000);
}

// Show confirmation dialog
function showConfirmation(options) {
    return new Promise((resolve) => {
        const { title, message, details } = options;
        
        // Create modal backdrop
        const backdrop = document.createElement('div');
        backdrop.style.cssText = `
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background-color: rgba(0,0,0,0.5);
            z-index: 9998;
            display: flex;
            align-items: center;
            justify-content: center;
        `;
        
        // Create modal
        const modal = document.createElement('div');
        modal.style.cssText = `
            background: white;
            border-radius: 8px;
            padding: 30px;
            max-width: 500px;
            width: 90%;
            box-shadow: 0 10px 25px rgba(0,0,0,0.2);
        `;
        
        // Build details HTML
        let detailsHTML = '';
        if (details) {
            detailsHTML = '<div style="margin: 15px 0; padding: 15px; background: #f8f9fa; border-radius: 5px;">';
            for (const [key, value] of Object.entries(details)) {
                detailsHTML += `<p style="margin: 5px 0;"><strong>${key}:</strong> ${value}</p>`;
            }
            detailsHTML += '</div>';
        }
        
        modal.innerHTML = `
            <h3 style="margin-top: 0; color: #333;">
                <i class="fas fa-exclamation-triangle" style="color: #ffc107;"></i> ${title}
            </h3>
            <p style="color: #666; font-size: 16px;">${message}</p>
            ${detailsHTML}
            <div style="margin-top: 20px; text-align: right;">
                <button id="cancelBtn" style="
                    padding: 10px 20px;
                    margin-right: 10px;
                    border: 1px solid #ddd;
                    background: white;
                    border-radius: 5px;
                    cursor: pointer;
                    font-size: 14px;
                ">Cancel</button>
                <button id="confirmBtn" style="
                    padding: 10px 20px;
                    border: none;
                    background: #007bff;
                    color: white;
                    border-radius: 5px;
                    cursor: pointer;
                    font-size: 14px;
                ">Confirm</button>
            </div>
        `;
        
        backdrop.appendChild(modal);
        document.body.appendChild(backdrop);
        
        // Handle button clicks
        document.getElementById('confirmBtn').onclick = () => {
            backdrop.remove();
            resolve(true);
        };
        
        document.getElementById('cancelBtn').onclick = () => {
            backdrop.remove();
            resolve(false);
        };
        
        // Close on backdrop click
        backdrop.onclick = (e) => {
            if (e.target === backdrop) {
                backdrop.remove();
                resolve(false);
            }
        };
    });
}

// Refresh user data
async function refreshUserData(userId) {
    try {
        const response = await fetch(`${API_BASE_URL}/admin/users/${userId}`, {
            method: 'GET',
            headers: {
                'Authorization': `Bearer ${getAdminToken()}`,
                'Content-Type': 'application/json'
            }
        });
        
        const data = await response.json();
        
        if (data.success) {
            return data.data;
        } else {
            throw new Error(data.message || 'Failed to refresh user data');
        }
    } catch (error) {
        console.error('Error refreshing user data:', error);
        throw error;
    }
}

// Format currency
function formatCurrency(amount, currency = 'FC') {
    if (currency === 'FC') {
        return `${parseFloat(amount).toFixed(2)} FC`;
    } else if (currency === 'NGN') {
        return `₦${parseFloat(amount).toLocaleString('en-NG', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    }
    return `${parseFloat(amount).toFixed(2)} ${currency}`;
}

// Format date
function formatDate(dateString) {
    if (!dateString) return 'N/A';
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    });
}

// Check authentication
function checkAuth() {
    const token = getAdminToken();
    if (!token) {
        window.location.href = 'admin_login.html';
        return false;
    }
    return true;
}

// Logout
function logout() {
    localStorage.removeItem('admin_token');
    localStorage.removeItem('admin_permissions');
    localStorage.removeItem('admin_user');
    window.location.href = 'admin_login.html';
}

// Add CSS animations
const style = document.createElement('style');
style.textContent = `
    @keyframes slideIn {
        from {
            transform: translateX(100%);
            opacity: 0;
        }
        to {
            transform: translateX(0);
            opacity: 1;
        }
    }
    
    @keyframes slideOut {
        from {
            transform: translateX(0);
            opacity: 1;
        }
        to {
            transform: translateX(100%);
            opacity: 0;
        }
    }
`;
document.head.appendChild(style);
