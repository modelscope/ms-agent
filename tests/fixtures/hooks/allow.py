#!/usr/bin/env python3
"""Allow hook for tests."""
import json
import sys

json.load(sys.stdin)
print(json.dumps({"decision": "allow", "reason": "allowed by test"}))
