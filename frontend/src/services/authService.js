import { API_ENDPOINTS } from '../config/api.js';

const TOKEN_KEY = 'trustbond_auth_token';

export const authService = {
  // Get stored token
  getToken() {
    return localStorage.getItem(TOKEN_KEY);
  },

  // Store token
  setToken(token) {
    localStorage.setItem(TOKEN_KEY, token);
  },

  // Remove token
  removeToken() {
    localStorage.removeItem(TOKEN_KEY);
  },

  // Login
  async login(email, password) {
    const url = API_ENDPOINTS.auth.login;
    console.log('[AuthService] Login attempt to:', url);
    
    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ email, password }),
      });

      console.log('[AuthService] Response status:', response.status);

      if (!response.ok) {
        let errorDetail = 'Login failed';
        try {
          const errorData = await response.json();
          errorDetail = errorData.detail || errorDetail;
        } catch (e) {
          errorDetail = `HTTP ${response.status}: ${response.statusText}`;
        }
        throw new Error(errorDetail);
      }

      const data = await response.json();
      this.setToken(data.access_token);
      return data;
    } catch (err) {
      if (err.message.includes('Failed to fetch') || err.message.includes('NetworkError')) {
        throw new Error('Cannot connect to backend. Make sure the server is running at http://localhost:8000');
      }
      throw err;
    }
  },

  // Get current user info
  async getMe() {
    const token = this.getToken();
    if (!token) {
      throw new Error('No token found');
    }

    const url = API_ENDPOINTS.auth.me;
    console.log('[AuthService] Getting user info from:', url);

    try {
      const response = await fetch(url, {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });

      if (!response.ok) {
        if (response.status === 401) {
          this.removeToken();
        }
        throw new Error(`Failed to get user info: ${response.status}`);
      }

      return response.json();
    } catch (err) {
      if (err.message.includes('Failed to fetch') || err.message.includes('NetworkError')) {
        throw new Error('Cannot connect to backend. Make sure the server is running.');
      }
      throw err;
    }
  },

  // Logout
  logout() {
    this.removeToken();
  },

  // Request password reset code (sends email)
  async forgotPassword(email) {
    const res = await fetch(API_ENDPOINTS.auth.forgotPassword, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: email.trim().toLowerCase() }),
    });
    if (!res.ok) {
      const text = await res.text();
      let detail = 'Failed to send reset code';
      try {
        const j = JSON.parse(text);
        detail = j.detail || detail;
      } catch (_) {}
      throw new Error(detail);
    }
    return res.json();
  },

  // Reset password with code from email
  async resetPassword(email, code, newPassword) {
    const res = await fetch(API_ENDPOINTS.auth.resetPassword, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: email.trim().toLowerCase(),
        code: code.trim(),
        new_password: newPassword,
      }),
    });
    if (!res.ok) {
      const text = await res.text();
      let detail = 'Invalid or expired code';
      try {
        const j = JSON.parse(text);
        detail = j.detail || detail;
      } catch (_) {}
      throw new Error(detail);
    }
    return res.json();
  },

  // Change own password
  async changePassword(currentPassword, newPassword) {
    const token = this.getToken();
    if (!token) throw new Error('Not authenticated');
    const res = await fetch(API_ENDPOINTS.auth.changePassword, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
    });
    if (!res.ok) {
      const text = await res.text();
      let detail = 'Failed to change password';
      try {
        const j = JSON.parse(text);
        detail = j.detail || detail;
      } catch (_) {}
      throw new Error(detail);
    }
    return res.json();
  },
};
