#!/usr/bin/env python3
"""Deny hook for tests."""
import json
import sys

json.load(sys.stdin)
print(json.dumps({"decision": "deny", "reason": "blocked by test"}))
