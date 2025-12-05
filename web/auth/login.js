class ApiClient {
    constructor() {
        this.baseURL = '/api';
    }
    
    async request(endpoint, options = {}) {
        const config = {
            headers: {
                'Content-Type': 'application/json',
                ...options.headers
            },
            ...options
        };
        
        const response = await fetch(`${this.baseURL}${endpoint}`, config);
        return response;
    }
    
    async login(username, token) {
        return await this.request('/auth/login', {
            method: 'POST',
            body: JSON.stringify({ username, token })
        });
    }
}

document.addEventListener('DOMContentLoaded', function() {
    const loginForm = document.getElementById('loginForm');
    const loginBtn = document.getElementById('loginBtn');
    const loading = document.getElementById('loading');
    const errorMessage = document.getElementById('errorMessage');
    const api = new ApiClient();

    // Check if already logged in
    const token = localStorage.getItem('access_token');
    if (token) {
        console.log('Existing token found, verifying...');
        // Verify token is still valid
        fetch('/api/auth/verify', {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        }).then(response => {
            if (response.ok) {
                console.log('Token still valid, redirecting to dashboard');
                window.location.href = '/dashboard';
            } else if (response.status === 401) {
                // Check if token expired and should be cleared
                const tokenExpired = response.headers.get('X-Token-Expired');
                if (tokenExpired === 'true') {
                    // Clear expired token from storage
                    localStorage.removeItem('access_token');
                    localStorage.removeItem('user_id');
                    localStorage.removeItem('username');
                    console.log('Expired token automatically cleared from storage');
                } else {
                    // Invalid token (not just expired)
                    localStorage.removeItem('access_token');
                    localStorage.removeItem('user_id');
                    localStorage.removeItem('username');
                    console.log('Invalid token cleared from storage');
                }
            } else {
                console.log('Token verification returned status:', response.status);
                // For other errors, clear the token as well to be safe
                localStorage.removeItem('access_token');
                localStorage.removeItem('user_id');
                localStorage.removeItem('username');
                console.log('Token cleared due to verification error');
            }
        }).catch(error => {
            console.error('Token verification failed with error:', error);
            // Clear token on network errors too, to prevent infinite loops
            localStorage.removeItem('access_token');
            localStorage.removeItem('user_id');
            localStorage.removeItem('username');
            console.log('Token cleared due to verification network error');
        });
    } else {
        console.log('No existing token found');
    }

    function showError(message) {
        errorMessage.textContent = message;
        errorMessage.style.display = 'block';
        setTimeout(() => {
            errorMessage.style.display = 'none';
        }, 5000);
    }

    function setLoading(isLoading) {
        loginBtn.disabled = isLoading;
        loading.style.display = isLoading ? 'block' : 'none';
        loginBtn.textContent = isLoading ? '' : 'Sign In';
    }

    loginForm.addEventListener('submit', async function(e) {
        e.preventDefault();
        
        const username = document.getElementById('username').value.trim();
        const token = document.getElementById('token').value.trim();

        if (!username || !token) {
            showError('Please enter both username and token');
            return;
        }

        setLoading(true);
        errorMessage.style.display = 'none';

        try {
            const response = await api.login(username, token);
            
            if (response.ok) {
                const data = await response.json();
                
                // Store token
                localStorage.setItem('access_token', data.access_token);
                localStorage.setItem('user_id', data.user_id);
                localStorage.setItem('username', data.username);
                
                // Redirect to dashboard
                window.location.href = '/dashboard';
            } else {
                // Check if this is an expired token error (might happen during concurrent requests)
                if (response.status === 401) {
                    const tokenExpired = response.headers.get('X-Token-Expired');
                    if (tokenExpired === 'true') {
                        localStorage.removeItem('access_token');
                        localStorage.removeItem('user_id');
                        localStorage.removeItem('username');
                        console.log('Expired token automatically cleared from storage during login');
                    }
                }
                
                // Try to parse response as JSON, fallback to text
                let errorMessage = 'Login failed. Please check your credentials.';
                try {
                    const contentType = response.headers.get('content-type');
                    if (contentType && contentType.includes('application/json')) {
                        const error = await response.json();
                        errorMessage = error.detail || errorMessage;
                    } else {
                        // If we get HTML instead of JSON, it's likely a server error
                        const htmlText = await response.text();
                        if (htmlText.includes('<!DOCTYPE')) {
                            console.error('Received HTML response instead of JSON:', htmlText.substring(0, 200) + '...');
                            errorMessage = 'Server error occurred. Please try again later.';
                        } else {
                            errorMessage = htmlText || errorMessage;
                        }
                    }
                } catch (parseError) {
                    console.error('Error parsing server response:', parseError);
                    errorMessage = 'Server communication error. Please try again.';
                }
                
                showError(errorMessage);
            }
        } catch (error) {
            console.error('Login error:', error);
            
            // Enhanced error handling
            let errorMessage = 'Connection error. Please try again.';
            if (error instanceof SyntaxError && error.message.includes('Unexpected token')) {
                errorMessage = 'Server returned an unexpected response. Please try again or contact support.';
                console.error('SyntaxError suggests server returned HTML instead of JSON');
            } else if (error.name === 'TypeError') {
                errorMessage = 'Network error. Please check your connection and try again.';
            }
            
            showError(errorMessage);
        } finally {
            setLoading(false);
        }
    });

    // Enter key support
    document.getElementById('token').addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
            loginForm.dispatchEvent(new Event('submit'));
        }
    });
});
