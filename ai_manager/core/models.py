# Persistent Django data models for user preferences, tasks, and chat history.
# UserSettings extends Django's built-in User with per-account UI, AI, and vault
# configuration; EncryptedCharField protects repository credentials at rest.
# Signals provision default settings for newly created accounts.
from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from cryptography.fernet import Fernet
from django.conf import settings
import base64

# Build the Fernet cipher used by the encrypted repository-token field.
# The key is derived from Django's SECRET_KEY so deployment configuration is
# required to decrypt stored credentials.
def get_fernet():
    """
    Derive the credential-encryption key from the current Django SECRET_KEY.
    A database copy alone is insufficient to decrypt repository tokens.
    """
    key = settings.SECRET_KEY.encode('utf-8')[:32].ljust(32, b'0')
    return Fernet(base64.urlsafe_b64encode(key))

class EncryptedCharField(models.CharField):
    # Transparently decrypt values read from the database and encrypt values
    # prepared for persistence, while allowing legacy plaintext rows to load.
    """
    Custom database field that transparently encrypts text when saving and decrypts it when reading in Python.
    This ensures that sensitive data like GitHub tokens are stored securely in the database.
    """
    def from_db_value(self, value, expression, connection):
        # Convert ciphertext into application text; retain the original value if
        # it is blank, legacy plaintext, or cannot be decrypted with this key.
        if not value:
            return value
        try:
            return get_fernet().decrypt(value.encode('utf-8')).decode('utf-8')
        except Exception:
            return value

    def get_prep_value(self, value):
        # Avoid double-encrypting already encrypted values before database writes.
        if not value:
            return value
        if value.startswith('gAAAAAB'):
            return value
        return get_fernet().encrypt(value.encode('utf-8')).decode('utf-8')

# The following models represent account preferences, work items, and persisted chat.

class UserSettings(models.Model):
    # One settings row belongs to exactly one Django account.
    AI_STRATEGY_CHOICES = [
        ('auto', 'Auto-Hybrid'),
        ('local_only', 'Strictly Local'),
        ('cloud_only', 'Cloud Only'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='settings')
    display_name = models.CharField(max_length=100, blank=True)
    theme = models.CharField(max_length=20, default='cyberpunk')
    accent_color = models.CharField(max_length=20, default='cyan')
    ai_strategy = models.CharField(max_length=20, choices=AI_STRATEGY_CHOICES, default='auto')
    temperature = models.FloatField(default=0.7)

    github_repo_url = models.URLField(max_length=500, blank=True, default="")
    # 500: a Fernet-encrypted 128+ character token is longer than 255 (B-14).
    github_token = EncryptedCharField(max_length=500, blank=True, default="")

    # Which model answered last (Round 2 indicator on Home/Settings).
    last_model_used = models.CharField(max_length=100, blank=True, default="")
    last_model_at = models.DateTimeField(null=True, blank=True)

    # Tasks note in the vault (Round 3 / G-C1): empty = settings.TASKS_NOTE_PATH.
    tasks_note_path = models.CharField(max_length=300, blank=True, default="")
    tasks_last_sync = models.DateTimeField(null=True, blank=True)
    tasks_sync_error = models.TextField(blank=True, default="")

    # Round 4: cloud provider for chat/agent (Gemini or Claude), Claude model, agent option.
    CLOUD_PROVIDER_CHOICES = [('gemini', 'Gemini'), ('claude', 'Claude')]
    cloud_provider = models.CharField(max_length=20, choices=CLOUD_PROVIDER_CHOICES, default='gemini')
    claude_model = models.CharField(max_length=40, blank=True, default='')
    agent_auto_apply_additions = models.BooleanField(default=False)

    def __str__(self):
        # Provide a concise identifier for Django admin and diagnostic output.
        return f"Settings for {self.user.username}"

class Task(models.Model):
    # A user-owned task with workflow status, urgency, optional due date, and tags.
    STATUS_CHOICES = [
        ('todo', 'To Do'),
        ('in_progress', 'In Progress'),
        ('done', 'Done'),
        ('cancelled', 'Cancelled'),     # - [-] in the tasks note (Round 3)
        ('forwarded', 'Forwarded'),     # - [>] moved to another week (Round 5)
    ]
    
    PRIORITY_CHOICES = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('urgent', 'Urgent')
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='tasks')
    title = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='todo')
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='medium')
    due_date = models.DateField(null=True, blank=True)
    tags = models.CharField(max_length=100, blank=True) 
    created_at = models.DateTimeField(auto_now_add=True)

    # Round 3: with a connected vault this row is a CACHE of one line of the tasks
    # note (docs/TASKS_FORMAT.md); the note is the source of truth.
    vault_id = models.CharField(max_length=16, blank=True, default="", db_index=True)   # 🆔
    vault_line = models.TextField(blank=True, default="")     # raw line (identifies lines without 🆔)
    section = models.CharField(max_length=120, blank=True, default="")
    position = models.IntegerField(default=0)
    synced = models.BooleanField(default=True)                # False = waiting in VaultOutbox

    @property
    def tag_list(self):
        return [tag.strip().lstrip('#') for tag in (self.tags or '').split(',') if tag.strip()]

    def __str__(self):
        # Include the current workflow state in task representations.
        return f"{self.title} ({self.status})"
    
class VaultOutbox(models.Model):
    """Vault operations waiting for GitHub to be reachable again (Round 3 / G-C5)."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='vault_outbox')
    kind = models.CharField(max_length=20, default='tasks')
    op = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    attempts = models.IntegerField(default=0)
    last_error = models.TextField(blank=True, default="")

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f"{self.user.username}: {self.kind} {self.op.get('op')}"


class AgentBatch(models.Model):
    """Changes proposed by the AI agent; applied only after confirmation (Round 4 / G-E3)."""
    STATUS_CHOICES = [('pending', 'ожидает'), ('partial', 'применён частично'), ('applied', 'применён'),
                      ('rejected', 'отклонён'), ('reverted', 'откачен')]
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='agent_batches')
    request = models.CharField(max_length=500)
    provider = models.CharField(max_length=60, blank=True, default='')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    changes = models.JSONField(default=list)        # [{kind, path, diff, after, pending, op}]
    commits = models.JSONField(default=list)        # shas of the "ai: …" commits
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-id']


class ApiToken(models.Model):
    """Personal REST API token (Round 4 / G-API1). Only the SHA-256 hash is stored.

    Rights (Link2Note contract): scopes read / write / delete / ai; ``write_paths`` and
    ``delete_paths`` limit write/delete to these folders or notes (whole path segments);
    an empty list means the whole vault.
    """
    SCOPES = ('read', 'write', 'delete', 'ai')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='api_tokens')
    name = models.CharField(max_length=60)
    prefix = models.CharField(max_length=12)
    token_hash = models.CharField(max_length=64, unique=True)
    scopes = models.JSONField(default=list)
    write_paths = models.JSONField(default=list, blank=True)
    delete_paths = models.JSONField(default=list, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-id']

    @classmethod
    def create_for(cls, user, name, scopes, expires_at=None, write_paths=None, delete_paths=None):
        import hashlib
        import secrets
        scopes = [s for s in cls.SCOPES if s in (scopes or [])]
        if not scopes:
            raise ValueError("Нужно хотя бы одно право: read, write или ai.")
        raw = "sb_" + secrets.token_urlsafe(32)
        obj = cls.objects.create(user=user, name=str(name or "token")[:60], prefix=raw[:10],
                                 token_hash=hashlib.sha256(raw.encode()).hexdigest(), scopes=scopes, expires_at=expires_at,
                                 write_paths=clean_rights_paths(write_paths), delete_paths=clean_rights_paths(delete_paths))
        return obj, raw

    @classmethod
    def authenticate(cls, raw):
        import hashlib
        from django.utils import timezone
        if not raw or not str(raw).startswith("sb_"):
            return None
        token = cls.objects.select_related('user').filter(
            token_hash=hashlib.sha256(str(raw).encode()).hexdigest(), revoked_at__isnull=True).first()
        if token is None or (token.expires_at and token.expires_at <= timezone.now()) or not token.user.is_active:
            return None
        return token

    def touch(self):
        from django.utils import timezone
        ApiToken.objects.filter(pk=self.pk).update(last_used_at=timezone.now())

    @property
    def active(self):
        from django.utils import timezone
        return self.revoked_at is None and (self.expires_at is None or self.expires_at > timezone.now())


def clean_rights_paths(paths):
    """Normalise token rights paths: NFC, '/' separators, no empty / '..' / hidden segments."""
    import unicodedata
    if isinstance(paths, str):
        paths = paths.replace(';', '\n').splitlines()
    out = []
    for raw in paths or []:
        rel = unicodedata.normalize('NFC', str(raw).replace('\\', '/').strip().strip('/'))
        if not rel:
            continue
        parts = rel.split('/')
        if any(p in ('', '.', '..') or p.startswith('.') or ':' in p for p in parts):
            raise ValueError(f"Недопустимый путь в правах токена: {raw}")
        if rel not in out:
            out.append(rel)
    return out


class IdempotencyRecord(models.Model):
    """Stored final answer of a mutating API request by ``Idempotency-Key`` (kept ≥ 7 days)."""
    token = models.ForeignKey(ApiToken, on_delete=models.CASCADE, related_name='idempotency_records')
    key = models.CharField(max_length=200)
    fingerprint = models.CharField(max_length=64)
    in_progress = models.BooleanField(default=True)
    status = models.IntegerField(default=0)
    body = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['token', 'key'], name='uniq_idempotency_key_per_token')]


class ApiCallLog(models.Model):
    """API call journal without bodies or note contents (also used for the rate limit)."""
    token = models.ForeignKey(ApiToken, on_delete=models.CASCADE, related_name='calls')
    method = models.CharField(max_length=10)
    path = models.CharField(max_length=200)
    status = models.IntegerField()
    duration_ms = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)


class ChatMessage(models.Model):
    # Store each user or assistant turn so the chat page can restore recent history.
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='chat_messages')
    role = models.CharField(max_length=10) 
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at'] 

    def __str__(self):
        # Keep administrative list labels short while preserving the message role.
        return f"{self.user.username} - {self.role}: {self.content[:20]}"

    # Provision defaults immediately after Django creates a new user so application
    # views can safely access the related settings row.
@receiver(post_save, sender=User)
def create_user_settings(sender, instance, created, **kwargs):
    if created:
        UserSettings.objects.create(
            user=instance, 
            display_name=instance.username,
            theme='cyberpunk',
            accent_color='cyan',
            ai_strategy='auto',
            temperature=0.7,
            github_repo_url="",
            github_token=""
        )

def get_user_settings(user):
    """Return the user's settings row, recreating it with defaults if it is missing (B-07).

    The row can be missing for accounts created before the post_save signal
    existed, or after an administrator deleted it in Core Matrix; previously
    every page then crashed with RelatedObjectDoesNotExist.
    """
    try:
        return user.settings
    except UserSettings.DoesNotExist:
        settings_row, _ = UserSettings.objects.get_or_create(
            user=user, defaults={'display_name': user.username}
        )
        user.settings = settings_row
        return settings_row
