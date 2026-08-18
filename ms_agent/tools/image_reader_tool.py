# Copyright (c) ModelScope Contributors. All rights reserved.
"""``image_reader``: let a text-only model ask a vision model about an image.

The main conversation model may have no image understanding at all — measured
across seven providers, roughly a third of configured models are in that class,
and four of them accept an image block with HTTP 200 and simply cannot see it.
For those, an attached image degrades to a path and the answer is "I can't view
images", which is honest but useless.

This tool closes that gap without changing the main model: it sends the image to
a SEPARATELY configured vision model and returns that model's description as
text. The main model then reasons over the text. Lossy by construction — a
description is not the pixels — so it is the fallback, never the preferred path:
when the main model can see images, the transports show it the real thing and
this tool should not be needed.

Configuration (all under ``llm.vision.auxiliary``; absent ⇒ the tool is not
registered, so nothing changes for anyone who has not opted in)::

    llm:
      vision:
        auxiliary:
          service: dashscope          # provider id / SDK service name
          model: qwen3.8-max          # a model that CAN see images
          api_key: ...                # optional; falls back to the env/spec
          base_url: ...               # optional; same
          protocol: openai            # optional; 'anthropic' for that wire format

Modelled on hermes-agent's ``vision_analyze``.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from ms_agent.llm.utils import Tool
from ms_agent.tools.base import ToolBase
from ms_agent.utils import get_logger

logger = get_logger()

#: Asked of the auxiliary model when the caller has no specific question. Aims at
#: a description another model can reason over rather than prose for a human:
#: verbatim text first, because that is what callers most often actually need.
DEFAULT_PROMPT = (
    'Describe this image for another AI model that cannot see it. Start with '
    'every piece of text in the image, transcribed verbatim. Then describe the '
    'layout, the objects, their colours and any relationships that matter. Be '
    'specific and factual; do not speculate about intent.')


def _fail(error: str) -> str:
    """A failed ``image_reader`` result, in the same JSON shape as a success."""
    return json.dumps({'ok': False, 'error': error}, ensure_ascii=False)


def auxiliary_config(config: Any) -> Optional[Dict[str, Any]]:
    """The ``llm.vision.auxiliary`` block as a plain dict, or None if unset.

    Returning None is the opt-in switch: no auxiliary model configured means the
    tool is never registered, so a user who has not asked for this pays nothing —
    not a tool definition in the prompt, not a stray dependency.
    """
    llm = getattr(config, 'llm', None)
    vision = getattr(llm, 'vision', None) if llm is not None else None
    aux = getattr(vision, 'auxiliary', None) if vision is not None else None
    if aux is None:
        return None
    model = getattr(aux, 'model', None)
    if not model:
        return None
    out: Dict[str, Any] = {'model': str(model)}
    for key in ('service', 'api_key', 'base_url', 'protocol'):
        value = getattr(aux, key, None)
        if value:
            out[key] = str(value)
    return out


class ImageReaderTool(ToolBase):
    """One tool: ``image_reader(path, question=None)``."""

    server_name = 'image_reader'

    def __init__(self, config, **kwargs):
        super().__init__(config)
        self.exclude_func(getattr(config.tools, 'image_reader', None))
        self._aux = auxiliary_config(config) or {}
        self._llm = None  # built lazily: no cost unless the tool is called

    async def connect(self) -> None:
        if not self._aux:
            logger.warning(
                '[image_reader] no llm.vision.auxiliary.model configured; the '
                'tool will report that it is unavailable')

    async def cleanup(self) -> None:
        self._llm = None

    async def _get_tools_inner(self):
        return {
            'image_reader': [
                Tool(
                    tool_name='image_reader',
                    server_name='image_reader',
                    description=
                    ('Look at an image file and get a text description of it, '
                     'produced by a vision model.\n\n'
                     'Use this ONLY when you cannot see an image yourself. '
                     'Images the user attached to the conversation are shown '
                     'to you directly when this model supports it — asking '
                     'this tool about them instead would give you a lossy '
                     'second-hand description.\n\n'
                     'Typical use: the user attached an image but you cannot '
                     'see it, or you need to inspect an image file in the '
                     'workspace that was never attached.'),
                    parameters={
                        'type': 'object',
                        'properties': {
                            'path': {
                                'type':
                                'string',
                                'description':
                                ('Workspace-relative path of the image '
                                 '(png/jpg/jpeg/gif/webp).'),
                            },
                            'question': {
                                'type':
                                'string',
                                'description':
                                ('What you need to know about the image. Omit '
                                 'for a full general description.'),
                            },
                        },
                        'required': ['path'],
                        'additionalProperties': False,
                    })
            ]
        }

    def _build_llm(self):
        """Construct the auxiliary vision LLM (once)."""
        if self._llm is not None:
            return self._llm
        from omegaconf import OmegaConf

        from ms_agent.llm import LLM

        aux = self._aux
        service = aux.get('service') or 'openai'
        llm_cfg: Dict[str, Any] = {
            'service': service,
            'model': aux['model'],
            # The auxiliary model is chosen BECAUSE it can see images, so state
            # that outright rather than letting the resolver guess.
            'supports_vision': True,
            'use_provider_router': True,
        }
        if aux.get('protocol'):
            llm_cfg['protocol'] = aux['protocol']
        if aux.get('api_key'):
            llm_cfg[f'{service}_api_key'] = aux['api_key']
        if aux.get('base_url'):
            llm_cfg[f'{service}_base_url'] = aux['base_url']
        cfg = OmegaConf.create({
            'llm': llm_cfg,
            'generation_config': {
                'stream': False
            },
            # So the attachment's relative path resolves against the same
            # workspace the caller is talking about.
            'output_dir': self.output_dir,
        })
        self._llm = LLM.from_config(cfg)
        return self._llm

    async def call_tool(self, server_name: str, *, tool_name: str,
                        tool_args: dict) -> str:
        # Same dispatch shape as FileSystemTool: the tool name IS the method.
        return await getattr(self, tool_name)(**(tool_args or {}))

    async def image_reader(self,
                           path: str = '',
                           question: Optional[str] = None) -> str:
        """Describe the image at ``path`` using the auxiliary vision model."""
        if not self._aux:
            return _fail(
                'No auxiliary vision model is configured '
                '(llm.vision.auxiliary.model), so this image cannot be '
                'described. Tell the user to configure one, enable image '
                'understanding for the current model, or switch to a model '
                'that supports images.')
        if not path:
            return _fail('path is required')

        from ms_agent.llm import multimodal
        from ms_agent.llm.utils import Message, collect_response

        opts = multimodal.VisionOptions.from_config(
            self.config, workspace_root=self.output_dir)
        refs = multimodal.image_refs([{'type': 'image', 'path': path}], opts)
        if not refs:
            return _fail(f'{path!r} is not a readable image type (expected '
                         'png/jpg/jpeg/gif/webp).')
        # Resolve to bytes here rather than trusting the path to exist later, so
        # a missing file is one clear error instead of a provider-side failure.
        if multimodal.load_image(refs[0], opts) is None:
            return _fail(f'cannot read or decode the image at {path!r}')

        prompt = (question or '').strip() or DEFAULT_PROMPT
        attachment = {
            'type': 'image',
            'path': path,
            'media_type': refs[0].media_type,
            'label': f'Image: {os.path.basename(path)}',
        }
        try:
            llm = self._build_llm()
            response = collect_response(
                llm.generate([
                    Message(
                        role='user', content=prompt, attachments=[attachment])
                ]))
            description = (getattr(response, 'content', '') or '').strip()
        except Exception as exc:
            logger.warning('[image_reader] %s failed: %s',
                           self._aux.get('model'), exc)
            return _fail(f'{type(exc).__name__}: {exc}')

        if not description:
            return _fail('the vision model returned nothing')
        return json.dumps(
            {
                'ok': True,
                'path': path,
                'model': self._aux.get('model'),
                # Named so the reader cannot mistake it for having seen the
                # image: it is one model's account of another's pixels.
                'description_from_vision_model': description,
            },
            ensure_ascii=False,
            indent=2)
