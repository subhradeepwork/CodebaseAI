import { CSSProperties, KeyboardEvent, PointerEvent as ReactPointerEvent, useEffect, useMemo, useRef, useState } from 'react'
import { api } from './api'
import type { Conversation, Message, Repository, SourceRef, SystemStatus } from './types'

const MIN_SIDEBAR_WIDTH = 220
const MAX_SIDEBAR_WIDTH = 520
const DEFAULT_SIDEBAR_WIDTH = 280

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

function uniqueIds(ids: number[]) {
  return [...new Set(ids.filter(Boolean))]
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

function SourceDrawer({ repos, fallbackRepo, source, onClose }: { repos: Repository[]; fallbackRepo: Repository; source: SourceRef; onClose: () => void }) {
  const sourceRepo = repos.find(r => r.id === source.repository_id) || fallbackRepo
  const [data, setData] = useState<{lines:{line:number;text:string}[]}|null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    setData(null)
    setError('')
    const start = Math.max(1, source.start_line - 12)
    const end = source.end_line + 18
    api.file(sourceRepo.id, source.path, start, end).then(setData).catch(e => setError(e.message))
  }, [sourceRepo.id, source])
  return (
    <div className="drawer-backdrop" onMouseDown={onClose}>
      <aside className="source-drawer" onMouseDown={e => e.stopPropagation()}>
        <div className="drawer-head">
          <div>
            <div className="drawer-title">{source.path}</div>
            <div className="muted">{sourceRepo.name} · lines {source.start_line}-{source.end_line}</div>
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
  const [contextRepoIds, setContextRepoIds] = useState<number[]>([])
  const [repoContextDraft, setRepoContextDraft] = useState<number[]>([])
  const [showRepoContext, setShowRepoContext] = useState(false)
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [conversationId, setConversationId] = useState<number | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [referencedMessage, setReferencedMessage] = useState<Message | null>(null)
  const [input, setInput] = useState('')
  const [search, setSearch] = useState('')
  const [busy, setBusy] = useState(false)
  const [branchingMessageId, setBranchingMessageId] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [source, setSource] = useState<SourceRef | null>(null)
  const [showSettings, setShowSettings] = useState(false)
  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null)
  const [manualRepoPath, setManualRepoPath] = useState('')
  const [sidebarWidth, setSidebarWidth] = useState(() => {
    const stored = Number(window.localStorage.getItem('codebase-ai-sidebar-width'))
    return Number.isFinite(stored) && stored >= MIN_SIDEBAR_WIDTH && stored <= MAX_SIDEBAR_WIDTH ? stored : DEFAULT_SIDEBAR_WIDTH
  })
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => window.localStorage.getItem('codebase-ai-sidebar-collapsed') === '1')
  const resizingRef = useRef(false)
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const composerInputRef = useRef<HTMLTextAreaElement | null>(null)

  const repo = useMemo(() => repos.find(r => r.id === repoId) || null, [repos, repoId])
  const conversation = useMemo(() => conversations.find(c => c.id === conversationId) || null, [conversations, conversationId])
  const contextRepos = useMemo(() => contextRepoIds.map(id => repos.find(r => r.id === id)).filter(Boolean) as Repository[], [contextRepoIds, repos])

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
      setContextRepoIds([])
      setConversations([])
      setConversationId(null)
      setMessages([])
      setReferencedMessage(null)
      return
    }
    setContextRepoIds([repoId])
    setConversationId(null)
    setMessages([])
    setReferencedMessage(null)
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
    if (!contextRepoIds.length) return
    const timer = window.setInterval(async () => {
      try {
        const current = await Promise.all(contextRepoIds.map(id => api.repo(id)))
        const byId = new Map(current.map(r => [r.id, r]))
        setRepos(prev => prev.map(r => byId.get(r.id) || r))
      } catch { /* ignore transient poll errors */ }
    }, 1800)
    return () => window.clearInterval(timer)
  }, [contextRepoIds.join(',')])

  useEffect(() => {
    window.localStorage.setItem('codebase-ai-sidebar-width', String(sidebarWidth))
  }, [sidebarWidth])

  useEffect(() => {
    window.localStorage.setItem('codebase-ai-sidebar-collapsed', sidebarCollapsed ? '1' : '0')
  }, [sidebarCollapsed])

  useEffect(() => {
    function move(e: PointerEvent) {
      if (!resizingRef.current) return
      const next = Math.max(MIN_SIDEBAR_WIDTH, Math.min(MAX_SIDEBAR_WIDTH, e.clientX))
      setSidebarWidth(next)
    }
    function stop() {
      if (!resizingRef.current) return
      resizingRef.current = false
      document.body.classList.remove('resizing-sidebar')
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', stop)
    window.addEventListener('pointercancel', stop)
    return () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', stop)
      window.removeEventListener('pointercancel', stop)
    }
  }, [])

  function startSidebarResize(e: ReactPointerEvent<HTMLDivElement>) {
    e.preventDefault()
    resizingRef.current = true
    document.body.classList.add('resizing-sidebar')
  }

  async function addRepository(options: { makePrimary?: boolean; addToDraft?: boolean } = {}) {
    setError('')
    try {
      let path = manualRepoPath.trim()
      if (!path) {
        const picked = await api.pickFolder()
        path = picked.path
      }
      const added = await api.addRepository(path)
      setManualRepoPath('')
      const all = await refreshRepos()
      const current = all.find(r => r.id === added.id) || added
      if (current.status !== 'ready' && current.status !== 'indexing') {
        await api.indexRepository(added.id)
      }
      if (options.makePrimary || !repoId) {
        setRepoId(added.id)
      } else if (options.addToDraft) {
        setRepoContextDraft(prev => uniqueIds([...(prev.length ? prev : contextRepoIds), added.id]))
      }
      const refreshed = await api.repo(added.id)
      setRepos(prev => prev.map(r => r.id === refreshed.id ? refreshed : r))
      return refreshed
    } catch (e: any) {
      if (!String(e.message).toLowerCase().includes('cancel')) setError(e.message)
      return null
    }
  }

  async function newChat() {
    if (!repoId) return
    setError('')
    try {
      const ids = uniqueIds([repoId, ...contextRepoIds])
      const c = await api.createConversation(repoId, ids)
      setConversations(prev => [c, ...prev])
      setConversationId(c.id)
      setContextRepoIds(c.repository_ids || ids)
      setMessages([])
      setReferencedMessage(null)
    } catch (e: any) { setError(e.message) }
  }

  async function openConversation(c: Conversation) {
    setConversationId(c.id)
    setContextRepoIds(uniqueIds([c.repository_id, ...(c.repository_ids || [])]))
    setReferencedMessage(null)
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
        setReferencedMessage(null)
      }
    } catch (e: any) { setError(e.message) }
  }

  async function openInNewBranch(message: Message) {
    if (!conversationId || message.id <= 0 || busy || branchingMessageId != null) return
    setError('')
    setBranchingMessageId(message.id)
    try {
      const branched = await api.branchConversation(conversationId, message.id)
      setConversations(prev => [branched, ...prev.filter(c => c.id !== branched.id)])
      setConversationId(branched.id)
      setContextRepoIds(uniqueIds([branched.repository_id, ...(branched.repository_ids || [])]))
      setMessages(await api.messages(branched.id))
      setReferencedMessage(null)
      await refreshConversations(repoId, search)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setBranchingMessageId(null)
    }
  }

  function useAsReference(message: Message) {
    if (message.id <= 0 || message.role === 'system' || busy) return
    setReferencedMessage(message)
    window.requestAnimationFrame(() => composerInputRef.current?.focus())
  }

  function clearReference() {
    setReferencedMessage(null)
    window.requestAnimationFrame(() => composerInputRef.current?.focus())
  }

  function openRepositoryContext() {
    if (!repoId) return
    setRepoContextDraft(uniqueIds([repoId, ...contextRepoIds]))
    setShowRepoContext(true)
  }

  function toggleDraftRepository(id: number) {
    if (id === repoId) return
    setRepoContextDraft(prev => prev.includes(id) ? prev.filter(x => x !== id) : uniqueIds([...prev, id]))
  }

  async function applyRepositoryContext() {
    if (!repoId) return
    const ids = uniqueIds([repoId, ...repoContextDraft])
    try {
      if (conversationId) {
        const updated = await api.updateConversationRepositories(conversationId, ids)
        setConversations(prev => prev.map(c => c.id === updated.id ? updated : c))
        setContextRepoIds(updated.repository_ids || ids)
      } else {
        setContextRepoIds(ids)
      }
      setShowRepoContext(false)
    } catch (e: any) { setError(e.message) }
  }

  async function removeContextRepository(id: number) {
    if (!repoId || id === repoId) return
    const ids = contextRepoIds.filter(x => x !== id)
    try {
      if (conversationId) {
        const updated = await api.updateConversationRepositories(conversationId, ids)
        setConversations(prev => prev.map(c => c.id === updated.id ? updated : c))
        setContextRepoIds(updated.repository_ids || ids)
      } else {
        setContextRepoIds(ids)
      }
    } catch (e: any) { setError(e.message) }
  }

  async function send() {
    const text = input.trim()
    if (!text || busy || !repoId) return
    setError('')
    let cid = conversationId
    const activeReference = referencedMessage
    try {
      if (!cid) {
        const ids = uniqueIds([repoId, ...contextRepoIds])
        const c = await api.createConversation(repoId, ids)
        setConversations(prev => [c, ...prev])
        cid = c.id
        setConversationId(c.id)
        setContextRepoIds(c.repository_ids || ids)
      }
      const temp: Message = {
        id: -Date.now(), conversation_id: cid!, role: 'user', content: text,
        created_at: new Date().toISOString(), sequence_number: messages.length + 1,
        referenced_message_id: activeReference?.id ?? null,
        reference: activeReference ? { id: activeReference.id, role: activeReference.role, content: activeReference.content, sequence_number: activeReference.sequence_number } : null,
      }
      setMessages(prev => [...prev, temp])
      setInput('')
      setReferencedMessage(null)
      setBusy(true)
      await api.sendMessage(cid!, text, activeReference?.id ?? null)
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
    if (!contextRepoIds.length) return
    try {
      await Promise.all(contextRepoIds.map(id => api.indexRepository(id, force)))
      const current = await Promise.all(contextRepoIds.map(id => api.repo(id)))
      const byId = new Map(current.map(r => [r.id, r]))
      setRepos(prev => prev.map(r => byId.get(r.id) || r))
    } catch (e: any) { setError(e.message) }
  }

  async function openSettings() {
    setShowSettings(true)
    try { setSystemStatus(await api.status()) } catch (e: any) { setError(e.message) }
  }

  const allContextReady = contextRepos.length > 0 && contextRepos.every(r => r.status === 'ready')
  const anyContextIndexing = contextRepos.some(r => r.status === 'indexing')
  const semanticReadyCount = contextRepos.filter(r => r.semantic_ready).length
  const placeholder = !repo ? 'Choose a repository to begin' : !allContextReady ? 'Repository context is still indexing…' : contextRepos.length > 1 ? 'Ask anything across these repositories…' : 'Ask anything about this repository…'
  const shellStyle = { gridTemplateColumns: sidebarCollapsed ? '0px minmax(0, 1fr)' : `${sidebarWidth}px minmax(0, 1fr)` } as CSSProperties

  return (
    <div className="app-shell" style={shellStyle}>
      <aside className={`sidebar ${sidebarCollapsed ? 'collapsed' : ''}`}>
        <div className="brand-row">
          <div className="brand-mark">C</div>
          <div>
            <div className="brand">Codebase AI</div>
            <div className="brand-sub">Local repository intelligence</div>
          </div>
        </div>

        <button className="new-chat" disabled={!repoId} onClick={newChat}>+ New chat</button>

        <div className="repo-card">
          <div className="section-label">Repository context</div>
          {repos.length > 0 && (
            <div className="repo-select-row">
              <select className="repo-select" value={repoId ?? ''} onChange={e => setRepoId(Number(e.target.value))}>
                {repos.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}
              </select>
              <button className="repo-plus" onClick={openRepositoryContext} title="Add repository to context" aria-label="Add repository to context">+</button>
            </div>
          )}
          {contextRepos.length > 1 && (
            <div className="context-repo-list">
              {contextRepos.filter(r => r.id !== repoId).map(r => (
                <div className="context-repo-chip" key={r.id} title={r.path}>
                  <span className={`status-dot ${r.status}`}></span>
                  <span>{r.name}</span>
                  <button onClick={() => removeContextRepository(r.id)} aria-label={`Remove ${r.name} from context`}>×</button>
                </div>
              ))}
            </div>
          )}
          <button className="secondary full" onClick={() => addRepository({ makePrimary: true })}>Open local repository</button>
          <details className="manual-path">
            <summary>Enter path manually</summary>
            <div className="manual-row">
              <input value={manualRepoPath} onChange={e => setManualRepoPath(e.target.value)} placeholder="/Users/me/project" />
              <button onClick={() => addRepository({ makePrimary: true })}>Add</button>
            </div>
          </details>
          {repo && (
            <div className="repo-status">
              <span className={`status-dot ${repo.status}`}></span>
              <span>{contextRepos.length > 1 ? `${contextRepos.length} repositories` : repo.status === 'indexing' ? 'Indexing' : repo.status === 'ready' ? 'Indexed' : repo.status}</span>
              {repo.status === 'ready' && contextRepos.length === 1 && <span className="counts">{repo.total_files} files · {repo.total_symbols} symbols</span>}
            </div>
          )}
        </div>

        <div className="chat-search-wrap">
          <input className="chat-search" value={search} onChange={e => setSearch(e.target.value)} placeholder="Search conversations" />
        </div>

        <div className="conversation-list">
          {conversations.map(c => (
            <div key={c.id} className={`conversation-row ${conversationId === c.id ? 'active' : ''}`}>
              <button className="conversation-open" onClick={() => openConversation(c)}>
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

      {!sidebarCollapsed && <div className="sidebar-resizer" style={{ left: sidebarWidth - 3 }} onPointerDown={startSidebarResize} aria-hidden="true" />}
      <button
        className="sidebar-toggle"
        style={{ left: sidebarCollapsed ? 8 : sidebarWidth - 14 }}
        onClick={() => setSidebarCollapsed(v => !v)}
        title={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        aria-label={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
      >{sidebarCollapsed ? '›' : '‹'}</button>

      <main className="main-panel">
        <header className="topbar">
          <div className={sidebarCollapsed ? 'topbar-title-collapsed' : ''}>
            <div className="top-title">{conversation?.title || repo?.name || 'Codebase AI'}</div>
            {repo && <div className="top-sub">{repo.path} · {shortCommit(repo.git_commit)}{contextRepos.length > 1 ? ` · ${contextRepos.length} repositories in context` : ''}</div>}
          </div>
          {repo && (
            <div className="top-actions">
              <div className={`semantic-pill ${semanticReadyCount === contextRepos.length && contextRepos.length ? 'good' : ''}`}>
                {contextRepos.length > 1 ? `${semanticReadyCount}/${contextRepos.length} semantic` : repo.semantic_ready ? 'Semantic ready' : 'Lexical + structural'}
              </div>
              <button className="secondary" disabled={anyContextIndexing} onClick={() => reindex(false)}>{anyContextIndexing ? 'Indexing…' : contextRepos.length > 1 ? 'Refresh indexes' : 'Refresh index'}</button>
            </div>
          )}
        </header>

        <div className="status-area">
          {error && <div className="error-banner"><span>{error}</span><button onClick={() => setError('')}>×</button></div>}
          {contextRepos.some(r => r.status === 'indexing') && <div className="index-banner"><span className="spinner small"></span>Indexing repository context…</div>}
          {contextRepos.some(r => r.status === 'error') && <div className="error-banner"><span>One or more repositories could not be indexed.</span><button onClick={() => reindex(true)}>Retry full index</button></div>}
        </div>

        <div className="messages" ref={scrollRef}>
          {!repo && (
            <div className="empty-state">
              <div className="empty-logo">C</div>
              <h1>Understand a private codebase locally.</h1>
              <p>Open a repository. Codebase AI will build a local structural, lexical and semantic index without uploading the source.</p>
              <button className="primary" onClick={() => addRepository({ makePrimary: true })}>Open repository</button>
            </div>
          )}
          {repo && messages.length === 0 && (
            <div className="empty-state chat-empty">
              <h1>What do you want to understand?</h1>
              <p>{allContextReady ? contextRepos.length > 1 ? `Ask across ${contextRepos.length} repositories in the current context.` : 'Ask about flow, ownership, symbols, tests, integrations, change impact, or where a feature should be implemented.' : 'The current repository context is still being indexed.'}</p>
              {allContextReady && (
                <div className="suggestions">
                  {[
                    'Map the high-level architecture of this repository context.',
                    'Where are the main entry points and what do they call?',
                    'Find the backend handlers and explain their dependencies.',
                    'How are tests and automation organized across the codebase?',
                  ].map(s => <button key={s} onClick={() => setInput(s)}>{s}</button>)}
                </div>
              )}
            </div>
          )}
          {messages.map(m => (
            <article id={m.id > 0 ? `message-${m.id}` : undefined} className={`message ${m.role}`} key={m.id}>
              <div className="message-avatar">{m.role === 'assistant' ? 'AI' : 'You'}</div>
              <div className="message-content">
                {m.reference && (
                  <button className="message-reference" onClick={() => document.getElementById(`message-${m.reference!.id}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })} title="Jump to referenced message">
                    <span className="message-reference-label">Referenced {m.reference.role === 'assistant' ? 'AI response' : 'user message'}</span>
                    <span className="message-reference-text">{m.reference.content.replace(/\s+/g, ' ').trim().slice(0, 180)}{m.reference.content.length > 180 ? '…' : ''}</span>
                  </button>
                )}
                <MessageBody text={m.content} />
                {m.role === 'assistant' && m.sources && m.sources.length > 0 && (
                  <div className="sources">
                    <div className="sources-label">Repository evidence</div>
                    <div className="source-chips">
                      {m.sources.slice(0, 12).map((s, idx) => (
                        <button key={`${m.id}-${idx}`} className={`source-chip ${s.stale ? 'stale' : ''}`} onClick={() => setSource(s)} title={s.stale ? 'This file has changed since the answer was generated' : `Open source${s.repository_name ? ` from ${s.repository_name}` : ''}`}>
                          <span>{contextRepos.length > 1 && s.repository_name ? `${s.repository_name} / ` : ''}{s.path.split('/').pop()}</span><small>{s.stale ? 'changed' : `${s.start_line}-${s.end_line}`}</small>
                        </button>
                      ))}
                    </div>
                  </div>
                )}
                {conversationId && m.id > 0 && m.role !== 'system' && (
                  <div className="message-actions">
                    <button
                      className="reference-message-button"
                      onClick={() => useAsReference(m)}
                      disabled={busy}
                      title="Refer to this message in your next prompt"
                    >
                      Reference
                    </button>
                    {m.role === 'assistant' && (
                      <button
                        className="branch-message-button"
                        onClick={() => openInNewBranch(m)}
                        disabled={busy || branchingMessageId != null}
                        title="Create a new conversation containing the history through this response"
                      >
                        {branchingMessageId === m.id ? 'Opening branch…' : 'Open in new branch'}
                      </button>
                    )}
                  </div>
                )}
              </div>
            </article>
          ))}
          {busy && (
            <article className="message assistant">
              <div className="message-avatar">AI</div>
              <div className="thinking"><span className="spinner"></span>Reading the repository context and reasoning locally…</div>
            </article>
          )}
        </div>

        <div className="composer-wrap">
          <div className={`composer ${referencedMessage ? 'has-reference' : ''}`}>
            {referencedMessage && (
              <div className="composer-reference">
                <div className="composer-reference-copy">
                  <span className="composer-reference-label">Referencing {referencedMessage.role === 'assistant' ? 'AI response' : 'your message'}</span>
                  <span className="composer-reference-text">{referencedMessage.content.replace(/\s+/g, ' ').trim().slice(0, 220)}{referencedMessage.content.length > 220 ? '…' : ''}</span>
                </div>
                <button className="composer-reference-clear" onClick={clearReference} aria-label="Clear reference" title="Clear reference">×</button>
              </div>
            )}
            <div className="composer-input-row">
              <textarea
                ref={composerInputRef}
                value={input}
                disabled={!repo || !allContextReady || busy}
                onChange={e => setInput(e.target.value)}
                onKeyDown={onComposerKey}
                placeholder={referencedMessage ? 'Ask about the referenced message…' : placeholder}
                rows={1}
              />
              <button className="send-button" disabled={!input.trim() || !allContextReady || busy} onClick={send}>Send</button>
            </div>
          </div>
          <div className="composer-note">Read-only repository analysis · chats and indexes stay on this Mac</div>
        </div>
      </main>

      {repo && source && <SourceDrawer repos={repos} fallbackRepo={repo} source={source} onClose={() => setSource(null)} />}

      {showRepoContext && repo && (
        <div className="modal-backdrop" onMouseDown={() => setShowRepoContext(false)}>
          <div className="settings-modal repository-context-modal" onMouseDown={e => e.stopPropagation()}>
            <div className="drawer-head">
              <div><div className="drawer-title">Repository context</div><div className="muted">Queries can retrieve evidence across multiple local repositories.</div></div>
              <button className="icon-button" onClick={() => setShowRepoContext(false)}>×</button>
            </div>
            <div className="repository-context-body">
              <div className="context-repository-options">
                {repos.map(r => {
                  const checked = r.id === repoId || repoContextDraft.includes(r.id)
                  return (
                    <label className="context-repository-option" key={r.id}>
                      <input type="checkbox" checked={checked} disabled={r.id === repoId} onChange={() => toggleDraftRepository(r.id)} />
                      <span className={`status-dot ${r.status}`}></span>
                      <span className="context-repository-copy"><strong>{r.name}</strong><small>{r.path}</small></span>
                      {r.id === repoId && <span className="primary-repo-label">Primary</span>}
                    </label>
                  )
                })}
              </div>
              <button className="secondary full" onClick={() => addRepository({ addToDraft: true })}>Open another repository</button>
            </div>
            <div className="modal-actions">
              <button className="secondary" onClick={() => setShowRepoContext(false)}>Cancel</button>
              <button className="primary-button" onClick={applyRepositoryContext}>Apply context</button>
            </div>
          </div>
        </div>
      )}

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
