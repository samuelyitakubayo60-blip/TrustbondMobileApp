import React from 'react';

const Card = ({ 
  children, 
  title, 
  action, 
  onAction,
  className = '',
  ...props 
}) => {
  return (
    <div className={`card ${className}`} {...props}>
      {(title || action) && (
        <div className="card-header">
          {title && <div className="card-title">{title}</div>}
          {action && (
            <div className="card-action" onClick={onAction}>
              {action}
            </div>
          )}
        </div>
      )}
      {children}
    </div>
  );
};

export default Card;