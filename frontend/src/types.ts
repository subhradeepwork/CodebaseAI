export type Repository = {
  id: number
  name: string
  path: string
  status: 'new' | 'indexing' | 'ready' | 'error' | string
  status_message: string
  total_files: number
  total_chunks: number
  total_symbols: number
  git_commit?: string | null
  semantic_ready: number
  last_indexed_at?: string | null
}

export type Conversation = {
  id: number
  repository_id: number
  repository_ids: number[]
  title: string
  created_at: string
  updated_at: string
  archived: number
}

export type SourceRef = {
  path: string
  start_line: number
  end_line: number
  score: number
  kind: string
  stale?: boolean
  file_hash?: string
  repository_id?: number | null
  repository_name?: string | null
}

export type Message = {
  id: number
  conversation_id: number
  role: 'user' | 'assistant' | 'system'
  content: string
  created_at: string
  sequence_number: number
  repository_commit?: string | null
  sources?: SourceRef[]
}

export type SystemStatus = {
  platform: string
  machine: string
  python: string
  ollama: { ok: boolean; message: string; url: string; model: string }
  mlx: { ok: boolean; message: string; url: string; model: string }
  privacy: { bind: string; cloud_fallback: boolean; telemetry: boolean }
}
