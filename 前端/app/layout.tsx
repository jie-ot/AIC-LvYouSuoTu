import { Analytics } from '@vercel/analytics/next'
import type { Metadata, Viewport } from 'next'
import { AppFrame } from '@/components/shared/app-frame'
import { AuthGate, AuthProvider } from '@/components/shared/auth-context'
import { MobileShell } from '@/components/shared/mobile-shell'
import './globals.css'
import './journal.css'
import './editorial.css'
import './persona.css'
import './discovery.css'
import './interaction.css'
import './journey.css'
import './auth.css'

export const metadata: Metadata = {
  title: '旅有所图',
  description: '照片创作、旅行记忆与行程规划。',
}

export const viewport: Viewport = {
  colorScheme: 'light',
  themeColor: '#faf9f6',
  width: 'device-width',
  initialScale: 1,
  viewportFit: 'cover',
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="zh-CN" className="bg-background" suppressHydrationWarning>
      <body className="font-sans antialiased" suppressHydrationWarning>
        <AuthProvider>
          <MobileShell>
            <AuthGate><AppFrame>{children}</AppFrame></AuthGate>
          </MobileShell>
        </AuthProvider>
        {process.env.VERCEL === '1' && <Analytics />}
      </body>
    </html>
  )
}
