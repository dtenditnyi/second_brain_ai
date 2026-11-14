"""manage.py export_tasks_to_note — move the old database tasks into the tasks note (Round 3 / G-C6).

    python manage.py export_tasks_to_note --user USERNAME --dry-run   # print the resulting note, write nothing
    python manage.py export_tasks_to_note --user USERNAME             # commit + push once

Only tasks that were never in the note are exported (they get a 🆔 and are
linked to their line), so running it again adds nothing. Tags outside the
allowed list are dropped and reported. Never run it against the production
database by accident: see docs/DEPLOY.md ("Перенос со старого ПК").
"""
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

from core import tasks_service
from core.vault_writer import VaultError


class Command(BaseCommand):
    help = "Export database-only tasks of a user into their Obsidian tasks note."

    def add_arguments(self, parser):
        parser.add_argument("--user", required=True)
        parser.add_argument("--dry-run", action="store_true", help="show the resulting note, change nothing")

    def handle(self, *args, **options):
        try:
            user = User.objects.get(username=options["user"])
        except User.DoesNotExist:
            raise CommandError(f"User {options['user']!r} not found.")
        if not tasks_service.vault_configured(user):
            raise CommandError("This user has no GitHub vault configured (Settings → repository URL).")
        try:
            if options["dry_run"]:
                text, count, dropped = tasks_service.export_preview(user)
                self.stdout.write(f"--- {tasks_service.tasks_note_path(user)} (dry run: {count} task(s) would be added) ---")
                self.stdout.write(text)
            else:
                count, dropped = tasks_service.export_to_note(user)
                self.stdout.write(f"exported {count} task(s) to {tasks_service.tasks_note_path(user)}")
        except (VaultError, tasks_service.TaskSyncError) as error:
            raise CommandError(str(error))
        if dropped:
            self.stdout.write("tags not in the allowed list were dropped: " + ", ".join(dropped))
