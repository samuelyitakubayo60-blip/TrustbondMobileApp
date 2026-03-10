import React, { useState, useEffect } from 'react';
import './Layout.css';
import Topbar from './Topbar';
import Sidebar from './Sidebar';

const Layout = ({
  children,
  currentScreen,
  titles,
  isLightMode,
  toggleMode,
  goToScreen,
  user,
  onLogout,
  sidebarCounts,
}) => {
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const toggleSidebar = () => {
    setSidebarOpen(!sidebarOpen);
  };

  const closeSidebar = () => {
    if (window.innerWidth <= 900) {
      setSidebarOpen(false);
    }
  };

  useEffect(() => {
    const handleResize = () => {
      if (window.innerWidth > 900) {
        setSidebarOpen(false);
      }
    };

    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  const handleScreenChange = (id, idx) => {
    goToScreen(id, idx);
    closeSidebar();
  };

  return (
    <div id="app">
      <Topbar 
        currentScreen={currentScreen}
        titles={titles}
        isLightMode={isLightMode}
        toggleMode={toggleMode}
        toggleSidebar={toggleSidebar}
        goToScreen={goToScreen}
        user={user}
        onLogout={onLogout}
      />
      
      <div id="body-row">
        <Sidebar 
          isOpen={sidebarOpen}
          currentScreen={currentScreen}
          onNavigate={handleScreenChange}
          sidebarCounts={sidebarCounts}
          user={user}
        />
        
        <div 
          id="overlay" 
          className={sidebarOpen ? 'open' : ''} 
          onClick={closeSidebar}
        ></div>
        
        <main id="main">
          <div className={`screen active`} id={`screen-${currentScreen}`}>
            {children}
          </div>
        </main>
      </div>
    </div>
  );
};

export default Layout;