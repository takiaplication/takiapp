export type KanbanStatus =
  | 'queue'
  | 'processing'
  | 'error'
  | 'review'
  | 'approved'
  | 'library'
  | 'created'     // legacy — treated as queue

export interface Project {
  id: string
  name: string
  status: KanbanStatus | string
  source_url: string | null
  pipeline_step: string | null
  pipeline_error: string | null
  created_at: string
  updated_at: string
}

export interface Slide {
  id: string
  project_id: string
  sort_order: number
  slide_type: 'dm' | 'meme'
  frame_type: string            // 'dm' | 'meme' | 'app_ad'
  frame_url: string | null      // preview URL for the assigned meme / source frame
  extracted_clip_url: string | null  // URL of the auto-extracted meme clip (immutable)
  rendered_path: string | null
  is_active: boolean
  hold_duration_ms: number
  meme_category: string | null  // 'opening' | 'sport' | 'coocked' | 'cooking' | 'shoot_our_shot' | 'succes'
}

export interface Message {
  id: string
  slide_id: string
  sort_order: number
  sender: 'self' | 'other'
  text: string
  message_type: string
  show_timestamp: boolean
  timestamp_text: string | null
  read_receipt: string | null
  emoji_reaction: string | null
  story_image_path: string | null
  story_reply_label: string | null
  content_hash: string | null
  story_group_id: string | null
}

export interface RenderSettings {
  other_username: string
  other_avatar_path: string | null
  other_verified: boolean
  self_username: string
  theme: 'dark' | 'light'
  transition_type: string
  transition_duration_ms: number
  default_hold_duration_ms: number
  output_fps: number
  background_music_path: string | null
  music_volume: number
}

export interface Job {
  id: string
  project_id: string
  job_type: string
  status: string
  progress: number
  progress_message: string | null
  error_message: string | null
}
