#!/usr/bin/env python3
"""Release script for La Suite Calendars.

This script automates the release process by:
- Validating the release version (semver format)
- Optionally calculating the next version automatically
- Updating version files (backend pyproject.toml + uv.lock, frontend package.json)
- Updating the CHANGELOG
- Creating a release branch and pushing it

It is the calendars counterpart of suitenumerique/messages' bin/release.py and
follows the same workflow. Differences:
- the frontend uses pnpm; pnpm-lock.yaml does not store the project's own version
  so it needs no change on a version bump
- uv/pnpm are not required on the host: uv.lock's project entry is patched in
  place (the only change a version bump implies); run `make back-lock` afterwards
  if you want a full re-resolution
- the e2e package (src/e2e) keeps its own independent version and is left alone
"""

from __future__ import annotations

import argparse
import datetime
import re
import subprocess
import sys
from pathlib import Path
from typing import Literal

REPO = "suitenumerique/calendars"

RELEASE_KINDS = {"p": "patch", "m": "minor", "mj": "major"}
ReleaseKind = Literal["p", "m", "mj"]

SEMVER_PATTERN = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def run_command(
    cmd: str, shell: bool = False, capture_output: bool = False
) -> subprocess.CompletedProcess:
    """Run a shell command and return the result."""
    if capture_output:
        return subprocess.run(
            cmd, shell=shell, capture_output=True, text=True, check=False
        )
    subprocess.run(cmd, shell=shell, check=True)
    return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")


def get_current_version() -> str | None:
    """Extract current version from the backend pyproject.toml."""
    path = Path("src/backend/pyproject.toml")
    if not path.exists():
        return None
    match = re.search(
        r'^version\s*=\s*"([^"]+)"', path.read_text(), re.MULTILINE
    )
    return match.group(1) if match else None


def calculate_next_version(current: str, kind: ReleaseKind) -> str:
    """Calculate next version based on release kind."""
    match = SEMVER_PATTERN.match(current)
    if not match:
        raise ValueError(f"Current version '{current}' is not valid semver")

    major, minor, patch = map(int, match.groups())

    if kind == "mj":
        return f"{major + 1}.0.0"
    if kind == "m":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def validate_version(version: str) -> bool:
    """Validate that version follows semver format."""
    return bool(SEMVER_PATTERN.match(version))


def check_git_status() -> tuple[bool, str]:
    """Check if git working directory is clean and on main branch."""
    result = run_command("git status --porcelain", shell=True, capture_output=True)
    if result.stdout.strip():
        return False, "Working directory has uncommitted changes"

    result = run_command("git branch --show-current", shell=True, capture_output=True)
    current_branch = result.stdout.strip()
    if current_branch != "main":
        return False, f"Not on main branch (currently on '{current_branch}')"

    return True, ""


def check_changelog_has_unreleased() -> bool:
    """Check if CHANGELOG has entries in the Unreleased section."""
    path = Path("CHANGELOG.md")
    if not path.exists():
        return False

    match = re.search(
        r"## \[Unreleased\]\s*\n(.*?)(?=\n## \[|$)", path.read_text(), re.DOTALL
    )
    if not match:
        return False
    return bool(match.group(1).strip())


def update_files(version: str) -> None:
    """Update all files needed with the new release version."""
    # Backend: pyproject.toml
    sys.stdout.write("Updating backend pyproject.toml...\n")
    pyproject = Path("src/backend/pyproject.toml")
    content = pyproject.read_text()
    content = re.sub(
        r'^(version\s*=\s*)"[^"]+"', f'\\1"{version}"', content, count=1, flags=re.MULTILINE
    )
    pyproject.write_text(content)
    sys.stdout.write(f"  → {pyproject}\n")

    # Backend: uv.lock — patch the project's own entry so `uv sync --locked`
    # (used by the Docker build) stays satisfied without needing uv on the host.
    lock = Path("src/backend/uv.lock")
    if lock.exists():
        sys.stdout.write("Updating backend uv.lock...\n")
        lock_content = lock.read_text()
        lock_content, n = re.subn(
            r'(name = "calendars"\nversion = )"[^"]+"',
            f'\\1"{version}"',
            lock_content,
            count=1,
        )
        lock.write_text(lock_content)
        if n:
            sys.stdout.write(f"  → {lock}\n")
        else:
            sys.stdout.write(
                "  ⚠️  could not find the calendars entry in uv.lock; "
                "run `make back-lock` manually\n"
            )

    # Frontend: package.json (pnpm-lock.yaml has no project version → no change)
    sys.stdout.write("Updating frontend package.json...\n")
    package_json = Path("src/frontend/package.json")
    pkg_content = package_json.read_text()
    pkg_content = re.sub(
        r'("version":\s*)"[^"]+"', f'\\1"{version}"', pkg_content, count=1
    )
    package_json.write_text(pkg_content)
    sys.stdout.write(f"  → {package_json}\n")


def update_changelog(version: str) -> None:
    """Update the changelog: open a new version section and refresh compare links.

    Handles both the very first release (no compare-link footer yet) and
    subsequent releases.
    """
    sys.stdout.write("Updating CHANGELOG.md...\n")
    path = Path("CHANGELOG.md")
    content = path.read_text()
    today = datetime.date.today()
    base = f"https://github.com/{REPO}"

    if "## [Unreleased]" not in content:
        sys.stderr.write("❌ No '## [Unreleased]' section found in CHANGELOG.md\n")
        sys.exit(1)

    # 1. Open a new dated section right after [Unreleased].
    content = content.replace(
        "## [Unreleased]",
        f"## [Unreleased]\n\n## [{version}] - {today}",
        1,
    )

    # 2. Determine the previous released version from the footer links (if any).
    prev_match = re.search(r"^\[(\d+\.\d+\.\d+)\]:", content, re.MULTILINE)
    previous = prev_match.group(1) if prev_match else None

    unreleased_link = f"[unreleased]: {base}/compare/v{version}...HEAD"
    if previous:
        release_link = f"[{version}]: {base}/compare/v{previous}...v{version}"
    else:
        release_link = f"[{version}]: {base}/releases/tag/v{version}"

    if re.search(r"^\[unreleased\]:", content, re.MULTILINE | re.IGNORECASE):
        content = re.sub(
            r"^\[unreleased\]:.*$",
            unreleased_link,
            content,
            count=1,
            flags=re.MULTILINE | re.IGNORECASE,
        )
        content = content.replace(
            unreleased_link, f"{unreleased_link}\n{release_link}", 1
        )
    else:
        content = f"{content.rstrip()}\n\n{unreleased_link}\n{release_link}\n"

    path.write_text(content)


def print_next_steps(version: str, branch_name: str) -> None:
    """Print the manual steps to finish the release."""
    sys.stdout.write(
        f"""\033[1;34m- Create PR: https://github.com/{REPO}/compare/{branch_name}?expand=1
- After the PR is merged, tag the release on main:
   >> git checkout main
   >> git pull
   >> git tag v{version}
   >> git push origin v{version}
- Pushing the tag triggers .github/workflows/calendars-ghcr.yml which builds and
  publishes the versioned backend / frontend / caldav images.
\x1b[0m"""
    )


def create_release(version: str, kind: ReleaseKind, dry_run: bool = False) -> None:
    """Create the release branch, apply the version bump and push it."""
    branch_name = f"release/{version}"

    if dry_run:
        sys.stdout.write(f"\n[DRY-RUN] Would create branch: {branch_name}\n")
        sys.stdout.write("[DRY-RUN] Would update version files\n")
        sys.stdout.write("[DRY-RUN] Would update CHANGELOG\n")
        sys.stdout.write(f"[DRY-RUN] Would push to origin/{branch_name}\n")
        return

    sys.stdout.write(f"\nCreating release branch: {branch_name}\n")
    run_command(f"git checkout -b {branch_name}", shell=True)
    run_command("git pull --rebase origin main", shell=True)

    update_changelog(version)
    update_files(version)

    run_command("git add CHANGELOG.md src/", shell=True)

    message = (
        f"🔖({RELEASE_KINDS[kind]}) release version {version}\n\n"
        f"Update all version files and changelog for "
        f"{RELEASE_KINDS[kind]} release."
    )
    run_command(["git", "commit", "-m", message])

    confirm = (
        input(
            f"""
\033[0;32m### RELEASE ###
Ready to push branch '{branch_name}' to origin.
Continue? (y/n): \x1b[0m"""
        )
        .strip()
        .lower()
    )

    if confirm == "y":
        run_command(f"git push origin {branch_name}", shell=True)
        sys.stdout.write("\033[1;34m✅ Release branch pushed successfully!\x1b[0m\n")
    else:
        sys.stdout.write("\n⚠️  Push cancelled. Branch created locally.\n")
        sys.stdout.write(
            f"\033[1;34m- Push the release branch:\n"
            f">> git push origin {branch_name}\x1b[0m\n"
        )

    sys.stdout.write("\n\033[1;34mNEXT STEPS:\x1b[0m\n")
    print_next_steps(version, branch_name)


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Create a new release for calendars")
    parser.add_argument("--version", "-v", help="Release version (semver format)")
    parser.add_argument("--kind", "-k", choices=RELEASE_KINDS.keys(), help="Release kind")
    parser.add_argument(
        "--dry-run", "-n", action="store_true", help="Show what would be done"
    )
    parser.add_argument(
        "--skip-checks", action="store_true", help="Skip git status checks"
    )
    args = parser.parse_args()

    if not args.skip_checks:
        is_clean, error = check_git_status()
        if not is_clean:
            sys.stderr.write(f"\033[0;31m❌ {error}\033[0m\n")
            sys.stderr.write("Use --skip-checks to bypass this check.\n")
            sys.exit(1)

    current_version = get_current_version()
    if current_version:
        sys.stdout.write(f"Current version: {current_version}\n")

    kind = args.kind
    while kind not in RELEASE_KINDS:
        kind = input("Release kind (p=patch, m=minor, mj=major): ").strip()

    version = args.version
    if not version and current_version:
        suggested = calculate_next_version(current_version, kind)
        version = input(f"Version [{suggested}]: ").strip() or suggested

    while not version or not validate_version(version):
        if version:
            sys.stdout.write(f"❌ Invalid version format: '{version}' (expected: X.Y.Z)\n")
        version = input("Enter release version (X.Y.Z): ").strip()

    if not check_changelog_has_unreleased():
        sys.stdout.write(
            "\033[0;33m⚠️  Warning: No entries found in CHANGELOG [Unreleased] "
            "section\033[0m\n"
        )
        if input("Continue anyway? (y/n): ").strip().lower() != "y":
            sys.exit(0)

    sys.stdout.write(f"\n📦 Preparing {RELEASE_KINDS[kind]} release: v{version}\n")

    create_release(version, kind, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
