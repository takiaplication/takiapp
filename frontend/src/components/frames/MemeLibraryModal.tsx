/**
 * MemeLibraryModal — category-based meme library
 *
 * Shows 6 category tabs: opening | sport | coocked | cooking | shoot_our_shot | succes
 * - Browse / select an existing meme per category
 * - Upload a new meme (image or video) directly into the active category
 * - Confirm assigns the selected meme to the current meme slide
 */

import { useState, useEffect, useRef } from 'react'
import { MEME_CATEGORIES, type LibraryMeme, type MemeCategory } from '../../api/projects'
import { API_BASE } from '../../api/config'

interface Props {
  projectId: string
  slideId: string
  initialCategory?: MemeCategory | null
  onAssigned: (frameUrl: string, holdMs: number, category: MemeCategory) => void
  onClose: () => void
}

export default function MemeLibraryModal({
  projectId,
  slideId,
  initialCategory,
  onAssigned,
  onClose,
}: Props) {
  const [allMemes, setAllMemes]   = useState<LibraryMeme[]>([])
  const [loading, setLoading]     = useState(true)
  const [activeCat, setActiveCat] = useState<MemeCategory>(initialCategory ?? 'cooking')
  const [selected, setSelected]   = useState<LibraryMeme | null>(null)
  const [uploading, setUploading] = useState(false)
  const [assigning, setAssigning] = useState(false)
  const [deletingKey, setDeletingKey] = useState<string | null>(null)   // `${cat}/${filename}`
  const uploadRef                 = useRef<HTMLInputElement>(null)

  const fetchLibrary = async () => {
    setLoading(true)
    try {
      const res = await fetch(`${API_BASE}/api/meme-library`)
      setAllMemes(await res.json())
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchLibrary() }, [])
  useEffect(() => { setSelected(null) }, [activeCat])

  const memesInCat = allMemes.filter((m) => m.category === activeCat)

  const handleBackdrop = (e: React.MouseEvent<HTMLDivElement>) => {
    if (e.target === e.currentTarget) onClose()
  }

  const handleUpload = async (file: File) => {
    setUploading(true)
    try {
      const form = new FormData()
      form.append('file', file)
      form.append('category', activeCat)
      const res  = await fetch(`${API_BASE}/api/meme-library/upload`, { method: 'POST', body: form })
      const item = await res.json() as LibraryMeme
      setAllMemes((prev) => [...prev, item])
      setSelected(item)
    } finally {
      setUploading(false)
    }
  }

  const handleDelete = async (meme: LibraryMeme) => {
    const key = `${meme.category}/${meme.filename}`
    setDeletingKey(key)
    try {
      await fetch(`${API_BASE}/api/meme-library/${meme.category}/${encodeURIComponent(meme.filename)}`, {
        method: 'DELETE',
      })
      setAllMemes((prev) => prev.filter((m) => !(m.filename === meme.filename && m.category === meme.category)))
      if (selected?.filename === meme.filename && selected?.category === meme.category) {
        setSelected(null)
      }
    } finally {
      setDeletingKey(null)
    }
  }

  const handleAssign = async () => {
    if (!selected) return
    setAssigning(true)
    try {
      const res = await fetch(
        `${API_BASE}/api/projects/${projectId}/slides/${slideId}/assign-library-meme`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ category: selected.category, filename: selected.filename }),
        },
      )
      const data = await res.json()
      onAssigned(data.frame_url, data.hold_duration_ms, selected.category)
    } finally {
      setAssigning(false)
    }
  }

  const catMeta = (id: MemeCategory) => MEME_CATEGORIES.find((c) => c.id === id)!

  return (
    <div
      className="fixed inset-0 bg-black/80 z-50 flex items-center justify-center p-4"
      onClick={handleBackdrop}
    >
      <div className="bg-zinc-900 border border-zinc-700 rounded-xl w-full max-w-2xl max-h-[90vh] flex flex-col shadow-2xl">

        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-zinc-800 flex-shrink-0">
          <div>
            <h2 className="font-semibold text-base">🎭 Meme Bibliotheek</h2>
            <p className="text-zinc-400 text-xs mt-0.5">Selecteer categorie → kies of upload een meme</p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => uploadRef.current?.click()}
              disabled={uploading}
              className="bg-amber-600 hover:bg-amber-500 disabled:opacity-50 text-white text-xs font-medium px-3 py-1.5 rounded transition-colors"
            >
              {uploading ? 'Uploading…' : `+ Upload naar ${catMeta(activeCat).label}`}
            </button>
            <button onClick={onClose} className="text-zinc-400 hover:text-white text-lg leading-none px-2">✕</button>
          </div>
        </div>

        {/* Hidden file input */}
        <input
          ref={uploadRef}
          type="file"
          accept="image/*,video/mp4,video/quicktime,video/avi"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0]
            if (f) handleUpload(f)
            ;(e.target as HTMLInputElement).value = ''
          }}
        />

        {/* Category tabs */}
        <div className="flex border-b border-zinc-800 flex-shrink-0 overflow-x-auto">
          {MEME_CATEGORIES.map((cat) => {
            const count = allMemes.filter((m) => m.category === cat.id).length
            return (
              <button
                key={cat.id}
                onClick={() => setActiveCat(cat.id)}
                className={`flex-shrink-0 px-4 py-2.5 text-xs font-medium transition-colors border-b-2 whitespace-nowrap ${
                  activeCat === cat.id
                    ? 'border-amber-400 text-amber-300 bg-amber-500/10'
                    : 'border-transparent text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/50'
                }`}
              >
                {cat.emoji} {cat.label}
                {count > 0 && (
                  <span className={`ml-1.5 text-[10px] px-1 rounded-full ${
                    activeCat === cat.id ? 'bg-amber-500/30 text-amber-300' : 'bg-zinc-700 text-zinc-400'
                  }`}>
                    {count}
                  </span>
                )}
              </button>
            )
          })}
        </div>

        {/* Grid */}
        <div className="flex-1 overflow-y-auto p-4">
          {loading ? (
            <div className="flex items-center justify-center h-40 text-zinc-500 text-sm">Laden…</div>
          ) : memesInCat.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-40 gap-3 text-zinc-500">
              <span className="text-4xl">📂</span>
              <p className="text-sm text-center">
                Geen memes in <strong className="text-zinc-300">{catMeta(activeCat).emoji} {catMeta(activeCat).label}</strong>
              </p>
              <button
                onClick={() => uploadRef.current?.click()}
                disabled={uploading}
                className="bg-amber-600 hover:bg-amber-500 disabled:opacity-50 text-white text-xs font-medium px-4 py-1.5 rounded transition-colors"
              >
                + Upload eerste meme
              </button>
            </div>
          ) : (
            <div className="grid grid-cols-4 gap-3">
              {memesInCat.map((m) => (
                <button
                  key={m.filename}
                  onClick={() => setSelected(m)}
                  className={`group relative rounded-lg overflow-hidden border-2 transition-all aspect-[9/16] ${
                    selected?.filename === m.filename
                      ? 'border-amber-400 scale-[1.02]'
                      : 'border-transparent hover:border-zinc-500'
                  }`}
                >
                  {m.type === 'video' ? (
                    <div className="w-full h-full bg-zinc-800 flex flex-col items-center justify-center gap-2">
                      <span className="text-3xl">▶️</span>
                      <span className="text-zinc-400 text-xs text-center px-2 leading-tight break-all">{m.name}</span>
                    </div>
                  ) : (
                    <div className="w-full h-full bg-black flex items-center justify-center">
                      <img src={`${API_BASE}${m.url}`} alt={m.name} className="w-full h-full object-contain" />
                    </div>
                  )}

                  {m.type === 'video' && (
                    <span className="absolute top-1 right-1 bg-purple-600/90 text-white text-[10px] px-1 py-0.5 rounded">
                      video
                    </span>
                  )}

                  {selected?.filename === m.filename && (
                    <div className="absolute top-1 left-1 bg-amber-400 rounded-full w-5 h-5 flex items-center justify-center">
                      <svg className="w-3 h-3 text-black" fill="none" viewBox="0 0 10 8">
                        <path d="M1 4l3 3 5-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                      </svg>
                    </div>
                  )}

                  {/* Delete button — visible on hover */}
                  <button
                    onClick={(e) => { e.stopPropagation(); handleDelete(m) }}
                    disabled={deletingKey === `${m.category}/${m.filename}`}
                    className="absolute top-1 right-1 w-5 h-5 bg-red-600/90 hover:bg-red-500 disabled:opacity-50 rounded flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity z-10"
                    title="Verwijder uit bibliotheek"
                  >
                    {deletingKey === `${m.category}/${m.filename}` ? (
                      <span className="text-white text-[8px]">…</span>
                    ) : (
                      <svg className="w-2.5 h-2.5 text-white" fill="none" viewBox="0 0 10 10">
                        <path d="M1 1l8 8M9 1L1 9" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/>
                      </svg>
                    )}
                  </button>

                  <div className="absolute bottom-0 inset-x-0 bg-black/60 px-1.5 py-1">
                    <p className="text-white text-[10px] truncate">{m.name}</p>
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-5 py-3 border-t border-zinc-800 flex-shrink-0">
          <p className="text-zinc-500 text-xs">
            {selected
              ? `${selected.name} · ${selected.type === 'video' ? 'video — duur = videolengte' : 'afbeelding — 1,5 sec'}`
              : 'Nog geen meme geselecteerd'}
          </p>
          <div className="flex gap-2">
            <button
              onClick={onClose}
              className="text-zinc-400 hover:text-white text-sm px-4 py-1.5 rounded transition-colors"
            >
              Annuleren
            </button>
            <button
              onClick={handleAssign}
              disabled={!selected || assigning}
              className="bg-amber-500 hover:bg-amber-400 disabled:opacity-50 text-black font-semibold text-sm px-5 py-1.5 rounded transition-colors"
            >
              {assigning ? 'Toepassen…' : 'Gebruik deze meme'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
