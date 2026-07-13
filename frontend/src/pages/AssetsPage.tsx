import { useEffect, useRef, useState } from 'react'
import {
  getStoryLibrary,
  uploadStoryPhoto,
  deleteStoryPhoto,
  getMusicLibrary,
  uploadMusicTrack,
  deleteMusicTrack,
} from '../api/projects'
import type { AssetItem } from '../api/projects'
import { API_BASE } from '../api/config'

export default function AssetsPage() {
  const [storyItems, setStoryItems] = useState<AssetItem[]>([])
  const [musicItems, setMusicItems] = useState<AssetItem[]>([])
  const [busy, setBusy] = useState(false)
  const storyInput = useRef<HTMLInputElement>(null)
  const musicInput = useRef<HTMLInputElement>(null)

  const reload = () => {
    getStoryLibrary().then((r) => setStoryItems(r.items)).catch(() => {})
    getMusicLibrary().then((r) => setMusicItems(r.items)).catch(() => {})
  }

  useEffect(reload, [])

  const handleUpload = async (
    files: FileList | null,
    upload: (f: File) => Promise<AssetItem>,
  ) => {
    if (!files || files.length === 0) return
    setBusy(true)
    try {
      for (const f of Array.from(files)) {
        await upload(f)
      }
      reload()
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="p-6 overflow-y-auto h-full space-y-10">
      {/* ── Story photos ─────────────────────────────────────────────── */}
      <section>
        <div className="flex items-center justify-between mb-1">
          <h2 className="text-2xl font-bold text-white">📸 Story-foto's</h2>
          <button
            onClick={() => storyInput.current?.click()}
            disabled={busy}
            className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium disabled:opacity-50"
          >
            + Foto's toevoegen
          </button>
          <input
            ref={storyInput}
            type="file"
            accept=".jpg,.jpeg,.png,.webp"
            multiple
            className="hidden"
            onChange={(e) => {
              handleUpload(e.target.files, uploadStoryPhoto)
              e.target.value = ''
            }}
          />
        </div>
        <p className="text-sm text-zinc-400 mb-4">
          Elke foto wordt in <b>exact één</b> video gebruikt en daarna automatisch
          uit deze lijst verwijderd. Binnen één video is de story-foto overal
          hetzelfde.
        </p>

        {storyItems.length <= 3 && (
          <div className={`mb-4 rounded-lg px-4 py-3 text-sm border ${
            storyItems.length === 0
              ? 'bg-red-950/60 border-red-800 text-red-300'
              : 'bg-amber-950/60 border-amber-800 text-amber-300'
          }`}>
            {storyItems.length === 0
              ? '⚠️ De story-library is leeg — video\'s met een story-reply worden geblokkeerd tot je foto\'s toevoegt.'
              : `⚠️ Nog maar ${storyItems.length} foto${storyItems.length === 1 ? '' : "'s"} over — vul aan om de pipeline draaiende te houden.`}
          </div>
        )}

        <div className="grid grid-cols-3 sm:grid-cols-5 lg:grid-cols-8 gap-3">
          {storyItems.map((it) => (
            <div key={it.filename} className="relative group rounded-lg overflow-hidden bg-zinc-900 border border-zinc-800">
              <img
                src={`${API_BASE}${it.url}`}
                alt={it.filename}
                className="w-full aspect-[9/16] object-cover"
              />
              <button
                onClick={() => deleteStoryPhoto(it.filename).then(reload)}
                className="absolute top-1 right-1 w-6 h-6 rounded-full bg-black/70 text-red-400 opacity-0 group-hover:opacity-100 transition-opacity text-xs"
                title="Verwijderen"
              >
                ✕
              </button>
            </div>
          ))}
          {storyItems.length === 0 && (
            <div className="col-span-full text-zinc-600 text-sm py-8 text-center border border-dashed border-zinc-800 rounded-lg">
              Leeg — klik "+ Foto's toevoegen"
            </div>
          )}
        </div>
      </section>

      {/* ── Music tracks ─────────────────────────────────────────────── */}
      <section>
        <div className="flex items-center justify-between mb-1">
          <h2 className="text-2xl font-bold text-white">🎵 Muziek</h2>
          <button
            onClick={() => musicInput.current?.click()}
            disabled={busy}
            className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium disabled:opacity-50"
          >
            + Tracks toevoegen
          </button>
          <input
            ref={musicInput}
            type="file"
            accept=".mp3,.m4a,.wav,.aac,.ogg"
            multiple
            className="hidden"
            onChange={(e) => {
              handleUpload(e.target.files, uploadMusicTrack)
              e.target.value = ''
            }}
          />
        </div>
        <p className="text-sm text-zinc-400 mb-4">
          Bij elke export zonder eigen muziek wordt hier een willekeurige track
          uit gekozen (herbruikbaar — tracks blijven staan). De audio wordt in de
          video gebakken vóór het posten.
        </p>

        <div className="space-y-2 max-w-2xl">
          {musicItems.map((it) => (
            <div
              key={it.filename}
              className="flex items-center gap-3 bg-zinc-900 border border-zinc-800 rounded-lg px-4 py-2"
            >
              <span className="text-zinc-300 text-sm flex-1 truncate">🎵 {it.filename}</span>
              <audio controls preload="none" src={`${API_BASE}${it.url}`} className="h-8" />
              <button
                onClick={() => deleteMusicTrack(it.filename).then(reload)}
                className="text-red-400 hover:text-red-300 text-sm px-2"
                title="Verwijderen"
              >
                ✕
              </button>
            </div>
          ))}
          {musicItems.length === 0 && (
            <div className="text-zinc-600 text-sm py-6 text-center border border-dashed border-zinc-800 rounded-lg">
              Geen tracks — video's worden zonder muziek geëxporteerd
            </div>
          )}
        </div>
      </section>
    </div>
  )
}
