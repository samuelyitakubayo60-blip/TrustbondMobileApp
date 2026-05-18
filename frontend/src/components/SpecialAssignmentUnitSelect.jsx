import React, { useState, useEffect } from 'react';
import api from '../api/client';

/**
 * Dropdown for special_assignment_unit / assigned_unit fields.
 * Stores unit_code on the case; displays unit_name in the list.
 */
const SpecialAssignmentUnitSelect = ({
  value = '',
  onChange,
  required = false,
  disabled = false,
  placeholder = 'Select unit',
  className = 'select',
  allowEmpty = true,
}) => {
  const [units, setUnits] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        setLoading(true);
        setError(null);
        const response = await api.get('/api/v1/special-assignment-units/');
        const list = Array.isArray(response?.data)
          ? response.data
          : Array.isArray(response)
            ? response
            : [];
        if (!cancelled) setUnits(list);
      } catch {
        if (!cancelled) {
          setError('Failed to load units');
          setUnits([]);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const handleChange = (e) => {
    if (typeof onChange === 'function') {
      onChange(e.target.value);
    }
  };

  const normalizedValue = value == null ? '' : String(value);
  const knownCode = units.some((u) => u.unit_code === normalizedValue);
  const legacyLabel =
    normalizedValue && !knownCode ? `${normalizedValue} (saved value)` : null;

  if (loading) {
    return (
      <select
        className={className}
        value={normalizedValue}
        onChange={handleChange}
        required={required}
        disabled
      >
        <option value="">{placeholder}</option>
        <option value="" disabled>
          Loading units…
        </option>
      </select>
    );
  }

  if (error) {
    return (
      <select
        className={className}
        value={normalizedValue}
        onChange={handleChange}
        required={required}
        disabled
      >
        <option value="">{error}</option>
      </select>
    );
  }

  return (
    <select
      className={className}
      style={{ width: "100%" }}
      value={normalizedValue}
      onChange={handleChange}
      required={required}
      disabled={disabled}
    >
      {allowEmpty && <option value="">{placeholder}</option>}
      {legacyLabel && (
        <option value={normalizedValue}>{legacyLabel}</option>
      )}
      {units.map((unit) => (
        <option key={unit.unit_id} value={unit.unit_code}>
          {unit.unit_name}
        </option>
      ))}
    </select>
  );
};

export default SpecialAssignmentUnitSelect;
