import { useEffect, useState } from 'react'
import { getLibrary } from '../api/projects'
import type { LibraryItem } from '../api/projects'

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString('nl-NL', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  })
}

export default function LibraryPage() {
  const [items, setItems] = useState<LibraryItem[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getLibrary()
      .then(setItems)
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="h-full overflow-y-auto bg-zinc-950">
      <div className="max-w-6xl mx-auto px-6 py-8">
        <h2 className="text-2xl font-bold mb-6 text-white">Library</h2>

        {loading && (
          <div className="text-zinc-500 text-sm">Laden…</div>
        )}

        {!loading && items.length === 0 && (
          <div className="text-center py-24 text-zinc-600">
            <p className="text-5xl mb-4">🎬</p>
            <p className="text-lg font-medium">Nog geen voltooide projecten</p>
            <p className="text-sm mt-1">
              Exporteer een project en het verschijnt hier automatisch.
            </p>
          </div>
        )}

        {/* 4-column grid */}
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-5">
          {items.map((item) => (
            <div
              key={item.id}
              className="group flex flex-col rounded-xl overflow-hidden bg-zinc-900
                         border border-zinc-800 hover:border-zinc-600 transition-all"
            >
              {/* Square thumbnail */}
              <div className="aspect-square bg-zinc-800 relative overflow-hidden">
                {item.thumbnail_url ? (
                  <img
                    src={item.thumbnail_url}
                    alt={item.name}
                    className="w-full h-full object-cover"
                  />
                ) : (
                  <div className="w-full h-full flex items-center justify-center text-zinc-600 text-4xl">
                    🎬
                  </div>
                )}

                {/* Hover overlay with download button */}
                <div className="absolute inset-0 bg-black/60 opacity-0 group-hover:opacity-100
                                transition-opacity flex items-center justify-center">
                  <a
                    href={item.download_url}
                    download
                    className="bg-white text-zinc-900 text-xs font-semibold px-4 py-2
                               rounded-lg hover:bg-zinc-100 transition-colors flex items-center gap-2"
                    onClick={(e) => e.stopPropagation()}
                  >
                    ↓ Download MP4
                  </a>
                </div>
              </div>

              {/* Card footer */}
              <div className="px-3 py-2.5 flex items-center justify-between gap-2">
                <div className="min-w-0">
                  <p className="text-sm font-medium text-white truncate">{item.name}</p>
                  <p className="text-xs text-zinc-500">{fmtDate(item.created_at)}</p>
                </div>
                <a
                  href={item.download_url}
                  download
                  title="Download MP4"
                  className="flex-shrink-0 text-zinc-500 hover:text-emerald-400 transition-colors"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                      d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                  </svg>
                </a>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
