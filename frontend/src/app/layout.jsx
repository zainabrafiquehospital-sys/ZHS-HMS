import { AppProviders } from '@/core/providers/AppProviders';
import { env } from '@/core/config/env';
import './globals.css';

export const metadata = {
  title: env.appName,
  description: 'Enterprise Gynecology Hospital Management System',
};

export default function RootLayout({ children }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>
        <AppProviders>{children}</AppProviders>
      </body>
    </html>
  );
}
