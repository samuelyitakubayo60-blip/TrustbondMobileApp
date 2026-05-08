import React, { useEffect, useMemo, useState } from 'react';
import api from '../../api/client';

const StationModal = ({ isOpen, onClose, mode = 'add', station = null, onSaved }) => {
  const isEdit = mode === 'edit';

  const initial = useMemo(
    () => ({
      station_code: station?.station_code || '',
      station_name: station?.station_name || '',
      station_type: station?.station_type || 'station',
      latitude: station?.latitude ?? '',
      longitude: station?.longitude ?? '',
      address_text: station?.address_text || '',
      phone_number: station?.phone_number || '',
      email: station?.email || '',
      is_active: station?.is_active ?? true,
      covered_cell_ids: station?.covered_cell_ids || [],
    }),
    [station]
  );

  const [form, setForm] = useState(initial);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const [coverageOptions, setCoverageOptions] = useState([]);
  const [selectedCellIds, setSelectedCellIds] = useState([]);
  const [expandedSectorIds, setExpandedSectorIds] = useState(new Set());
  const [locationSectorId, setLocationSectorId] = useState('');
  const [locationCellId, setLocationCellId] = useState('');
  const [locationVillageId, setLocationVillageId] = useState('');
  const [locationVillageOptions, setLocationVillageOptions] = useState([]);
  const [loadingVillageOptions, setLoadingVillageOptions] = useState(false);
  const [autoFillAddressFromLocation, setAutoFillAddressFromLocation] = useState(true);

  // Load coverage options (sectors -> cells) and station selection
  useEffect(() => {
    setForm(initial);
    setError('');
    setSaving(false);
    if (!isOpen) return;
    let cancelled = false;
    const loadOptions = async () => {
      try {
        const sid = station?.station_id ? `?station_id=${station.station_id}` : '';
        const res = await api.get(`/api/v1/stations/coverage/options${sid}`);
        if (cancelled) return;
        setCoverageOptions(res?.items || []);
        const selected = res?.selected_cell_ids || initial.covered_cell_ids || [];
        setSelectedCellIds(Array.isArray(selected) ? selected : []);
        setLocationSectorId('');
        setLocationCellId('');
        setLocationVillageId('');
        setLocationVillageOptions([]);
        setAutoFillAddressFromLocation(true);
        // Expand sectors that contain selected cells
        const selectedSet = new Set(selected);
        const expanded = new Set();
        for (const sec of (res?.items || [])) {
          if ((sec.cells || []).some((c) => selectedSet.has(c.cell_id))) {
            expanded.add(sec.sector_id);
          }
        }
        setExpandedSectorIds(expanded);
      } catch (e) {
        if (cancelled) return;
        setCoverageOptions([]);
        setSelectedCellIds(initial.covered_cell_ids || []);
      }
    };
    loadOptions();
    return () => { cancelled = true; };
  }, [initial, isOpen, station]);

  // Load villages whenever station-location cell changes.
  useEffect(() => {
    if (!isOpen || !locationCellId) {
      setLocationVillageOptions([]);
      setLocationVillageId('');
      return;
    }
    let cancelled = false;
    const loadVillages = async () => {
      setLoadingVillageOptions(true);
      try {
        const res = await api.get(
          `/api/v1/public/locations/?location_type=village&parent_id=${locationCellId}&limit=2000`
        );
        if (cancelled) return;
        setLocationVillageOptions(Array.isArray(res) ? res : []);
      } catch (_) {
        if (cancelled) return;
        setLocationVillageOptions([]);
      } finally {
        if (!cancelled) setLoadingVillageOptions(false);
      }
    };
    loadVillages();
    return () => { cancelled = true; };
  }, [isOpen, locationCellId]);

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

  const toggleSectorExpanded = (sectorId) => {
    setExpandedSectorIds((prev) => {
      const next = new Set(prev);
      if (next.has(sectorId)) next.delete(sectorId);
      else next.add(sectorId);
      return next;
    });
  };

  const toggleCell = (cellId) => {
    setSelectedCellIds((prev) => {
      const set = new Set(prev);
      if (set.has(cellId)) set.delete(cellId);
      else set.add(cellId);
      return Array.from(set);
    });
  };

  const toggleAllCellsInSector = (sector) => {
    const ids = (sector.cells || []).map((c) => c.cell_id);
    setSelectedCellIds((prev) => {
      const set = new Set(prev);
      const allSelected = ids.length > 0 && ids.every((id) => set.has(id));
      for (const id of ids) {
        if (allSelected) set.delete(id);
        else set.add(id);
      }
      return Array.from(set);
    });
    setExpandedSectorIds((prev) => {
      const next = new Set(prev);
      next.add(sector.sector_id);
      return next;
    });
  };

  const locationSectorOptions = useMemo(
    () => (coverageOptions || []).map((s) => ({ id: String(s.sector_id), name: s.sector_name, cells: s.cells || [] })),
    [coverageOptions]
  );

  const locationCellOptions = useMemo(() => {
    const sec = locationSectorOptions.find((s) => s.id === String(locationSectorId));
    return sec ? sec.cells : [];
  }, [locationSectorId, locationSectorOptions]);

  const onLocationSectorChange = (e) => {
    const sid = e.target.value;
    setLocationSectorId(sid);
    setLocationCellId('');
    setLocationVillageId('');
    setLocationVillageOptions([]);
  };

  const onLocationCellChange = (e) => {
    const cid = e.target.value;
    setLocationCellId(cid);
    setLocationVillageId('');
    setLocationVillageOptions([]);
  };

  const onLocationVillageChange = (e) => {
    const vid = e.target.value;
    setLocationVillageId(vid);
    const village = locationVillageOptions.find((v) => String(v.location_id) === String(vid));
    if (!village) return;
    const lat = village.centroid_lat;
    const lng = village.centroid_long;
    if (lat != null && lng != null) {
      setForm((prev) => ({
        ...prev,
        latitude: String(lat),
        longitude: String(lng),
      }));
    }
    if (autoFillAddressFromLocation) {
      const sectorName = locationSectorOptions.find((s) => String(s.id) === String(locationSectorId))?.name || '';
      const cellName = locationCellOptions.find((c) => String(c.cell_id) === String(locationCellId))?.cell_name || '';
      const villageName = village.location_name || '';
      const parts = [villageName, cellName, sectorName].filter(Boolean);
      if (parts.length > 0) {
        setForm((prev) => ({
          ...prev,
          address_text: parts.join(', '),
        }));
      }
    }
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
      latitude: form.latitude ? Number(form.latitude) : null,
      longitude: form.longitude ? Number(form.longitude) : null,
      address_text: form.address_text.trim() || null,
      phone_number: form.phone_number.trim() || null,
      email: form.email.trim() || null,
      is_active: !!form.is_active,
      covered_cell_ids: selectedCellIds.map(Number),
    };
    
    if (!payload.station_name) {
      setError('Name is required.');
      return;
    }
    if (!payload.covered_cell_ids || payload.covered_cell_ids.length === 0) {
      setError('Please select at least one covered cell.');
      return;
    }

    setSaving(true);
    try {
      if (isEdit && station?.station_id) {
        await api.put(`/api/v1/stations/${station.station_id}`, payload);
      } else {
        await api.post('/api/v1/stations/', payload);
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
        </div>

        <div className="form-grid">
          <div className="input-group">
            <div className="input-label">Station Sector (for coordinates)</div>
            <select className="select" value={locationSectorId} onChange={onLocationSectorChange}>
              <option value="">Select sector…</option>
              {locationSectorOptions.map((s) => (
                <option key={s.id} value={s.id}>{s.name}</option>
              ))}
            </select>
          </div>
          <div className="input-group">
            <div className="input-label">Station Cell (for coordinates)</div>
            <select
              className="select"
              value={locationCellId}
              onChange={onLocationCellChange}
              disabled={!locationSectorId}
            >
              <option value="">Select cell…</option>
              {locationCellOptions.map((c) => (
                <option key={c.cell_id} value={c.cell_id}>{c.cell_name}</option>
              ))}
            </select>
          </div>
        </div>

        <div className="input-group">
          <div className="input-label">
            Station Village (auto-fills coordinates)
            <span style={{ fontSize: '10px', color: 'var(--muted)', marginLeft: '4px' }}>
              (optional)
            </span>
          </div>
          <select
            className="select"
            value={locationVillageId}
            onChange={onLocationVillageChange}
            disabled={!locationCellId}
          >
            <option value="">
              {loadingVillageOptions ? 'Loading villages…' : 'Select village…'}
            </option>
            {locationVillageOptions.map((v) => (
              <option key={v.location_id} value={v.location_id}>{v.location_name}</option>
            ))}
          </select>
        </div>

        <div className="input-group" style={{ marginTop: '-4px' }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '12px', color: 'var(--muted)' }}>
            <input
              type="checkbox"
              checked={autoFillAddressFromLocation}
              onChange={(e) => setAutoFillAddressFromLocation(e.target.checked)}
            />
            Auto-fill address from selected village/cell/sector
          </label>
        </div>

        <div className="input-group">
          <div className="input-label">
            Coverage (cells) *
            <span style={{ fontSize: '10px', color: 'var(--muted)', marginLeft: '4px' }}>
              (select one or many cells; sectors can be shared by cell)
            </span>
          </div>
          <div style={{ border: '1px solid var(--border)', borderRadius: '6px', padding: '10px', maxHeight: '240px', overflowY: 'auto' }}>
            {coverageOptions.length === 0 ? (
              <div style={{ fontSize: '12px', color: 'var(--muted)' }}>Loading coverage options…</div>
            ) : (
              coverageOptions.map((sec) => {
                const sectorExpanded = expandedSectorIds.has(sec.sector_id);
                const cellIds = (sec.cells || []).map((c) => c.cell_id);
                const selectedSet = new Set(selectedCellIds);
                const selectedCount = cellIds.filter((id) => selectedSet.has(id)).length;
                const allSelected = cellIds.length > 0 && selectedCount === cellIds.length;
                return (
                  <div key={sec.sector_id} style={{ marginBottom: '10px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px' }}>
                      <div
                        style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}
                        onClick={() => toggleSectorExpanded(sec.sector_id)}
                      >
                        <span style={{ width: '16px', textAlign: 'center', color: 'var(--muted)' }}>
                          {sectorExpanded ? '▾' : '▸'}
                        </span>
                        <strong style={{ fontSize: '13px' }}>{sec.sector_name}</strong>
                        {selectedCount > 0 && (
                          <span className="badge b-blue" style={{ fontSize: '10px' }}>
                            {selectedCount}/{cellIds.length}
                          </span>
                        )}
                      </div>
                      <button
                        type="button"
                        className="btn btn-outline btn-sm"
                        onClick={() => toggleAllCellsInSector(sec)}
                        disabled={cellIds.length === 0}
                      >
                        {allSelected ? 'Unselect all' : 'Select all'}
                      </button>
                    </div>
                    {sectorExpanded && (
                      <div style={{ marginTop: '8px', paddingLeft: '24px', display: 'grid', gap: '6px' }}>
                        {(sec.cells || []).length === 0 ? (
                          <div style={{ fontSize: '12px', color: 'var(--muted)' }}>No cells</div>
                        ) : (
                          (sec.cells || []).map((c) => (
                            <label key={c.cell_id} style={{ display: 'flex', gap: '8px', alignItems: 'center', fontSize: '12px', color: 'var(--muted)' }}>
                              <input
                                type="checkbox"
                                checked={selectedSet.has(c.cell_id)}
                                onChange={() => toggleCell(c.cell_id)}
                              />
                              <span style={{ color: 'var(--text)' }}>{c.cell_name}</span>
                            </label>
                          ))
                        )}
                      </div>
                    )}
                  </div>
                );
              })
            )}
          </div>
        </div>

        <div className="form-grid">
          <div className="input-group">
            <div className="input-label">Latitude</div>
            <input
              className="input"
              type="number"
              step="0.000001"
              value={form.latitude}
              onChange={handleChange('latitude')}
            />
          </div>
          <div className="input-group">
            <div className="input-label">Longitude</div>
            <input
              className="input"
              type="number"
              step="0.000001"
              value={form.longitude}
              onChange={handleChange('longitude')}
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

