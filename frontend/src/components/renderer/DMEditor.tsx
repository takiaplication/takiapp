import { useState, useRef } from 'react'
import { useProjectStore } from '../../store/projectStore'
import { uploadStoryImage, uploadMemeToSlide, useOriginalClip, saveClipToLibrary, MEME_CATEGORIES } from '../../api/projects'
import type { Message } from '../../types/project'
import type { MemeCategory } from '../../api/projects'
import MemeLibraryModal from '../frames/MemeLibraryModal'
import { API_BASE } from '../../api/config'

// ─── Meme slide panel ────────────────────────────────────────────────────────

type MemeTab = 'original' | 'custom'

function MemeSlidePanel({ slideId, projectId }: { slideId: string; projectId: string }) {
  const { slides, updateSlideMeme } = useProjectStore()
  const [showLibrary, setShowLibrary]   = useState(false)
  const [activeTab, setActiveTab]       = useState<MemeTab>('original')
  const [loadingOriginal, setLoadingOriginal] = useState(false)
  const [savingToLib, setSavingToLib]   = useState(false)
  const [savedToLib, setSavedToLib]     = useState(false)

  const slide             = slides.find((s) => s.id === slideId)
  const hasExtracted      = !!slide?.extracted_clip_url
  const hasAssigned       = !!slide?.frame_url
  const isAssignedVideo   = slide?.frame_url?.match(/\.(mp4|mov|webm)$/i)

  const handleAssigned = (frameUrl: string, holdMs: number, _category: MemeCategory) => {
    updateSlideMeme(slideId, frameUrl, holdMs)
    setShowLibrary(false)
  }

  const handleUseOriginal = async () => {
    if (!slide?.extracted_clip_url) return
    setLoadingOriginal(true)
    try {
      const result = await useOriginalClip(projectId, slideId)
      updateSlideMeme(slideId, result.frame_url, result.hold_duration_ms)
    } finally {
      setLoadingOriginal(false)
    }
  }

  const handleSaveToLibrary = async () => {
    setSavingToLib(true)
    try {
      await saveClipToLibrary(projectId, slideId)
      setSavedToLib(true)
    } finally {
      setSavingToLib(false)
    }
  }

  return (
    <div className="p-4 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="bg-amber-500/20 text-amber-400 text-xs font-bold px-2 py-0.5 rounded border border-amber-500/30">
            🎭 MEME SLIDE
          </span>
          {slide?.meme_category && (() => {
            const cat = MEME_CATEGORIES.find((c) => c.id === slide.meme_category)
            return cat ? (
              <span className="bg-zinc-800 text-zinc-300 text-xs px-2 py-0.5 rounded border border-zinc-700">
                {cat.emoji} {cat.label}
              </span>
            ) : null
          })()}
        </div>
        {hasExtracted && (
          <button
            onClick={handleSaveToLibrary}
            disabled={savingToLib || savedToLib}
            className="text-xs px-2.5 py-1 rounded bg-zinc-800 hover:bg-zinc-700 disabled:opacity-50 transition-colors text-zinc-300"
            title="Clip opslaan in de gedeelde meme-bibliotheek"
          >
            {savedToLib ? '✅ Opgeslagen' : savingToLib ? '⏳ Opslaan…' : '📥 Sla op in bibliotheek'}
          </button>
        )}
      </div>

      {/* Tabs — only show if an extracted clip exists */}
      {hasExtracted && (
        <div className="flex rounded-lg overflow-hidden border border-zinc-700 text-sm">
          <button
            onClick={() => setActiveTab('original')}
            className={`flex-1 py-1.5 font-medium transition-colors ${
              activeTab === 'original'
                ? 'bg-amber-600/30 text-amber-300'
                : 'bg-zinc-900 text-zinc-500 hover:text-zinc-300'
            }`}
          >
            🎬 Originele meme
          </button>
          <button
            onClick={() => setActiveTab('custom')}
            className={`flex-1 py-1.5 font-medium transition-colors ${
              activeTab === 'custom'
                ? 'bg-zinc-700 text-white'
                : 'bg-zinc-900 text-zinc-500 hover:text-zinc-300'
            }`}
          >
            🗂️ Eigen meme
          </button>
        </div>
      )}

      {/* ── Tab: Original extracted clip ── */}
      {(!hasExtracted || activeTab === 'original') && hasExtracted && (
        <div className="space-y-3">
          {/* Video preview */}
          <div className="w-full aspect-[9/16] bg-black rounded-lg overflow-hidden border border-zinc-800 flex items-center justify-center max-h-64">
            <video
              key={slide?.extracted_clip_url}
              src={`${API_BASE}${slide?.extracted_clip_url}`}
              controls
              muted
              loop
              className="w-full h-full object-contain"
            />
          </div>

          <button
            onClick={handleUseOriginal}
            disabled={loadingOriginal}
            className="w-full bg-amber-600 hover:bg-amber-500 disabled:opacity-50 text-black font-semibold text-sm py-2.5 rounded transition-colors"
          >
            {loadingOriginal ? '⏳ Laden…' : '✅ Gebruik originele meme'}
          </button>

          <p className="text-zinc-600 text-xs text-center">
            Auto-uitgeknipte clip uit het bronvideo
          </p>
        </div>
      )}

      {/* ── Tab: Custom / library ── */}
      {(!hasExtracted || activeTab === 'custom') && (
        <div className="space-y-3">
          {/* Preview of currently assigned meme */}
          <div className="w-full aspect-[9/16] bg-black rounded-lg overflow-hidden border border-zinc-800 flex items-center justify-center max-h-64">
            {!hasAssigned ? (
              <div className="flex flex-col items-center gap-3 text-zinc-600">
                <span className="text-5xl">🎭</span>
                <p className="text-sm text-center px-4">
                  Kies een meme uit de bibliotheek
                </p>
              </div>
            ) : isAssignedVideo ? (
              <video
                key={slide?.frame_url}
                src={`${API_BASE}${slide?.frame_url}`}
                controls
                muted
                loop
                className="w-full h-full object-contain"
              />
            ) : (
              <img
                src={`${API_BASE}${slide?.frame_url}`}
                alt="Assigned meme"
                className="w-full h-full object-contain"
              />
            )}
          </div>

          <button
            onClick={() => setShowLibrary(true)}
            className="w-full bg-amber-600 hover:bg-amber-500 text-black font-semibold text-sm py-2.5 rounded transition-colors"
          >
            {hasAssigned ? '🔄 Andere meme kiezen' : '➕ Meme toevoegen uit bibliotheek'}
          </button>

          {hasAssigned && (
            <p className="text-zinc-600 text-xs text-center">
              {isAssignedVideo
                ? 'De video speelt volledig af in de export'
                : 'Afbeelding wordt 1,5 seconden getoond'}
            </p>
          )}
        </div>
      )}

      {showLibrary && (
        <MemeLibraryModal
          projectId={projectId}
          slideId={slideId}
          initialCategory={(slide?.meme_category as MemeCategory) ?? undefined}
          onAssigned={handleAssigned}
          onClose={() => setShowLibrary(false)}
        />
      )}
    </div>
  )
}

// ─── App Ad slide panel ──────────────────────────────────────────────────────

function AppAdSlidePanel({ slideId, projectId }: { slideId: string; projectId: string }) {
  const { slides, updateSlideMeme } = useProjectStore()
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const [uploading, setUploading] = useState(false)

  const slide = slides.find((s) => s.id === slideId)
  const hasImage = !!slide?.frame_url

  const handleUpload = async (file: File) => {
    setUploading(true)
    try {
      const result = await uploadMemeToSlide(projectId, slideId, file)
      updateSlideMeme(slideId, result.frame_url, slide?.hold_duration_ms ?? 1000)
    } finally {
      setUploading(false)
    }
  }

  return (
    <div className="p-4 space-y-4">
      {/* Header */}
      <div className="flex items-center gap-2">
        <span className="bg-green-600/20 text-green-400 text-xs font-bold px-2 py-0.5 rounded border border-green-600/30">
          📱 APP AD
        </span>
        <span className="text-zinc-500 text-xs">
          {hasImage ? 'Afbeelding toegevoegd' : 'Nog geen afbeelding'}
        </span>
      </div>

      {/* Preview */}
      <div
        className="w-full aspect-[9/16] bg-black rounded-lg overflow-hidden border border-zinc-800 flex items-center justify-center max-h-64 cursor-pointer relative group"
        onClick={() => fileInputRef.current?.click()}
      >
        {hasImage ? (
          <>
            <img
              src={`http://localhost:8000${slide?.frame_url}`}
              alt="App Ad"
              className="w-full h-full object-contain"
            />
            <div className="absolute inset-0 bg-black/60 opacity-0 group-hover:opacity-100 transition-opacity flex flex-col items-center justify-center gap-1 pointer-events-none">
              <span className="text-2xl">🔄</span>
              <span className="text-white text-xs font-medium">Vervangen</span>
            </div>
          </>
        ) : (
          <div className="flex flex-col items-center gap-3 text-zinc-600">
            <span className="text-5xl">📱</span>
            <p className="text-sm text-center px-4 text-zinc-500">
              Klik om jouw app-afbeelding<br />te uploaden
            </p>
          </div>
        )}
      </div>

      {/* Upload button */}
      <button
        onClick={() => fileInputRef.current?.click()}
        disabled={uploading}
        className="w-full bg-green-700 hover:bg-green-600 disabled:opacity-50 text-white font-semibold text-sm py-2.5 rounded transition-colors"
      >
        {uploading ? '⏳ Uploading…' : hasImage ? '🔄 Andere afbeelding' : '📤 Afbeelding uploaden'}
      </button>

      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (file) handleUpload(file)
          e.target.value = ''
        }}
      />

      <p className="text-zinc-600 text-xs text-center">
        Wordt 1 seconde getoond in de video
      </p>
    </div>
  )
}

// ─── DM message editor ───────────────────────────────────────────────────────

export default function DMEditor() {
  const { activeSlideId, currentProject, slides, messages, settings, setMessages, updateSettings } = useProjectStore()
  const storyInputRefs = useRef<Record<number, HTMLInputElement | null>>({})

  if (!activeSlideId || !currentProject) {
    return (
      <div className="flex items-center justify-center h-full text-zinc-500 text-sm">
        Selecteer een slide om te bewerken
      </div>
    )
  }

  // Route to the correct panel based on frame_type
  const activeSlide = slides.find((s) => s.id === activeSlideId)
  if (activeSlide?.frame_type === 'meme') {
    return <MemeSlidePanel slideId={activeSlideId} projectId={currentProject.id} />
  }
  if (activeSlide?.frame_type === 'app_ad') {
    return <AppAdSlidePanel slideId={activeSlideId} projectId={currentProject.id} />
  }

  // ── DM slide editor ──────────────────────────────────────────────────────

  const addMessage = (sender: 'self' | 'other') => {
    const newMsg: Message = {
      id: `temp-${Date.now()}`,
      slide_id: activeSlideId,
      sort_order: messages.length,
      sender,
      text: '',
      message_type: 'text',
      show_timestamp: false,
      timestamp_text: null,
      read_receipt: null,
      emoji_reaction: null,
      story_image_path: null,
      story_reply_label: null,
      content_hash: null,
      story_group_id: null,
    }
    setMessages([...messages, newMsg])
  }

  const addStoryReply = (sender: 'self' | 'other') => {
    const label = sender === 'self' ? 'You replied to their story' : 'Replied to your story'
    const newMsg: Message = {
      id: `temp-${Date.now()}`,
      slide_id: activeSlideId,
      sort_order: messages.length,
      sender,
      text: '',
      message_type: 'story_reply',
      show_timestamp: false,
      timestamp_text: null,
      read_receipt: null,
      emoji_reaction: null,
      story_image_path: null,
      story_reply_label: label,
      content_hash: null,
      story_group_id: null,
    }
    setMessages([...messages, newMsg])
  }

  const updateMessage = (index: number, field: keyof Message, value: string | boolean | null) => {
    const updated = [...messages]
    updated[index] = { ...updated[index], [field]: value }
    setMessages(updated)
  }

  const removeMessage = (index: number) => {
    setMessages(messages.filter((_, i) => i !== index))
  }

  const handleStoryImageUpload = async (index: number, file: File) => {
    const path = await uploadStoryImage(currentProject.id, file)
    updateMessage(index, 'story_image_path', path)
  }

  return (
    <div className="p-4 space-y-4">
      {/* Contact settings */}
      <div className="space-y-2">
        <h3 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">Contact</h3>
        <div className="flex gap-2 items-center">
          <input
            type="text"
            value={settings?.other_username || ''}
            onChange={(e) => updateSettings({ other_username: e.target.value })}
            placeholder="Username"
            className="flex-1 bg-zinc-900 border border-zinc-700 rounded px-3 py-1.5 text-sm focus:outline-none focus:border-blue-500"
          />
          <label className="flex items-center gap-1.5 text-sm whitespace-nowrap">
            <input
              type="checkbox"
              checked={settings?.other_verified || false}
              onChange={(e) => updateSettings({ other_verified: e.target.checked })}
            />
            Verified
          </label>
          <select
            value={settings?.theme || 'dark'}
            onChange={(e) => updateSettings({ theme: e.target.value as 'dark' | 'light' })}
            className="bg-zinc-900 border border-zinc-700 rounded px-2 py-1.5 text-sm"
          >
            <option value="dark">Dark</option>
            <option value="light">Light</option>
          </select>
        </div>
      </div>

      {/* Messages */}
      <div className="space-y-2">
        <h3 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">Messages</h3>

        {messages.map((msg, i) => (
          <div key={msg.id} className="flex gap-2 items-start group">
            <button
              onClick={() => updateMessage(i, 'sender', msg.sender === 'self' ? 'other' : 'self')}
              className={`mt-1 w-8 h-8 rounded-full flex-shrink-0 text-xs font-bold flex items-center justify-center transition-colors ${
                msg.sender === 'self' ? 'bg-blue-600 text-white' : 'bg-zinc-700 text-zinc-300'
              }`}
              title="Click to toggle sender"
            >
              {msg.sender === 'self' ? 'Y' : 'O'}
            </button>

            <div className="flex-1 min-w-0 space-y-1.5">
              {msg.message_type === 'story_reply' ? (
                <div className="p-2.5 bg-zinc-900 rounded-lg border border-purple-900/50 space-y-2">
                  <span className="text-xs text-purple-400 font-medium">Story Reply</span>
                  <input
                    type="text"
                    value={msg.story_reply_label || ''}
                    onChange={(e) => updateMessage(i, 'story_reply_label', e.target.value || null)}
                    placeholder="e.g. You replied to their story"
                    className="w-full bg-zinc-800 border border-zinc-600 rounded px-2 py-1 text-xs focus:outline-none focus:border-purple-500"
                  />
                  <div className="flex items-center gap-2">
                    <span className={`text-xs flex-1 truncate ${msg.story_image_path ? 'text-green-400' : 'text-zinc-500'}`}>
                      {msg.story_image_path ? 'Story image uploaded' : 'No story image yet'}
                    </span>
                    <button
                      onClick={() => storyInputRefs.current[i]?.click()}
                      className="text-xs bg-zinc-700 hover:bg-zinc-600 px-2.5 py-1 rounded transition-colors flex-shrink-0"
                    >
                      {msg.story_image_path ? 'Change' : 'Upload Image'}
                    </button>
                    <input
                      ref={(el) => { storyInputRefs.current[i] = el }}
                      type="file"
                      accept="image/*"
                      className="hidden"
                      onChange={(e) => {
                        const file = e.target.files?.[0]
                        if (file) handleStoryImageUpload(i, file)
                      }}
                    />
                  </div>
                  <input
                    type="text"
                    value={msg.text}
                    onChange={(e) => updateMessage(i, 'text', e.target.value)}
                    placeholder="Reply text (optional)"
                    className="w-full bg-zinc-800 border border-zinc-600 rounded px-2 py-1 text-xs focus:outline-none focus:border-purple-500"
                  />
                </div>
              ) : (
                <textarea
                  value={msg.text}
                  onChange={(e) => updateMessage(i, 'text', e.target.value)}
                  placeholder="Type message..."
                  rows={1}
                  className="w-full bg-zinc-900 border border-zinc-700 rounded px-3 py-1.5 text-sm focus:outline-none focus:border-blue-500 resize-none"
                  onInput={(e) => {
                    const t = e.target as HTMLTextAreaElement
                    t.style.height = 'auto'
                    t.style.height = t.scrollHeight + 'px'
                  }}
                />
              )}

              <div className="flex flex-wrap gap-2 text-xs">
                <label className="flex items-center gap-1">
                  <input
                    type="checkbox"
                    checked={msg.show_timestamp}
                    onChange={(e) => updateMessage(i, 'show_timestamp', e.target.checked)}
                    className="w-3 h-3"
                  />
                  <span className="text-zinc-500">Timestamp</span>
                </label>
                {msg.show_timestamp && (
                  <input
                    type="text"
                    value={msg.timestamp_text || ''}
                    onChange={(e) => updateMessage(i, 'timestamp_text', e.target.value || null)}
                    placeholder="Today 2:34 PM"
                    className="bg-zinc-900 border border-zinc-700 rounded px-2 py-0.5 w-36"
                  />
                )}
                <input
                  type="text"
                  value={msg.read_receipt || ''}
                  onChange={(e) => updateMessage(i, 'read_receipt', e.target.value || null)}
                  placeholder="Seen"
                  className="bg-zinc-900 border border-zinc-700 rounded px-2 py-0.5 w-20"
                />
                <input
                  type="text"
                  value={msg.emoji_reaction || ''}
                  onChange={(e) => updateMessage(i, 'emoji_reaction', e.target.value || null)}
                  placeholder="❤️"
                  className="bg-zinc-900 border border-zinc-700 rounded px-2 py-0.5 w-14"
                />
              </div>
            </div>

            <button
              onClick={() => removeMessage(i)}
              className="mt-1 text-zinc-600 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity text-xl leading-none"
            >
              ×
            </button>
          </div>
        ))}
      </div>

      {/* Add buttons */}
      <div className="grid grid-cols-2 gap-2">
        <button onClick={() => addMessage('other')} className="bg-zinc-800 hover:bg-zinc-700 text-sm py-2 rounded transition-colors">
          + Received
        </button>
        <button onClick={() => addMessage('self')} className="bg-blue-600/20 hover:bg-blue-600/30 text-blue-400 text-sm py-2 rounded transition-colors">
          + Sent
        </button>
        <button onClick={() => addStoryReply('self')} className="col-span-2 bg-purple-900/30 hover:bg-purple-900/50 text-purple-400 text-sm py-2 rounded transition-colors">
          + Story Reply (sent)
        </button>
      </div>
    </div>
  )
}
