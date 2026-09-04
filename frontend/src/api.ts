import type { Conversation, Message, Repository, SystemStatus } from './types'

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...(options?.headers || {}) },
  })
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`
    try {
      const body = await response.json()
      if (body?.detail) message = body.detail
    } catch { /* keep HTTP message */ }
    throw new Error(message)
  }
  return response.json() as Promise<T>
}

export const api = {
  repositories: () => request<Repository[]>('/api/repositories'),
  addRepository: (path: string) => request<Repository>('/api/repositories', { method: 'POST', body: JSON.stringify({ path }) }),
  pickFolder: () => request<{ path: string }>('/api/system/pick-folder', { method: 'POST' }),
  indexRepository: (id: number, force = false) => request<{ ok: boolean; started: boolean; message: string }>(`/api/repositories/${id}/index`, { method: 'POST', body: JSON.stringify({ force, embeddings: true }) }),
  repo: (id: number) => request<Repository>(`/api/repositories/${id}`),
  deleteRepo: (id: number) => request<{ok: boolean}>(`/api/repositories/${id}`, { method: 'DELETE' }),
  conversations: (repoId: number, search = '') => request<Conversation[]>(`/api/conversations?repository_id=${repoId}&search=${encodeURIComponent(search)}`),
  createConversation: (repoId: number, repositoryIds?: number[]) => request<Conversation>('/api/conversations', { method: 'POST', body: JSON.stringify({ repository_id: repoId, repository_ids: repositoryIds }) }),
  renameConversation: (id: number, title: string) => request<Conversation>(`/api/conversations/${id}`, { method: 'PATCH', body: JSON.stringify({ title }) }),
  updateConversationRepositories: (id: number, repositoryIds: number[]) => request<Conversation>(`/api/conversations/${id}`, { method: 'PATCH', body: JSON.stringify({ repository_ids: repositoryIds }) }),
  deleteConversation: (id: number) => request<{ok: boolean}>(`/api/conversations/${id}`, { method: 'DELETE' }),
  branchConversation: (id: number, branchFromMessageId: number) => request<Conversation>(`/api/conversations/${id}/branch`, { method: 'POST', body: JSON.stringify({ branch_from_message_id: branchFromMessageId }) }),
  messages: (conversationId: number) => request<Message[]>(`/api/conversations/${conversationId}/messages`),
  sendMessage: (conversationId: number, content: string, referencedMessageId?: number | null) => request<{ user_message_id: number; assistant_message_id: number; content: string; sources: any[] }>(`/api/conversations/${conversationId}/messages`, { method: 'POST', body: JSON.stringify({ content, referenced_message_id: referencedMessageId ?? null }) }),
  file: (repoId: number, path: string, start: number, end: number) => request<{ path: string; start_line: number; end_line: number; lines: {line:number;text:string}[]; hash: string }>(`/api/repositories/${repoId}/file?path=${encodeURIComponent(path)}&start_line=${start}&end_line=${end}`),
  status: () => request<SystemStatus>('/api/system/status'),
}
