import { useState, useEffect } from 'react'
import { useProjectStore } from '../../store/projectStore'
import * as api from '../../api/projects'
import { useJobProgress } from '../../hooks/useJobProgress'

interface Props {
  onNext: () => void
}

export default function ImportStep({ onNext }: Props) {
  const { currentProject } = useProjectStore()
  const [url, setUrl] = useState('')
  const [importStatus, setImportStatus] = useState<api.ImportStatus | null>(null)
  const downloadJob = useJobProgress()
  const extractJob = useJobProgress()

  useEffect(() => {
    if (!currentProject) return
    api.getImportStatus(currentProject.id).then(setImportStatus).catch(() => null)
  }, [currentProject])

  if (!currentProject) return null

  const handleDownload = async () => {
    if (!url.trim()) return
    const jobId = await api.importUrl(currentProject.id, url.trim())
    downloadJob.start(jobId)
  }

  const handleExtract = async () => {
    const jobId = await api.extractFrames(currentProject.id)
    extractJob.start(jobId)
    extractJob.state.status === 'completed' && setImportStatus(await api.getImportStatus(currentProject.id))
  }

  // Refresh status after download / extract completes
  useEffect(() => {
    if (downloadJob.state.status === 'completed' || extractJob.state.status === 'completed') {
      api.getImportStatus(currentProject.id).then(setImportStatus)
    }
  }, [downloadJob.state.status, extractJob.state.status, currentProject.id])

  const hasVideo = importStatus?.has_video
  const hasFrames = (importStatus?.frame_count ?? 0) > 0

  return (
    <div className="flex flex-col items-center justify-center h-full p-8 max-w-xl mx-auto space-y-6">
      <div className="text-center">
        <h2 className="text-xl font-semibold mb-1">Stage 1 — Import Video</h2>
        <p className="text-zinc-400 text-sm">Paste a TikTok, Instagram Reels, or YouTube Shorts URL</p>
      </div>

      {/* URL input */}
      <div className="w-full space-y-2">
        <div className="flex gap-2">
          <input
            type="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://www.tiktok.com/@user/video/..."
            className="flex-1 bg-zinc-900 border border-zinc-700 rounded px-3 py-2 text-sm focus:outline-none focus:border-blue-500"
          />
          <button
            onClick={handleDownload}
            disabled={!url.trim() || downloadJob.state.status === 'running'}
            className="bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white px-4 py-2 rounded text-sm font-medium transition-colors"
          >
            Download
          </button>
        </div>

        {/* Download progress */}
        {downloadJob.state.status === 'running' && (
          <ProgressBar progress={downloadJob.state.progress} label={downloadJob.state.message} />
        )}
        {downloadJob.state.status === 'error' && (
          <p className="text-red-400 text-xs">{downloadJob.state.error}</p>
        )}
        {downloadJob.state.status === 'completed' && (
          <p className="text-green-400 text-xs">Video downloaded successfully</p>
        )}
      </div>

      {/* Status badge */}
      {importStatus && (
        <div className="w-full bg-zinc-900 rounded-lg p-4 text-sm space-y-1">
          <div className="flex justify-between">
            <span className="text-zinc-400">Video</span>
            <span className={hasVideo ? 'text-green-400' : 'text-zinc-500'}>
              {hasVideo ? 'Ready' : 'Not downloaded'}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-zinc-400">Frames</span>
            <span className={hasFrames ? 'text-green-400' : 'text-zinc-500'}>
              {hasFrames ? `${importStatus.frame_count} slides` : 'Not extracted'}
            </span>
          </div>
          {importStatus.source_url && (
            <div className="flex justify-between gap-4">
              <span className="text-zinc-400 flex-shrink-0">Source</span>
              <span className="text-zinc-300 text-xs truncate">{importStatus.source_url}</span>
            </div>
          )}
        </div>
      )}

      {/* Extract frames */}
      {hasVideo && (
        <div className="w-full space-y-2">
          <button
            onClick={handleExtract}
            disabled={extractJob.state.status === 'running'}
            className="w-full bg-zinc-800 hover:bg-zinc-700 disabled:opacity-50 py-2.5 rounded text-sm font-medium transition-colors"
          >
            {hasFrames ? 'Re-extract Frames' : 'Extract Frames'}
          </button>
          {extractJob.state.status === 'running' && (
            <ProgressBar progress={extractJob.state.progress} label={extractJob.state.message} />
          )}
          {extractJob.state.status === 'error' && (
            <p className="text-red-400 text-xs">{extractJob.state.error}</p>
          )}
        </div>
      )}

      {/* Continue */}
      {hasFrames && (
        <button
          onClick={onNext}
          className="w-full bg-blue-600 hover:bg-blue-700 text-white py-2.5 rounded-lg text-sm font-medium transition-colors"
        >
          Continue to Frame Review →
        </button>
      )}
    </div>
  )
}

function ProgressBar({ progress, label }: { progress: number; label: string }) {
  return (
    <div className="space-y-1">
      <div className="h-1.5 bg-zinc-800 rounded-full overflow-hidden">
        <div
          className="h-full bg-blue-500 transition-all duration-300 rounded-full"
          style={{ width: `${Math.round(progress * 100)}%` }}
        />
      </div>
      <p className="text-xs text-zinc-400">{label}</p>
    </div>
  )
}
