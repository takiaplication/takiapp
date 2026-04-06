import { useState } from 'react'
import { useProjectStore } from '../../store/projectStore'
import { useSSE } from '../../hooks/useSSE'
import * as projectsApi from '../../api/projects'

export default function ExportPanel() {
  const { currentProject, settings, updateSettings } = useProjectStore()
  const [exportJobId, setExportJobId] = useState<string | null>(null)

  const exportSSE = useSSE(exportJobId)

  if (!currentProject) return null

  const handleExport = async () => {
    const jobId = await projectsApi.exportVideo(currentProject.id)
    setExportJobId(jobId)
  }

  return (
    <div className="max-w-xl mx-auto p-8 space-y-6">
      <h2 className="text-xl font-bold">Export Video</h2>

      {/* Settings */}
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-xs text-zinc-500 mb-1">Transition</label>
            <select
              value={settings?.transition_type || 'crossfade'}
              onChange={(e) => updateSettings({ transition_type: e.target.value })}
              className="w-full bg-zinc-900 border border-zinc-700 rounded px-3 py-2 text-sm"
            >
              <option value="crossfade">Crossfade</option>
              <option value="cut">Cut</option>
            </select>
          </div>
          <div>
            <label className="block text-xs text-zinc-500 mb-1">Transition Duration (ms)</label>
            <input
              type="number"
              value={settings?.transition_duration_ms || 300}
              onChange={(e) => updateSettings({ transition_duration_ms: parseInt(e.target.value) || 300 })}
              className="w-full bg-zinc-900 border border-zinc-700 rounded px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label className="block text-xs text-zinc-500 mb-1">Hold Duration (ms)</label>
            <input
              type="number"
              value={settings?.default_hold_duration_ms || 3000}
              onChange={(e) => updateSettings({ default_hold_duration_ms: parseInt(e.target.value) || 3000 })}
              className="w-full bg-zinc-900 border border-zinc-700 rounded px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label className="block text-xs text-zinc-500 mb-1">FPS</label>
            <input
              type="number"
              value={settings?.output_fps || 30}
              onChange={(e) => updateSettings({ output_fps: parseInt(e.target.value) || 30 })}
              className="w-full bg-zinc-900 border border-zinc-700 rounded px-3 py-2 text-sm"
            />
          </div>
        </div>

        <div>
          <label className="block text-xs text-zinc-500 mb-1">Music Volume ({Math.round((settings?.music_volume || 0.3) * 100)}%)</label>
          <input
            type="range"
            min="0"
            max="1"
            step="0.05"
            value={settings?.music_volume || 0.3}
            onChange={(e) => updateSettings({ music_volume: parseFloat(e.target.value) })}
            className="w-full"
          />
        </div>
      </div>

      {/* Progress */}
      {exportJobId && exportSSE.status !== 'idle' && (
        <div className="space-y-2">
          <div className="flex justify-between text-sm">
            <span className="text-zinc-400">{exportSSE.message}</span>
            <span className="text-zinc-500">{Math.round(exportSSE.progress * 100)}%</span>
          </div>
          <div className="w-full bg-zinc-800 rounded-full h-2">
            <div
              className={`h-2 rounded-full transition-all ${
                exportSSE.status === 'error' ? 'bg-red-500' : exportSSE.status === 'completed' ? 'bg-green-500' : 'bg-blue-500'
              }`}
              style={{ width: `${exportSSE.progress * 100}%` }}
            />
          </div>
          {exportSSE.error && (
            <p className="text-red-400 text-sm">{exportSSE.error}</p>
          )}
        </div>
      )}

      {/* Export button */}
      <button
        onClick={handleExport}
        disabled={exportSSE.status === 'running'}
        className="w-full bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white py-3 rounded-lg text-sm font-medium transition-colors"
      >
        {exportSSE.status === 'running' ? 'Exporting…' : 'Export Video'}
      </button>

      {/* Download */}
      {exportSSE.status === 'completed' && (
        <a
          href={projectsApi.getExportDownloadUrl(currentProject.id)}
          download
          className="block text-center bg-green-600 hover:bg-green-700 text-white py-3 rounded-lg text-sm font-medium transition-colors"
        >
          ↓ Download Video
        </a>
      )}
    </div>
  )
}
