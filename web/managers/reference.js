// Reference Manager - Exposed globally for dashboard integration
window.initReferenceManager = (function() {
    const API_BASE = '/api/managers/reference';
    let currentType = null;
    let currentRefId = null;
    let originalData = null;
    let initialized = false;
    
    // Initialize
    function init() {
        if (initialized) return; // Prevent double initialization
        
        document.querySelectorAll('.ref-type-btn').forEach(btn => {
            btn.addEventListener('click', handleTypeSelect);
        });
        
        document.getElementById('save-reference-btn').addEventListener('click', handleSaveReference);
        document.getElementById('format-json-btn').addEventListener('click', handleFormatJson);
        document.getElementById('reload-references-btn').addEventListener('click', handleReloadReferences);
        
        initialized = true;
    }
    
    // Handle type selection
    async function handleTypeSelect(event) {
        const btnId = event.target.id;
        currentType = btnId.replace('ref-type-', '');
        
        // Update button states
        document.querySelectorAll('.ref-type-btn').forEach(btn => {
            btn.classList.remove('btn-primary');
            btn.classList.add('btn-outline');
        });
        event.target.classList.remove('btn-outline');
        event.target.classList.add('btn-primary');
        
        // Hide editor
        document.getElementById('reference-editor-container').style.display = 'none';
        
        // Load references of this type
        await loadReferences(currentType);
    }
    
    // Load references
    async function loadReferences(type) {
        try {
            const token = localStorage.getItem('access_token');
            const response = await fetch(`${API_BASE}/list/${type}`, {
                headers: {
                    'Authorization': `Bearer ${token}`
                }
            });
            
            if (!response.ok) throw new Error('Failed to load references');
            
            const references = await response.json();
            const container = document.getElementById('reference-buttons');
            container.innerHTML = '';
            
            if (references.length === 0) {
                container.innerHTML = '<p class="text-secondary">No references found</p>';
            } else {
                references.forEach(ref => {
                    const btn = document.createElement('button');
                    btn.className = 'btn btn-outline';
                    btn.textContent = ref.id;
                    btn.dataset.refId = ref.id;
                    btn.addEventListener('click', () => loadReferenceData(type, ref.id));
                    container.appendChild(btn);
                });
            }
            
            document.getElementById('reference-list-container').style.display = 'block';
        } catch (error) {
            showMessage('error', 'Failed to load references: ' + error.message);
        }
    }
    
    // Load reference data
    async function loadReferenceData(type, refId) {
        try {
            const token = localStorage.getItem('access_token');
            const response = await fetch(`${API_BASE}/get/${type}/${refId}`, {
                headers: {
                    'Authorization': `Bearer ${token}`
                }
            });
            
            if (!response.ok) throw new Error('Failed to load reference data');
            
            const result = await response.json();
            currentRefId = refId;
            originalData = result.data;
            
            document.getElementById('current-reference-name').textContent = `${type}/${refId}`;
            document.getElementById('reference-data').value = JSON.stringify(result.data, null, 2);
            document.getElementById('reference-editor-container').style.display = 'block';
            
            // Highlight selected button
            document.querySelectorAll('#reference-buttons .btn').forEach(btn => {
                if (btn.dataset.refId === refId) {
                    btn.classList.remove('btn-outline');
                    btn.classList.add('btn-primary');
                } else {
                    btn.classList.remove('btn-primary');
                    btn.classList.add('btn-outline');
                }
            });
        } catch (error) {
            showMessage('error', 'Failed to load reference data: ' + error.message);
        }
    }
    
    // Handle save reference
    async function handleSaveReference() {
        if (!currentType || !currentRefId) return;
        
        try {
            // Parse JSON
            const data = JSON.parse(document.getElementById('reference-data').value);
            
            const token = localStorage.getItem('access_token');
            const response = await fetch(`${API_BASE}/update`, {
                method: 'PUT',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    ref_type: currentType,
                    ref_id: currentRefId,
                    data: data
                })
            });
            
            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || 'Failed to save reference');
            }
            
            const result = await response.json();
            showMessage('success', result.message, document.getElementById('save-reference-btn'));
            originalData = data;
        } catch (error) {
            if (error instanceof SyntaxError) {
                showMessage('error', 'Invalid JSON: ' + error.message, document.getElementById('save-reference-btn'));
            } else {
                showMessage('error', 'Failed to save reference: ' + error.message, document.getElementById('save-reference-btn'));
            }
        }
    }
    
    // Handle format JSON
    function handleFormatJson() {
        try {
            const data = JSON.parse(document.getElementById('reference-data').value);
            document.getElementById('reference-data').value = JSON.stringify(data, null, 2);
            showMessage('success', 'JSON formatted successfully', document.getElementById('format-json-btn'));
        } catch (error) {
            showMessage('error', 'Invalid JSON: ' + error.message, document.getElementById('format-json-btn'));
        }
    }
    
    // Handle reload references
    async function handleReloadReferences() {
        if (!confirm('Reload all references from database? This will discard any unsaved changes.')) return;
        
        try {
            const token = localStorage.getItem('access_token');
            const response = await fetch(`${API_BASE}/reload`, {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${token}`
                }
            });
            
            if (!response.ok) throw new Error('Failed to reload references');
            
            const result = await response.json();
            showMessage('success', result.message, document.getElementById('reload-references-btn'));
            
            // Reload current view
            if (currentType) {
                await loadReferences(currentType);
            }
            
            // Hide editor
            document.getElementById('reference-editor-container').style.display = 'none';
            currentRefId = null;
        } catch (error) {
            showMessage('error', 'Failed to reload references: ' + error.message, document.getElementById('reload-references-btn'));
        }
    }
    
    // Show message
    function showMessage(type, text, targetElement = null) {
        const messageDiv = document.getElementById('reference-message');
        messageDiv.className = `alert alert-${type === 'error' ? 'danger' : 'success'}`;
        messageDiv.textContent = text;
        messageDiv.style.display = 'block';
        
        // Position the message near the triggering element if provided
        if (targetElement) {
            // Find the closest card container or use the element's parent
            const container = targetElement.closest('.card') || targetElement.closest('.card-body') || targetElement.parentElement;
            if (container && container.parentElement) {
                // Insert the message after the container
                container.parentElement.insertBefore(messageDiv, container.nextSibling);
            }
        }
        
        setTimeout(() => {
            messageDiv.style.display = 'none';
        }, 5000);
    }
    
    // Return the init function for external initialization
    return init;
})();
