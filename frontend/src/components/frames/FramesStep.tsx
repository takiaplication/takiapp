import { useState, useEffect, useRef } from 'react'
import { useProjectStore } from '../../store/projectStore'
import * as api from '../../api/projects'
import type { MemeCategory } from '../../api/projects'
import { useJobProgress } from '../../hooks/useJobProgress'
import MemeLibraryModal from './MemeLibraryModal'

const API_BASE = 'http://localhost:8000'

interface Props {
  onNext: () => void
  onBack: () => void
}

export default function FramesStep({ onNext, onBack }: Props) {
  const { currentProject, loadProject } = useProjectStore()
  const [frames, setFrames] = useState<api.FrameSlide[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [librarySlideId, setLibrarySlideId] = useState<string | null>(null)   // which meme slot is open
  const extractJob = useJobProgress()
  const didLoadRef = useRef(false)

  const reload = async () => {
    if (!currentProject) return
    const f = await api.listFrameSlides(currentProject.id)
    setFrames(f)
  }

  useEffect(() => {
    if (!currentProject) return
    reload()
  }, [currentProject])

  useEffect(() => {
    if (extractJob.state.status === 'completed' && !didLoadRef.current) {
      didLoadRef.current = true
      reload()
    }
    if (extractJob.state.status !== 'completed') {
      didLoadRef.current = false
    }
  }, [extractJob.state.status])

  if (!currentProject) return null

  const toggleActive = async (slideId: string, current: boolean) => {
    setFrames((f) => f.map((s) => s.id === slideId ? { ...s, is_active: !current } : s))
    await fetch(`${API_BASE}/api/projects/${currentProject.id}/slides/${slideId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ is_active: !current }),
    })
  }

  const toggleFrameType = async (slideId: string, current: string) => {
    // Cycle: dm → meme → app_ad → dm
    const next = current === 'dm' ? 'meme' : current === 'meme' ? 'app_ad' : 'dm'
    setFrames((f) => f.map((s) => s.id === slideId ? { ...s, frame_type: next } : s))
    await api.setFrameType(currentProject.id, slideId, next)
  }

  const handleReExtract = async () => {
    const jobId = await api.extractFrames(currentProject.id)
    extractJob.start(jobId)
  }

  const handleMemeAssigned = (slideId: string, frameUrl: string, holdMs: number, category: MemeCategory) => {
    setFrames((f) =>
      f.map((fr) =>
        fr.id === slideId ? { ...fr, frame_url: frameUrl, hold_duration_ms: holdMs, meme_category: category } : fr
      )
    )
    setLibrarySlideId(null)
  }

  const activeCount = frames.filter((f) => f.is_active).length
  const selectedFrame = frames.find((f) => f.id === selected)

  return (
    <div className="h-full flex flex-col">
      {/* Meme library modal */}
      {librarySlideId && currentProject && (
        <MemeLibraryModal
          projectId={currentProject.id}
          slideId={librarySlideId}
          initialCategory={(frames.find((f) => f.id === librarySlideId)?.meme_category as MemeCategory) ?? undefined}
          onAssigned={(url, ms, cat) => handleMemeAssigned(librarySlideId, url, ms, cat)}
          onClose={() => setLibrarySlideId(null)}
        />
      )}
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-3 border-b border-zinc-800 flex-shrink-0 gap-4">
        <div className="flex-shrink-0">
          <h2 className="text-base font-semibold">Stage 2 — Frame Review</h2>
          <p className="text-zinc-400 text-xs mt-0.5">
            {activeCount}/{frames.length} selected · DM = re-render · Meme = voeg eigen meme toe
          </p>
        </div>

        <div className="flex gap-2 flex-shrink-0 ml-auto">
          <button
            onClick={handleReExtract}
            disabled={extractJob.state.status === 'running'}
            className="bg-zinc-800 hover:bg-zinc-700 disabled:opacity-50 text-sm px-3 py-1.5 rounded transition-colors whitespace-nowrap"
          >
            {extractJob.state.status === 'running' ? 'Extracting…' : 'Re-extract'}
          </button>
          <button onClick={onBack} className="text-zinc-400 hover:text-white text-sm px-3 py-1.5 rounded transition-colors">
            ← Back
          </button>
          <button
            onClick={async () => { await loadProject(currentProject.id); onNext() }}
            disabled={activeCount === 0}
            className="bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-sm px-4 py-1.5 rounded transition-colors whitespace-nowrap"
          >
            Continue to OCR →
          </button>
        </div>
      </div>

      {/* Extract progress */}
      {extractJob.state.status === 'running' && (
        <div className="px-6 py-2 border-b border-zinc-800 flex-shrink-0 space-y-1">
          <div className="h-1 bg-zinc-800 rounded-full overflow-hidden">
            <div
              className="h-full bg-blue-500 transition-all duration-300 rounded-full"
              style={{ width: `${Math.round(extractJob.state.progress * 100)}%` }}
            />
          </div>
          <p className="text-xs text-zinc-400">{extractJob.state.message}</p>
        </div>
      )}

      <div className="flex-1 overflow-hidden flex">
        {/* Grid */}
        <div className="flex-1 overflow-y-auto p-4">
          {frames.length === 0 ? (
            <div className="flex items-center justify-center h-full text-zinc-500 text-sm">
              No frames yet — click Re-extract to start
            </div>
          ) : (
            <div className="grid grid-cols-4 gap-3">
              {frames.map((frame) => (
                <div
                  key={frame.id}
                  className={`relative rounded-lg overflow-hidden cursor-pointer border-2 transition-colors ${
                    selected === frame.id ? 'border-blue-500' : 'border-transparent'
                  } ${!frame.is_active ? 'opacity-40' : ''}`}
                  onClick={() => setSelected(frame.id)}
                >
                  {/* ── Image / placeholder area ── */}
                  {frame.frame_type === 'meme' ? (
                    <div
                      className="w-full aspect-[9/16] cursor-pointer"
                      onClick={(e) => { e.stopPropagation(); setLibrarySlideId(frame.id) }}
                      title="Klik om meme te kiezen uit bibliotheek"
                    >
                      {frame.frame_url ? (
                        // Assigned meme — show preview with hover-replace overlay
                        <div className="relative w-full h-full group bg-black">
                          {frame.frame_url.endsWith('.mp4') || frame.frame_url.endsWith('.mov') ? (
                            <div className="w-full h-full bg-zinc-800 flex flex-col items-center justify-center gap-1">
                              <span className="text-2xl">▶️</span>
                              <span className="text-[10px] text-zinc-400 text-center px-2 leading-tight truncate w-full">
                                {frame.frame_url.split('/').pop()}
                              </span>
                            </div>
                          ) : (
                            <img
                              src={`${API_BASE}${frame.frame_url}`}
                              alt={`Meme ${frame.sort_order + 1}`}
                              className="w-full h-full object-contain"
                            />
                          )}
                          <div className="absolute inset-0 bg-black/60 opacity-0 group-hover:opacity-100 transition-opacity flex flex-col items-center justify-center gap-1 pointer-events-none">
                            <span className="text-2xl">🔄</span>
                            <span className="text-white text-xs font-medium">Vervangen</span>
                          </div>
                        </div>
                      ) : (
                        // Empty meme placeholder
                        <div className="w-full h-full bg-zinc-900 border-2 border-dashed border-zinc-600 hover:border-amber-500/70 hover:bg-zinc-800/60 transition-colors flex flex-col items-center justify-center gap-2">
                          <span className="text-3xl select-none">🎭</span>
                          <span className="text-xs text-zinc-500 text-center px-3 leading-tight">
                            Klik om<br/>meme te kiezen
                          </span>
                        </div>
                      )}
                    </div>
                  ) : frame.frame_type === 'app_ad' ? (
                    // App Ad slot — user uploads their own promotional image
                    <div
                      className="w-full aspect-[9/16] cursor-pointer"
                      onClick={(e) => { e.stopPropagation(); setLibrarySlideId(frame.id) }}
                      title="Klik om jouw app-promotie afbeelding toe te voegen"
                    >
                      {frame.frame_url ? (
                        <div className="relative w-full h-full group bg-black">
                          <img
                            src={`${API_BASE}${frame.frame_url}`}
                            alt={`App Ad ${frame.sort_order + 1}`}
                            className="w-full h-full object-contain"
                          />
                          <div className="absolute inset-0 bg-black/60 opacity-0 group-hover:opacity-100 transition-opacity flex flex-col items-center justify-center gap-1 pointer-events-none">
                            <span className="text-2xl">🔄</span>
                            <span className="text-white text-xs font-medium">Vervangen</span>
                          </div>
                        </div>
                      ) : (
                        <div className="w-full h-full bg-zinc-900 border-2 border-dashed border-green-600/60 hover:border-green-500/80 hover:bg-zinc-800/60 transition-colors flex flex-col items-center justify-center gap-2">
                          <span className="text-3xl select-none">📱</span>
                          <span className="text-xs text-zinc-500 text-center px-3 leading-tight">
                            Klik om jouw<br/>app afbeelding<br/>toe te voegen
                          </span>
                        </div>
                      )}
                    </div>
                  ) : frame.frame_url ? (
                    <img
                      src={`${API_BASE}${frame.frame_url}`}
                      alt={`Frame ${frame.sort_order + 1}`}
                      className="w-full aspect-[9/16] object-cover"
                    />
                  ) : (
                    <div className="w-full aspect-[9/16] bg-zinc-800 flex items-center justify-center text-zinc-500 text-xs">
                      No image
                    </div>
                  )}

                  {/* Frame number */}
                  <div className="absolute top-1.5 left-1.5 bg-black/70 text-white text-xs px-1.5 py-0.5 rounded pointer-events-none">
                    {frame.sort_order + 1}
                  </div>

                  {/* Frame type badge
                      DM frames: read-only label
                      Meme / app_ad frames: click to reclassify */}
                  {frame.frame_type === 'dm' ? (
                    <span className="absolute bottom-1.5 left-1.5 text-xs px-1.5 py-0.5 rounded font-medium bg-blue-600/90 text-white pointer-events-none">
                      DM
                    </span>
                  ) : frame.frame_type === 'app_ad' ? (
                    <button
                      className="absolute bottom-1.5 left-1.5 text-xs px-1.5 py-0.5 rounded font-medium bg-green-600/90 text-white hover:bg-green-500 transition-colors"
                      onClick={(e) => { e.stopPropagation(); toggleFrameType(frame.id, 'app_ad') }}
                      title="App Ad slot (1 sec) — klik om type te wisselen"
                    >
                      App Ad ↺
                    </button>
                  ) : (
                    <button
                      className="absolute bottom-1.5 left-1.5 text-xs px-1.5 py-0.5 rounded font-medium bg-amber-500/90 text-black hover:bg-red-500/90 hover:text-white transition-colors max-w-[90%] truncate"
                      onClick={(e) => { e.stopPropagation(); toggleFrameType(frame.id, 'meme') }}
                      title="Verkeerd geclassificeerd? Klik om naar DM te zetten"
                    >
                      {frame.meme_category ? `meme — ${frame.meme_category} ↺` : 'Meme ↺'}
                    </button>
                  )}

                  {/* Include/exclude checkbox */}
                  <div
                    className="absolute top-1.5 right-1.5"
                    onClick={(e) => { e.stopPropagation(); toggleActive(frame.id, frame.is_active) }}
                  >
                    <div className={`w-4 h-4 rounded border-2 flex items-center justify-center transition-colors ${
                      frame.is_active ? 'bg-blue-500 border-blue-500' : 'border-zinc-500 bg-transparent'
                    }`}>
                      {frame.is_active && (
                        <svg className="w-2.5 h-2.5 text-white" fill="none" viewBox="0 0 10 8">
                          <path d="M1 4l3 3 5-6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Preview pane */}
        {selectedFrame && (
          <div className="w-64 border-l border-zinc-800 flex flex-col items-center justify-center p-4 flex-shrink-0 gap-3">
            {selectedFrame.frame_url ? (
              <img
                src={`${API_BASE}${selectedFrame.frame_url}`}
                alt="Preview"
                className="max-h-[65%] max-w-full object-contain rounded-lg"
              />
            ) : selectedFrame.frame_type === 'meme' ? (
              <div
                className="w-full aspect-[9/16] max-h-[65%] bg-zinc-900 border-2 border-dashed border-zinc-600 rounded-lg flex flex-col items-center justify-center gap-2 cursor-pointer hover:border-amber-500/70 transition-colors"
                onClick={() => setLibrarySlideId(selectedFrame.id)}
              >
                <span className="text-4xl">🎭</span>
                <span className="text-xs text-zinc-500 text-center px-2">Klik om meme<br/>te kiezen</span>
              </div>
            ) : selectedFrame.frame_type === 'app_ad' ? (
              <div
                className="w-full aspect-[9/16] max-h-[65%] bg-zinc-900 border-2 border-dashed border-green-600/60 rounded-lg flex flex-col items-center justify-center gap-2 cursor-pointer hover:border-green-500/80 transition-colors"
                onClick={() => setLibrarySlideId(selectedFrame.id)}
              >
                <span className="text-4xl">📱</span>
                <span className="text-xs text-zinc-500 text-center px-2">Klik om jouw<br/>app afbeelding<br/>toe te voegen</span>
              </div>
            ) : null}

            <div className="text-center space-y-1.5 w-full">
              <p className="text-zinc-500 text-xs">Frame {selectedFrame.sort_order + 1}</p>

              {/* Type label + toggle (cycles dm → meme → app_ad → dm) */}
              <button
                className={`w-full text-xs px-3 py-1.5 rounded font-medium transition-colors ${
                  selectedFrame.frame_type === 'dm'
                    ? 'bg-blue-600/20 text-blue-400 hover:bg-blue-600/40'
                    : selectedFrame.frame_type === 'app_ad'
                    ? 'bg-green-600/20 text-green-400 hover:bg-green-600/40'
                    : 'bg-amber-500/20 text-amber-400 hover:bg-amber-500/40'
                }`}
                onClick={() => toggleFrameType(selectedFrame.id, selectedFrame.frame_type || 'dm')}
              >
                {selectedFrame.frame_type === 'dm'
                  ? '🔵 DM slide'
                  : selectedFrame.frame_type === 'app_ad'
                  ? '🟢 App Ad (1s)'
                  : selectedFrame.meme_category ? `🟡 Meme — ${selectedFrame.meme_category}` : '🟡 Meme'} — klik om te wisselen
              </button>

              {(selectedFrame.frame_type === 'meme' || selectedFrame.frame_type === 'app_ad') && (
                <button
                  className={`w-full text-xs px-3 py-1.5 rounded transition-colors ${
                    selectedFrame.frame_type === 'app_ad'
                      ? 'bg-green-600/20 hover:bg-green-600/40 text-green-300'
                      : 'bg-amber-600/20 hover:bg-amber-600/40 text-amber-300'
                  }`}
                  onClick={() => setLibrarySlideId(selectedFrame.id)}
                >
                  {selectedFrame.frame_url
                    ? '🔄 Vervangen'
                    : selectedFrame.frame_type === 'app_ad'
                    ? '📱 Voeg afbeelding toe'
                    : '🎭 Kies uit bibliotheek'}
                </button>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
