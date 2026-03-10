import React from 'react';

const Table = ({ 
  children, 
  headers = [], 
  data = [],
  renderRow,
  minWidth = '540px',
  className = '',
  ...props 
}) => {
  return (
    <div className={`tbl-wrap ${className}`} {...props}>
      <table style={{ minWidth }}>
        {headers.length > 0 && (
          <thead>
            <tr>
              {headers.map((header, index) => (
                <th key={index}>{header}</th>
              ))}
            </tr>
          </thead>
        )}
        <tbody>
          {children}
          {data.length > 0 && renderRow && data.map((item, index) => renderRow(item, index))}
        </tbody>
      </table>
    </div>
  );
};

export const TableRow = ({ children, onClick, className = '', ...props }) => {
  return (
    <tr onClick={onClick} className={className} {...props}>
      {children}
    </tr>
  );
};

export const TableCell = ({ children, variant, className = '', ...props }) => {
  const variantStyles = {
    mono: { fontFamily: 'monospace', fontSize: '10px' },
    muted: { color: 'var(--muted)' },
    success: { color: 'var(--success)' },
    danger: { color: 'var(--danger)' },
    warning: { color: 'var(--warning)' }
  };

  const style = variant ? variantStyles[variant] : {};

  return (
    <td style={style} className={className} {...props}>
      {children}
    </td>
  );
};

export default Table;