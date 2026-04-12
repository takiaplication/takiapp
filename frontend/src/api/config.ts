/**
 * Single source of truth for the backend base URL.
 *
 * - Local dev (no env var set): '' → relative URLs hit the Vite dev proxy
 * - Production (VITE_API_URL=https://takiapp-production.up.railway.app):
 *   full URL prepended to every request
 */
export const API_BASE: string = import.meta.env.VITE_API_URL ?? ''
