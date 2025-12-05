// Global manager initialization functions
let chatManagerInitialized = false;
let referenceManagerInitialized = false;
let userManagerInitialized = false;

// Check authentication on page load
async function checkAuth() {
    const token = localStorage.getItem('access_token');
    
    if (!token) {
        window.location.href = '/login';
        return;
    }
    
    try {
        const response = await fetch('/api/auth/verify', {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });
        
        if (!response.ok) {
            throw new Error('Token invalid');
        }
        
        const data = await response.json();
        document.getElementById('username-display').textContent = data.user.username;
        
        // Load manager sections
        await loadManagerSections();
        
        // Small delay to ensure scripts are fully executed
        await new Promise(resolve => setTimeout(resolve, 100));
        
        // Initialize the first visible section (chat)
        await initializeSection('chat');
    } catch (error) {
        localStorage.removeItem('access_token');
        window.location.href = '/login';
    }
}

// Load manager HTML sections
async function loadManagerSections() {
    try {
        // Load chat manager
        const chatResponse = await fetch('/static/managers/chat.html');
        const chatHtml = await chatResponse.text();
        document.getElementById('chat-section').innerHTML = chatHtml;
        
        // Load reference manager
        const refResponse = await fetch('/static/managers/reference.html');
        const refHtml = await refResponse.text();
        document.getElementById('reference-section').innerHTML = refHtml;
        
        // Load user manager
        const userResponse = await fetch('/static/managers/user.html');
        const userHtml = await userResponse.text();
        document.getElementById('user-section').innerHTML = userHtml;
        
        // Execute scripts in loaded HTML (this makes functions available globally)
        await executeScripts('chat-section');
        await executeScripts('reference-section');
        await executeScripts('user-section');
    } catch (error) {
        console.error('Failed to load manager sections:', error);
    }
}

// Execute scripts in loaded HTML
async function executeScripts(containerId) {
    console.log(`Executing scripts for ${containerId}...`);
    const container = document.getElementById(containerId);
    const scripts = container.querySelectorAll('script');
    
    console.log(`Found ${scripts.length} scripts in ${containerId}`);
    
    for (let script of scripts) {
        const newScript = document.createElement('script');
        
        if (script.src) {
            // For external scripts
            console.log(`Loading external script: ${script.src}`);
            newScript.src = script.src;
            // Wait for external script to load
            await new Promise((resolve, reject) => {
                newScript.onload = () => {
                    console.log(`External script loaded: ${script.src}`);
                    resolve();
                };
                newScript.onerror = (err) => {
                    console.error(`Failed to load external script: ${script.src}`, err);
                    reject(err);
                };
                document.body.appendChild(newScript);
            });
        } else {
            // For inline scripts, execute immediately
            console.log(`Executing inline script in ${containerId} (${script.textContent.length} chars)`);
            newScript.textContent = script.textContent;
            document.body.appendChild(newScript);
        }
        
        // Remove old script
        script.remove();
    }
    
    console.log(`Finished executing scripts for ${containerId}`);
}

// Initialize a specific section
async function initializeSection(section) {
    console.log(`Attempting to initialize ${section} manager...`);
    
    try {
        switch(section) {
            case 'chat':
                if (!chatManagerInitialized && typeof window.initChatManager === 'function') {
                    console.log('Initializing chat manager...');
                    await window.initChatManager();
                    chatManagerInitialized = true;
                    console.log('Chat manager initialized successfully');
                } else if (chatManagerInitialized) {
                    console.log('Chat manager already initialized');
                } else {
                    console.error('window.initChatManager is not a function:', typeof window.initChatManager);
                }
                break;
            case 'reference':
                if (!referenceManagerInitialized && typeof window.initReferenceManager === 'function') {
                    console.log('Initializing reference manager...');
                    await window.initReferenceManager();
                    referenceManagerInitialized = true;
                    console.log('Reference manager initialized successfully');
                } else if (referenceManagerInitialized) {
                    console.log('Reference manager already initialized');
                } else {
                    console.error('window.initReferenceManager is not a function:', typeof window.initReferenceManager);
                }
                break;
            case 'user':
                if (!userManagerInitialized && typeof window.initUserManager === 'function') {
                    console.log('Initializing user manager...');
                    await window.initUserManager();
                    userManagerInitialized = true;
                    console.log('User manager initialized successfully');
                } else if (userManagerInitialized) {
                    console.log('User manager already initialized');
                } else {
                    console.error('window.initUserManager is not a function:', typeof window.initUserManager);
                }
                break;
        }
    } catch (error) {
        console.error(`Failed to initialize ${section} manager:`, error);
    }
}

// Show section
async function showSection(section, buttonElement) {
    // Update nav buttons
    document.querySelectorAll('.nav-btn').forEach(btn => {
        btn.classList.remove('active');
    });
    
    // Find and activate the button that was clicked
    if (buttonElement) {
        buttonElement.classList.add('active');
    } else {
        // Fallback: find button by section name
        const buttons = document.querySelectorAll('.nav-btn');
        buttons.forEach(btn => {
            if (btn.textContent.toLowerCase().includes(section)) {
                btn.classList.add('active');
            }
        });
    }
    
    // Hide all sections
    document.querySelectorAll('.manager-section').forEach(sec => {
        sec.classList.remove('active');
    });
    
    // Show selected section
    document.getElementById(section + '-section').classList.add('active');
    
    // Initialize the section if needed
    await initializeSection(section);
}

// Logout
async function logout() {
    const token = localStorage.getItem('access_token');
    
    try {
        await fetch('/api/auth/logout', {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });
    } catch (error) {
        console.error('Logout error:', error);
    }
    
    localStorage.removeItem('access_token');
    window.location.href = '/login';
}

// Set up event listeners
function setupEventListeners() {
    // Logout button
    const logoutBtn = document.getElementById('logout-btn');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', logout);
    }
    
    // Navigation buttons
    const navButtons = document.querySelectorAll('.nav-btn');
    navButtons.forEach(button => {
        button.addEventListener('click', function() {
            const section = this.getAttribute('data-section');
            showSection(section, this);
        });
    });
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    setupEventListeners();
    checkAuth();
});
