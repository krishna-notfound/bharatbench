import pytest

from app.conversations.store import MemoryConversationStore, set_conversation_store


@pytest.fixture(autouse=True)
def _in_memory_conversations():
    """Realtime tests must never touch a real Supabase project, whatever api/.env says."""
    set_conversation_store(MemoryConversationStore())
    yield
    set_conversation_store(None)
