#!/usr/bin/env python3
# Copyright (c) Alibaba, Inc. and its affiliates.
"""
MS-Agent API Server startup script
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.main import main

if __name__ == '__main__':
    main()
