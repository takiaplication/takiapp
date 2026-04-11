import api from './client'
import type { Project, Slide, Message, RenderSettings } from '../types/project'

export async function listProjects(): Promise<Project[]> {
  const res = await api.get('/projects')
  return res.data
}

export async function createProject(name: string): Promise<Project> {
  const res = await api.post('/projects', { name })
  return res.data
}

export async function getProject(id: string): Promise<Project> {
  const res = await api.get(`/projects/${id}`)
  return res.data
}

export async function deleteProject(id: string): Promise<void> {
  await api.delete(`/projects/${id}`)
}

export async function listSlides(projectId: string): Promise<Slide[]> {
  const res = await api.get(`/projects/${projectId}/slides`)
  return res.data
}

export async function createSlide(projectId: string): Promise<Slide> {
  const res = await api.post(`/projects/${projectId}/slides`, { slide_type: 'dm', frame_type: 'dm' })
  return res.data
}

export async function createMemeSlide(projectId: string): Promise<Slide> {
  const res = await api.post(`/projects/${projectId}/slides`, { slide_type: 'meme', frame_type: 'meme' })
  return res.data
}

export async function deleteSlide(projectId: string, slideId: string): Promise<void> {
  await api.delete(`/projects/${projectId}/slides/${slideId}`)
}

export async function reorderSlides(projectId: string, slides: { id: string; sort_order: number }[]): Promise<void> {
  await api.patch(`/projects/${projectId}/slides/reorder`, { slides })
}

export async function getMessages(projectId: string, slideId: string): Promise<Message[]> {
  const res = await api.get(`/projects/${projectId}/slides/${slideId}/messages`)
  return res.data
}

export async function replaceMessages(projectId: string, slideId: string, messages: Omit<Message, 'id' | 'slide_id' | 'sort_order'>[]): Promise<void> {
  await api.put(`/projects/${projectId}/slides/${slideId}/messages`, messages)
}

export async function getSettings(projectId: string): Promise<RenderSettings> {
  const res = await api.get(`/projects/${projectId}/settings`)
  return res.data
}

export async function updateSettings(projectId: string, settings: Partial<RenderSettings>): Promise<RenderSettings> {
  const res = await api.put(`/projects/${projectId}/settings`, settings)
  return res.data
}

export async function renderPreview(projectId: string, slideId: string): Promise<string> {
  const res = await api.post(`/projects/${projectId}/render-preview/${slideId}`, null, {
    responseType: 'blob',
  })
  return URL.createObjectURL(res.data)
}

export async function renderAll(projectId: string): Promise<string> {
  const res = await api.post(`/projects/${projectId}/render-all`)
  return res.data.job_id
}

export async function exportVideo(projectId: string): Promise<string> {
  const res = await api.post(`/projects/${projectId}/export`)
  return res.data.job_id
}

export function getExportDownloadUrl(projectId: string): string {
  return `/api/projects/${projectId}/export/download`
}

export async function uploadStoryImage(projectId: string, file: File): Promise<string> {
  const form = new FormData()
  form.append('file', file)
  const res = await api.post(`/projects/${projectId}/upload-story`, form)
  return res.data.path
}

// --- Import pipeline ---

export interface ImportStatus {
  source_url: string | null
  has_video: boolean
  frame_count: number
}

export interface FrameSlide {
  id: string
  sort_order: number
  source_frame_path: string | null
  frame_url: string | null
  frame_type: string        // 'dm' | 'meme' | 'app_ad'
  is_active: boolean
  hold_duration_ms: number
  meme_category: string | null   // 'opening' | 'sport' | 'coocked' | 'cooking' | 'shoot_our_shot' | 'succes'
}

export async function importUrl(projectId: string, url: string): Promise<string> {
  const res = await api.post(`/projects/${projectId}/import/url`, { url })
  return res.data.job_id
}

export async function extractFrames(projectId: string): Promise<string> {
  const res = await api.post(`/projects/${projectId}/import/extract-frames`, {})
  return res.data.job_id
}

export async function setFrameType(projectId: string, slideId: string, frameType: string): Promise<void> {
  await api.patch(`/projects/${projectId}/slides/${slideId}/frame-type`, { frame_type: frameType })
}

export async function uploadMemeToSlide(
  projectId: string,
  slideId: string,
  file: File,
): Promise<{ frame_url: string }> {
  const form = new FormData()
  form.append('file', file)
  const res = await api.post(`/projects/${projectId}/slides/${slideId}/upload-meme`, form)
  return res.data
}

export async function runOcr(projectId: string): Promise<string> {
  const res = await api.post(`/projects/${projectId}/import/run-ocr`, {})
  return res.data.job_id
}

export async function getImportStatus(projectId: string): Promise<ImportStatus> {
  const res = await api.get(`/projects/${projectId}/import/status`)
  return res.data
}

export async function listFrameSlides(projectId: string): Promise<FrameSlide[]> {
  const res = await api.get(`/projects/${projectId}/import/frames`)
  return res.data
}

export async function rerenderAppad(
  projectId: string,
  slideId: string,
): Promise<{ frame_url: string; slide_id: string }> {
  const res = await api.post(`/projects/${projectId}/slides/${slideId}/rerender-appad`)
  return res.data
}

// --- Meme library ---

export type MemeCategory = 'opening' | 'sport' | 'coocked' | 'cooking' | 'shoot_our_shot' | 'succes'

export const MEME_CATEGORIES: { id: MemeCategory; label: string; emoji: string }[] = [
  { id: 'opening',        label: 'Opening',        emoji: '🎬' },
  { id: 'sport',          label: 'Sport',          emoji: '⚽' },
  { id: 'coocked',        label: 'Coocked',        emoji: '😬' },
  { id: 'cooking',        label: 'Cooking',        emoji: '🔥' },
  { id: 'shoot_our_shot', label: 'Shoot our shot', emoji: '🎯' },
  { id: 'succes',         label: 'Succes',         emoji: '🏆' },
]

export interface LibraryMeme {
  filename: string
  name: string
  url: string              // e.g. /meme-library/cooking/grappig.jpg
  type: 'image' | 'video'
  category: MemeCategory
}

export async function listMemeLibrary(): Promise<LibraryMeme[]> {
  const res = await api.get('/meme-library')
  return res.data
}

export async function uploadToMemeLibrary(file: File, category: MemeCategory): Promise<LibraryMeme> {
  const form = new FormData()
  form.append('file', file)
  form.append('category', category)
  const res = await api.post('/meme-library/upload', form)
  return res.data
}

export async function assignLibraryMeme(
  projectId: string,
  slideId: string,
  category: MemeCategory,
  filename: string,
): Promise<{ frame_url: string; hold_duration_ms: number; meme_category: string }> {
  const res = await api.post(
    `/projects/${projectId}/slides/${slideId}/assign-library-meme`,
    { category, filename },
  )
  return res.data
}

export async function useOriginalClip(
  projectId: string,
  slideId: string,
): Promise<{ frame_url: string; hold_duration_ms: number }> {
  const res = await api.post(
    `/projects/${projectId}/slides/${slideId}/use-original-clip`,
  )
  return res.data
}

export async function saveClipToLibrary(
  projectId: string,
  slideId: string,
): Promise<LibraryMeme> {
  const res = await api.post(
    `/projects/${projectId}/slides/${slideId}/save-clip-to-library`,
  )
  return res.data
}

// --- Library ---

export interface LibraryItem {
  id: string
  name: string
  created_at: string
  thumbnail_url: string | null
  download_url: string
}

export async function getLibrary(): Promise<LibraryItem[]> {
  const res = await api.get('/library')
  return res.data
}

// --- Auto-pipeline ---

export async function submitPipeline(urls: string[]): Promise<{ project_ids: string[]; queued: number }> {
  const res = await api.post('/pipeline', { urls })
  return res.data
}

export async function approveProject(projectId: string): Promise<void> {
  await api.post(`/projects/${projectId}/approve`)
}

export async function retryProject(projectId: string): Promise<void> {
  await api.post(`/projects/${projectId}/pipeline/retry`)
}

export async function reexportProject(projectId: string): Promise<void> {
  await api.post(`/projects/${projectId}/reexport`)
}

// --- Global app settings ---

export interface AppSettings {
  openai_api_key: string
}

export async function getAppSettings(): Promise<AppSettings> {
  const res = await api.get('/settings')
  return res.data
}

export async function saveAppSettings(s: AppSettings): Promise<AppSettings> {
  const res = await api.put('/settings', s)
  return res.data
}
