"""
Frontmatter validator for the 777 knowledge-base vault.

Reads schema from schema.json (same directory as this script).

THREE MODES
-----------
1. Claude Code pre-write hook mode:
    Called by Claude Code PreToolUse hook with no CLI arguments.
    Reads hook JSON from stdin (fields: tool_name, tool_input with file_path,
    and for Write: content; Edit: old_string/new_string/replace_all;
    MultiEdit: edits array).  Computes the prospective final file content,
    determines the zone, validates frontmatter.
    Exit 0 = allow.  Exit 2 + stderr message = block (Claude Code surfaces
    the stderr as the error reason).

2. Codex CLI post-write hook mode:
    Called by Codex PostToolUse hook with no CLI arguments.
    Reads hook JSON from stdin (fields: tool_name == "apply_patch",
    tool_input.command = patch text, cwd = vault root).
    Parses patch header lines to find Add/Update File paths; resolves each
    against cwd; validates the file ON DISK (post-write).
    For Add File paths not yet on disk (edge case), reconstructs content
    from the patch's + lines and validates that.
    Exit 0 = allow.  Exit 2 + stderr message = block (Codex surfaces the
    reason and the model fixes it).

3. CLI mode:
    Invoked as: python3 validate.py <file.md> [<file2.md> ...]
    Reads each file from disk, prints PASS/FAIL per file.
    Exits non-zero if any file fails.
"""

import json
import os
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Schema loading
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).parent.resolve()


def load_schema():
    schema_path = SCRIPT_DIR / "schema.json"
    with open(schema_path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Minimal YAML frontmatter parser
# ---------------------------------------------------------------------------

def extract_frontmatter(text):
    """Return the raw frontmatter block (between --- fences) or None."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    end = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end = i
            break
    if end is None:
        return None
    return lines[1:end]


def parse_frontmatter(lines):
    """
    Parse a list of frontmatter lines into a dict.
    Supports:
      key: scalar_value
      key: [a, b, c]         (inline list)
      key:                   (followed by - item block lines)
      key: []                (empty inline list)
    Returns dict of {key: value_or_list}.
    """
    result = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r'^(\w[\w-]*):\s*(.*)', line)
        if m:
            key = m.group(1)
            raw = m.group(2).strip()
            if raw.startswith('[') and raw.endswith(']'):
                # Inline list: [a, b] or []
                inner = raw[1:-1].strip()
                if not inner:
                    result[key] = []
                else:
                    result[key] = [v.strip().strip('"\'') for v in inner.split(',') if v.strip()]
            elif raw == '' or raw is None:
                # Possibly a block list follows
                block_items = []
                j = i + 1
                while j < len(lines) and re.match(r'^\s*-\s+(.+)', lines[j]):
                    bm = re.match(r'^\s*-\s+(.*)', lines[j])
                    if bm:
                        block_items.append(bm.group(1).strip())
                    j += 1
                if block_items:
                    result[key] = block_items
                    i = j
                    continue
                else:
                    result[key] = ''
            else:
                result[key] = raw
        i += 1
    return result


# ---------------------------------------------------------------------------
# Validation logic
# ---------------------------------------------------------------------------

DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


def validate_content(content, zone, schema):
    """
    Validate frontmatter of file content against schema for the given zone.
    Returns (ok: bool, error_message: str or None).
    """
    zone_schema = schema["zones"].get(zone)
    if zone_schema is None:
        return True, None

    fm_lines = extract_frontmatter(content)
    if fm_lines is None:
        return False, (
            f"Zone '{zone}' requires YAML frontmatter (--- ... ---) but none was found."
        )

    fm = parse_frontmatter(fm_lines)
    required = zone_schema.get("required", [])
    status_enum = zone_schema.get("status_enum")
    date_fields = schema.get("date_fields", [])

    errors = []

    for field in required:
        if field not in fm:
            errors.append(f"Missing required field: '{field}'")
        elif field == "links":
            # links: [] is allowed (present but empty list)
            pass
        else:
            val = fm[field]
            if isinstance(val, list):
                if len(val) == 0:
                    errors.append(f"Field '{field}' must not be empty.")
            elif val == '' or val is None:
                errors.append(f"Field '{field}' must not be empty.")

    if not errors and status_enum is not None:
        status_val = fm.get("status", "")
        if status_val not in status_enum:
            errors.append(
                f"Field 'status' has invalid value '{status_val}'. "
                f"Allowed values for zone '{zone}': {status_enum}"
            )

    if not errors:
        for df in date_fields:
            if df in fm:
                val = fm[df]
                if isinstance(val, str) and not DATE_RE.match(val):
                    errors.append(
                        f"Field '{df}' must be a date in YYYY-MM-DD format, got: '{val}'"
                    )

    if errors:
        return False, "\n".join(errors)
    return True, None


# ---------------------------------------------------------------------------
# Path → zone resolution
# ---------------------------------------------------------------------------

# Directories that mark a project root (in priority order after env var)
_ROOT_MARKERS = (".claude", ".codex", ".obsidian")


def resolve_zone(file_path_str, schema, cwd=None):
    """
    Given an absolute (or relative) file path, determine the zone name.
    Zone = first path segment under the project root.
    Returns (zone: str or None, in_enforced: bool).

    Project-root resolution order:
      1. $CLAUDE_PROJECT_DIR env var
      2. Walk up from file location looking for .claude, .codex, or .obsidian
      3. cwd argument (used when file path is relative, e.g. from Codex payload)
      4. Script-relative fallback: parent of the _meta/ directory
    """
    enforced = schema.get("enforced_zones", [])

    # Resolve file path: if relative, anchor to cwd first
    raw_path = Path(file_path_str)
    if not raw_path.is_absolute() and cwd:
        raw_path = Path(cwd) / raw_path
    file_path = raw_path.resolve()

    # Determine project root
    project_root = None
    env_root = os.environ.get("CLAUDE_PROJECT_DIR")
    if env_root:
        project_root = Path(env_root).resolve()
    else:
        # Walk up from file location looking for any root marker
        candidate = file_path.parent
        for _ in range(20):
            for marker in _ROOT_MARKERS:
                if (candidate / marker).exists():
                    project_root = candidate
                    break
            if project_root is not None:
                break
            parent = candidate.parent
            if parent == candidate:
                break
            candidate = parent

        if project_root is None and cwd:
            # Try walking up from cwd as well
            candidate = Path(cwd).resolve()
            for _ in range(20):
                for marker in _ROOT_MARKERS:
                    if (candidate / marker).exists():
                        project_root = candidate
                        break
                if project_root is not None:
                    break
                parent = candidate.parent
                if parent == candidate:
                    break
                candidate = parent

        if project_root is None:
            project_root = Path(__file__).resolve().parent.parent

    try:
        rel = file_path.relative_to(project_root)
    except ValueError:
        return None, False

    parts = rel.parts
    if not parts:
        return None, False

    zone = parts[0]
    return zone, (zone in enforced)


# ---------------------------------------------------------------------------
# Prospective content computation (for Claude Code hook mode)
# ---------------------------------------------------------------------------

def apply_edit(current, old_string, new_string, replace_all=False):
    if replace_all:
        return current.replace(old_string, new_string)
    return current.replace(old_string, new_string, 1)


def compute_prospective_content(tool_name, tool_input, file_path):
    """
    Given tool name and input dict, return the prospective file content
    after the tool call would execute.
    """
    if tool_name == "Write":
        return tool_input.get("content", "")

    # For Edit / MultiEdit we need the current file on disk
    try:
        with open(file_path, encoding="utf-8") as f:
            current = f.read()
    except (FileNotFoundError, OSError):
        current = ""

    if tool_name == "Edit":
        old_s = tool_input.get("old_string", "")
        new_s = tool_input.get("new_string", "")
        replace_all = tool_input.get("replace_all", False)
        return apply_edit(current, old_s, new_s, replace_all)

    if tool_name == "MultiEdit":
        content = current
        for edit in tool_input.get("edits", []):
            old_s = edit.get("old_string", "")
            new_s = edit.get("new_string", "")
            replace_all = edit.get("replace_all", False)
            content = apply_edit(content, old_s, new_s, replace_all)
        return content

    return ""


# ---------------------------------------------------------------------------
# apply_patch parser (for Codex hook mode)
# ---------------------------------------------------------------------------

# Matches: *** Add File: relative/path.md
#          *** Update File: relative/path.md
_PATCH_FILE_RE = re.compile(r'^\*\*\* (Add|Update) File: (.+)$')
_PATCH_DELETE_RE = re.compile(r'^\*\*\* Delete File:')


def parse_apply_patch(command_text):
    """
    Parse an OpenAI apply_patch command string.
    Returns a list of (operation, relative_path, content_lines) tuples where:
      operation  = "Add" | "Update"
      relative_path = path string from the header
      content_lines = list of added lines ('+' stripped) for Add File sections;
                      empty list for Update (on-disk validation preferred)
    """
    results = []
    lines = command_text.splitlines()

    current_op = None
    current_path = None
    current_add_lines = []
    in_add_section = False

    for line in lines:
        m = _PATCH_FILE_RE.match(line)
        if m:
            # Save previous entry
            if current_op is not None:
                results.append((current_op, current_path, current_add_lines))
            current_op = m.group(1)   # "Add" or "Update"
            current_path = m.group(2).strip()
            current_add_lines = []
            in_add_section = (current_op == "Add")
            continue

        if _PATCH_DELETE_RE.match(line):
            if current_op is not None:
                results.append((current_op, current_path, current_add_lines))
            current_op = None
            current_path = None
            current_add_lines = []
            in_add_section = False
            continue

        if line.startswith("*** "):
            # Other patch header (Begin Patch, End Patch, @@ context, etc.)
            in_add_section = False
            continue

        if in_add_section and line.startswith("+"):
            current_add_lines.append(line[1:])

    if current_op is not None:
        results.append((current_op, current_path, current_add_lines))

    return results


# ---------------------------------------------------------------------------
# Hook mode
# ---------------------------------------------------------------------------

def run_hook_mode():
    try:
        raw = sys.stdin.read()
        hook_data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        # Not valid hook JSON — fail safe (allow)
        sys.exit(0)

    tool_name = hook_data.get("tool_name", "")

    # ---- Codex apply_patch (PostToolUse) ----
    if tool_name == "apply_patch":
        run_codex_mode(hook_data)
        return

    # ---- Claude Code Write/Edit/MultiEdit (PreToolUse) ----
    if tool_name not in ("Write", "Edit", "MultiEdit"):
        sys.exit(0)

    tool_input = hook_data.get("tool_input", {})
    file_path_str = tool_input.get("file_path", "")

    if not file_path_str.endswith(".md"):
        sys.exit(0)

    schema = load_schema()
    zone, in_enforced = resolve_zone(file_path_str, schema)

    if not in_enforced:
        sys.exit(0)

    content = compute_prospective_content(tool_name, tool_input, file_path_str)
    ok, msg = validate_content(content, zone, schema)

    if not ok:
        print(
            f"[validate.py] Frontmatter validation FAILED for '{file_path_str}' (zone: {zone}):\n{msg}",
            file=sys.stderr,
        )
        sys.exit(2)

    sys.exit(0)


def run_codex_mode(hook_data):
    """
    Codex PostToolUse handler for apply_patch.
    Validates affected .md files in enforced zones ON DISK (post-write).
    Falls back to patch content reconstruction for Add File paths not on disk.
    """
    tool_input = hook_data.get("tool_input", {})
    command_text = tool_input.get("command", "")
    cwd = hook_data.get("cwd", "") or os.getcwd()

    schema = load_schema()
    patch_entries = parse_apply_patch(command_text)

    failures = []

    for op, rel_path, add_lines in patch_entries:
        # op is "Add" or "Update"
        if not rel_path.endswith(".md"):
            continue

        # Resolve the path against cwd
        abs_path = (Path(cwd) / rel_path).resolve()

        zone, in_enforced = resolve_zone(str(abs_path), schema, cwd=cwd)
        if not in_enforced:
            continue

        # Try reading from disk first (normal case for both Add and Update)
        if abs_path.exists():
            try:
                content = abs_path.read_text(encoding="utf-8")
            except OSError as e:
                failures.append(f"{rel_path}: cannot read file: {e}")
                continue
        elif op == "Add" and add_lines:
            # Fallback: reconstruct from patch + lines
            content = "\n".join(add_lines)
        else:
            # File doesn't exist and we can't reconstruct — skip
            continue

        ok, msg = validate_content(content, zone, schema)
        if not ok:
            failures.append(
                f"[validate.py] Frontmatter validation FAILED for '{rel_path}' (zone: {zone}):\n{msg}"
            )

    if failures:
        print("\n".join(failures), file=sys.stderr)
        sys.exit(2)

    sys.exit(0)


# ---------------------------------------------------------------------------
# CLI mode
# ---------------------------------------------------------------------------

def run_cli_mode(paths):
    schema = load_schema()
    any_failed = False

    for path_str in paths:
        path = Path(path_str)
        if not path.suffix == ".md":
            print(f"SKIP  {path_str}  (not .md)")
            continue

        zone, in_enforced = resolve_zone(str(path.resolve()), schema)

        if not in_enforced:
            print(f"SKIP  {path_str}  (zone '{zone}' not enforced)")
            continue

        try:
            content = path.read_text(encoding="utf-8")
        except (FileNotFoundError, OSError) as e:
            print(f"ERROR {path_str}  ({e})")
            any_failed = True
            continue

        ok, msg = validate_content(content, zone, schema)
        if ok:
            print(f"PASS  {path_str}")
        else:
            print(f"FAIL  {path_str}\n      {msg.replace(chr(10), chr(10) + '      ')}")
            any_failed = True

    sys.exit(1 if any_failed else 0)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) > 1:
        run_cli_mode(sys.argv[1:])
    else:
        run_hook_mode()
