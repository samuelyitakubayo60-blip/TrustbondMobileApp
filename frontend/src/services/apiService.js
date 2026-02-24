import { API_ENDPOINTS } from '../config/api.js';
import { authService } from './authService.js';

async function fetchWithAuth(url, options = {}) {
  const token = authService.getToken();
  if (!token) throw new Error('Not authenticated');
  const headers = {
    ...options.headers,
    Authorization: `Bearer ${token}`,
  };
  const res = await fetch(url, { ...options, headers });
  if (!res.ok) {
    if (res.status === 401) authService.removeToken();
    const text = await res.text();
    let detail = text;
    try {
      const j = JSON.parse(text);
      detail = j.detail || text;
    } catch (_) {}
    throw new Error(detail);
  }
  return res.json();
}

export const apiService = {
  async getReports(params = {}) {
    const sp = new URLSearchParams();
    if (params.rule_status != null) sp.set('rule_status', params.rule_status);
    if (params.from_date != null) sp.set('from_date', params.from_date);
    if (params.to_date != null) sp.set('to_date', params.to_date);
    if (params.limit != null) sp.set('limit', String(params.limit));
    if (params.offset != null) sp.set('offset', String(params.offset));
    const qs = sp.toString();
    const url = qs ? `${API_ENDPOINTS.reports.list}?${qs}` : API_ENDPOINTS.reports.list;
    return fetchWithAuth(url);
  },

  async getReport(id) {
    return fetchWithAuth(API_ENDPOINTS.reports.get(id));
  },

  async addReportReview(reportId, body) {
    const res = await fetch(API_ENDPOINTS.reports.reviews(reportId), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${authService.getToken()}`,
      },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const text = await res.text();
      let detail = text;
      try { detail = JSON.parse(text).detail || text; } catch (_) {}
      throw new Error(detail);
    }
    return res.json();
  },

  async assignReport(reportId, body) {
    const res = await fetch(API_ENDPOINTS.reports.assign(reportId), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${authService.getToken()}`,
      },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const text = await res.text();
      let detail = text;
      try {
        detail = JSON.parse(text).detail || text;
      } catch (_) {}
      throw new Error(detail);
    }
    return res.json();
  },

  async getDashboardStats() {
    return fetchWithAuth(API_ENDPOINTS.stats.dashboard);
  },

  async getPoliceUsers() {
    return fetchWithAuth(API_ENDPOINTS.policeUsers.list);
  },

  async getOfficerOptions() {
    return fetchWithAuth(API_ENDPOINTS.policeUsers.options);
  },

  async getPoliceUser(id) {
    return fetchWithAuth(API_ENDPOINTS.policeUsers.get(id));
  },

  async createPoliceUser(body) {
    const res = await fetch(API_ENDPOINTS.policeUsers.create, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${authService.getToken()}`,
      },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const text = await res.text();
      let detail = text;
      try {
        detail = JSON.parse(text).detail || text;
      } catch (_) {}
      throw new Error(detail);
    }
    return res.json();
  },

  async getNotifications(params = {}) {
    const sp = new URLSearchParams();
    if (params.unread_only) sp.set('unread_only', 'true');
    if (params.limit != null) sp.set('limit', String(params.limit));
    const url = sp.toString() ? `${API_ENDPOINTS.notifications.list}?${sp}` : API_ENDPOINTS.notifications.list;
    return fetchWithAuth(url);
  },

  async getUnreadNotificationCount() {
    return fetchWithAuth(API_ENDPOINTS.notifications.unreadCount);
  },

  async markNotificationRead(id) {
    const res = await fetch(API_ENDPOINTS.notifications.markRead(id), {
      method: 'PATCH',
      headers: { Authorization: `Bearer ${authService.getToken()}` },
    });
    if (!res.ok) throw new Error('Failed to mark read');
    return res.json();
  },

  async getAuditLogs(params = {}) {
    const sp = new URLSearchParams();
    if (params.entity_type) sp.set('entity_type', params.entity_type);
    if (params.entity_id) sp.set('entity_id', params.entity_id);
    if (params.action_type) sp.set('action_type', params.action_type);
    if (params.limit != null) sp.set('limit', String(params.limit));
    const url = sp.toString() ? `${API_ENDPOINTS.auditLogs.list}?${sp}` : API_ENDPOINTS.auditLogs.list;
    return fetchWithAuth(url);
  },

  async updatePoliceUser(id, body) {
    const res = await fetch(API_ENDPOINTS.policeUsers.update(id), {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${authService.getToken()}`,
      },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const text = await res.text();
      let detail = text;
      try {
        detail = JSON.parse(text).detail || text;
      } catch (_) {}
      throw new Error(detail);
    }
    return res.json();
  },

  async deletePoliceUser(id) {
    const res = await fetch(API_ENDPOINTS.policeUsers.delete(id), {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${authService.getToken()}` },
    });
    if (!res.ok) {
      const text = await res.text();
      let detail = text;
      try {
        detail = JSON.parse(text).detail || text;
      } catch (_) {}
      throw new Error(detail);
    }
  },

  async getHotspots(params = {}) {
    const sp = new URLSearchParams();
    if (params.risk_level) sp.set('risk_level', params.risk_level);
    if (params.limit != null) sp.set('limit', String(params.limit));
    const qs = sp.toString();
    const url = qs ? `${API_ENDPOINTS.hotspots.list}?${qs}` : API_ENDPOINTS.hotspots.list;
    return fetchWithAuth(url);
  },

  async getHotspotEvidence(hotspotId) {
    return fetchWithAuth(API_ENDPOINTS.hotspots.evidence(hotspotId));
  },

  async getLocations(params = {}) {
    const sp = new URLSearchParams();
    if (params.location_type) sp.set('location_type', params.location_type);
    if (params.parent_id != null) sp.set('parent_id', params.parent_id);
    if (params.limit != null) sp.set('limit', String(params.limit));
    const qs = sp.toString();
    const url = qs ? `${API_ENDPOINTS.locations.list}?${qs}` : API_ENDPOINTS.locations.list;
    return fetchWithAuth(url);
  },

  async getIncidentGroups(params = {}) {
    const sp = new URLSearchParams();
    if (params.incident_type_id != null) sp.set('incident_type_id', String(params.incident_type_id));
    if (params.limit != null) sp.set('limit', String(params.limit));
    const qs = sp.toString();
    const url = qs ? `${API_ENDPOINTS.incidentGroups.list}?${qs}` : API_ENDPOINTS.incidentGroups.list;
    return fetchWithAuth(url);
  },

  async getIncidentTypes(includeInactive = false) {
    const url = includeInactive
      ? `${API_ENDPOINTS.incidentTypes.list}?include_inactive=true`
      : API_ENDPOINTS.incidentTypes.list;
    return fetchWithAuth(url);
  },

  async createIncidentType(body) {
    const res = await fetch(API_ENDPOINTS.incidentTypes.create, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${authService.getToken()}`,
      },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const text = await res.text();
      let detail = text;
      try {
        detail = JSON.parse(text).detail || text;
      } catch (_) {}
      throw new Error(detail);
    }
    return res.json();
  },

  async updateIncidentType(id, body) {
    const res = await fetch(API_ENDPOINTS.incidentTypes.update(id), {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${authService.getToken()}`,
      },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const text = await res.text();
      let detail = text;
      try {
        detail = JSON.parse(text).detail || text;
      } catch (_) {}
      throw new Error(detail);
    }
    return res.json();
  },
};
