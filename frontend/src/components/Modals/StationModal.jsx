import React, { useEffect, useMemo, useState } from 'react';
import api from '../../api/client';

const StationModal = ({ isOpen, onClose, mode = 'add', station = null, onSaved }) => {
  const isEdit = mode === 'edit';

  const initial = useMemo(
    () => ({
      station_code: station?.station_code || '',
      station_name: station?.station_name || '',
      station_type: station?.station_type || 'station',
      location_id: station?.location_id || '',
      sector2_id: station?.sector2_id || '',
      latitude: station?.latitude ?? '',
      longitude: station?.longitude ?? '',
      address_text: station?.address_text || '',
      phone_number: station?.phone_number || '',
      email: station?.email || '',
      is_active: station?.is_active ?? true,
    }),
    [station]
  );

  const [form, setForm] = useState(initial);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const [locations, setLocations] = useState([]);
  const [sectorId, setSectorId] = useState(null);
  const [cellId, setCellId] = useState(null);
  const [villageId, setVillageId] = useState(null);
  const [sector2Id, setSector2Id] = useState(null);

  // Load all locations once (sectors, cells, villages)
  useEffect(() => {
    let cancelled = false;
    const loadLocations = async () => {
      try {
        const data = await api.get('/api/v1/locations?limit=2000');
        if (cancelled) return;
        setLocations(data || []);
      } catch {
        if (cancelled) return;
        setLocations([]);
      }
    };
    loadLocations();
    return () => {
      cancelled = true;
    };
  }, []);

  // When opening / station changes, derive sector/cell/village from station.location_id and sector2_id
  useEffect(() => {
    setForm(initial);
    setError('');
    setSaving(false);

    if (!station || !locations.length) {
      setSectorId(null);
      setCellId(null);
      setVillageId(null);
      setSector2Id(station?.sector2_id || null);
      return;
    }

    // Handle primary sector
    if (station.location_id) {
      const villages = locations.filter((l) => l.location_type === 'village');
      const cells = locations.filter((l) => l.location_type === 'cell');
      const sectors = locations.filter((l) => l.location_type === 'sector');

      const v = villages.find((l) => l.location_id === station.location_id);
      if (v) {
        setVillageId(v.location_id);

        const c = cells.find((l) => l.location_id === v.parent_location_id);
        if (c) {
          setCellId(c.location_id);
          const s = sectors.find((l) => l.location_id === c.parent_location_id);
          if (s) setSectorId(s.location_id);
        }
      }
    } else {
      setSectorId(null);
      setCellId(null);
      setVillageId(null);
    }

    // Handle second sector (direct sector selection)
    setSector2Id(station?.sector2_id || null);
  }, [initial, isOpen, locations, station]);

  const sectors = locations.filter((l) => l.location_type === 'sector');
  const cells = locations.filter((l) => l.location_type === 'cell' && (!sectorId || l.parent_location_id === sectorId));
  const villages = locations.filter((l) => l.location_type === 'village' && (!cellId || l.parent_location_id === cellId));

  const handleChange = (field) => (e) => {
    if (field === 'is_active') {
      const value = e.target.checked;
      setForm((prev) => ({ ...prev, is_active: value }));
      return;
    }
    if (field === 'phone_number') {
      const rawDigits = e.target.value.replace(/\D/g, '');
      let digits = rawDigits;
      // Normalize toward 2507xxxxxxxx (but allow partial while typing)
      if (digits.startsWith('0')) {
        digits = digits.slice(1);
      }
      if (!digits.startsWith('250')) {
        digits = '250' + digits;
      }
      // Keep max 12 digits (2507xxxxxxxx)
      digits = digits.slice(0, 12);
      let formatted = '';
      if (digits.length <= 3) {
        formatted = '+' + digits;
      } else if (digits.length <= 6) {
        formatted = `+${digits.slice(0, 3)} ${digits.slice(3)}`;
      } else if (digits.length <= 9) {
        formatted = `+${digits.slice(0, 3)} ${digits.slice(3, 6)} ${digits.slice(6)}`;
      } else {
        formatted = `+${digits.slice(0, 3)} ${digits.slice(3, 6)} ${digits.slice(6, 9)} ${digits.slice(9)}`;
      }
      setForm((prev) => ({ ...prev, phone_number: formatted }));
      return;
    }
    const value = e.target.value;
    setForm((prev) => ({ ...prev, [field]: value }));
  };

  const handleSectorChange = (e) => {
    const id = e.target.value ? Number(e.target.value) : null;
    setSectorId(id);
    setCellId(null);
    setVillageId(null);
    setForm((prev) => ({ ...prev, location_id: '', latitude: '', longitude: '' }));
  };

  const handleCellChange = (e) => {
    const id = e.target.value ? Number(e.target.value) : null;
    setCellId(id);
    setVillageId(null);
    setForm((prev) => ({ ...prev, location_id: '', latitude: '', longitude: '' }));
  };

  const handleVillageChange = (e) => {
    const id = e.target.value ? Number(e.target.value) : null;
    setVillageId(id);
    if (!id) {
      setForm((prev) => ({ ...prev, location_id: '', latitude: '', longitude: '' }));
      return;
    }
    const v = locations.find((l) => l.location_id === id);
    if (v) {
      setForm((prev) => ({
        ...prev,
        location_id: v.location_id,
        latitude: v.centroid_lat ?? '',
        longitude: v.centroid_long ?? '',
      }));
    }
  };

  const handleSector2Change = (e) => {
    const id = e.target.value ? Number(e.target.value) : null;
    setSector2Id(id);
    setForm((prev) => ({ ...prev, sector2_id: id || '' }));
  };

  const submit = async () => {
    setError('');
    // Basic local validation for Rwandan phone numbers (optional)
    const phoneRaw = form.phone_number.trim();
    if (phoneRaw) {
      const digitsOnly = phoneRaw.replace(/\D/g, '');
      let normalized = digitsOnly;
      if (normalized.startsWith('0')) normalized = normalized.slice(1);
      if (!normalized.startsWith('250')) normalized = '250' + normalized;
      if (!normalized.startsWith('2507') || normalized.length !== 12) {
        setError('Phone must be a valid Rwandan mobile number, e.g. +250 781 798 011.');
        return;
      }
    }

    // Email validation (optional)
    const emailRaw = form.email.trim();
    if (emailRaw) {
      const emailOk = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(emailRaw);
      if (!emailOk) {
        setError('Please enter a valid email address (e.g. station@rnp.gov.rw).');
        return;
      }
    }
    const payload = {
      station_code: form.station_code.trim() || null,
      station_name: form.station_name.trim(),
      station_type: form.station_type.trim(),
      location_id: form.location_id || null,
      sector2_id: form.sector2_id || null,
      latitude: form.latitude ? Number(form.latitude) : null,
      longitude: form.longitude ? Number(form.longitude) : null,
      address_text: form.address_text.trim() || null,
      phone_number: form.phone_number.trim() || null,
      email: form.email.trim() || null,
      is_active: !!form.is_active,
    };
    
    // Debug: Log the payload to see what's being sent
    console.log('Station payload being sent:', payload);
    console.log('Form sector2_id value:', form.sector2_id);
    console.log('Payload sector2_id value:', payload.sector2_id);
    if (!payload.station_name) {
      setError('Name is required.');
      return;
    }
    if (!payload.location_id) {
      setError('Please select sector, cell, and village.');
      return;
    }

    setSaving(true);
    try {
      if (isEdit && station?.station_id) {
        await api.put(`/api/v1/stations/${station.station_id}`, payload);
      } else {
        await api.post('/api/v1/stations', payload);
      }
      onSaved?.();
      onClose?.();
    } catch (e) {
      console.error('Station save error:', e);
      const errorMessage = e?.response?.data?.detail || e?.message || 'Failed to save station.';
      setError(errorMessage);
      // Don't close the form on error - let user see the error and try again
    } finally {
      setSaving(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="modal-overlay open" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="modal-header">
          <div className="modal-title">{isEdit ? 'Edit Station' : 'Add Station'}</div>
          <div className="modal-close" onClick={onClose}>✕</div>
        </div>

        {error && (
          <div className="alert alert-danger" style={{ marginBottom: '10px' }}>
            <span className="alert-icon">!</span>
            <div>{error}</div>
          </div>
        )}

        <div className="input-group">
          <div className="input-label">Name *</div>
          <input
            className="input"
            placeholder="e.g. Musanze Central Station"
            value={form.station_name}
            onChange={handleChange('station_name')}
          />
        </div>

        <div className="form-grid">
          <div className="input-group">
            <div className="input-label">Type</div>
            <select className="select" value={form.station_type} onChange={handleChange('station_type')}>
              <option value="headquarters">Headquarters</option>
              <option value="station">Station</option>
              <option value="post">Post</option>
            </select>
          </div>
          <div className="input-group">
            <div className="input-label">Sector</div>
            <select className="select" value={sectorId || ''} onChange={handleSectorChange}>
              <option value="">Select sector…</option>
              {sectors.map((s) => (
                <option key={s.location_id} value={s.location_id}>
                  {s.location_name}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="form-grid">
          <div className="input-group">
            <div className="input-label">Cell</div>
            <select className="select" value={cellId || ''} onChange={handleCellChange} disabled={!sectorId}>
              <option value="">Select cell…</option>
              {cells.map((c) => (
                <option key={c.location_id} value={c.location_id}>
                  {c.location_name}
                </option>
              ))}
            </select>
          </div>
          <div className="input-group">
            <div className="input-label">Village</div>
            <select className="select" value={villageId || ''} onChange={handleVillageChange} disabled={!cellId}>
              <option value="">Select village…</option>
              {villages.map((v) => (
                <option key={v.location_id} value={v.location_id}>
                  {v.location_name}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="input-group">
          <div className="input-label">
            Secondary Sector
            <span style={{ fontSize: '10px', color: 'var(--muted)', marginLeft: '4px' }}>
              (optional – maximum 2 sectors per station)
            </span>
          </div>
          <select className="select" value={sector2Id || ''} onChange={handleSector2Change}>
            <option value="">No secondary sector…</option>
            {sectors
              .filter(s => s.location_id !== sectorId) // Don't allow same sector as primary
              .map((s) => (
                <option key={s.location_id} value={s.location_id}>
                  {s.location_name}
                </option>
              ))}
          </select>
        </div>

        <div className="form-grid">
          <div className="input-group">
            <div className="input-label">Latitude (auto from village)</div>
            <input
              className="input"
              type="number"
              step="0.000001"
              value={form.latitude}
              readOnly
            />
          </div>
          <div className="input-group">
            <div className="input-label">Longitude (auto from village)</div>
            <input
              className="input"
              type="number"
              step="0.000001"
              value={form.longitude}
              readOnly
            />
          </div>
        </div>

        <div className="input-group">
          <div className="input-label">
            Address
            <span style={{ fontSize: '10px', color: 'var(--muted)', marginLeft: '4px' }}>
              (optional – e.g. near landmarks or road names)
            </span>
          </div>
          <input
            className="input"
            placeholder="e.g. Near Muhoza market, main road to Kinigi"
            value={form.address_text}
            onChange={handleChange('address_text')}
          />
        </div>

        <div className="form-grid">
          <div className="input-group">
            <div className="input-label">Phone</div>
            <input
              className="input"
              placeholder="+250 781 798 011"
              value={form.phone_number}
              onChange={handleChange('phone_number')}
            />
          </div>
          <div className="input-group">
            <div className="input-label">Email</div>
            <input
              className="input"
              type="email"
              placeholder="station@rnp.gov.rw"
              value={form.email}
              onChange={handleChange('email')}
            />
          </div>
        </div>

        <div className="input-group" style={{ marginTop: '4px' }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '12px', color: 'var(--muted)' }}>
            <input
              type="checkbox"
              checked={!!form.is_active}
              onChange={handleChange('is_active')}
            />
            Active
          </label>
        </div>

        <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end', marginTop: '10px' }}>
          <button className="btn btn-outline" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" onClick={submit} disabled={saving}>
            {saving ? 'Saving…' : (isEdit ? 'Update Station' : 'Add Station')}
          </button>
        </div>
      </div>
    </div>
  );
};

export default StationModal;

