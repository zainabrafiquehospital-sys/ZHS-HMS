import { httpClient } from '@/services/api/httpClient';
import { buildResourcePath } from '@/services/api/endpoints';

/**
 * Generic, resource-agnostic CRUD service. Feature-level services extend or
 * compose this rather than re-implementing the same Axios calls per feature.
 */
export class BaseService {
  constructor(resource) {
    this.resource = resource;
  }

  list(params) {
    return httpClient.get(buildResourcePath(this.resource), { params });
  }

  getById(id) {
    return httpClient.get(buildResourcePath(this.resource, id));
  }

  create(payload) {
    return httpClient.post(buildResourcePath(this.resource), payload);
  }

  update(id, payload) {
    return httpClient.patch(buildResourcePath(this.resource, id), payload);
  }

  remove(id) {
    return httpClient.delete(buildResourcePath(this.resource, id));
  }
}
