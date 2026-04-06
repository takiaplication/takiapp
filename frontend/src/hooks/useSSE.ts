import { useEffect, useRef, useState } from 'react'

interface SSEEvent {
  type: string
  progress: number
  message?: string
  result?: string
}

export function useSSE(jobId: string | null) {
  const [progress, setProgress] = useState(0)
  const [message, setMessage] = useState('')
  const [status, setStatus] = useState<'idle' | 'running' | 'completed' | 'error'>('idle')
  const [error, setError] = useState<string | null>(null)
  const sourceRef = useRef<EventSource | null>(null)

  useEffect(() => {
    if (!jobId) {
      setStatus('idle')
      return
    }

    setStatus('running')
    setProgress(0)
    setMessage('')
    setError(null)

    const source = new EventSource(`/api/jobs/${jobId}/stream`)
    sourceRef.current = source

    source.addEventListener('progress', (e) => {
      const data: SSEEvent = JSON.parse(e.data)
      setProgress(data.progress)
      setMessage(data.message || '')
    })

    source.addEventListener('completed', (_e) => {
      setProgress(1)
      setMessage('Done')
      setStatus('completed')
      source.close()
    })

    source.addEventListener('error', (e) => {
      try {
        const data: SSEEvent = JSON.parse((e as MessageEvent).data)
        setError(data.message || 'Unknown error')
      } catch {
        setError('Connection lost')
      }
      setStatus('error')
      source.close()
    })

    return () => {
      source.close()
    }
  }, [jobId])

  return { progress, message, status, error }
}
