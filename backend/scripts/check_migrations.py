"""CI guard (spec §13): a migration that is already on `main` must never be edited.

New revisions are always fine; rewriting history is not. Falls back to "no baseline yet" when
`origin/main` has no migrations (first merge), so it never blocks the very first migration set.
"""

from __future__ import annotations

import subprocess

PREFIX = "backend/migrations/versions/"


def _git(*args: str) -> str:
    result = subprocess.run(("git", *args), capture_output=True, text=True, check=False)
    return result.stdout if result.returncode == 0 else ""


def main() -> int:
    base = next((ref for ref in ("origin/main", "main") if _git("rev-parse", "--verify", ref.strip())), "")
    if not base:
        print("no base branch to compare against — skipping")
        return 0
    merged = {line.strip() for line in _git("ls-tree", "-r", "--name-only", base, "--", PREFIX).splitlines() if line.strip()}
    if not merged:
        print("base branch has no migrations yet — first migration set, nothing to protect")
        return 0
    changed = {line.split("\t")[-1].strip() for line in _git("diff", "--name-only", f"{base}...HEAD", "--", PREFIX).splitlines()}
    touched_status = {
        parts[0]: parts[1]
        for parts in (line.split("\t") for line in _git("diff", "--name-status", f"{base}...HEAD", "--", PREFIX).splitlines())
        if len(parts) == 2
    }
    edited = sorted({path for path, status in touched_status.items() if status in {"M", "D"} and path in merged} | (changed & merged))
    if edited:
        print("ERROR: already-merged migration(s) touched:")
        for name in edited:
            print(f"  - {name}   (add a new revision instead of editing a merged one)")
        return 1
    added = sorted({path for path, status in touched_status.items() if status == "A"} - merged)
    print(f"migration immutability ok ({len(merged)} merged, {len(added)} new)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
