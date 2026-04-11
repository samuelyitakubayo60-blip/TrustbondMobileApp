import React from 'react';

const Button = ({ 
  children, 
  variant = 'primary', 
  size = 'md',
  fullWidth = false,
  className = '',
  onClick,
  ...props 
}) => {
  const variantMap = {
    primary: 'btn-primary',
    outline: 'btn-outline',
    danger: 'btn-danger',
    success: 'btn-success',
    warn: 'btn-warn'
  };

  const sizeMap = {
    sm: 'btn-sm',
    md: '',
    lg: ''
  };

  const classes = [
    'btn',
    variantMap[variant],
    sizeMap[size],
    fullWidth ? 'btn-full' : '',
    className
  ].filter(Boolean).join(' ');

  return (
    <button className={classes} onClick={onClick} {...props}>
      {children}
    </button>
  );
};

export default Button;