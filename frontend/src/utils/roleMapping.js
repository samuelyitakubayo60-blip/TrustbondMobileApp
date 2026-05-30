/**
 * Role mapping and permission helpers for TrustBond staff roles.
 * Backend roles: admin (DPC), supervisor (IO), officer (station commander).
 */

export const ROLE_MAPPING = {
  admin: 'DPC',
  supervisor: 'IO',
  officer: 'Officer',
  chief_of_village: 'Village Chief',
  executive_of_cell: 'Cell Executive',
};

/** Screens only DPC may open (configuration / district admin). */
export const ADMIN_ONLY_SCREENS = [
  'incident-types',
  'special-assignment-units',
  'stations',
  'system-config',
  'audit-log',
  'active-sessions',
];

export const getRoleDisplayName = (role) => {
  return ROLE_MAPPING[role] || role?.replace('_', ' ') || 'Unknown';
};

export const getRoleDescription = (role) => {
  const descriptions = {
    DPC: 'District Police Commander — district-wide oversight and configuration',
    IO: 'Investigating Officer — operational cases and assignments in station scope',
    Officer: 'Police Officer — frontline response within station scope',
    'Village Chief': 'Local village leader — community verification',
    'Cell Executive': 'Cell executive — area coordination',
  };
  const displayRole = getRoleDisplayName(role);
  return descriptions[displayRole] || 'System user';
};

export const getRolePermissions = (role) => {
  const keys = [];
  if (canViewDistrictWide(role)) keys.push('view_all');
  if (canCreateUsers(role)) keys.push('create_users');
  if (canEditUsers(role)) keys.push('edit_users');
  if (canManageIncidentTypes(role)) keys.push('manage_incident_types');
  if (canManageStations(role)) keys.push('manage_stations');
  if (canManageAssignmentUnits(role)) keys.push('manage_assignment_units');
  if (canAssignReports(role)) keys.push('assign_reports');
  if (canCreateCases(role)) keys.push('create_cases');
  if (canManageCases(role)) keys.push('manage_cases');
  if (canDeployHotspotUnits(role)) keys.push('deploy_hotspot_units');
  if (canHandoverToRib(role)) keys.push('handover_to_rib');
  return keys;
};

export const isDpc = (role) => role === 'admin';
export const isIo = (role) => role === 'supervisor';

/** DPC sees district-wide lists; IO and officers are station-scoped on the API. */
export const canViewDistrictWide = (role) => role === 'admin';

export const canAccessScreen = (screenId, role) => {
  if (ADMIN_ONLY_SCREENS.includes(screenId)) {
    return role === 'admin';
  }
  if (screenId === 'local-leaders') {
    return ['admin', 'supervisor', 'officer'].includes(role);
  }
  if (screenId === 'users') {
    return ['admin', 'supervisor', 'officer'].includes(role);
  }
  if (screenId === 'district-security-analysis' || screenId === 'security-situation' || screenId === 'station-security') {
    return ['admin', 'supervisor', 'officer'].includes(role);
  }
  if (screenId === 'case-management') {
    return ['admin', 'supervisor', 'officer'].includes(role);
  }
  return true;
};

export const canCreateUsers = (role) => role === 'admin';
export const canEditUsers = (role) => ['admin', 'supervisor'].includes(role);
export const canDeleteUsers = (role) => role === 'admin';

export const canManageIncidentTypes = (role) => role === 'admin';
export const canManageStations = (role) => role === 'admin';
export const canManageAssignmentUnits = (role) => role === 'admin';
/** Local leaders in station coverage — officers manage their area; DPC district-wide. */
export const canManageLocalLeaders = (role) =>
  ['admin', 'supervisor', 'officer'].includes(role);

export const canAssignReports = (role) => ['admin', 'supervisor'].includes(role);
export const canCreateCases = (role) => ['admin', 'supervisor'].includes(role);
export const canDeleteCases = (role) => ['admin', 'supervisor'].includes(role);
export const canManageReportCaseLinks = (role) => ['admin', 'supervisor'].includes(role);

/** Edit / update cases (officers: assigned cases only — enforced in UI + API). */
export const canManageCases = (role) => ['admin', 'supervisor', 'officer'].includes(role);

/** RIB unit, handover fields on case edit — DPC and IO. */
export const canEditCaseLeadFields = (role) => ['admin', 'supervisor'].includes(role);

export const canDeployHotspotUnits = (role) => ['admin', 'supervisor'].includes(role);

export const isOperationalLead = (role) => ['admin', 'supervisor', 'officer'].includes(role);

export const canAccessCommanderDashboard = (role) => isOperationalLead(role);

export const canMakeDeploymentDecisions = (role) => canDeployHotspotUnits(role);

export const canHandoverToRib = (role) => ['admin', 'supervisor', 'officer'].includes(role);
