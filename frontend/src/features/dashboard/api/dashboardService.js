import { httpClient } from '@/services/api/httpClient';

export const dashboardService = {
  getReceptionSummary() {
    return httpClient.get('/dashboard/reception');
  },

  getDoctorSummary() {
    return httpClient.get('/dashboard/doctor');
  },

  getVitalsSummary() {
    return httpClient.get('/dashboard/vitals');
  },
};
