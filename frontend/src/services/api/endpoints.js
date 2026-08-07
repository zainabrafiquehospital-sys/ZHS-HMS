/**
 * Shared path-building helpers. Feature-specific endpoint constants live
 * inside each feature's own `api/` folder and are built on top of these.
 */
export function buildResourcePath(resource, id) {
  return id ? `/${resource}/${id}` : `/${resource}`;
}
