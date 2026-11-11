"""Models, signal and encrypted field."""
import pytest
from django.db import connection

from core.models import UserSettings, Task, ChatMessage, EncryptedCharField, get_fernet

pytestmark = pytest.mark.django_db


def test_signal_creates_default_settings(user):
    s = UserSettings.objects.get(user=user)
    assert s.display_name == "alice"
    assert (s.theme, s.accent_color, s.ai_strategy, s.temperature) == ("cyberpunk", "cyan", "auto", 0.7)
    assert s.github_repo_url == "" and s.github_token == ""
    assert str(s) == "Settings for alice"


def test_signal_does_not_duplicate_on_resave(user):
    user.first_name = "A"
    user.save()
    assert UserSettings.objects.filter(user=user).count() == 1


def test_github_token_encrypted_at_rest_and_decrypted_on_read(user):
    s = user.settings
    s.github_token = "ghp_secret_token_123"
    s.save()
    with connection.cursor() as cur:
        cur.execute("SELECT github_token FROM core_usersettings WHERE id=%s", [s.id])
        raw = cur.fetchone()[0]
    assert raw != "ghp_secret_token_123"
    assert raw.startswith("gAAAAAB")
    assert get_fernet().decrypt(raw.encode()).decode() == "ghp_secret_token_123"
    assert UserSettings.objects.get(id=s.id).github_token == "ghp_secret_token_123"


def test_encrypted_field_does_not_double_encrypt():
    f = EncryptedCharField(max_length=255)
    once = f.get_prep_value("abc")
    assert f.get_prep_value(once) == once


def test_encrypted_field_legacy_plaintext_is_returned_as_is():
    f = EncryptedCharField(max_length=255)
    assert f.from_db_value("plain-legacy", None, None) == "plain-legacy"
    assert f.from_db_value("", None, None) == ""
    assert f.from_db_value(None, None, None) is None


def test_task_defaults_and_str(user):
    t = Task.objects.create(user=user, title="Write tests")
    assert t.status == "todo" and t.priority == "medium" and t.due_date is None and t.tags == ""
    assert str(t) == "Write tests (todo)"


def test_chat_message_ordering_and_str(user):
    m1 = ChatMessage.objects.create(user=user, role="user", content="hello world, long message")
    m2 = ChatMessage.objects.create(user=user, role="ai", content="answer")
    assert list(ChatMessage.objects.filter(user=user)) == [m1, m2]
    assert str(m1) == "alice - user: hello world, long me"


def test_user_delete_cascades(user):
    Task.objects.create(user=user, title="x")
    ChatMessage.objects.create(user=user, role="user", content="y")
    user.delete()
    assert Task.objects.count() == 0 and ChatMessage.objects.count() == 0 and UserSettings.objects.count() == 0
