function readEnv(key, fallback) {
  const value = process.env[key];
  if (value === undefined || value === '') {
    if (fallback !== undefined) return fallback;
    throw new Error(`Missing required environment variable: ${key}`);
  }
  return value;
}

export const env = {
  apiBaseUrl: readEnv('NEXT_PUBLIC_API_BASE_URL', 'http://localhost:8000'),
  apiVersion: readEnv('NEXT_PUBLIC_API_VERSION', 'v1'),
  appName: readEnv('NEXT_PUBLIC_APP_NAME', 'Gynecology HMS'),
  isProduction: process.env.NODE_ENV === 'production',
};
