# Copyright (c) ModelScope Contributors. All rights reserved.
"""MCP images must survive through the existing attachment/wire contract."""
import asyncio
import base64
import io
from unittest.mock import AsyncMock

import pytest
from mcp.types import CallToolResult, ImageContent, TextContent
from omegaconf import OmegaConf
from PIL import Image

from ms_agent.llm import multimodal
from ms_agent.llm.utils import ToolResult
from ms_agent.tools.mcp_client import MCPClient
from ms_agent.utils.artifact_manager import ArtifactManager


def png(color='red'):
    out = io.BytesIO()
    Image.new('RGB', (24, 24), color).save(out, format='PNG')
    return base64.b64encode(out.getvalue()).decode()


def invoke(tmp_path, content, error=False):
    client = MCPClient(config=OmegaConf.create({'output_dir': str(tmp_path), 'tools': {}}))
    client.sessions['image'] = AsyncMock()
    client.sessions['image'].call_tool.return_value = CallToolResult(
        content=content, isError=error)
    return asyncio.run(client.call_tool('image', 'draw', {}))


def test_image_only_survives_replay_and_both_protocols(tmp_path):
    encoded = png()
    result = ToolResult.from_raw(invoke(tmp_path, [ImageContent(
        type='image', data=encoded, mimeType='image/png')]))
    assert len(result.attachments) == 1
    ref = result.attachments[0]
    assert (tmp_path / ref['path']).read_bytes() == base64.b64decode(encoded)
    assert encoded not in result.text
    opts = multimodal.VisionOptions(workspace_root=str(tmp_path))
    # Fresh formatters read persisted references; the MCP connection is gone.
    openai = multimodal.openai_tool_media_message(result.attachments, opts)
    anthropic = multimodal.anthropic_tool_result_blocks(result.attachments, opts)
    assert any(b['type'] == 'image_url' for b in openai['content'])
    assert any(b['type'] == 'image' for b in anthropic)
    assert multimodal.tool_media_withheld(result.attachments, opts, False)


def test_mixed_text_and_multiple_images_keep_order(tmp_path):
    result = ToolResult.from_raw(invoke(tmp_path, [
        TextContent(type='text', text='two pictures'),
        ImageContent(type='image', data=png('red'), mimeType='image/png'),
        ImageContent(type='image', data=png('blue'), mimeType='image/png'),
    ]))
    assert result.text.startswith('two pictures')
    for ref, expected in zip(result.attachments, [(255, 0, 0), (0, 0, 255)]):
        with Image.open(tmp_path / ref['path']) as im:
            assert im.getpixel((0, 0)) == expected


@pytest.mark.parametrize('data,mime', [
    ('not-base64', 'image/png'),
    (base64.b64encode(b'not an image').decode(), 'image/png'),
    (png(), 'image/jpeg'),
    (png(), 'image/svg+xml'),
])
def test_bad_images_report_error_without_dropping_readable_text(tmp_path, data, mime):
    result = ToolResult.from_raw(invoke(tmp_path, [
        TextContent(type='text', text='partial result'),
        ImageContent(type='image', data=data, mimeType=mime),
    ]))
    assert result.is_error
    assert 'partial result' in result.text and 'Could not read tool image' in result.text
    assert result.attachments == []


def test_error_response_never_serializes_image_bytes(tmp_path):
    encoded = png()
    result = ToolResult.from_raw(invoke(tmp_path, [
        ImageContent(type='image', data=encoded, mimeType='image/png'),
        TextContent(type='text', text='tool failed'),
    ], error=True))
    assert result.is_error and 'tool failed' in result.text
    assert encoded not in result.text


def test_plain_text_return_shape_is_unchanged(tmp_path):
    assert invoke(tmp_path, [TextContent(type='text', text='ok')]) == 'ok'


def test_artifacts_cannot_escape_via_directory_symlink(tmp_path):
    outside = tmp_path.parent / 'outside-images'
    outside.mkdir(exist_ok=True)
    (tmp_path / '.ms_agent').symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match='outside the workspace'):
        ArtifactManager(tmp_path).store_image(png(), 'image/png')


def test_encoded_size_is_bounded_before_decode(tmp_path):
    with pytest.raises(ValueError, match='input limit'):
        ArtifactManager(tmp_path).store_image('A' * (23 * 1024 * 1024), 'image/png')
