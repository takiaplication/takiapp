/**
 * MemeLibraryModal
 *
 * Shows the shared Dutch meme library.
 * - Browse / select an existing meme
 * - Upload a new meme (image or video) directly to the library
 * - Confirm assigns the selected meme to the current meme slide
 */

import { useState, useEffect, useRef } from 'react'

const API_BASE = 'http://localhost:8000'

export interface LibraryMeme {
  filename: string
  name: string
  url: string       // e.g. /meme-library/grappig.jpg
  type: 'image' | 'video'
}

interface Props {
  projectId: string
  slideId: string
  onAssigned: (frameUrl: string, holdMs: number) => void
  onClose: () => void
}

export default function MemeLibraryModal({ projectId, slideId, onAssigned, onClose }: Props) {
  const [memes, setMemes]           = useState<LibraryMeme[]>([])
  const [loading, setLoading]       = useState(true)
  const [selected, setSelected]     = useState<LibraryMeme | null>(null)
  const [uploading, setUploading]   = useState(false)
  const [assigning, setAssigning]   = useState(false)
  const uploadRef                   = useRef<HTMLInputElement>(null)

  const fetchLibrary = async () => {
    setLoading(true)
    try {
      const res = await fetch(`${API_BASE}/api/meme-library`)
      setMemes(await res.json())
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchLibrary() }, [])

  // Close on backdrop click
  const handleBackdrop = (e: React.MouseEvent<HTMLDivElement>) => {
    if (e.target === e.currentTarget) onClose()
  }

  const handleUpload = async (file: File) => {
    setUploading(true)
    try {
      const form = new FormData()
      form.append('file', file)
      const res  = await fetch(`${API_BASE}/api/meme-library/upload`, { method: 'POST', body: form })
      const item = await res.json() as LibraryMeme
      setMemes((prev) => [item, ...prev])
      setSelected(item)
    } finally {
      setUploading(false)
    }
  }

  const handleAssign = async () => {
    if (!selected) return
    setAssigning(true)
    try {
      const res  = await fetch(
        `${API_BASE}/api/projects/${projectId}/slides/${slideId}/assign-library-meme`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ filename: selected.filename }),
        },
      )
      const data = await res.json()
      onAssigned(data.frame_url, data.hold_duration_ms)
    } finally {
      setAssigning(false)
    }
  }

  return (
    <div
      className="fixed inset-0 bg-black/80 z-50 flex items-center justify-center p-4"
      onClick={handleBackdrop}
    >
      <div className="bg-zinc-900 border border-zinc-700 rounded-xl w-full max-w-2xl max-h-[85vh] flex flex-col shadow-2xl">

        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-zinc-800 flex-shrink-0">
          <div>
            <h2 className="font-semibold text-base">🎭 Meme Bibliotheek</h2>
            <p className="text-zinc-400 text-xs mt-0.5">Kies een Nederlandse meme of upload een nieuwe</p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => uploadRef.current?.click()}
              disabled={uploading}
              className="bg-amber-600 hover:bg-amber-500 disabled:opacity-50 text-white text-xs font-medium px-3 py-1.5 rounded transition-colors"
            >
              {uploading ? 'Uploading…' : '+ Upload meme'}
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

        {/* Grid */}
        <div className="flex-1 overflow-y-auto p-4">
          {loading ? (
            <div className="flex items-center justify-center h-40 text-zinc-500 text-sm">
              Laden…
            </div>
          ) : memes.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-40 gap-3 text-zinc-500">
              <span className="text-4xl">📂</span>
              <p className="text-sm">Bibliotheek is leeg — upload je eerste meme!</p>
            </div>
          ) : (
            <div className="grid grid-cols-4 gap-3">
              {memes.map((m) => (
                <button
                  key={m.filename}
                  onClick={() => setSelected(m)}
                  className={`relative rounded-lg overflow-hidden border-2 transition-all aspect-[9/16] ${
                    selected?.filename === m.filename
                      ? 'border-amber-400 scale-[1.02]'
                      : 'border-transparent hover:border-zinc-500'
                  }`}
                >
                  {m.type === 'video' ? (
                    <div className="w-full h-full bg-zinc-800 flex flex-col items-center justify-center gap-2">
                      <span className="text-3xl">▶️</span>
                      <span className="text-zinc-400 text-xs text-center px-2 leading-tight break-all">
                        {m.name}
                      </span>
                    </div>
                  ) : (
                    <div className="w-full h-full bg-black flex items-center justify-center">
                      <img
                        src={`${API_BASE}${m.url}`}
                        alt={m.name}
                        className="w-full h-full object-contain"
                      />
                    </div>
                  )}

                  {/* Video badge */}
                  {m.type === 'video' && (
                    <span className="absolute top-1 right-1 bg-purple-600/90 text-white text-[10px] px-1 py-0.5 rounded">
                      video
                    </span>
                  )}

                  {/* Selected checkmark */}
                  {selected?.filename === m.filename && (
                    <div className="absolute top-1 left-1 bg-amber-400 rounded-full w-5 h-5 flex items-center justify-center">
                      <svg className="w-3 h-3 text-black" fill="none" viewBox="0 0 10 8">
                        <path d="M1 4l3 3 5-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                      </svg>
                    </div>
                  )}

                  {/* Name label */}
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
              ? `Geselecteerd: ${selected.name} (${selected.type === 'video' ? 'video — duur = videolengte' : 'afbeelding — 1,5 sec'})`
              : 'Nog geen meme geselecteerd'}
          </p>
          <div className="flex gap-2">
            <button onClick={onClose} className="text-zinc-400 hover:text-white text-sm px-4 py-1.5 rounded transition-colors">
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
