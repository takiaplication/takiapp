import { useState, useCallback, useRef } from 'react'

export interface JobState {
  jobId: string | null
  status: 'idle' | 'running' | 'completed' | 'error'
  progress: number
  message: string
  error: string | null
}

const API_BASE = 'http://localhost:8000/api'

export function useJobProgress() {
  const [state, setState] = useState<JobState>({
    jobId: null,
    status: 'idle',
    progress: 0,
    message: '',
    error: null,
  })
  const esRef = useRef<EventSource | null>(null)

  const start = useCallback((jobId: string) => {
    if (esRef.current) esRef.current.close()

    setState({ jobId, status: 'running', progress: 0, message: 'Starting...', error: null })

    const es = new EventSource(`${API_BASE}/jobs/${jobId}/stream`)
    esRef.current = es

    es.addEventListener('progress', (e) => {
      const data = JSON.parse(e.data)
      setState((s) => ({ ...s, progress: data.progress, message: data.message || '' }))
    })

    es.addEventListener('completed', (e) => {
      const data = JSON.parse(e.data)
      setState((s) => ({ ...s, status: 'completed', progress: 1, message: data.message || 'Done' }))
      es.close()
    })

    es.addEventListener('error', (e) => {
      const data = 'data' in e ? JSON.parse((e as MessageEvent).data) : {}
      setState((s) => ({ ...s, status: 'error', error: data.message || 'Unknown error' }))
      es.close()
    })

    es.onerror = () => {
      // SSE connection closed after stream ends — ignore if already completed
      setState((s) =>
        s.status === 'running'
          ? { ...s, status: 'error', error: 'Connection lost' }
          : s,
      )
      es.close()
    }
  }, [])

  const reset = useCallback(() => {
    if (esRef.current) esRef.current.close()
    setState({ jobId: null, status: 'idle', progress: 0, message: '', error: null })
  }, [])

  return { state, start, reset }
}
