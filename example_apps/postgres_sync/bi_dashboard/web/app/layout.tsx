import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Postgres vs Snowflake',
  description: 'One Cube model, two data sources, the same 32 tiles on each.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
