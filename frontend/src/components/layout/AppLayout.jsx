import { useEffect } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import AppHeader from './AppHeader.jsx'
import Toaster from '../ui/Toaster.jsx'

export default function AppLayout() {
  const { pathname } = useLocation()
  // Start each screen at the top (query-string changes, e.g. audit filters, keep the scroll position).
  useEffect(() => {
    window.scrollTo(0, 0)
  }, [pathname])

  return (
    <div className="min-h-screen bg-gradient-to-br from-[#f8fafc] via-[#f9fbfe] to-[#f1f5f9] text-[#0f172a]">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-[90] focus:bg-white focus:px-3 focus:py-2 focus:rounded-lg focus:shadow-card"
      >
        Skip to content
      </a>
      <AppHeader />
      <main id="main" className="w-full pt-14 min-h-screen">
        <Outlet />
      </main>
      <Toaster />
    </div>
  )
}
