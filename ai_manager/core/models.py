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
    github_token = EncryptedCharField(max_length=255, blank=True, default="")

    def __str__(self):
        # Provide a concise identifier for Django admin and diagnostic output.
        return f"Settings for {self.user.username}"

class Task(models.Model):
    # A user-owned task with workflow status, urgency, optional due date, and tags.
    STATUS_CHOICES = [
        ('todo', 'To Do'),
        ('in_progress', 'In Progress'),
        ('done', 'Done')
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

    def __str__(self):
        # Include the current workflow state in task representations.
        return f"{self.title} ({self.status})"
    
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
