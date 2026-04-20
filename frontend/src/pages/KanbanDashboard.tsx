import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  listProjects,
  submitPipeline,
  retryProject,
  reexportProject,
  deleteProject,
  regenerateProject,
  updateProjectViews,
} from '../api/projects'
import { getExportDownloadUrl } from '../api/projects'
import type { Project } from '../types/project'

// ── Column definitions ──────────────────────────────────────────────────────

const COLUMNS: {
  key: string
  label: string
  statuses: string[]
  accent: string
  dot: string
}[] = [
  {
    key: 'queue',
    label: 'Queue',
    statuses: ['queue', 'created'],
    accent: 'border-zinc-600',
    dot: 'bg-zinc-400',
  },
  {
    key: 'processing',
    label: 'Processing',
    statuses: ['processing', 'error'],
    accent: 'border-amber-500',
    dot: 'bg-amber-400',
  },
  {
    key: 'review',
    label: 'Review',
    statuses: ['review'],
    accent: 'border-blue-500',
    dot: 'bg-blue-400',
  },
  {
    key: 'approved',
    label: 'Approved',
    statuses: ['approved'],
    accent: 'border-violet-500',
    dot: 'bg-violet-400',
  },
  {
    key: 'library',
    label: 'Library',
    statuses: ['library'],
    accent: 'border-emerald-500',
    dot: 'bg-emerald-400',
  },
]

// ── Helpers ─────────────────────────────────────────────────────────────────

function truncateUrl(url: string | null, max = 40): string {
  if (!url) return '—'
  try {
    const u = new URL(url)
    const path = u.pathname + u.search
    return (u.hostname + path).length > max
      ? (u.hostname + path).slice(0, max) + '…'
      : u.hostname + path
  } catch {
    return url.length > max ? url.slice(0, max) + '…' : url
  }
}

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString('nl-NL', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  })
}

// ── Card ─────────────────────────────────────────────────────────────────────

function ProjectCard({
  project,
  onRefresh,
}: {
  project: Project
  onRefresh: () => void
}) {
  const navigate = useNavigate()
  const isError = project.status === 'error'
  const isReview = project.status === 'review'
  const isLibrary = project.status === 'library'
  const isProcessing = project.status === 'processing'

  async function handleRetry() {
    await retryProject(project.id)
    onRefresh()
  }

  async function handleReexport(e: React.MouseEvent) {
    e.stopPropagation()
    await reexportProject(project.id)
    onRefresh()
  }

  async function handleRegenerate(e: React.MouseEvent) {
    e.stopPropagation()
    if (!confirm(`Video opnieuw genereren voor "${project.name}"?\n\nDe bestaande Drive-link wordt vervangen door een nieuwe.`)) return
    try {
      await regenerateProject(project.id)
      onRefresh()
    } catch {
      alert('Regenereren mislukt.')
    }
  }

  async function handleViewsBlur(e: React.FocusEvent<HTMLInputElement>) {
    const raw = e.target.value
    const parsed = Math.max(0, parseInt(raw || '0', 10) || 0)
    if (parsed === project.views) return
    try {
      await updateProjectViews(project.id, parsed)
      onRefresh()
    } catch {
      // silent — next poll will correct the display
    }
  }

  async function handleDelete(e: React.MouseEvent) {
    e.stopPropagation()
    if (!confirm(`Project "${project.name}" verwijderen?`)) return
    await deleteProject(project.id)
    onRefresh()
  }

  function handleCardClick() {
    if (isLibrary) return          // library cards are read-only
    if (isReview || isProcessing || project.status === 'approved') {
      navigate(`/project/${project.id}`)
    }
  }

  const clickable = !isLibrary && (isReview || isProcessing || project.status === 'approved')

  return (
    <div
      onClick={handleCardClick}
      className={[
        'rounded-xl border p-4 flex flex-col gap-2 text-sm transition-all select-none',
        isError
          ? 'bg-red-950/60 border-red-700'
          : isReview
          ? 'bg-blue-950/60 border-blue-600 shadow-lg shadow-blue-900/30'
          : isLibrary
          ? 'bg-emerald-950/40 border-emerald-800'
          : 'bg-zinc-900 border-zinc-800',
        clickable ? 'cursor-pointer hover:brightness-110' : 'cursor-default',
      ].join(' ')}
    >
      {/* Header row: name + date + delete */}
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="font-semibold text-white leading-tight">{project.name}</p>
          <p className="text-xs text-zinc-500 mt-0.5">{fmtDate(project.created_at)}</p>
        </div>
        <button
          onClick={handleDelete}
          className="text-zinc-600 hover:text-red-400 text-xs transition-colors flex-shrink-0 mt-0.5"
          title="Verwijderen"
        >
          ✕
        </button>
      </div>

      {/* URL */}
      <p className="text-xs text-zinc-500 font-mono truncate" title={project.source_url ?? ''}>
        {truncateUrl(project.source_url)}
      </p>

      {/* Step / status line */}
      {isProcessing && project.pipeline_step && (
        <div className="flex items-center gap-2">
          <span className="inline-block w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse flex-shrink-0" />
          <span className="text-xs text-amber-300 truncate">{project.pipeline_step}</span>
        </div>
      )}

      {project.status === 'queue' && (
        <div className="flex items-center gap-2">
          <span className="inline-block w-1.5 h-1.5 rounded-full bg-zinc-400 flex-shrink-0" />
          <span className="text-xs text-zinc-400">Wachten op start…</span>
        </div>
      )}

      {isReview && (
        <div className="flex items-center gap-2">
          <span className="inline-block w-1.5 h-1.5 rounded-full bg-blue-400 flex-shrink-0" />
          <span className="text-xs text-blue-300 font-medium">Klik om te bekijken →</span>
        </div>
      )}

      {project.status === 'approved' && (
        <div className="flex flex-col gap-2">
          {project.pipeline_error ? (
            // Export failed — show error + red retry button (stays in Approved column)
            <>
              <div className="flex items-center gap-2">
                <span className="inline-block w-1.5 h-1.5 rounded-full bg-red-400 flex-shrink-0" />
                <span className="text-xs text-red-300 truncate">
                  {project.pipeline_step || 'Export mislukt'}
                </span>
              </div>
              <p className="text-xs text-red-400 font-mono line-clamp-2" title={project.pipeline_error}>
                {project.pipeline_error}
              </p>
              <button
                onClick={handleReexport}
                className="w-full text-xs font-medium py-1.5 px-3 rounded-lg bg-red-700
                           hover:bg-red-600 text-white transition-colors"
              >
                ↻ Export opnieuw proberen
              </button>
            </>
          ) : (
            // Export running normally — violet progress indicator + re-export fallback
            <>
              <div className="flex items-center gap-2">
                <span className="inline-block w-1.5 h-1.5 rounded-full bg-violet-400 animate-pulse flex-shrink-0" />
                <span className="text-xs text-violet-300 truncate">
                  {project.pipeline_step || 'Video exporteren…'}
                </span>
              </div>
              <button
                onClick={handleReexport}
                className="w-full text-xs font-medium py-1.5 px-3 rounded-lg bg-violet-800/60
                           hover:bg-violet-700 text-violet-200 transition-colors border border-violet-700/50"
              >
                🔄 Opnieuw exporteren
              </button>
            </>
          )}
        </div>
      )}

      {isLibrary && (
        <div className="mt-1 flex flex-col gap-1.5">
          {project.drive_url ? (
            <a
              href={project.drive_url}
              target="_blank"
              rel="noopener noreferrer"
              onClick={(e) => e.stopPropagation()}
              className="flex items-center justify-center gap-2 bg-emerald-700 hover:bg-emerald-600 text-white text-xs font-medium py-1.5 px-3 rounded-lg transition-colors"
            >
              <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="currentColor">
                <path d="M6.28 3l5.72 9.9L6.28 21H2l5.72-9.9L2 3h4.28zm4.44 0H22l-5.72 9.9L22 21h-4.28l-5.72-9.9L14.72 3z"/>
              </svg>
              Open in Drive
            </a>
          ) : (
            <a
              href={getExportDownloadUrl(project.id)}
              download
              onClick={(e) => e.stopPropagation()}
              className="flex items-center justify-center gap-2 bg-emerald-700 hover:bg-emerald-600 text-white text-xs font-medium py-1.5 px-3 rounded-lg transition-colors"
            >
              ↓ Download MP4
            </a>
          )}

          <button
            onClick={handleRegenerate}
            className="flex items-center justify-center gap-2 bg-blue-700/70 hover:bg-blue-600 text-white text-xs font-medium py-1.5 px-3 rounded-lg transition-colors border border-blue-600/50"
          >
            🔁 Regenereer video
          </button>

          <label
            className="flex items-center gap-2 text-xs text-zinc-400 mt-0.5"
            onClick={(e) => e.stopPropagation()}
          >
            <span>👁 Views</span>
            <input
              type="number"
              min={0}
              defaultValue={project.views}
              key={project.views /* reset when server value changes */}
              onBlur={handleViewsBlur}
              onClick={(e) => e.stopPropagation()}
              className="flex-1 bg-zinc-800 border border-zinc-700 rounded text-xs text-white px-2 py-1 text-right focus:outline-none focus:border-emerald-500"
            />
          </label>
        </div>
      )}

      {/* Error state */}
      {isError && (
        <div className="mt-1 flex flex-col gap-2">
          {project.pipeline_error && (
            <p className="text-xs text-red-400 font-mono line-clamp-2" title={project.pipeline_error}>
              {project.pipeline_error}
            </p>
          )}
          <button
            onClick={(e) => { e.stopPropagation(); handleRetry() }}
            className="bg-red-700 hover:bg-red-600 text-white text-xs font-medium py-1.5 px-3 rounded-lg transition-colors"
          >
            ↻ Opnieuw proberen
          </button>
        </div>
      )}
    </div>
  )
}

// ── Column ───────────────────────────────────────────────────────────────────

function KanbanColumn({
  label,
  accent,
  dot,
  projects,
  onRefresh,
}: {
  label: string
  accent: string
  dot: string
  projects: Project[]
  onRefresh: () => void
}) {
  return (
    <div className="flex flex-col w-72 flex-shrink-0 h-full">
      {/* Column header */}
      <div className={`flex items-center gap-2 mb-3 pb-2 border-b-2 ${accent}`}>
        <span className={`w-2 h-2 rounded-full ${dot}`} />
        <span className="font-semibold text-sm text-white">{label}</span>
        <span className="ml-auto text-xs text-zinc-500 bg-zinc-800 px-2 py-0.5 rounded-full">
          {projects.length}
        </span>
      </div>

      {/* Cards */}
      <div className="flex-1 overflow-y-auto space-y-3 pr-1">
        {projects.length === 0 && (
          <div className="text-xs text-zinc-600 text-center py-8">Leeg</div>
        )}
        {projects.map((p) => (
          <ProjectCard key={p.id} project={p} onRefresh={onRefresh} />
        ))}
      </div>
    </div>
  )
}

// ── Dashboard ────────────────────────────────────────────────────────────────

export default function KanbanDashboard() {
  const [projects, setProjects] = useState<Project[]>([])
  const [urlInput, setUrlInput] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState('')
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  async function refresh() {
    try {
      const data = await listProjects()
      setProjects(data)
    } catch {
      // silently ignore polling errors
    }
  }

  useEffect(() => {
    refresh()
    intervalRef.current = setInterval(refresh, 3000)
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current)
    }
  }, [])

  async function handleSubmit() {
    const urls = urlInput
      .split('\n')
      .map((u) => u.trim())
      .filter(Boolean)

    if (!urls.length) return
    if (urls.length > 10) {
      setSubmitError('Maximum 10 URLs tegelijk')
      return
    }

    setSubmitError('')
    setSubmitting(true)
    try {
      await submitPipeline(urls)
      setUrlInput('')
      await refresh()
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err)
      setSubmitError(msg)
    } finally {
      setSubmitting(false)
    }
  }

  // Build per-column project lists
  const columnProjects = COLUMNS.map((col) => ({
    ...col,
    items: projects.filter((p) => col.statuses.includes(p.status)),
  }))

  const hasActive = projects.some((p) =>
    ['queue', 'processing'].includes(p.status),
  )

  return (
    <div className="h-full flex flex-col bg-zinc-950 overflow-hidden">
      {/* ── URL input bar ─────────────────────────────────────────────── */}
      <div className="flex-shrink-0 border-b border-zinc-800 p-4 flex gap-3 items-start">
        <textarea
          value={urlInput}
          onChange={(e) => setUrlInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) handleSubmit()
          }}
          placeholder={
            'Plak 1–10 TikTok / Instagram / YouTube URLs (één per regel)…\n' +
            'Ctrl+Enter om te versturen'
          }
          rows={3}
          className="flex-1 bg-zinc-900 border border-zinc-700 rounded-lg px-4 py-3 text-sm
                     resize-none focus:outline-none focus:border-blue-500 transition-colors
                     placeholder:text-zinc-600 font-mono"
        />
        <div className="flex flex-col gap-2">
          <button
            onClick={handleSubmit}
            disabled={submitting || !urlInput.trim()}
            className="bg-blue-600 hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed
                       text-white px-5 py-2.5 rounded-lg text-sm font-medium transition-colors
                       whitespace-nowrap"
          >
            {submitting ? 'Bezig…' : '+ Toevoegen aan wachtrij'}
          </button>
          {hasActive && (
            <div className="flex items-center gap-1.5 text-xs text-amber-400 justify-center">
              <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
              Pipeline actief
            </div>
          )}
        </div>
      </div>

      {submitError && (
        <div className="flex-shrink-0 px-4 py-2 bg-red-950 border-b border-red-800 text-xs text-red-400">
          {submitError}
        </div>
      )}

      {/* ── Kanban board ──────────────────────────────────────────────── */}
      <div className="flex-1 flex overflow-hidden">
        <div className="flex gap-4 p-4 overflow-x-auto flex-1">
          {columnProjects.map((col) => (
            <KanbanColumn
              key={col.key}
              label={col.label}
              accent={col.accent}
              dot={col.dot}
              projects={col.items}
              onRefresh={refresh}
            />
          ))}
        </div>
      </div>
    </div>
  )
}
