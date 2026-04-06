import { useState, useEffect } from 'react'
import * as api from '../../api/projects'

interface Props {
  open: boolean
  onClose: () => void
}

export default function SettingsModal({ open, onClose }: Props) {
  const [key, setKey] = useState('')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    if (open) {
      api.getAppSettings().then((s) => setKey(s.openai_api_key))
      setSaved(false)
    }
  }, [open])

  if (!open) return null

  const handleSave = async () => {
    setSaving(true)
    try {
      await api.saveAppSettings({ openai_api_key: key.trim() })
      setSaved(true)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="bg-zinc-900 border border-zinc-700 rounded-xl w-full max-w-md p-6 space-y-5 shadow-2xl">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold">Instellingen</h2>
          <button onClick={onClose} className="text-zinc-500 hover:text-white text-xl leading-none">×</button>
        </div>

        {/* OpenAI key */}
        <div className="space-y-2">
          <label className="text-sm font-medium">OpenAI API-sleutel</label>
          <p className="text-xs text-zinc-400">
            Vereist voor vertaling (GPT-4o-mini). Sla je sleutel op in de DB — je hoeft de server niet te herstarten.
          </p>
          <input
            type="password"
            value={key}
            onChange={(e) => { setKey(e.target.value); setSaved(false) }}
            placeholder="sk-..."
            className="w-full bg-zinc-800 border border-zinc-600 rounded px-3 py-2 text-sm font-mono focus:outline-none focus:border-blue-500 transition-colors"
          />
          {key && (
            <p className="text-xs text-zinc-500">
              {key.startsWith('sk-') ? '✓ Ziet er geldig uit' : '⚠ Sleutels beginnen normaal met sk-'}
            </p>
          )}
        </div>

        <div className="flex justify-end gap-3 pt-1">
          <button onClick={onClose} className="text-zinc-400 hover:text-white text-sm px-4 py-2 rounded transition-colors">
            Annuleren
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-sm px-4 py-2 rounded transition-colors"
          >
            {saving ? 'Opslaan…' : saved ? '✓ Opgeslagen' : 'Opslaan'}
          </button>
        </div>
      </div>
    </div>
  )
}
