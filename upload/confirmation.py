from playwright.sync_api import TimeoutError as PWTimeout


def wait_for_success_text(page, texts, timeout: int = 12_000) -> bool:
    """Return True only when a post-action success message becomes visible."""
    try:
        page.wait_for_function(
            """(texts) => {
                const visible = [...document.querySelectorAll('body *')].filter(el => {
                    const style = window.getComputedStyle(el);
                    return style.visibility !== 'hidden' && style.display !== 'none';
                });
                return visible.some(el => {
                    const value = (el.textContent || '').trim().toLowerCase();
                    return texts.some(text => value === text.toLowerCase());
                });
            }""",
            arg=list(texts),
            timeout=timeout,
        )
        return True
    except PWTimeout:
        return False
