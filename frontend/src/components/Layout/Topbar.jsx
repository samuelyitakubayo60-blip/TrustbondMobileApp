import React from 'react';

const Topbar = ({
  currentScreen,
  titles,
  isLightMode,
  toggleMode,
  toggleSidebar,
  goToScreen,
  user,
  onLogout,
}) => {
  const getCurrentDate = () => {
    const date = new Date();
    return date.toLocaleDateString('en-US', { 
      month: 'short', 
      day: 'numeric', 
      year: 'numeric' 
    }).replace(',', '');
  };

  return (
    <header id="topbar">
      <div id="hamburger" onClick={toggleSidebar}>☰</div>
      <div id="page-title">{titles[currentScreen] || 'Dashboard'}</div>
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexShrink: 0 }}>
        <button id="modeToggle" onClick={toggleMode}>
          {isLightMode ? 'Dark Mode' : 'Light Mode'}
        </button>
        <div className="tb-chip">{getCurrentDate()}</div>
        {user && (
          <div className="tb-chip" style={{ fontSize: 11 }}>
            {user.first_name} {user.last_name} ({user.role})
          </div>
        )}
        <div className="notif-btn" onClick={() => goToScreen('notifications', 11)}>
          Notifications
          <div className="notif-dot"></div>
        </div>
        <div className="logout-btn" onClick={onLogout}>Logout</div>
      </div>
    </header>
  );
};

export default Topbar;