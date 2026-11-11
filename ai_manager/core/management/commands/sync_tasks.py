"""manage.py sync_tasks — refresh the task cache from each user's tasks note (Round 3 / G-C4).

Run periodically in production (the compose `scheduler` service does it every
TASKS_SYNC_INTERVAL seconds). Sends queued offline operations first.
"""
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

from core import tasks_service
from core.models import UserSettings


class Command(BaseCommand):
    help = "Sync tasks between the Obsidian tasks note and the site cache."

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group()
        group.add_argument("--user", help="username to sync")
        group.add_argument("--all", action="store_true", help="every user with a connected vault (default)")
        parser.add_argument("--if-stale", action="store_true",
                            help="skip users synced less than TASKS_SYNC_INTERVAL seconds ago")

    def handle(self, *args, **options):
        if options["user"]:
            try:
                users = [User.objects.get(username=options["user"])]
            except User.DoesNotExist:
                raise CommandError(f"User {options['user']!r} not found.")
        else:
            ids = UserSettings.objects.exclude(github_repo_url="").values_list("user_id", flat=True)
            users = list(User.objects.filter(id__in=ids).order_by("id"))
        failures = 0
        for user in users:
            result = tasks_service.sync_tasks(user, force=not options["if_stale"])
            status = result.get("status")
            if status in ("ok", "fresh", "local"):
                self.stdout.write(f"{user.username}: {status}")
            else:
                failures += 1
                self.stderr.write(f"{user.username}: {status} — {result.get('error', '')}")
        self.stdout.write(f"synced {len(users) - failures}/{len(users)} user(s)")
