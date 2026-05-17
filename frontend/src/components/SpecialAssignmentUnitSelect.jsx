import React, { useState, useEffect } from 'react';
import api from '../api/client';
import { getToken } from '../api/client';

const SpecialAssignmentUnitSelect = ({ value, onChange, required = false, disabled = false, placeholder = "Select Unit" }) => {
  const [units, setUnits] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    loadUnits();
  }, []);

  const loadUnits = async () => {
    try {
      setLoading(true);
      const token = getToken();
      console.log('SpecialAssignmentUnitSelect - Loading units...');
      console.log('Token available:', !!token);
      
      const response = await api.get('/api/v1/special-assignment-units/');
      console.log('SpecialAssignmentUnitSelect - API response:', response);
      
      if (response && response.data) {
        console.log('SpecialAssignmentUnitSelect - Setting units:', response.data);
        setUnits(response.data);
      } else if (response && Array.isArray(response)) {
        console.log('SpecialAssignmentUnitSelect - Setting units from array:', response);
        setUnits(response);
      } else {
        console.log('SpecialAssignmentUnitSelect - No valid response, setting empty array');
        setUnits([]);
      }
    } catch (err) {
      console.error('SpecialAssignmentUnitSelect - Failed to load units:', err);
      console.error('Error details:', err.response);
      setError('Failed to load special units');
      setUnits([]);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <select 
        value={value}
        onChange={onChange}
        required={required}
        disabled={disabled || true}
        style={{ 
          width: '100%', 
          padding: '8px', 
          border: '1px solid #dee2e6', 
          borderRadius: '4px',
          backgroundColor: '#f8f9fa'
        }}
      >
        <option value="" disabled>{placeholder}</option>
        <option value="" disabled>Loading units...</option>
      </select>
    );
  }

  if (error) {
    return (
      <select 
        value={value}
        onChange={onChange}
        required={required}
        disabled={true}
        style={{ 
          width: '100%', 
          padding: '8px', 
          border: '1px solid #dc3545', 
          borderRadius: '4px',
          backgroundColor: '#f8d7da'
        }}
      >
        <option value="" disabled>Error loading units</option>
      </select>
    );
  }

  return (
    <select 
      value={value}
      onChange={onChange}
      required={required}
      disabled={disabled}
      style={{ 
        width: '100%', 
        padding: '8px', 
        border: '1px solid #dee2e6', 
        borderRadius: '4px'
      }}
    >
      <option value="" disabled>{placeholder}</option>
      {units.map((unit) => (
        <option key={unit.unit_id} value={unit.unit_code}>
          {unit.unit_name}
        </option>
      ))}
    </select>
  );
};

export default SpecialAssignmentUnitSelect;
