import { useProjectStore } from '../../store/projectStore'

export default function DMPreview() {
  const { previewUrl, previewRendering, activeSlideId } = useProjectStore()

  if (!activeSlideId) {
    return (
      <div className="text-zinc-500 text-sm">
        Select a slide to preview
      </div>
    )
  }

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
