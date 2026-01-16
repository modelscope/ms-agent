# Copyright (c) Alibaba, Inc. and its affiliates.
"""
Shared instances for backend modules.
Ensures api.py and websocket_handler.py use the same manager instances.
"""
import os

from session_manager import SessionManager
from project_discovery import ProjectDiscovery
from config_manager import ConfigManager

# Initialize paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROJECTS_DIR = os.path.join(BASE_DIR, 'projects')
CONFIG_DIR = os.path.join(BASE_DIR, 'webui', 'config')

# Shared instances
project_discovery = ProjectDiscovery(PROJECTS_DIR)
config_manager = ConfigManager(CONFIG_DIR)
session_manager = SessionManager()

print(f"[Shared] Initialized managers")
print(f"[Shared] Projects dir: {PROJECTS_DIR}")
print(f"[Shared] Config dir: {CONFIG_DIR}")
