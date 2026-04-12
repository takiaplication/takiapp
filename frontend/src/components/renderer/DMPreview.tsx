import { useState } from 'react'
import { useProjectStore } from '../../store/projectStore'
import { rerenderAppad } from '../../api/projects'
import { API_BASE } from '../../api/config'

export default function DMPreview() {
  const { previewUrl, previewRendering, activeSlideId, slides, currentProject, updateSlideFrame } =
    useProjectStore()

  const [rerendering, setRerendering] = useState(false)
  const [rerenderError, setRerenderError] = useState<string | null>(null)
  // bump this to bust the <img> cache after a re-render
  const [cacheBust, setCacheBust] = useState(0)

  const activeSlide = slides.find((s) => s.id === activeSlideId)
  const isAppAd = activeSlide?.frame_type === 'app_ad'

  const appAdUrl =
    isAppAd && activeSlide?.frame_url
      ? `${API_BASE}${activeSlide.frame_url}${activeSlide.frame_url.includes('?') ? '&' : '?'}_t=${cacheBust}`
      : null

  async function handleRefresh() {
    if (!currentProject || !activeSlideId) return
    setRerendering(true)
    setRerenderError(null)
    try {
      const result = await rerenderAppad(currentProject.id, activeSlideId)
      updateSlideFrame(activeSlideId, result.frame_url, activeSlide?.hold_duration_ms ?? 3000)
      setCacheBust((n) => n + 1)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Onbekende fout'
      setRerenderError(msg)
    } finally {
      setRerendering(false)
    }
  }

  if (!activeSlideId) {
    return (
      <div className="text-zinc-500 text-sm">
        Select a slide to preview
      </div>
    )
  }

  // ── App-ad slide ──────────────────────────────────────────────────────────
  if (isAppAd) {
    return (
      <div className="flex flex-col items-center gap-4">
        {/* Square preview (1080×1080 scaled down) */}
        <div className="w-[300px] h-[300px] rounded-xl overflow-hidden shadow-2xl border border-zinc-700 bg-zinc-900 flex items-center justify-center relative">
          {rerendering && (
            <div className="absolute inset-0 flex items-center justify-center bg-black/60 z-10">
              <svg
                className="w-10 h-10 animate-spin text-green-400"
                xmlns="http://www.w3.org/2000/svg"
                fill="none"
                viewBox="0 0 24 24"
              >
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
              </svg>
            </div>
          )}
          {appAdUrl ? (
            <img
              key={cacheBust}
              src={appAdUrl}
              alt="App Ad Preview"
              className="w-full h-full object-contain"
            />
          ) : (
            <div className="text-zinc-500 text-xs text-center px-4">
              <p>📱 App ad</p>
              <p className="mt-1">Klik Refresh om te renderen</p>
            </div>
          )}
        </div>

        {/* Refresh button */}
        <button
          onClick={handleRefresh}
          disabled={rerendering}
          className="flex items-center gap-2 px-5 py-2 rounded-lg bg-green-700 hover:bg-green-600
                     disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-semibold
                     transition-colors shadow"
        >
          <span className={rerendering ? 'animate-spin inline-block' : ''}>🔄</span>
          {rerendering ? 'Bezig met renderen…' : 'Refresh app_ad'}
        </button>

        {rerenderError && (
          <p className="text-red-400 text-xs text-center max-w-[280px]">{rerenderError}</p>
        )}

        <p className="text-zinc-500 text-[11px] text-center max-w-[260px] leading-snug">
          Pas de omliggende DM-slides aan en klik Refresh om de app_ad opnieuw te renderen.
        </p>
      </div>
    )
  }

  // ── Regular DM / meme slide ───────────────────────────────────────────────
  return (
    <div className="relative">
      {/* Phone frame */}
      <div className="w-[270px] h-[480px] rounded-[32px] border-[3px] border-zinc-700 overflow-hidden shadow-2xl bg-black">
        {previewUrl ? (
          <img
            src={previewUrl}
            alt="DM Preview"
            className={`w-full h-full object-cover transition-opacity duration-300 ${previewRendering ? 'opacity-40' : 'opacity-100'}`}
          />
        ) : (
          <div className="w-full h-full flex flex-col items-center justify-center text-zinc-600 text-xs text-center px-4 gap-2">
            {previewRendering ? null : (
              <>
                <p>No preview yet</p>
                <p>Add messages to auto-render</p>
              </>
            )}
          </div>
        )}

        {/* Spinner overlay while rendering */}
        {previewRendering && (
          <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
            <svg
              className="w-10 h-10 animate-spin text-blue-400 opacity-90"
              xmlns="http://www.w3.org/2000/svg"
              fill="none"
              viewBox="0 0 24 24"
            >
              <circle
                className="opacity-25"
                cx="12" cy="12" r="10"
                stroke="currentColor"
                strokeWidth="3"
              />
              <path
                className="opacity-75"
                fill="currentColor"
                d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"
              />
            </svg>
          </div>
        )}
      </div>
    </div>
  )
}
