const apiOrigin = import.meta.env.VITE_API_ORIGIN || "";

export function apiUrl(path) {
  return `${apiOrigin}${path}`;
}
