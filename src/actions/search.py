"""Google search — opens query in the default browser."""
import logging
import urllib.parse
import webbrowser

logger = logging.getLogger(__name__)


def google_search(query: str) -> str:
    """Open a Google search for *query* in the default browser.

    Args:
        query: The search string.

    Returns:
        Confirmation message string.
    """
    query = query.strip()
    if not query:
        return "What should I search for?"
    url = "https://www.google.com/search?q=" + urllib.parse.quote_plus(query)
    webbrowser.open(url)
    logger.debug("Opened search: %s", url)
    return f"Opened Google search for: {query}"
