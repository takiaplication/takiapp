import { useEffect, useState } from 'react'
import {
  getLibrary,
  getLibraryExportAllUrl,
  regenerateProject,
  updateProjectViews,
} from '../api/projects'
import type { LibraryItem } from '../api/projects'

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString('nl-NL', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  })
}

function fmtViews(v: number): string {
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(v >= 10_000_000 ? 0 : 1)}M`
  if (v >= 1_000) return `${(v / 1_000).toFixed(v >= 10_000 ? 0 : 1)}K`
  return `${v}`
}

export default function LibraryPage() {
  const [items, setItems] = useState<LibraryItem[]>([])
  const [loading, setLoading] = useState(true)
  const [regenerating, setRegenerating] = useState<Set<string>>(new Set())

  useEffect(() => {
    getLibrary()
      .then(setItems)
      .finally(() => setLoading(false))
  }, [])

  const handleViewsChange = async (id: string, raw: string) => {
    const parsed = Math.max(0, parseInt(raw || '0', 10) || 0)
    const prev = items
    setItems((cur) => cur.map((it) => (it.id === id ? { ...it, views: parsed } : it)))
    try {
      await updateProjectViews(id, parsed)
    } catch (err) {
      console.error('Failed to update views', err)
      setItems(prev) // revert
    }
  }

  const handleRegenerate = async (id: string, name: string) => {
    if (!confirm(`Video opnieuw genereren voor "${name}"?\n\nDe bestaande Drive-link wordt vervangen door een nieuwe.`)) {
      return
    }
    setRegenerating((s) => new Set(s).add(id))
    try {
      await regenerateProject(id)
      // Once regeneration kicks off, the project leaves 'library' status and
      // shows up in the Approved kanban column until export finishes.
      setItems((cur) => cur.filter((it) => it.id !== id))
    } catch (err) {
      console.error('Failed to regenerate', err)
      alert('Regenereren mislukt — kijk in de console voor details.')
    } finally {
      setRegenerating((s) => {
        const next = new Set(s)
        next.delete(id)
        return next
      })
    }
  }

  return (
    <div className="h-full overflow-y-auto bg-zinc-950">
      <div className="max-w-6xl mx-auto px-6 py-8">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-2xl font-bold text-white">Library</h2>
          {items.length > 0 && (
            <a
              href={getLibraryExportAllUrl()}
              className="bg-zinc-800 hover:bg-zinc-700 text-white text-sm font-semibold
                         px-4 py-2 rounded-lg transition-colors flex items-center gap-2
                         border border-zinc-700"
            >
              📦 Export alle JSON
            </a>
          )}
        </div>

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
          {items.map((item) => {
            const isRegen = regenerating.has(item.id)
            return (
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

                  {/* Views badge (top-right) */}
                  {item.views > 0 && (
                    <div className="absolute top-2 right-2 bg-black/70 backdrop-blur-sm
                                    text-white text-[11px] font-semibold px-2 py-1 rounded-md
                                    flex items-center gap-1">
                      👁 {fmtViews(item.views)}
                    </div>
                  )}

                  {/* Hover overlay */}
                  <div className="absolute inset-0 bg-black/70 opacity-0 group-hover:opacity-100
                                  transition-opacity flex flex-col items-center justify-center gap-2 p-3">
                    {item.drive_url && (
                      <a
                        href={item.drive_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="w-full bg-emerald-500 text-white text-xs font-semibold px-3 py-2
                                   rounded-lg hover:bg-emerald-400 transition-colors flex items-center
                                   justify-center gap-1.5"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="currentColor">
                          <path d="M6.28 3l5.72 9.9L6.28 21H2l5.72-9.9L2 3h4.28zm4.44 0H22l-5.72 9.9L22 21h-4.28l-5.72-9.9L14.72 3z"/>
                        </svg>
                        Open Drive
                      </a>
                    )}
                    <button
                      type="button"
                      disabled={isRegen}
                      onClick={(e) => {
                        e.stopPropagation()
                        handleRegenerate(item.id, item.name)
                      }}
                      className="w-full bg-blue-500 text-white text-xs font-semibold px-3 py-2
                                 rounded-lg hover:bg-blue-400 disabled:bg-zinc-600 disabled:cursor-not-allowed
                                 transition-colors flex items-center justify-center gap-1.5"
                    >
                      {isRegen ? '⏳ Bezig…' : '🔁 Regenereer video'}
                    </button>
                    <a
                      href={`/api/projects/${item.id}/json`}
                      download
                      className="w-full bg-zinc-700 text-white text-xs font-semibold px-3 py-2
                                 rounded-lg hover:bg-zinc-600 transition-colors flex items-center
                                 justify-center gap-1.5"
                      onClick={(e) => e.stopPropagation()}
                    >
                      ⬇ JSON
                    </a>
                  </div>
                </div>

                {/* Drive-upload failure banner — always visible when no Drive URL */}
                {!item.drive_url && item.pipeline_error && (
                  <div className="px-3 py-2 bg-red-950/60 border-t border-red-800">
                    <p className="text-[11px] text-red-300 font-semibold mb-1">⚠ Drive upload mislukt</p>
                    <p className="text-[10px] text-red-300/80 font-mono leading-snug break-words line-clamp-3">
                      {item.pipeline_error}
                    </p>
                  </div>
                )}

                {/* Card footer */}
                <div className="px-3 py-2.5 flex items-center justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-white truncate">{item.name}</p>
                    <p className="text-xs text-zinc-500">{fmtDate(item.created_at)}</p>
                  </div>
                  <label className="flex items-center gap-1 flex-shrink-0" title="Views (handmatig)">
                    <span className="text-zinc-500 text-xs">👁</span>
                    <input
                      type="number"
                      min={0}
                      value={item.views}
                      onChange={(e) => handleViewsChange(item.id, e.target.value)}
                      className="w-16 bg-zinc-800 border border-zinc-700 rounded
                                 text-xs text-white px-1.5 py-1 text-right
                                 focus:outline-none focus:border-emerald-500"
                    />
                  </label>
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
