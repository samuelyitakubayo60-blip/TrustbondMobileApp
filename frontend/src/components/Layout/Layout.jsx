import React, { useState, useEffect } from "react";
import "./Layout.css";
import Topbar from "./Topbar";
import Sidebar from "./Sidebar";

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
  const [isMobile, setIsMobile] = useState(false);

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
      const mobile = window.innerWidth <= 768;
      setIsMobile(mobile);
      if (window.innerWidth > 900) {
        setSidebarOpen(false);
      }
    };

    handleResize();
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  const handleScreenChange = (id, idx) => {
    goToScreen(id, idx);
    closeSidebar();
  };

  // Wrap children to hide page headers on mobile
  const wrappedChildren = React.Children.map(children, (child) => {
    if (React.isValidElement(child)) {
      return React.cloneElement(child, { isMobile });
    }
    return child;
  });

  return (
    <div id="app">
      <div id="body-row">
        <Sidebar
          isOpen={sidebarOpen}
          currentScreen={currentScreen}
          onNavigate={handleScreenChange}
          sidebarCounts={sidebarCounts}
          user={user}
          onLogout={onLogout}
        />

        <div id="content-col">
          <Topbar
            currentScreen={currentScreen}
            titles={titles}
            isLightMode={isLightMode}
            toggleMode={toggleMode}
            toggleSidebar={toggleSidebar}
            goToScreen={goToScreen}
            onLogout={onLogout}
          />

          <main id="main">
            <div className={`screen active`} id={`screen-${currentScreen}`}>
              {wrappedChildren}
            </div>
          </main>
        </div>

        <div
          id="overlay"
          className={sidebarOpen ? "open" : ""}
          onClick={closeSidebar}
        ></div>
      </div>
    </div>
  );
};

export default Layout;
