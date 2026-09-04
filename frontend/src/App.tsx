import { KeyboardEvent, useEffect, useMemo, useRef, useState } from 'react'
import { api } from './api'
import type { Conversation, Message, Repository, SourceRef, SystemStatus } from './types'

function formatDate(value: string) {
  const d = new Date(value.replace(' ', 'T') + (value.includes('Z') ? '' : 'Z'))
  if (Number.isNaN(d.getTime())) return value
  const now = new Date()
  const sameDay = now.toDateString() === d.toDateString()
  return sameDay ? d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }) : d.toLocaleDateString([], { month: 'short', day: 'numeric' })
}

function shortCommit(value?: string | null) {
  return value ? value.slice(0, 8) : 'no commit'
}

function MessageBody({ text }: { text: string }) {
  const blocks = text.split(/```/)
  return (
    <div className="message-body">
      {blocks.map((block, i) =>
        i % 2 === 1 ? (
          <pre className="code-block" key={i}><code>{block.replace(/^\w+\n/, '')}</code></pre>
        ) : (
          <div className="prose" key={i}>{block}</div>
        ),
      )}
    </div>
  )
}

function SourceDrawer({ repo, source, onClose }: { repo: Repository; source: SourceRef; onClose: () => void }) {
  const [data, setData] = useState<{lines:{line:number;text:string}[]}|null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    const start = Math.max(1, source.start_line - 12)
    const end = source.end_line + 18
    api.file(repo.id, source.path, start, end).then(setData).catch(e => setError(e.message))
  }, [repo.id, source])
  return (
    <div className="drawer-backdrop" onMouseDown={onClose}>
      <aside className="source-drawer" onMouseDown={e => e.stopPropagation()}>
        <div className="drawer-head">
          <div>
            <div className="drawer-title">{source.path}</div>
            <div className="muted">lines {source.start_line}-{source.end_line}</div>
          </div>
          <button className="icon-button" onClick={onClose} aria-label="Close">×</button>
        </div>
        {error && <div className="error-box">{error}</div>}
        <div className="source-code">
          {data?.lines.map(line => (
            <div className={`source-line ${line.line >= source.start_line && line.line <= source.end_line ? 'focus-line' : ''}`} key={line.line}>
              <span className="line-no">{line.line}</span><code>{line.text || ' '}</code>
            </div>
          ))}
        </div>
      </aside>
    </div>
  )
}

function App() {
  const [repos, setRepos] = useState<Repository[]>([])
  const [repoId, setRepoId] = useState<number | null>(null)
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [conversationId, setConversationId] = useState<number | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [search, setSearch] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [source, setSource] = useState<SourceRef | null>(null)
  const [showSettings, setShowSettings] = useState(false)
  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null)
  const [manualRepoPath, setManualRepoPath] = useState('')
  const scrollRef = useRef<HTMLDivElement | null>(null)

  const repo = useMemo(() => repos.find(r => r.id === repoId) || null, [repos, repoId])
  const conversation = useMemo(() => conversations.find(c => c.id === conversationId) || null, [conversations, conversationId])

  async function refreshRepos(selectFirst = false) {
    const data = await api.repositories()
    setRepos(data)
    if ((selectFirst || repoId == null) && data.length) setRepoId(data[0].id)
    return data
  }

  async function refreshConversations(targetRepoId = repoId, q = search) {
    if (!targetRepoId) return []
    const data = await api.conversations(targetRepoId, q)
    setConversations(data)
    return data
  }

  useEffect(() => {
    refreshRepos(true).catch(e => setError(e.message))
  }, [])

  useEffect(() => {
    if (!repoId) {
      setConversations([])
      setConversationId(null)
      setMessages([])
      return
    }
    setConversationId(null)
    setMessages([])
    refreshConversations(repoId, '').catch(e => setError(e.message))
  }, [repoId])

  useEffect(() => {
    const t = window.setTimeout(() => {
      if (repoId) refreshConversations(repoId, search).catch(() => {})
    }, 220)
    return () => window.clearTimeout(t)
  }, [search, repoId])

  useEffect(() => {
    if (!conversationId) {
      setMessages([])
      return
    }
    api.messages(conversationId).then(setMessages).catch(e => setError(e.message))
  }, [conversationId])

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages, busy])

  useEffect(() => {
    if (!repoId) return
    const timer = window.setInterval(async () => {
      try {
        const current = await api.repo(repoId)
        setRepos(prev => prev.map(r => r.id === current.id ? current : r))
      } catch { /* ignore transient poll errors */ }
    }, 1800)
    return () => window.clearInterval(timer)
  }, [repoId])

  async function addRepository() {
    setError('')
    try {
      let path = manualRepoPath.trim()
      if (!path) {
        const picked = await api.pickFolder()
        path = picked.path
      }
      const added = await api.addRepository(path)
      setManualRepoPath('')
      await refreshRepos()
      setRepoId(added.id)
      await api.indexRepository(added.id)
      const current = await api.repo(added.id)
      setRepos(prev => prev.map(r => r.id === current.id ? current : r))
    } catch (e: any) {
      if (!String(e.message).toLowerCase().includes('cancel')) setError(e.message)
    }
  }

  async function newChat() {
    if (!repoId) return
    setError('')
    try {
      const c = await api.createConversation(repoId)
      setConversations(prev => [c, ...prev])
      setConversationId(c.id)
      setMessages([])
    } catch (e: any) { setError(e.message) }
  }

  async function openConversation(id: number) {
    setConversationId(id)
    setError('')
  }

  async function renameChat(c: Conversation) {
    const title = window.prompt('Rename conversation', c.title)
    if (!title || title.trim() === c.title) return
    try {
      const updated = await api.renameConversation(c.id, title.trim())
      setConversations(prev => prev.map(x => x.id === c.id ? updated : x))
    } catch (e: any) { setError(e.message) }
  }

  async function removeChat(c: Conversation) {
    if (!window.confirm(`Delete “${c.title}”? This only deletes the local chat history.`)) return
    try {
      await api.deleteConversation(c.id)
      setConversations(prev => prev.filter(x => x.id !== c.id))
      if (conversationId === c.id) {
        setConversationId(null)
        setMessages([])
      }
    } catch (e: any) { setError(e.message) }
  }

  async function send() {
    const text = input.trim()
    if (!text || busy || !repoId) return
    setError('')
    let cid = conversationId
    try {
      if (!cid) {
        const c = await api.createConversation(repoId)
        setConversations(prev => [c, ...prev])
        cid = c.id
        setConversationId(c.id)
      }
      const temp: Message = {
        id: -Date.now(), conversation_id: cid!, role: 'user', content: text,
        created_at: new Date().toISOString(), sequence_number: messages.length + 1,
      }
      setMessages(prev => [...prev, temp])
      setInput('')
      setBusy(true)
      await api.sendMessage(cid!, text)
      const refreshed = await api.messages(cid!)
      setMessages(refreshed)
      await refreshConversations(repoId, search)
    } catch (e: any) {
      setError(e.message)
      try { if (cid) setMessages(await api.messages(cid)) } catch { /* no-op */ }
    } finally {
      setBusy(false)
    }
  }

  function onComposerKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      void send()
    }
  }

  async function reindex(force = false) {
    if (!repoId) return
    try {
      await api.indexRepository(repoId, force)
      const current = await api.repo(repoId)
      setRepos(prev => prev.map(r => r.id === current.id ? current : r))
    } catch (e: any) { setError(e.message) }
  }

  async function openSettings() {
    setShowSettings(true)
    try { setSystemStatus(await api.status()) } catch (e: any) { setError(e.message) }
  }

  const ready = repo?.status === 'ready'
  const placeholder = !repo ? 'Choose a repository to begin' : !ready ? 'Repository is still indexing…' : 'Ask anything about this repository…'

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-row">
          <div className="brand-mark">C</div>
          <div>
            <div className="brand">Codebase AI</div>
            <div className="brand-sub">Local repository intelligence</div>
          </div>
        </div>

        <button className="new-chat" disabled={!repoId} onClick={newChat}>+ New chat</button>

        <div className="repo-card">
          <div className="section-label">Repository</div>
          {repos.length > 0 && (
            <select className="repo-select" value={repoId ?? ''} onChange={e => setRepoId(Number(e.target.value))}>
              {repos.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}
            </select>
          )}
          <button className="secondary full" onClick={addRepository}>Open local repository</button>
          <details className="manual-path">
            <summary>Enter path manually</summary>
            <div className="manual-row">
              <input value={manualRepoPath} onChange={e => setManualRepoPath(e.target.value)} placeholder="/Users/me/project" />
              <button onClick={addRepository}>Add</button>
            </div>
          </details>
          {repo && (
            <div className="repo-status">
              <span className={`status-dot ${repo.status}`}></span>
              <span>{repo.status === 'indexing' ? 'Indexing' : repo.status === 'ready' ? 'Indexed' : repo.status}</span>
              {repo.status === 'ready' && <span className="counts">{repo.total_files} files · {repo.total_symbols} symbols</span>}
            </div>
          )}
        </div>

        <div className="chat-search-wrap">
          <input className="chat-search" value={search} onChange={e => setSearch(e.target.value)} placeholder="Search conversations" />
        </div>

        <div className="conversation-list">
          {conversations.map(c => (
            <div key={c.id} className={`conversation-row ${conversationId === c.id ? 'active' : ''}`}>
              <button className="conversation-open" onClick={() => openConversation(c.id)}>
                <span className="conversation-title">{c.title}</span>
                <span className="conversation-time">{formatDate(c.updated_at)}</span>
              </button>
              <div className="conversation-actions">
                <button title="Rename" onClick={() => renameChat(c)}>Edit</button>
                <button title="Delete" onClick={() => removeChat(c)}>Delete</button>
              </div>
            </div>
          ))}
          {repoId && conversations.length === 0 && <div className="sidebar-empty">No conversations yet.</div>}
        </div>

        <div className="sidebar-bottom">
          <button className="settings-button" onClick={openSettings}>Settings & local status</button>
          <div className="privacy-line"><span className="status-dot ready"></span> Local only · 127.0.0.1</div>
        </div>
      </aside>

      <main className="main-panel">
        <header className="topbar">
          <div>
            <div className="top-title">{conversation?.title || repo?.name || 'Codebase AI'}</div>
            {repo && <div className="top-sub">{repo.path} · {shortCommit(repo.git_commit)}</div>}
          </div>
          {repo && (
            <div className="top-actions">
              <div className={`semantic-pill ${repo.semantic_ready ? 'good' : ''}`}>{repo.semantic_ready ? 'Semantic ready' : 'Lexical + structural'}</div>
              <button className="secondary" disabled={repo.status === 'indexing'} onClick={() => reindex(false)}>{repo.status === 'indexing' ? 'Indexing…' : 'Refresh index'}</button>
            </div>
          )}
        </header>

        <div className="status-area">
          {error && <div className="error-banner"><span>{error}</span><button onClick={() => setError('')}>×</button></div>}
          {repo?.status === 'indexing' && <div className="index-banner"><span className="spinner small"></span>{repo.status_message}</div>}
          {repo?.status === 'error' && <div className="error-banner"><span>{repo.status_message}</span><button onClick={() => reindex(true)}>Retry full index</button></div>}
        </div>

        <div className="messages" ref={scrollRef}>
          {!repo && (
            <div className="empty-state">
              <div className="empty-logo">C</div>
              <h1>Understand a private codebase locally.</h1>
              <p>Open a repository. Codebase AI will build a local structural, lexical and semantic index without uploading the source.</p>
              <button className="primary" onClick={addRepository}>Open repository</button>
            </div>
          )}
          {repo && messages.length === 0 && (
            <div className="empty-state chat-empty">
              <h1>What do you want to understand?</h1>
              <p>{ready ? 'Ask about flow, ownership, symbols, tests, AWS Lambda functions, change impact, or where a feature should be implemented.' : repo.status_message || 'Index the repository to begin.'}</p>
              {ready && (
                <div className="suggestions">
                  {[
                    'Map the high-level architecture of this repository.',
                    'Where are the main entry points and what do they call?',
                    'Find the AWS Lambda handlers and explain their dependencies.',
                    'How are tests organized across Playwright and Karate?',
                  ].map(s => <button key={s} onClick={() => setInput(s)}>{s}</button>)}
                </div>
              )}
            </div>
          )}
          {messages.map(m => (
            <article className={`message ${m.role}`} key={m.id}>
              <div className="message-avatar">{m.role === 'assistant' ? 'AI' : 'You'}</div>
              <div className="message-content">
                <MessageBody text={m.content} />
                {m.role === 'assistant' && m.sources && m.sources.length > 0 && (
                  <div className="sources">
                    <div className="sources-label">Repository evidence</div>
                    <div className="source-chips">
                      {m.sources.slice(0, 10).map((s, idx) => (
                        <button key={`${m.id}-${idx}`} className={`source-chip ${s.stale ? 'stale' : ''}`} onClick={() => setSource(s)} title={s.stale ? 'This file has changed since the answer was generated' : 'Open source'}>
                          <span>{s.path.split('/').pop()}</span><small>{s.stale ? 'changed' : `${s.start_line}-${s.end_line}`}</small>
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </article>
          ))}
          {busy && (
            <article className="message assistant">
              <div className="message-avatar">AI</div>
              <div className="thinking"><span className="spinner"></span>Reading the repository and reasoning locally…</div>
            </article>
          )}
        </div>

        <div className="composer-wrap">
          <div className="composer">
            <textarea
              value={input}
              disabled={!repo || !ready || busy}
              onChange={e => setInput(e.target.value)}
              onKeyDown={onComposerKey}
              placeholder={placeholder}
              rows={1}
            />
            <button className="send-button" disabled={!input.trim() || !ready || busy} onClick={send}>Send</button>
          </div>
          <div className="composer-note">Read-only repository analysis · chats and indexes stay on this Mac</div>
        </div>
      </main>

      {repo && source && <SourceDrawer repo={repo} source={source} onClose={() => setSource(null)} />}

      {showSettings && (
        <div className="modal-backdrop" onMouseDown={() => setShowSettings(false)}>
          <div className="settings-modal" onMouseDown={e => e.stopPropagation()}>
            <div className="drawer-head">
              <div><div className="drawer-title">Local runtime</div><div className="muted">No cloud fallback or telemetry</div></div>
              <button className="icon-button" onClick={() => setShowSettings(false)}>×</button>
            </div>
            {!systemStatus ? <div className="thinking"><span className="spinner"></span>Checking services…</div> : (
              <div className="settings-grid">
                <div className="setting-card"><span className={`status-dot ${systemStatus.mlx.ok ? 'ready' : 'error'}`}></span><div><strong>MLX coding model</strong><p>{systemStatus.mlx.model}</p><small>{systemStatus.mlx.message}</small></div></div>
                <div className="setting-card"><span className={`status-dot ${systemStatus.ollama.ok ? 'ready' : 'error'}`}></span><div><strong>Ollama embeddings</strong><p>{systemStatus.ollama.model}</p><small>{systemStatus.ollama.message}</small></div></div>
                <div className="setting-card"><span className="status-dot ready"></span><div><strong>Privacy</strong><p>Bound to {systemStatus.privacy.bind}</p><small>Cloud fallback: off · Telemetry: off</small></div></div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

export default App
