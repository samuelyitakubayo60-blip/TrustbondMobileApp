import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider } from './contexts/AuthContext.jsx';
import ProtectedRoute from './components/ProtectedRoute.jsx';
import Login from './pages/Login.jsx';
import Dashboard from './pages/Dashboard.jsx';
import Reports from './pages/Reports.jsx';
import ReportDetail from './pages/ReportDetail.jsx';
import Users from './pages/Users.jsx';
import Hotspots from './pages/Hotspots.jsx';
import ChangePassword from './pages/ChangePassword.jsx';
import AuditLog from './pages/AuditLog.jsx';
import IncidentTypes from './pages/IncidentTypes.jsx';
import './App.css';
import './pages/Pages.css';

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route
            path="/dashboard"
            element={
              <ProtectedRoute>
                <Dashboard />
              </ProtectedRoute>
            }
          />
          <Route
            path="/reports"
            element={
              <ProtectedRoute>
                <Reports />
              </ProtectedRoute>
            }
          />
          <Route
            path="/reports/:id"
            element={
              <ProtectedRoute>
                <ReportDetail />
              </ProtectedRoute>
            }
          />
          <Route
            path="/users"
            element={
              <ProtectedRoute>
                <Users />
              </ProtectedRoute>
            }
          />
          <Route
            path="/incident-types"
            element={
              <ProtectedRoute>
                <IncidentTypes />
              </ProtectedRoute>
            }
          />
          <Route
            path="/hotspots"
            element={
              <ProtectedRoute>
                <Hotspots />
              </ProtectedRoute>
            }
          />
          <Route
            path="/change-password"
            element={
              <ProtectedRoute>
                <ChangePassword />
              </ProtectedRoute>
            }
          />
          <Route
            path="/audit"
            element={
              <ProtectedRoute>
                <AuditLog />
              </ProtectedRoute>
            }
          />
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}

export default App;
