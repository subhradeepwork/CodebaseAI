from pathlib import Path


def test_chat_composer_is_outside_scroll_area_and_pinned_by_flex_layout():
    root = Path(__file__).resolve().parents[2]
    app = (root / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    css = (root / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")

    messages_pos = app.index('<div className="messages"')
    composer_pos = app.index('<div className="composer-wrap">')
    assert composer_pos > messages_pos
    assert '.main-panel { min-width: 0; height: 100%; min-height: 0; display: flex; flex-direction: column;' in css
    assert '.messages { flex: 1 1 auto; overflow-y: auto; min-height: 0;' in css
    assert '.composer-wrap {' in css
    assert 'flex: 0 0 auto;' in css
    assert 'height: 100dvh' in css


def test_sidebar_resize_collapse_and_repository_context_are_present():
    root = Path(__file__).resolve().parents[2]
    app = (root / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    css = (root / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")

    assert 'className="repo-plus"' in app
    assert 'Repository context' in app
    assert 'updateConversationRepositories' in app
    assert 'className="sidebar-resizer"' in app
    assert 'className="sidebar-toggle"' in app
    assert 'codebase-ai-sidebar-width' in app
    assert '.sidebar-resizer {' in css


def test_open_in_new_branch_action_is_wired_to_branch_api():
    root = Path(__file__).resolve().parents[2]
    app = (root / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    api = (root / "frontend" / "src" / "api.ts").read_text(encoding="utf-8")
    css = (root / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")

    assert "Open in new branch" in app
    assert "conversationId && m.id > 0 && m.role === 'assistant'" in app
    assert "m.role !== 'system'" not in app
    assert "openInNewBranch" in app
    assert "branchConversation" in app
    assert "/branch`" in api
    assert "branch_from_message_id" in api
    assert ".branch-message-button" in css
