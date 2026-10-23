/**
 * Shared API Client & Scholar Identity Helper
 * Handles persistent user_id in localStorage and standard HTTP requests.
 */

// Persistent Scholar User ID in LocalStorage
export function getScholarId() {
  const STORAGE_KEY = "azure_scholar_uid";
  let uid = localStorage.getItem(STORAGE_KEY);
  if (!uid) {
    if (typeof crypto !== "undefined" && crypto.randomUUID) {
      uid = "scholar-" + crypto.randomUUID().slice(0, 8);
    } else {
      uid = "scholar-" + Math.random().toString(36).substring(2, 10);
    }
    localStorage.setItem(STORAGE_KEY, uid);
  }
  return uid;
}

// Global user ID
export const userId = getScholarId();

/**
 * Standard GET JSON helper
 */
export async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
  }
  return response.json();
}

/**
 * Standard POST JSON helper
 */
export async function postJson(url, data) {
  const response = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify(data)
  });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
  }
  return response.json();
}
