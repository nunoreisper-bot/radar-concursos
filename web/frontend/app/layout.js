export const metadata = {
  title: 'Radar de Concursos',
  description: 'Radar TED Portugal',
};

import './globals.css';

export default function RootLayout({ children }) {
  return (
    <html lang="pt">
      <body>{children}</body>
    </html>
  );
}
