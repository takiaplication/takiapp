import { useProjectStore } from '../../store/projectStore'
import * as api from '../../api/projects'
import { useJobProgress } from '../../hooks/useJobProgress'

interface Props {
  onNext: () => void
  onBack: () => void
}

export default function OcrStep({ onNext, onBack }: Props) {
  const { currentProject, loadProject } = useProjectStore()
  const ocrJob = useJobProgress()

  if (!currentProject) return null

  const handleRunOcr = async () => {
    const jobId = await api.runOcr(currentProject.id)
    ocrJob.start(jobId)
  }

  const handleContinue = async () => {
    await loadProject(currentProject.id)
    onNext()
  }

  return (
    <div className="flex flex-col items-center justify-center h-full p-8 max-w-xl mx-auto space-y-6">
      <div className="text-center">
        <h2 className="text-xl font-semibold mb-1">Stage 3 — OCR & Vertaling</h2>
        <p className="text-zinc-400 text-sm">
          Leest tekst uit DM-frames via OCR, vertaalt automatisch naar <span className="text-white font-medium">Nederlands</span> via GPT-4o-mini.
          Meme-frames worden overgeslagen en ongewijzigd ingevoegd.
        </p>
      </div>

      {/* Run button */}
      <button
        onClick={handleRunOcr}
        disabled={ocrJob.state.status === 'running'}
        className="w-full bg-purple-700 hover:bg-purple-600 disabled:opacity-50 text-white py-2.5 rounded-lg text-sm font-medium transition-colors"
      >
        {ocrJob.state.status === 'running' ? 'Bezig met OCR…' : 'Start OCR & Vertaling'}
      </button>

      {/* Progress */}
      {ocrJob.state.status === 'running' && (
        <div className="w-full space-y-1">
          <div className="h-1.5 bg-zinc-800 rounded-full overflow-hidden">
            <div
              className="h-full bg-purple-500 transition-all duration-300 rounded-full"
              style={{ width: `${Math.round(ocrJob.state.progress * 100)}%` }}
            />
          </div>
          <p className="text-xs text-zinc-400">{ocrJob.state.message}</p>
        </div>
      )}

      {ocrJob.state.status === 'error' && (
        <p className="text-red-400 text-sm">{ocrJob.state.error}</p>
      )}

      {ocrJob.state.status === 'completed' && (
        <div className="w-full space-y-3">
          <p className="text-green-400 text-sm text-center">✓ OCR voltooid — berichten ingevuld per slide</p>
          <button
            onClick={handleContinue}
            className="w-full bg-blue-600 hover:bg-blue-700 text-white py-2.5 rounded-lg text-sm font-medium transition-colors"
          >
            Verder naar DM Editor →
          </button>
        </div>
      )}

      {ocrJob.state.status !== 'completed' && (
        <button
          onClick={handleContinue}
          className="text-zinc-500 hover:text-zinc-300 text-sm transition-colors"
        >
          Overslaan — ga naar DM Editor zonder OCR
        </button>
      )}

      <button onClick={onBack} className="text-zinc-500 hover:text-zinc-300 text-sm transition-colors">
        ← Terug naar Frames
      </button>
    </div>
  )
}
