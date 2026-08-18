# Copyright (c) ModelScope Contributors. All rights reserved.
"""flatten_message_text and the shape-preserving mutators.

Exists because a block list reaching a str-assuming call site never crashes — it
stores a Python repr or a guard skips the message. Both are silent, and two of
those sites (WebUI session auto-naming, TUI session naming) PERSIST what they
compute, so the garbage becomes permanent and user-visible.
"""
import unittest

from ms_agent.llm.message_text import (append_text, flatten_message_text,
                                       prepend_text)

BLOCKS = [
    {'type': 'text', 'text': 'Image 1: a.png'},
    {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,AAAA'}},
    {'type': 'text', 'text': 'what is in it'},
]


class TestFlatten(unittest.TestCase):

    def test_string_passes_through_unchanged(self):
        # The common case must be byte-identical, so no existing behaviour moves.
        for value in ('hello', '', '  spaced  ', 'multi\nline'):
            self.assertEqual(flatten_message_text(value), value)

    def test_none_is_empty_not_the_word_none(self):
        self.assertEqual(flatten_message_text(None), '')

    def test_text_blocks_joined_images_dropped(self):
        out = flatten_message_text(BLOCKS)
        self.assertEqual(out, 'Image 1: a.png\nwhat is in it')
        self.assertNotIn('base64', out)
        self.assertNotIn('AAAA', out)

    def test_every_non_text_modality_contributes_nothing(self):
        for kind in ('image', 'image_url', 'input_image', 'audio',
                     'input_audio', 'video', 'input_video', 'file', 'document'):
            self.assertEqual(
                flatten_message_text([{'type': kind, 'data': 'x' * 100}]), '',
                f'{kind} must not leak its payload')

    def test_anthropic_shaped_image_block(self):
        anthropic = [
            {'type': 'text', 'text': 'look'},
            {'type': 'image', 'source': {'type': 'base64', 'data': 'ZZZZ'}},
        ]
        self.assertEqual(flatten_message_text(anthropic), 'look')

    def test_bare_strings_inside_a_list(self):
        self.assertEqual(flatten_message_text(['a', 'b']), 'a\nb')

    def test_unknown_block_falls_back_to_its_text_field(self):
        self.assertEqual(
            flatten_message_text([{'type': 'weird', 'text': 'still text'}]),
            'still text')

    def test_custom_separator(self):
        self.assertEqual(flatten_message_text(BLOCKS, sep=' | '),
                         'Image 1: a.png | what is in it')

    def test_never_raises_on_junk(self):
        for junk in (123, 4.5, True, object(), {'no': 'type'}):
            self.assertIsInstance(flatten_message_text(junk), str)


class TestShapePreservingMutators(unittest.TestCase):
    """The framework augments a user turn in place (memory recall, update
    notices). Concatenating a string onto a list raises; replacing the list with
    a string silently drops the images."""

    def test_append_to_string(self):
        self.assertEqual(append_text('base', 'extra'), 'base\n\nextra')
        self.assertEqual(append_text('', 'extra'), 'extra')

    def test_append_to_blocks_adds_a_trailing_text_block(self):
        out = append_text(BLOCKS, 'recalled memory')
        self.assertIsInstance(out, list)
        self.assertEqual(len(out), len(BLOCKS) + 1)
        self.assertEqual(out[-1], {'type': 'text', 'text': 'recalled memory'})
        # The image block survives untouched — the whole point.
        self.assertEqual(out[1], BLOCKS[1])

    def test_prepend_to_blocks_puts_text_first(self):
        out = prepend_text(BLOCKS, 'NOTICE')
        self.assertEqual(out[0], {'type': 'text', 'text': 'NOTICE'})
        self.assertEqual(out[1:], BLOCKS)

    def test_empty_extra_is_a_no_op_on_both(self):
        self.assertEqual(append_text(BLOCKS, ''), BLOCKS)
        self.assertEqual(prepend_text('x', ''), 'x')

    def test_originals_are_not_mutated(self):
        original = list(BLOCKS)
        append_text(BLOCKS, 'a')
        prepend_text(BLOCKS, 'b')
        self.assertEqual(BLOCKS, original)


if __name__ == '__main__':
    unittest.main()
