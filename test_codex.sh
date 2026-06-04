#!/usr/bin/env bash
# Test script for validate.py Codex mode
set -uo pipefail

VALIDATE="/Users/Mikhail/Documents/projects/777-tooling/_meta/validate.py"
TMPDIR_BASE="/tmp/test_777_$$"

mkdir -p "$TMPDIR_BASE/.obsidian" "$TMPDIR_BASE/tasks" "$TMPDIR_BASE/artifacts" "$TMPDIR_BASE/_meta"
cp /Users/Mikhail/Documents/projects/777-tooling/_meta/schema.json "$TMPDIR_BASE/_meta/schema.json"

PASS=0
FAIL=0

check() {
    local desc="$1"
    local expected="$2"
    local actual="$3"
    if [ "$actual" -eq "$expected" ]; then
        echo "PASS  [$desc] (exit $actual)"
        PASS=$((PASS+1))
    else
        echo "FAIL  [$desc] expected exit $expected, got $actual"
        FAIL=$((FAIL+1))
    fi
}

echo "======================================================================"
echo "TEST 1a: apply_patch Add File INVALID task (on disk, missing 'why') => exit 2"
echo "======================================================================"
cat > "$TMPDIR_BASE/tasks/bad-task.md" << 'MDEOF'
---
author: alice
status: todo
updated: 2026-06-04
links: []
---
Body without why field.
MDEOF

python3 -c "
import json, sys
cwd = sys.argv[1]
payload = {
  'session_id': 'test',
  'cwd': cwd,
  'hook_event_name': 'PostToolUse',
  'tool_name': 'apply_patch',
  'tool_use_id': 'id1',
  'tool_input': {
    'command': '*** Begin Patch\n*** Add File: tasks/bad-task.md\n+---\n+author: alice\n+status: todo\n+updated: 2026-06-04\n+links: []\n+---\n+Body without why field.\n*** End Patch'
  }
}
print(json.dumps(payload))
" "$TMPDIR_BASE" | python3 "$VALIDATE" 2>&1
check "1a: Add File invalid on disk" 2 $?

echo ""
echo "======================================================================"
echo "TEST 1b: apply_patch Add File INVALID — reconstruct fallback (file NOT on disk)"
echo "======================================================================"
# Ensure file does NOT exist
rm -f "$TMPDIR_BASE/tasks/reconstructed.md"

python3 -c "
import json, sys
cwd = sys.argv[1]
payload = {
  'session_id': 'test',
  'cwd': cwd,
  'hook_event_name': 'PostToolUse',
  'tool_name': 'apply_patch',
  'tool_use_id': 'id2',
  'tool_input': {
    'command': '*** Begin Patch\n*** Add File: tasks/reconstructed.md\n+---\n+author: bob\n+status: backlog\n+updated: 2026-06-04\n+links: []\n+---\n+No why here.\n*** End Patch'
  }
}
print(json.dumps(payload))
" "$TMPDIR_BASE" | python3 "$VALIDATE" 2>&1
check "1b: Add File invalid reconstruct fallback" 2 $?

echo ""
echo "======================================================================"
echo "TEST 2: apply_patch Add File VALID task => exit 0"
echo "======================================================================"
cat > "$TMPDIR_BASE/tasks/good-task.md" << 'MDEOF'
---
author: alice
why: We need this feature
status: todo
updated: 2026-06-04
links: []
---
Valid task body.
MDEOF

python3 -c "
import json, sys
cwd = sys.argv[1]
payload = {
  'session_id': 'test',
  'cwd': cwd,
  'hook_event_name': 'PostToolUse',
  'tool_name': 'apply_patch',
  'tool_use_id': 'id3',
  'tool_input': {
    'command': '*** Begin Patch\n*** Add File: tasks/good-task.md\n*** End Patch'
  }
}
print(json.dumps(payload))
" "$TMPDIR_BASE" | python3 "$VALIDATE" 2>&1
check "2: Add File valid" 0 $?

echo ""
echo "======================================================================"
echo "TEST 3: apply_patch Update File leaves INVALID status on disk => exit 2"
echo "======================================================================"
cat > "$TMPDIR_BASE/tasks/updated-task.md" << 'MDEOF'
---
author: charlie
why: Important reason
status: INVALID_STATUS
updated: 2026-06-04
links: []
---
Task with bad status.
MDEOF

python3 -c "
import json, sys
cwd = sys.argv[1]
payload = {
  'session_id': 'test',
  'cwd': cwd,
  'hook_event_name': 'PostToolUse',
  'tool_name': 'apply_patch',
  'tool_use_id': 'id4',
  'tool_input': {
    'command': '*** Begin Patch\n*** Update File: tasks/updated-task.md\n@@ context\n-status: todo\n+status: INVALID_STATUS\n*** End Patch'
  }
}
print(json.dumps(payload))
" "$TMPDIR_BASE" | python3 "$VALIDATE" 2>&1
check "3: Update File invalid status on disk" 2 $?

echo ""
echo "======================================================================"
echo "TEST 4: apply_patch touching only artifacts/ => exit 0 (not enforced)"
echo "======================================================================"
cat > "$TMPDIR_BASE/artifacts/report.md" << 'MDEOF'
# Just a report — no frontmatter required
MDEOF

python3 -c "
import json, sys
cwd = sys.argv[1]
payload = {
  'session_id': 'test',
  'cwd': cwd,
  'hook_event_name': 'PostToolUse',
  'tool_name': 'apply_patch',
  'tool_use_id': 'id5',
  'tool_input': {
    'command': '*** Begin Patch\n*** Add File: artifacts/report.md\n+# Just a report\n*** End Patch'
  }
}
print(json.dumps(payload))
" "$TMPDIR_BASE" | python3 "$VALIDATE" 2>&1
check "4: artifacts/ not enforced" 0 $?

echo ""
echo "======================================================================"
echo "TEST 5a: Claude Code Write REGRESSION — INVALID task => exit 2"
echo "======================================================================"
python3 -c "
import json, sys
cwd = sys.argv[1]
payload = {
  'session_id': 'test',
  'cwd': cwd,
  'hook_event_name': 'PreToolUse',
  'tool_name': 'Write',
  'tool_use_id': 'id6',
  'tool_input': {
    'file_path': cwd + '/tasks/claude-write.md',
    'content': '---\nauthor: dave\nstatus: todo\nupdated: 2026-06-04\nlinks: []\n---\nMissing why.\n'
  }
}
print(json.dumps(payload))
" "$TMPDIR_BASE" | python3 "$VALIDATE" 2>&1
check "5a: Claude Code Write invalid" 2 $?

echo ""
echo "======================================================================"
echo "TEST 5b: Claude Code Write REGRESSION — VALID task => exit 0"
echo "======================================================================"
python3 -c "
import json, sys
cwd = sys.argv[1]
payload = {
  'session_id': 'test',
  'cwd': cwd,
  'hook_event_name': 'PreToolUse',
  'tool_name': 'Write',
  'tool_use_id': 'id7',
  'tool_input': {
    'file_path': cwd + '/tasks/claude-valid.md',
    'content': '---\nauthor: dave\nwhy: Very good reason\nstatus: todo\nupdated: 2026-06-04\nlinks: []\n---\nValid.\n'
  }
}
print(json.dumps(payload))
" "$TMPDIR_BASE" | python3 "$VALIDATE" 2>&1
check "5b: Claude Code Write valid" 0 $?

echo ""
echo "======================================================================"
echo "SUMMARY: $PASS passed, $FAIL failed"
echo "======================================================================"

# Cleanup
rm -rf "$TMPDIR_BASE"

[ "$FAIL" -eq 0 ] && exit 0 || exit 1
