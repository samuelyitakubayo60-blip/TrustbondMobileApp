/**
 * Incident-type → icon mapping for the TrustBond dashboard.
 *
 * Every incident card, notification badge, and alert banner should use
 * `incidentIcon(typeName)` so the same icon appears consistently everywhere.
 *
 * Icons come from lucide-react (already installed). All exported helpers
 * return a React element sized via the optional `size` prop (default 16).
 */
import React from 'react';
import {
  Eye,
  ShoppingBag,
  Hammer,
  PersonStanding,
  Car,
  Pill,
  Cigarette,
  Beer,
  Flame,
  Volume2,
  Home,
  Gavel,
  Ban,
  AlertTriangle,
  UserMinus,
  UserX,
  Bell,
  MapPin,
  BarChart3,
  TrendingUp,
  Map,
  Building2,
  Search,
  Zap,
  CheckCircle,
  XCircle,
  Info,
  AlertCircle,
} from 'lucide-react';

// ── Incident-type icon map ─────────────────────────────────────────────────
// Keys are lowercase substrings matched against the incident type name.
// Order matters — first match wins.
const INCIDENT_ICON_MAP = [
  { keys: ['suspicious'],                          Icon: Eye },
  { keys: ['theft', 'robbery', 'larceny', 'pickpocket'], Icon: ShoppingBag },
  { keys: ['vandalism'],                           Icon: Hammer },
  { keys: ['assault', 'beating', 'violence', 'stabbing', 'knife'], Icon: PersonStanding },
  { keys: ['traffic', 'accident', 'crash'],        Icon: Car },
  { keys: ['drug', 'narcotic'],                    Icon: Pill },
  { keys: ['cannabis', 'weed', 'smoking'],         Icon: Cigarette },
  { keys: ['drinking', 'alcohol'],                 Icon: Beer },
  { keys: ['fire', 'arson', 'hazard'],             Icon: Flame },
  { keys: ['noise', 'disturbance'],                Icon: Volume2 },
  { keys: ['domestic'],                            Icon: Home },
  { keys: ['fraud', 'scam', 'bribery', 'corruption'], Icon: Gavel },
  { keys: ['harassment'],                          Icon: Ban },
  { keys: ['defilement', 'rape', 'sexual', 'molest'], Icon: AlertTriangle },
  { keys: ['abduction', 'kidnap'],                 Icon: UserMinus },
  { keys: ['trespass', 'loiter', 'burglary'],      Icon: UserX },
];

/**
 * Returns the lucide-react Icon component class for the given incident type name.
 * Falls back to Bell for unknown types.
 */
export function incidentIconComponent(typeName) {
  const lower = (typeName || '').toLowerCase();
  for (const { keys, Icon } of INCIDENT_ICON_MAP) {
    if (keys.some((k) => lower.includes(k))) return Icon;
  }
  return Bell;
}

/**
 * Renders the icon for an incident type.
 * @param {string} typeName  - incident type name (e.g. "Theft", "Assault")
 * @param {number} size      - icon size in px (default 16)
 * @param {string} className - extra CSS class
 */
export function IncidentIcon({ typeName, size = 16, className = '' }) {
  const Icon = incidentIconComponent(typeName);
  return <Icon size={size} className={className} />;
}

// ── Notification-category icon map ────────────────────────────────────────
// Used in the Notifications screen for non-incident notifications.
export function notificationIcon(category, incidentTypeName, size = 16) {
  if (incidentTypeName) {
    const Icon = incidentIconComponent(incidentTypeName);
    return <Icon size={size} />;
  }
  switch ((category || '').toLowerCase()) {
    case 'report':    return <Bell size={size} />;
    case 'hotspot':   return <AlertCircle size={size} />;
    case 'assignment': return <MapPin size={size} />;
    case 'system':    return <Info size={size} />;
    default:          return <Bell size={size} />;
  }
}

// ── Generic status icons (replaces ✅ ❌ ⚠️) ─────────────────────────────
export const StatusOk    = ({ size = 16 }) => <CheckCircle size={size} />;
export const StatusError = ({ size = 16 }) => <XCircle size={size} />;
export const StatusWarn  = ({ size = 16 }) => <AlertTriangle size={size} />;
export const StatusInfo  = ({ size = 16 }) => <Info size={size} />;

// ── UI chrome icons (replaces 📊 📍 🗺️ etc.) ─────────────────────────────
export const IconChart    = ({ size = 16 }) => <BarChart3 size={size} />;
export const IconTrend    = ({ size = 16 }) => <TrendingUp size={size} />;
export const IconMap      = ({ size = 16 }) => <Map size={size} />;
export const IconPin      = ({ size = 16 }) => <MapPin size={size} />;
export const IconBuilding = ({ size = 16 }) => <Building2 size={size} />;
export const IconSearch   = ({ size = 16 }) => <Search size={size} />;
export const IconFlame    = ({ size = 16 }) => <Flame size={size} />;
export const IconZap      = ({ size = 16 }) => <Zap size={size} />;
export const IconHome     = ({ size = 16 }) => <Home size={size} />;
