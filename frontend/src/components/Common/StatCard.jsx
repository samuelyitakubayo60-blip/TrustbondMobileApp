import React from 'react';

const StatCard = ({ 
  label, 
  value, 
  change,
  variant = 'blue',
  className = '',
  ...props 
}) => {
  const variantMap = {
    blue: 'c-blue sv-blue',
    cyan: 'c-cyan sv-cyan',
    orange: 'c-orange sv-orange',
    green: 'c-green sv-green',
    red: 'c-red sv-red',
    purple: 'c-purple sv-purple'
  };

  const [cardVariant, valueVariant] = variantMap[variant].split(' ');

  return (
    <div className={`stat-card ${cardVariant} ${className}`} {...props}>
      <div className="stat-label">{label}</div>
      <div className={`stat-value ${valueVariant}`}>{value}</div>
      {change && <div className="stat-change">{change}</div>}
    </div>
  );
};

export default StatCard;