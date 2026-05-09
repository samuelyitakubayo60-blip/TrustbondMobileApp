/** Display labels for police dashboard roles (API values stay admin / supervisor / officer). */
export function staffRoleLabel(role) {
  if (role === "admin") return "DPC";
  if (role === "supervisor") return "IO";
  return "Officer";
}
