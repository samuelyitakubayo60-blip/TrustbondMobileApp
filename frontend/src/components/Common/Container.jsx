import React from 'react';

const Container = ({ 
  children, 
  size = 'md', 
  className = '', 
  ...props 
}) => {
  const sizes = {
    sm: 640,
    md: 768,
    lg: 1024,
    xl: 1280,
    full: null,
  };

  return (
    <div 
      style={{ 
        width: '100%',
        maxWidth: sizes[size] ?? sizes.md,
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