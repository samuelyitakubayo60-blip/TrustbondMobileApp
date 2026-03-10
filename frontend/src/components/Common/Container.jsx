import React from 'react';

const Container = ({ 
  children, 
  size = 'md', 
  className = '', 
  ...props 
}) => {
  const sizes = {
    sm: 'max-width: 640px',
    md: 'max-width: 768px',
    lg: 'max-width: 1024px',
    xl: 'max-width: 1280px',
    full: 'max-width: 100%'
  };

  return (
    <div 
      style={{ 
        width: '100%',
        marginLeft: 'auto',
        marginRight: 'auto',
        paddingLeft: '16px',
        paddingRight: '16px'
      }}
      className={className}
      {...props}
    >
      {children}
    </div>
  );
};

export default Container;