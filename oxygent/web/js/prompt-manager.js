/**
 * Live Prompt Manager - Optimized JavaScript Module
 * High-performance frontend for OxyGent live prompt management
 */

// State management - Optimized
const state = {
    prompts: [],
    filteredPrompts: [],
    currentPrompt: null,
    isLoading: false
};

// DOM cache - Performance optimization
const dom = {};

// Initialize DOM cache
function initDOMCache() {
    dom.searchInput = document.getElementById('searchInput');
    dom.promptsList = document.getElementById('promptsList');
    dom.editModal = document.getElementById('edit-modal');
    dom.historyModal = document.getElementById('history-modal');
    dom.previewModal = document.getElementById('preview-modal');
    dom.editForm = document.getElementById('edit-form');
    dom.editKey = document.getElementById('edit_prompt_key');
    dom.editContent = document.getElementById('edit_prompt_content');
    dom.editIsActive = document.getElementById('edit_is_active');
    dom.versionList = document.getElementById('version-list');
    dom.previewContent = document.getElementById('preview-content');
    dom.previewVersionInfo = document.getElementById('preview-version-info');
    dom.previewDateInfo = document.getElementById('preview-date-info');
    dom.previewStats = document.getElementById('preview-stats');
    dom.previewRollbackBtn = document.getElementById('preview-rollback-btn');
}

// Optimized debounce with immediate option
const debounce = (func, wait, immediate = false) => {
    let timeout;
    return (...args) => {
        const later = () => {
            timeout = null;
            if (!immediate) func.apply(null, args);
        };
        const callNow = immediate && !timeout;
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
        if (callNow) func.apply(null, args);
    };
};

// Optimized DOM ready
document.addEventListener('DOMContentLoaded', () => {
    console.log('🚀 Live Prompt Manager initialized');
    initDOMCache();
    setupEventListeners();
    loadPrompts();
});

// Event listeners - Optimized with delegation
function setupEventListeners() {
    // Search with optimized debounce
    dom.searchInput?.addEventListener('input', debounce(handleSearchInput, 300));

    // Keyboard shortcuts
    document.addEventListener('keydown', handleKeydown);

    // Modal close handlers - Event delegation
    document.addEventListener('click', handleModalClicks);

    // Form submission
    dom.editForm?.addEventListener('submit', handleFormSubmit);
}

function handleSearchInput(e) {
    const query = e.target.value;
    query.length > 0 ? searchPrompts() : resetSearch();
}

function handleKeydown(e) {
    if (e.key === 'Escape') {
        // Close modals in priority order - preview first, then others
        if (dom.previewModal && dom.previewModal.style.display === 'block') {
            hidePreviewModal();
        } else if (dom.editModal && dom.editModal.style.display === 'block') {
            hideEditModal();
        } else if (dom.historyModal && dom.historyModal.style.display === 'block') {
            hideHistoryModal();
        }
    }
}

function handleModalClicks(e) {
    if (e.target.classList.contains('modal')) {
        // Close the specific modal that was clicked
        if (e.target.id === 'preview-modal') {
            hidePreviewModal();
        } else if (e.target.id === 'edit-modal') {
            hideEditModal();
        } else if (e.target.id === 'history-modal') {
            hideHistoryModal();
        }
    }
}

function handleFormSubmit(e) {
    e.preventDefault();
    savePrompt();
}

function resetSearch() {
    state.filteredPrompts = [...state.prompts];
    renderPrompts();
}

// API functions - Optimized with error handling
async function loadPrompts() {
    if (state.isLoading) return;

    state.isLoading = true;
    showLoading("Loading prompts...");

    try {
        const response = await fetch('/api/prompts/', {
            headers: { 'Accept': 'application/json' }
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const result = await response.json();

        if (result.success) {
            state.prompts = result.data || [];
            state.filteredPrompts = [...state.prompts];
            renderPrompts();
            console.log(`✅ Loaded ${state.prompts.length} prompts`);
        } else {
            throw new Error(result.message || 'Failed to load prompts');
        }
    } catch (error) {
        console.error('❌ Error loading prompts:', error);
        showError('Failed to load prompts: ' + error.message);
    } finally {
        state.isLoading = false;
    }
}

// Optimized search with better performance
function searchPrompts() {
    const query = dom.searchInput.value.toLowerCase().trim();

    if (!query) {
        resetSearch();
        return;
    }

    // Optimized search algorithm
    state.filteredPrompts = state.prompts.filter(prompt => {
        const searchFields = [
            prompt.prompt_key,
            prompt.prompt_content,
            prompt.agent_type,
            prompt.description
        ].filter(Boolean);

        return searchFields.some(field =>
            field.toLowerCase().includes(query)
        );
    });

    renderPrompts();
    console.log(`🔍 Search "${query}" found ${state.filteredPrompts.length} results`);
}

// Legacy search handler for backward compatibility
function handleSearch(event) {
    if (event.key === 'Enter') {
        searchPrompts();
    }
}

// Optimized rendering with DocumentFragment
function renderPrompts() {
    if (!dom.promptsList) return;

    if (state.filteredPrompts.length === 0) {
        dom.promptsList.innerHTML = `
            <div class="empty-state">
                <div class="empty-icon">📝</div>
                <h3>No prompts found</h3>
                <p>Try adjusting your search or check if agents are running.</p>
            </div>
        `;
        return;
    }

    // Use DocumentFragment for better performance
    const fragment = document.createDocumentFragment();

    state.filteredPrompts.forEach(prompt => {
        const card = createPromptCard(prompt);
        fragment.appendChild(card);
    });

    dom.promptsList.innerHTML = '';
    dom.promptsList.appendChild(fragment);
}

// Optimized card creation
function createPromptCard(prompt) {
    const card = document.createElement('div');
    card.className = 'prompt-card';
    card.dataset.promptKey = prompt.prompt_key;

    const statusBadge = prompt.is_active ?
        '<span class="badge badge-active">Active</span>' :
        '<span class="badge badge-inactive">Inactive</span>';

    const truncatedContent = prompt.prompt_content.length > 200
        ? prompt.prompt_content.substring(0, 200) + '...'
        : prompt.prompt_content;

    card.innerHTML = `
        <div class="prompt-card-header">
            <h3 class="prompt-title">${escapeHtml(prompt.prompt_key)}</h3>
            <div class="prompt-meta">
                <span class="badge badge-agent">${escapeHtml(prompt.agent_type || 'General')}</span>
                ${statusBadge}
                <span class="badge badge-version">v${prompt.version || 1}</span>
            </div>
        </div>
        <div class="prompt-content">
            ${escapeHtml(truncatedContent)}
        </div>
        <div class="prompt-actions">
            <button class="btn btn-sm btn-info" onclick="editPrompt('${escapeHtml(prompt.prompt_key)}')">
                ✏️ Edit
            </button>
            <button class="btn btn-sm btn-success" onclick="refreshPrompt('${escapeHtml(prompt.prompt_key)}')">
                🔄 Refresh
            </button>
            <button class="btn btn-sm btn-warning" onclick="showVersionHistory('${escapeHtml(prompt.prompt_key)}')">
                📋 History
            </button>
        </div>
    `;

    return card;
}

// Optimized HTML escape
const escapeHtml = (() => {
    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    };
    const reg = /[&<>"']/g;
    return text => String(text).replace(reg, m => map[m]);
})();

// CRUD Operations - Optimized with better error handling
async function editPrompt(promptKey) {
    try {
        showNotification('Loading prompt...', 'info');

        const response = await fetch(`/api/prompts/${promptKey}`, {
            headers: { 'Accept': 'application/json' }
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const result = await response.json();

        if (result.success) {
            state.currentPrompt = result.data;
            dom.editKey.value = state.currentPrompt.prompt_key;
            dom.editContent.value = state.currentPrompt.prompt_content;
            dom.editIsActive.checked = state.currentPrompt.is_active || false;
            showEditModal();

            // Focus with better UX
            requestAnimationFrame(() => {
                dom.editContent?.focus();
                dom.editContent?.setSelectionRange(0, 0);
            });

            console.log(`📝 Editing prompt: ${promptKey}`);
        } else {
            throw new Error(result.message || 'Failed to load prompt');
        }
    } catch (error) {
        console.error('❌ Error loading prompt:', error);
        showNotification('Failed to load prompt: ' + error.message, 'error');
    }
}

async function savePrompt() {
    const promptKey = dom.editKey.value.trim();
    const promptContent = dom.editContent.value.trim();
    const isActive = dom.editIsActive.checked;

    if (!promptKey || !promptContent) {
        showNotification('Please fill in all required fields.', 'error');
        return;
    }

    try {
        showNotification('Saving prompt...', 'info');

        const payload = {
            prompt_key: promptKey,
            prompt_content: promptContent,
            agent_type: state.currentPrompt.agent_type,
            is_active: isActive,
            version: (state.currentPrompt.version || 1) + 1,
            description: state.currentPrompt.description,
            category: state.currentPrompt.category || 'agent'
        };

        const response = await fetch(`/api/prompts/${promptKey}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            },
            body: JSON.stringify(payload)
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const result = await response.json();

        if (result.success) {
            showNotification('Prompt updated successfully!', 'success');
            hideEditModal();
            await loadPrompts(); // Refresh data
            console.log(`✅ Saved prompt: ${promptKey}`);
        } else {
            throw new Error(result.message || 'Save failed');
        }
    } catch (error) {
        console.error('❌ Error saving prompt:', error);
        showNotification('Failed to save prompt: ' + error.message, 'error');
    }
}

async function refreshPrompt(promptKey) {
    try {
        showNotification('Refreshing prompt...', 'info');

        // Simply reload the prompts list to refresh the data
        await loadPrompts();

        showNotification('Prompt refreshed successfully!', 'success');
        console.log(`🔄 Refreshed: ${promptKey}`);
    } catch (error) {
        console.error('❌ Error refreshing prompt:', error);
        showNotification('Failed to refresh prompt: ' + error.message, 'error');
    }
}

async function showVersionHistory(promptKey) {
    try {
        showNotification('Loading version history...', 'info');

        const response = await fetch(`/api/prompts/${promptKey}/history`, {
            headers: { 'Accept': 'application/json' }
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const result = await response.json();

        if (result.success) {
            const versions = result.data || [];
            renderVersionHistory(versions, promptKey);
            showHistoryModal();
            console.log(`📋 Loaded ${versions.length} versions for: ${promptKey}`);
        } else {
            throw new Error(result.message || 'Failed to load version history');
        }
    } catch (error) {
        console.error('❌ Error loading version history:', error);
        showNotification('Failed to load version history: ' + error.message, 'error');
    }
}

// Version History & UI Components - Optimized
function renderVersionHistory(versions, promptKey) {
    if (!dom.versionList) return;

    if (versions.length === 0) {
        dom.versionList.innerHTML = `
            <div class="empty-state">
                <div class="empty-icon">📋</div>
                <p>No version history available.</p>
            </div>
        `;
        return;
    }

    // Sort versions efficiently
    versions.sort((a, b) => (b.version || 0) - (a.version || 0));

    const fragment = document.createDocumentFragment();

    versions.forEach(version => {
        const item = document.createElement('div');
        item.className = `version-item${version.is_current ? ' current' : ''}`;

        const date = new Date(version.created_at).toLocaleString();
        const isCurrent = version.is_current;

        item.innerHTML = `
            <div class="version-info">
                <div class="version-number">
                    Version ${version.version} ${isCurrent ? '(Current)' : ''}
                </div>
                <div class="version-date">📅 ${date}</div>
            </div>
            <div class="version-actions">
                <button class="btn btn-sm btn-info" onclick="previewVersion('${escapeHtml(promptKey)}', ${version.version})">
                    👁️ Preview
                </button>
                ${!isCurrent ? `<button class="btn btn-sm btn-warning" onclick="rollbackToVersion('${escapeHtml(promptKey)}', ${version.version})">
                    ↩️ Rollback
                </button>` : ''}
            </div>
        `;

        fragment.appendChild(item);
    });

    dom.versionList.innerHTML = '';
    dom.versionList.appendChild(fragment);
}

// Enhanced preview function with better modal
let currentPreviewData = null;

async function previewVersion(promptKey, version) {
    try {
        showNotification('Loading version preview...', 'info');

        const response = await fetch(`/api/prompts/${promptKey}/version/${version}`, {
            headers: { 'Accept': 'application/json' }
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const result = await response.json();

        if (result.success) {
            const versionData = result.data;
            currentPreviewData = { promptKey, version, data: versionData };

            // Update preview modal content
            updatePreviewModal(versionData, promptKey, version);
            showPreviewModal();

            console.log(`👁️ Previewed version ${version} of: ${promptKey}`);
        } else {
            throw new Error(result.message || 'Failed to load version');
        }
    } catch (error) {
        console.error('❌ Error loading version:', error);
        showNotification('Failed to load version: ' + error.message, 'error');
    }
}

function updatePreviewModal(versionData, promptKey, version) {
    // Update version info
    dom.previewVersionInfo.textContent = `Version ${version}`;

    // Update date info
    const date = new Date(versionData.created_at || Date.now()).toLocaleString();
    dom.previewDateInfo.textContent = `📅 ${date}`;

    // Update stats
    const content = versionData.prompt_content || '';
    const wordCount = content.split(/\s+/).filter(word => word.length > 0).length;
    const charCount = content.length;
    const lineCount = content.split('\n').length;

    dom.previewStats.innerHTML = `
        <span>📝 ${wordCount} words</span> •
        <span>🔤 ${charCount} characters</span> •
        <span>📄 ${lineCount} lines</span>
    `;

    // Update content
    dom.previewContent.textContent = content;
    dom.previewContent.className = 'preview-content wrapped';

    // Update rollback button
    dom.previewRollbackBtn.onclick = () => {
        hidePreviewModal();
        rollbackToVersion(promptKey, version);
    };
}

// Preview modal management - Don't interfere with history modal
function showPreviewModal() {
    if (dom.previewModal) {
        dom.previewModal.style.display = 'block';
        // Don't change body overflow since history modal might still be open
    }
}

function hidePreviewModal() {
    if (dom.previewModal) {
        dom.previewModal.style.display = 'none';
        // Only restore body overflow if no other modals are open
        const otherModalsOpen = (dom.editModal && dom.editModal.style.display === 'block') ||
                               (dom.historyModal && dom.historyModal.style.display === 'block');
        if (!otherModalsOpen) {
            document.body.style.overflow = 'auto';
        }
    }
    currentPreviewData = null;
}

// Preview utility functions
function copyPreviewContent() {
    if (!currentPreviewData) return;

    const content = currentPreviewData.data.prompt_content || '';

    navigator.clipboard.writeText(content).then(() => {
        showCopyFeedback();
        showNotification('Content copied to clipboard!', 'success');
    }).catch(err => {
        console.error('Failed to copy content:', err);
        showNotification('Failed to copy content', 'error');
    });
}

function togglePreviewMode() {
    if (!dom.previewContent) return;

    if (dom.previewContent.classList.contains('wrapped')) {
        dom.previewContent.classList.remove('wrapped');
        dom.previewContent.classList.add('raw');
    } else {
        dom.previewContent.classList.remove('raw');
        dom.previewContent.classList.add('wrapped');
    }
}

function showCopyFeedback() {
    // Remove existing feedback
    const existing = document.querySelector('.copy-feedback');
    if (existing) {
        existing.remove();
    }

    // Create feedback element
    const feedback = document.createElement('div');
    feedback.className = 'copy-feedback';
    feedback.textContent = 'Copied!';

    // Add to preview container
    const container = document.querySelector('.preview-content-container');
    if (container) {
        container.appendChild(feedback);

        // Show feedback
        requestAnimationFrame(() => {
            feedback.classList.add('show');
        });

        // Hide after delay
        setTimeout(() => {
            feedback.classList.remove('show');
            setTimeout(() => {
                if (feedback.parentNode) {
                    feedback.remove();
                }
            }, 300);
        }, 2000);
    }
}

async function rollbackToVersion(promptKey, version) {
    if (!confirm(`Are you sure you want to rollback "${promptKey}" to version ${version}?\n\nThis will create a new version with the content from version ${version}.`)) {
        return;
    }

    try {
        showNotification('Rolling back to version ' + version + '...', 'info');

        const response = await fetch(`/api/prompts/${promptKey}/revert/${version}`, {
            method: 'POST',
            headers: { 'Accept': 'application/json' }
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const result = await response.json();

        if (result.success) {
            showNotification('Successfully rolled back to version ' + version + '!', 'success');
            hideHistoryModal();
            await loadPrompts();
            console.log(`↩️ Rolled back ${promptKey} to version ${version}`);
        } else {
            throw new Error(result.message || 'Rollback failed');
        }
    } catch (error) {
        console.error('❌ Error rolling back:', error);
        showNotification('Failed to rollback: ' + error.message, 'error');
    }
}

// Modal Management - Optimized
function showEditModal() {
    if (dom.editModal) {
        dom.editModal.style.display = 'block';
        document.body.style.overflow = 'hidden';
    }
}

function hideEditModal() {
    if (dom.editModal) {
        dom.editModal.style.display = 'none';
        document.body.style.overflow = 'auto';
    }
}

function showHistoryModal() {
    if (dom.historyModal) {
        dom.historyModal.style.display = 'block';
        document.body.style.overflow = 'hidden';
    }
}

function hideHistoryModal() {
    if (dom.historyModal) {
        dom.historyModal.style.display = 'none';
        document.body.style.overflow = 'auto';
    }
}

// UI State Management - Optimized
function showLoading(message = "Loading...") {
    if (!dom.promptsList) return;

    dom.promptsList.innerHTML = `
        <div class="loading">
            <div class="loading-spinner"></div>
            <p>${escapeHtml(message)}</p>
        </div>
    `;
}

function showError(message) {
    if (!dom.promptsList) return;

    dom.promptsList.innerHTML = `
        <div class="empty-state">
            <div class="empty-icon">⚠️</div>
            <h3>Error</h3>
            <p>${escapeHtml(message)}</p>
            <button class="btn btn-primary" onclick="loadPrompts()">
                🔄 Retry
            </button>
        </div>
    `;
}

// Notification System - Optimized
let notificationTimeout;

function showNotification(message, type = 'info') {
    // Clear existing notification
    const existing = document.querySelector('.notification');
    if (existing) {
        existing.remove();
    }

    // Clear existing timeout
    if (notificationTimeout) {
        clearTimeout(notificationTimeout);
    }

    // Create notification
    const notification = document.createElement('div');
    notification.className = `notification ${type}`;
    notification.textContent = message;
    document.body.appendChild(notification);

    // Show with animation
    requestAnimationFrame(() => {
        notification.classList.add('show');
    });

    // Auto-hide
    const hideDelay = type === 'error' ? 5000 : 3000;
    notificationTimeout = setTimeout(() => {
        notification.classList.remove('show');
        setTimeout(() => {
            if (notification.parentNode) {
                notification.remove();
            }
        }, 300);
    }, hideDelay);
}

// Lazy Loading Implementation
const lazyLoad = (() => {
    let observer;

    const init = () => {
        if ('IntersectionObserver' in window) {
            observer = new IntersectionObserver((entries) => {
                entries.forEach(entry => {
                    if (entry.isIntersecting) {
                        const card = entry.target;
                        // Lazy load additional data if needed
                        observer.unobserve(card);
                    }
                });
            }, {
                rootMargin: '50px'
            });
        }
    };

    const observe = (element) => {
        if (observer) {
            observer.observe(element);
        }
    };

    return { init, observe };
})();

// Global API - Optimized exports
const LivePromptManager = {
    loadPrompts,
    searchPrompts,
    editPrompt,
    savePrompt,
    refreshPrompt,
    showVersionHistory,
    showNotification,
    // Additional utilities
    state: () => ({ ...state }),
    refresh: loadPrompts
};

// Initialize lazy loading
lazyLoad.init();

// Export to global scope
window.LivePromptManager = LivePromptManager;

console.log('📦 Live Prompt Manager optimized module loaded');