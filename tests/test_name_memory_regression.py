
from conduit.conversation.session import ConversationSession
from conduit.memory.learning import LongTermMemoryLearner
from conduit.memory.models import MemoryCategory


def test_name_recall_is_history_aware():
    assert ConversationSession._message_needs_history("what is my name") is True
    assert ConversationSession._message_needs_history("What's my name?") is True


def test_name_learning_persists_explicit_name():
    class Repo:
        def upsert_directive(self, *a, **k): pass
        def increment_behavior(self, *a, **k): pass
    class Manager:
        def __init__(self):
            self.repository = Repo()
            self.saved = []
        def remember(self, key, value, **kwargs):
            self.saved.append((key, value, kwargs))
    manager = Manager()
    LongTermMemoryLearner(manager).observe("my name is Ali", "Nice to meet you.")
    assert manager.saved
    key, value, kwargs = manager.saved[0]
    assert key == "user:name"
    assert value == "Ali"
    assert kwargs["source"] == "explicit_user_fact"


def test_name_learning_handles_natural_introduction_with_other_facts():
    class Repo:
        def upsert_directive(self, *a, **k): pass
        def increment_behavior(self, *a, **k): pass
    class Manager:
        def __init__(self):
            self.repository = Repo()
            self.saved = []
        def remember(self, key, value, **kwargs):
            self.saved.append((key, value, kwargs))
    manager = Manager()
    LongTermMemoryLearner(manager).observe("Hi my name is Ali and I like to automate things")
    assert manager.saved
    assert manager.saved[0][0] == "user:name"
    assert manager.saved[0][1] == "Ali"


def test_useful_preferences_are_learned_from_same_natural_sentence():
    class Repo:
        def upsert_directive(self, *a, **k): pass
        def increment_behavior(self, *a, **k): pass
    class Manager:
        def __init__(self):
            self.repository = Repo()
            self.saved = []
        def remember(self, key, value, **kwargs):
            self.saved.append((key, value, kwargs))
    manager = Manager()
    LongTermMemoryLearner(manager).observe("my name is ALi nad i like to automate things")
    saved = {(key, value) for key, value, _ in manager.saved}
    assert ("user:name", "ALi") in saved
    assert ("user:likes", "automate things") in saved


def test_useful_preference_learning_is_not_hardcoded_to_automation():
    class Repo:
        def upsert_directive(self, *a, **k): pass
        def increment_behavior(self, *a, **k): pass
    class Manager:
        def __init__(self):
            self.repository = Repo()
            self.saved = []
        def remember(self, key, value, **kwargs):
            self.saved.append((key, value, kwargs))
    manager = Manager()
    learner = LongTermMemoryLearner(manager)
    learner.observe("I enjoy editing videos and I work as a teacher")
    saved = {(key, value) for key, value, _ in manager.saved}
    assert ("user:likes", "editing videos") in saved
    assert ("user:occupation", "teacher") in saved


def test_preference_recall_is_history_aware():
    assert ConversationSession._message_needs_history("what do i like to do?") is True
