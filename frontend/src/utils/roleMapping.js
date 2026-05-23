/**
 * Role mapping utility to display user-friendly role names
 * Maps backend roles to display names for the TrustBond system
 */

export const ROLE_MAPPING = {
  // Backend role -> Display role
  'admin': 'DPC',           // District Police Commander
  'supervisor': 'IO',       // Investigating Officer  
  'officer': 'Officer',     // Regular Police Officer
  
  // Local leader roles
  'chief_of_village': 'Village Chief',
  'executive_of_cell': 'Cell Executive',
};

export const getRoleDisplayName = (role) => {
  return ROLE_MAPPING[role] || role?.replace('_', ' ') || 'Unknown';
};

export const getRoleDescription = (role) => {
  const descriptions = {
    'DPC': 'District Police Commander - Oversees all operations',
    'IO': 'Investigating Officer - Handles case investigations',
    'Officer': 'Police Officer - Frontline response',
    'Village Chief': 'Local village leader - Community verification',
    'Cell Executive': 'Cell executive - Area coordination',
  };
  
  const displayRole = getRoleDisplayName(role);
  return descriptions[displayRole] || 'System user';
};

export const getRolePermissions = (role) => {
  const permissions = {
    'admin': ['view_all', 'manage_users', 'manage_cases', 'deploy_teams', 'handover_to_rib'],
    'supervisor': ['view_assigned', 'manage_cases', 'deploy_teams', 'handover_to_rib'],
    'officer': ['view_assigned', 'manage_assigned_cases'],
  };
  
  return permissions[role] || [];
};

export const isOperationalLead = (role) => {
  return ['admin', 'supervisor', 'officer'].includes(role);
};

export const canAccessCommanderDashboard = (role) => {
  return isOperationalLead(role);
};

export const canMakeDeploymentDecisions = (role) => {
  return isOperationalLead(role);
};

export const canHandoverToRib = (role) => {
  return ['admin', 'supervisor', 'officer'].includes(role);
};
