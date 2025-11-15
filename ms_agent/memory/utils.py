# Copyright (c) Alibaba, Inc. and its affiliates.
from .default_memory import DefaultMemory
from .diversity import Diversity
from .mem0ai import Mem0Memory

memory_mapping = {
    'default_memory': DefaultMemory,
    'mem0': Mem0Memory,
    'diversity': Diversity,
}
