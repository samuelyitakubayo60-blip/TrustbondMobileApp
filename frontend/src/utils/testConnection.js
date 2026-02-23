// Test backend connection
export async function testBackendConnection() {
  const baseUrl = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';
  const healthUrl = `${baseUrl}/health`;
  
  try {
    console.log('[Connection Test] Testing:', healthUrl);
    const response = await fetch(healthUrl);
    const data = await response.json();
    console.log('[Connection Test] Success:', data);
    return { success: true, data };
  } catch (err) {
    console.error('[Connection Test] Failed:', err);
    return { success: false, error: err.message };
  }
}
