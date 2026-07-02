#!/usr/bin/env python3
"""Pass-through hook for tests."""
import json
import sys

event = json.load(sys.stdin)
print(json.dumps({}))
