interface Props {
  open: boolean
  onClose: () => void
}

export default function SettingsModal({ open, onClose }: Props) {
  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-zinc-900 border border-zinc-700 rounded-xl w-full max-w-md p-6 space-y-5 shadow-2xl">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold">Instellingen</h2>
          <button onClick={onClose} className="text-zinc-500 hover:text-white text-xl leading-none">×</button>
        </div>

        <div className="rounded-lg bg-zinc-800 border border-zinc-700 p-4 space-y-2">
          <p className="text-sm font-medium text-zinc-200">OpenAI API-sleutel</p>
          <p className="text-xs text-zinc-400">
            De sleutel wordt gelezen uit de{' '}
            <span className="font-mono text-zinc-300">OPENAI_API_KEY</span>{' '}
            omgevingsvariabele op Railway. Stel deze in via{' '}
            <span className="font-mono text-zinc-300">Railway → Variables</span>.
          </p>
        </div>

        <div className="flex justify-end pt-1">
          <button
            onClick={onClose}
            className="bg-zinc-700 hover:bg-zinc-600 text-white text-sm px-4 py-2 rounded transition-colors"
          >
            Sluiten
          </button>
        </div>
      </div>
    </div>
  )
}
