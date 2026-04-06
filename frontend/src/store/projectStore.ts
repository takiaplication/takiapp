import { create } from 'zustand'
import type { Project, Slide, Message, RenderSettings } from '../types/project'
import * as projectsApi from '../api/projects'

// Module-level debounce timer — lives outside Zustand so it survives re-renders
let autoRenderTimer: ReturnType<typeof setTimeout> | null = null

interface ProjectStore {
  projects: Project[]
  currentProject: Project | null
  slides: Slide[]
  activeSlideId: string | null
  messages: Message[]
  settings: RenderSettings | null
  previewUrl: string | null
  previewRendering: boolean
  loading: boolean

  fetchProjects: () => Promise<void>
  loadProject: (id: string) => Promise<void>
  createProject: (name: string) => Promise<Project>
  removeProject: (id: string) => Promise<void>
  addSlide: () => Promise<void>
  addMemeSlide: () => Promise<void>
  removeSlide: (slideId: string) => Promise<void>
  selectSlide: (slideId: string) => Promise<void>
  setMessages: (messages: Message[]) => void
  saveMessages: () => Promise<void>
  updateSettings: (settings: Partial<RenderSettings>) => Promise<void>
  refreshPreview: () => Promise<void>
  reorderSlides: (newOrder: string[]) => Promise<void>
  updateSlideMeme: (slideId: string, frameUrl: string, holdMs: number) => void
}

export const useProjectStore = create<ProjectStore>((set, get) => ({
  projects: [],
  currentProject: null,
  slides: [],
  activeSlideId: null,
  messages: [],
  settings: null,
  previewUrl: null,
  previewRendering: false,
  loading: false,

  fetchProjects: async () => {
    const projects = await projectsApi.listProjects()
    set({ projects })
  },

  loadProject: async (id: string) => {
    set({ loading: true })
    const [project, slides, settings] = await Promise.all([
      projectsApi.getProject(id),
      projectsApi.listSlides(id),
      projectsApi.getSettings(id),
    ])
    set({ currentProject: project, slides, settings, loading: false })

    // Select first slide if available
    if (slides.length > 0) {
      await get().selectSlide(slides[0].id)
    }
  },

  createProject: async (name: string) => {
    const project = await projectsApi.createProject(name)
    set((s) => ({ projects: [project, ...s.projects] }))
    return project
  },

  removeProject: async (id: string) => {
    await projectsApi.deleteProject(id)
    set((s) => ({
      projects: s.projects.filter((p) => p.id !== id),
      currentProject: s.currentProject?.id === id ? null : s.currentProject,
    }))
  },

  addSlide: async () => {
    const { currentProject } = get()
    if (!currentProject) return
    const slide = await projectsApi.createSlide(currentProject.id)
    set((s) => ({ slides: [...s.slides, slide] }))
    await get().selectSlide(slide.id)
  },

  addMemeSlide: async () => {
    const { currentProject } = get()
    if (!currentProject) return
    const slide = await projectsApi.createMemeSlide(currentProject.id)
    set((s) => ({ slides: [...s.slides, slide] }))
    await get().selectSlide(slide.id)
  },

  removeSlide: async (slideId: string) => {
    const { currentProject } = get()
    if (!currentProject) return
    await projectsApi.deleteSlide(currentProject.id, slideId)
    set((s) => ({
      slides: s.slides.filter((sl) => sl.id !== slideId),
      activeSlideId: s.activeSlideId === slideId ? null : s.activeSlideId,
    }))
  },

  selectSlide: async (slideId: string) => {
    const { currentProject } = get()
    if (!currentProject) return
    const messages = await projectsApi.getMessages(currentProject.id, slideId)
    set({ activeSlideId: slideId, messages, previewUrl: null })

    // Auto-render the newly selected slide (best-effort — ignore if no messages yet)
    set({ previewRendering: true })
    try {
      const url = await projectsApi.renderPreview(currentProject.id, slideId)
      set({ previewUrl: url })
    } catch {
      // No messages yet — that's fine
    } finally {
      set({ previewRendering: false })
    }
  },

  setMessages: (messages: Message[]) => {
    set({ messages })

    // Cancel any pending auto-render and schedule a new one (1.2 s debounce)
    if (autoRenderTimer) clearTimeout(autoRenderTimer)
    autoRenderTimer = setTimeout(async () => {
      autoRenderTimer = null
      const { currentProject, activeSlideId } = get()
      if (!currentProject || !activeSlideId) return
      set({ previewRendering: true })
      try {
        await get().saveMessages()
        const url = await projectsApi.renderPreview(currentProject.id, activeSlideId)
        set({ previewUrl: url })
      } catch {
        // Render failed (e.g. empty slide) — just leave the old preview
      } finally {
        set({ previewRendering: false })
      }
    }, 1200)
  },

  saveMessages: async () => {
    const { currentProject, activeSlideId, messages } = get()
    if (!currentProject || !activeSlideId) return
    const stripped = messages.map(({ sender, text, message_type, show_timestamp, timestamp_text, read_receipt, emoji_reaction, story_image_path, story_reply_label }) => ({
      sender, text, message_type, show_timestamp, timestamp_text, read_receipt, emoji_reaction, story_image_path, story_reply_label,
    }))
    await projectsApi.replaceMessages(currentProject.id, activeSlideId, stripped)
  },

  updateSettings: async (partial: Partial<RenderSettings>) => {
    const { currentProject } = get()
    if (!currentProject) return
    const updated = await projectsApi.updateSettings(currentProject.id, partial)
    set({ settings: updated })
  },

  refreshPreview: async () => {
    const { currentProject, activeSlideId } = get()
    if (!currentProject || !activeSlideId) return
    set({ previewRendering: true })
    try {
      await get().saveMessages()
      const url = await projectsApi.renderPreview(currentProject.id, activeSlideId)
      set({ previewUrl: url })
    } finally {
      set({ previewRendering: false })
    }
  },

  reorderSlides: async (newOrder: string[]) => {
    const { currentProject, slides } = get()
    if (!currentProject) return
    const reordered = newOrder.map((id, i) => {
      const slide = slides.find((s) => s.id === id)!
      return { ...slide, sort_order: i }
    })
    set({ slides: reordered })
    await projectsApi.reorderSlides(
      currentProject.id,
      newOrder.map((id, i) => ({ id, sort_order: i })),
    )
  },

  updateSlideMeme: (slideId: string, frameUrl: string, holdMs: number) => {
    set((s) => ({
      slides: s.slides.map((sl) =>
        sl.id === slideId ? { ...sl, frame_url: frameUrl, hold_duration_ms: holdMs } : sl,
      ),
    }))
  },

}))
