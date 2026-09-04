from pathlib import Path


def test_chat_composer_is_outside_scroll_area_and_pinned_by_flex_layout():
    root = Path(__file__).resolve().parents[2]
    app = (root / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
    css = (root / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")

    # The composer must be a sibling of the scrollable messages region, never
    # inside it. A column flex shell gives the message region only the remaining
    # viewport height and reserves the final row for the composer.
    messages_pos = app.index('<div className="messages"')
    composer_pos = app.index('<div className="composer-wrap">')
    assert composer_pos > messages_pos
    assert '.main-panel { min-width: 0; height: 100%; min-height: 0; display: flex; flex-direction: column;' in css
    assert '.messages { flex: 1 1 auto; overflow-y: auto; min-height: 0;' in css
    assert '.composer-wrap {' in css
    assert 'flex: 0 0 auto;' in css
    assert 'height: 100dvh' in css
