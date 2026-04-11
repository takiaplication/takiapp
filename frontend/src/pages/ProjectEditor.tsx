import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useProjectStore } from '../store/projectStore'
import DMEditor from '../components/renderer/DMEditor'
import DMPreview from '../components/renderer/DMPreview'
import Storyboard from '../components/frames/Storyboard'
import ExportPanel from '../components/export/ExportPanel'
import ImportStep from '../components/import/ImportStep'
import FramesStep from '../components/frames/FramesStep'
import OcrStep from '../components/ocr/OcrStep'
import { approveProject } from '../api/projects'

type Step = 'import' | 'frames' | 'ocr' | 'editor' | 'export'

const STEPS: { key: Step; label: string }[] = [
  { key: 'import', label: '1 Import' },
  { key: 'frames', label: '2 Frames' },
  { key: 'ocr', label: '3 OCR' },
  { key: 'editor', label: '4 Editor' },
  { key: 'export', label: '5 Export' },
]

export default function ProjectEditor() {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const { currentProject, loadProject, loading } = useProjectStore()
  const [activeStep, setActiveStep] = useState<Step>('import')
  const [approving, setApproving] = useState(false)

  async function handleGoodToGo() {
    if (!projectId) return
    setApproving(true)
    try {
      await approveProject(projectId)
      navigate('/')
    } finally {
      setApproving(false)
    }
  }

  useEffect(() => {
    if (projectId) {
      loadProject(projectId)
    }
  }, [projectId, loadProject])

  // Auto-jump to editor when opening a project that already went through OCR
  useEffect(() => {
    if (!currentProject) return
    const s = currentProject.status
    if (s === 'review' || s === 'approved' || s === 'library') {
      setActiveStep('editor')
    }
  }, [currentProject?.status])

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full text-zinc-500">
        Loading project...
      </div>
    )
  }

  if (!currentProject) {
    return (
      <div className="flex items-center justify-center h-full text-zinc-500">
        Project not found
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col">
      {/* Top bar */}
      <div className="h-12 border-b border-zinc-800 flex items-center px-4 gap-4 flex-shrink-0">
        <button
          onClick={() => navigate('/')}
          className="text-zinc-400 hover:text-white text-sm transition-colors"
        >
          &larr; Back
        </button>
        <span className="text-sm font-medium truncate max-w-xs">{currentProject.name}</span>
        <div className="flex-1" />

        {/* "Good to go" — visible in editor step only */}
        {activeStep === 'editor' && (
          <button
            onClick={handleGoodToGo}
            disabled={approving}
            className="mr-3 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50
                       text-white text-xs font-semibold px-4 py-1.5 rounded-lg transition-colors"
          >
            {approving ? 'Bezig…' : '✓ Good to go'}
          </button>
        )}

        {/* Step tabs */}
        <div className="flex gap-0.5">
          {STEPS.map(({ key, label }) => (
            <button
              key={key}
              onClick={() => setActiveStep(key)}
              className={`px-3 py-1 rounded text-xs transition-colors ${
                activeStep === key
                  ? 'bg-zinc-800 text-white'
                  : 'text-zinc-500 hover:text-zinc-300'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Main content */}
      <div className="flex-1 overflow-hidden">
        {activeStep === 'import' && (
          <ImportStep onNext={() => setActiveStep('frames')} />
        )}

        {activeStep === 'frames' && (
          <FramesStep
            onNext={() => setActiveStep('ocr')}
            onBack={() => setActiveStep('import')}
          />
        )}

        {activeStep === 'ocr' && (
          <OcrStep
            onNext={() => setActiveStep('editor')}
            onBack={() => setActiveStep('frames')}
          />
        )}

        {activeStep === 'editor' && (
          <div className="h-full flex">
            <div className="w-1/2 border-r border-zinc-800 overflow-y-auto">
              <DMEditor />
            </div>
            <div className="w-1/2 flex items-center justify-center bg-zinc-950 p-4">
              <DMPreview />
            </div>
          </div>
        )}

        {activeStep === 'export' && (
          <ExportPanel />
        )}
      </div>

      {/* Bottom storyboard — visible in editor and export steps */}
      {(activeStep === 'editor' || activeStep === 'export') && <Storyboard />}
    </div>
  )
}
