import { ReactNode, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import SettingsModal from '../shared/SettingsModal'

interface Props {
  children: ReactNode
}

export default function PageShell({ children }: Props) {
  const [settingsOpen, setSettingsOpen] = useState(false)
  const { pathname } = useLocation()

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100">
      <header className="h-14 border-b border-zinc-800 flex items-center px-6 gap-6">
        <h1 className="text-lg font-semibold tracking-tight">
          <Link to="/" className="hover:opacity-80 transition-opacity">
            <span className="text-blue-500">Reel</span>Factory
          </Link>
        </h1>

        {/* Main nav */}
        <nav className="flex gap-1 flex-1">
          <Link
            to="/"
            className={`px-3 py-1.5 rounded-lg text-sm transition-colors ${
              pathname === '/'
                ? 'bg-zinc-800 text-white'
                : 'text-zinc-400 hover:text-white hover:bg-zinc-800/60'
            }`}
          >
            Kanban
          </Link>
          <Link
            to="/library"
            className={`px-3 py-1.5 rounded-lg text-sm transition-colors ${
              pathname === '/library'
                ? 'bg-zinc-800 text-white'
                : 'text-zinc-400 hover:text-white hover:bg-zinc-800/60'
            }`}
          >
            🎬 Library
          </Link>
        </nav>

        <button
          onClick={() => setSettingsOpen(true)}
          className="text-zinc-400 hover:text-white transition-colors p-2 rounded-lg hover:bg-zinc-800"
          title="Instellingen"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8}
              d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8}
              d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
          </svg>
        </button>
      </header>
      <main className="h-[calc(100vh-3.5rem)]">
        {children}
      </main>
      <SettingsModal open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </div>
  )
}
