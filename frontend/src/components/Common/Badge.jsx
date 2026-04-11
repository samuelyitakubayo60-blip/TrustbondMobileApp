import React from 'react';

const Badge = ({ 
  children, 
  variant = 'green', 
  className = '', 
  ...props 
}) => {
  const variantMap = {
    green: 'b-green',
    orange: 'b-orange',
    red: 'b-red',
    blue: 'b-blue',
    gray: 'b-gray',
    purple: 'b-purple',
    cyan: 'b-cyan'
  };

  return (
    <span className={`badge ${variantMap[variant] || variantMap.green} ${className}`} {...props}>
      {children}
    </span>
  );
};

export default Badge;