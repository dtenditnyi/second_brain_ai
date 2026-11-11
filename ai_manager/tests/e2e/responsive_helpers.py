"""Shared data seeding and layout metrics for responsive tests/screenshots."""
from core.models import Task, ChatMessage
from tests.conftest import write_note

WIDTHS = [360, 390, 768, 1024, 1440]
HEIGHT = {360: 780, 390: 844, 768: 1024, 1024: 768, 1440: 900}

# Round 2 screenshot matrix: (label, width, height) — phones, tablets (incl.
# landscape), desktops and a phone in landscape (667x375).
SHOT_SIZES = [
    ("320", 320, 568), ("375", 375, 667), ("390", 390, 844), ("414", 414, 896),
    ("768", 768, 1024), ("834", 834, 1194), ("1024", 1024, 768),
    ("1280", 1280, 800), ("1440", 1440, 900), ("1920", 1920, 1080),
    ("667x375", 667, 375),
]

# name -> (path, needs_admin, optional action to run after load)
PAGES = {
    "login": ("/login/", None, None),
    "register": ("/register/", None, None),
    "home": ("/", "user", None),
    "chat": ("/chat/", "user", None),
    "chat-modal": ("/chat/", "user", "open_context_modal"),
    "notes": ("/notes/?file=Project%20Overview", "user", "wait_note"),
    "tasks": ("/tasks/", "user", None),
    "tasks-modal": ("/tasks/", "user", "open_task_modal"),
    "settings": ("/settings/", "user", None),
    "system-matrix": ("/system-matrix/", "admin", None),
    "system-matrix-tasks": ("/system-matrix/", "admin", "admin_tasks_tab"),
}


def seed(user, vault):
    """Realistic content so layout problems (long names, many items) show up."""
    for i, (title, prio, tags) in enumerate([
        ("Prepare quarterly review presentation for the whole engineering department", "urgent", "work, slides"),
        ("Refactor the retrieval pipeline", "high", "coding"),
        ("Buy groceries", "low", "home"),
        ("Read 'Designing Data-Intensive Applications' chapter 7", "medium", "reading"),
    ]):
        Task.objects.create(user=user, title=title, priority=prio, tags=tags, due_date=f"2026-12-0{i + 1}")
    Task.objects.create(user=user, title="Set up Cloudflare tunnel", status="in_progress", tags="infra")
    Task.objects.create(user=user, title="Write audit report", status="done")
    write_note(vault, user, "Project Overview", "# Project Overview\n\nA very long line of text " * 8 +
               "\n\n| Column A | Column B | Column C | Column D |\n|---|---|---|---|\n| value one | value two | value three | value four |\n\n"
               "```python\nprint('a fairly long code line that should not break the layout of the page at all')\n```\n\nSee [[Ideas]].")
    write_note(vault, user, "Ideas", "Link back to [[Project Overview]].")
    for i in range(12):
        write_note(vault, user, f"Daily note 2026-11-{i + 1:02d} with a rather long file name", "content")
    ChatMessage.objects.create(user=user, role="user", content="Summarise my project notes please")
    ChatMessage.objects.create(user=user, role="ai", content="Here is a summary of your notes: " + "lorem ipsum " * 30)


def run_action(page, action):
    if action == "open_context_modal":
        page.click("#add-documents-button")
    elif action == "open_task_modal":
        page.click("header button.btn-primary")
    elif action == "wait_note":
        page.wait_for_selector("#workspace-content-area .markdown-body", state="attached")
    elif action == "admin_tasks_tab":
        page.click('[data-tab="tasks-table"]')
    page.wait_for_timeout(250)


METRICS_JS = """
() => {
  const vw = document.documentElement.clientWidth;
  const res = {vw, docScroll: document.documentElement.scrollWidth, bodyScroll: document.body.scrollWidth,
               overflowing: [], smallTargets: [], tinyText: 0, scrollers: []};
  const visible = el => {
    const s = getComputedStyle(el);
    if (s.visibility === 'hidden' || s.display === 'none' || parseFloat(s.opacity) === 0) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const insideOffCanvas = el => { const sb = el.closest('#main-sidebar'); return sb && sb.getBoundingClientRect().right <= 0; };
  const label = el => el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') +
      (el.className && typeof el.className === 'string' ? '.' + el.className.split(' ').slice(0, 3).join('.') : '');
  const srOnly = el => { const r = el.getBoundingClientRect(); return r.width <= 1 || r.height <= 1; };
  // WCAG 2.5.8 exempts links inside running text (markdown, hints, sentences).
  const inlineLink = el => el.tagName === 'A' && !!el.closest('.markdown-body, .field-hint, .empty-state, p');
  const clippedByScroller = el => {
    for (let p = el.parentElement; p; p = p.parentElement) {
      const ox = getComputedStyle(p).overflowX;
      if ((ox === 'auto' || ox === 'scroll') && p.scrollWidth > p.clientWidth) return true;
    }
    return false;
  };
  for (const el of document.querySelectorAll('body *')) {
    if (!visible(el) || insideOffCanvas(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.right > vw + 1 && !clippedByScroller(el) && res.overflowing.length < 15) res.overflowing.push(label(el) + ' right=' + Math.round(r.right));
    if (el.matches('a, button, input:not([type=hidden]), select, textarea') && !srOnly(el) && !inlineLink(el)) {
      // A checkbox/radio is tapped through its wrapping <label> (the 44px hit zone).
      const hit = el.matches('input[type=checkbox], input[type=radio]') && el.closest('label')
        ? el.closest('label').getBoundingClientRect() : r;
      if ((hit.height < 43.5 || hit.width < 43.5) && res.smallTargets.length < 40)
        res.smallTargets.push(label(el) + ' ' + Math.round(hit.width) + 'x' + Math.round(hit.height));
    }
    if (el.childNodes.length && [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim()) &&
        parseFloat(getComputedStyle(el).fontSize) < 12) res.tinyText++;
    const ox = getComputedStyle(el).overflowX;
    if ((ox === 'auto' || ox === 'scroll') && el.scrollWidth > el.clientWidth + 1) res.scrollers.push(label(el));
  }
  return res;
}
"""
