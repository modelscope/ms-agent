# Copyright (c) ModelScope Contributors. All rights reserved.
"""Classification of failures on requests that carried images.

Every message quoted here was captured from a live endpoint; the provenance is
in ``llm/image_errors.py`` next to each pattern. The tests that matter most are
not the ones checking that a known string maps to a known verdict — they are:

* :meth:`TestTheOutage.test_size_complaint_is_never_a_capability_verdict`, which
  pins the exact failure that took a healthy vision model offline, and
* :meth:`TestStaleTableIsSafe.*`, which pins the property that makes matching on
  vendor prose acceptable at all: an unrecognised message can only ever cost an
  extra round-trip, never a wrong lasting conclusion.
"""
import unittest

from ms_agent.llm.image_errors import (ImageFailure, classify, edge_ladder,
                                       parse_max_edge, status_of)


class _Err(Exception):
    """An exception shaped like the OpenAI/Anthropic SDK errors."""

    def __init__(self, status=400, msg='bad request', body=None):
        super().__init__(msg)
        self.status_code = status
        if body is not None:
            self.body = body


# --------------------------------------------------------------------------- #
# The outage
# --------------------------------------------------------------------------- #
class TestTheOutage(unittest.TestCase):
    """ModelScope Qwen3-VL rejecting an oversized image, 2026-08-21."""

    # Verbatim apart from the request id, which is dropped: it identifies one
    # call on one account and proves nothing the message does not.
    MESSAGE = ("Error code: 400 - {'error': {'message': 'input size exceed "
               "limit 2048x2048,current input:(1183,2560)'}}")

    def test_size_complaint_is_never_a_capability_verdict(self):
        diag = classify(_Err(400, self.MESSAGE), sent_images=True)
        self.assertIs(diag.failure, ImageFailure.TOO_LARGE)
        # The whole outage in one assertion: this must never be allowed to
        # record "the model cannot see", which is what made one oversized
        # upload disable a working model for the life of the process.
        self.assertFalse(diag.remember)

    def test_the_stated_ceiling_is_used_not_guessed(self):
        diag = classify(_Err(400, self.MESSAGE), sent_images=True)
        # 2048 is the limit; 2560 in the same sentence is OUR input and must not
        # be mistaken for it.
        self.assertEqual(diag.max_edge, 2048)

    def test_recovery_tries_the_stated_ceiling_first(self):
        self.assertEqual(edge_ladder(2048, 2560)[0], 2048)


# --------------------------------------------------------------------------- #
# Ordering
# --------------------------------------------------------------------------- #
class TestOrdering(unittest.TestCase):

    def test_structural_signal_beats_everything(self):
        # Even a textbook capability sentence is not ours to act on if this
        # request carried no images.
        diag = classify(
            _Err(400, 'this model is text-only'), sent_images=False)
        self.assertIs(diag.failure, ImageFailure.NOT_IMAGE_RELATED)

    def test_non_4xx_is_not_ours(self):
        for status in (401, 403, 404, 429, 500, 503):
            diag = classify(_Err(status, 'model does not support image input'),
                            sent_images=True)
            self.assertIs(diag.failure, ImageFailure.NOT_IMAGE_RELATED,
                          f'HTTP {status} must not be blamed on the images')

    def test_size_wins_over_capability_when_both_words_appear(self):
        # Providers do mix vocabularies. Shrinking is cheaper than concluding
        # blindness and is reversible, so it goes first.
        diag = classify(
            _Err(400, 'image exceeds the maximum allowed size: 1024; this '
                 'model does not support images larger than that'),
            sent_images=True)
        self.assertIs(diag.failure, ImageFailure.TOO_LARGE)
        self.assertFalse(diag.remember)

    def test_veto_wins_over_size(self):
        diag = classify(
            _Err(400, 'context length exceeded: image exceeds budget'),
            sent_images=True)
        self.assertIs(diag.failure, ImageFailure.NOT_IMAGE_RELATED)


# --------------------------------------------------------------------------- #
# Semantic vetoes
# --------------------------------------------------------------------------- #
class TestVetoes(unittest.TestCase):

    CASES = {
        'content filter': 'blocked by content_filter',
        'moderation': 'flagged by moderation',
        'context length': 'This model maximum context length is 128000 tokens',
        'token limit': 'you exceeded the tokens limit for this request',
        'corrupt asset': 'the uploaded file appears corrupted',
        'undecodable': 'could not decode the attachment',
        'invalid asset': 'invalid image supplied',
        'bad format': 'unsupported image format: image/tiff',
    }

    def test_none_of_these_are_about_capability(self):
        for label, msg in self.CASES.items():
            diag = classify(_Err(400, msg), sent_images=True)
            self.assertIs(diag.failure, ImageFailure.NOT_IMAGE_RELATED,
                          f'{label!r} must not be treated as an image failure')
            self.assertFalse(diag.remember)

    def test_413_shrinks_but_never_remembers(self):
        # The BODY was too big. That says nothing about the model's eyesight —
        # dropping media may incidentally make the next request fit, which is a
        # coincidence, not a learned capability.
        diag = classify(_Err(413, 'Payload Too Large'), sent_images=True)
        self.assertIs(diag.failure, ImageFailure.TOO_LARGE)
        self.assertFalse(diag.remember)


# --------------------------------------------------------------------------- #
# Capability — the only class allowed to write memory
# --------------------------------------------------------------------------- #
class TestCapability(unittest.TestCase):

    MEASURED = {
        'DashScope 2026-08-18':
        ('<400> InternalError.Algo.InvalidParameter: The provided messages '
         'input is invalid. The error info is [Unexpected item type in '
         'content.]'),
        'Zhipu glm-5.2 2026-08-21':
        ("Error code: 400 - {'error': {'code': '1210', 'message': "
         "\"messages.content.type 参数非法，取值范围 ['text']\"}}"),
        'generic text-only':
        'this deployment is text-only',
        'generic unsupported':
        "the model doesn't support multimodal input",
        'vision disabled':
        'vision is not enabled for this deployment',
    }

    def test_measured_refusals_are_recognised(self):
        for label, msg in self.MEASURED.items():
            diag = classify(_Err(400, msg), sent_images=True)
            self.assertIs(diag.failure, ImageFailure.MODEL_NO_VISION, label)
            self.assertTrue(diag.remember, label)

    def test_shape_complaints_are_not_capability(self):
        for msg in ('you may send at most 1 image per request',
                    'multiple images are not supported in one message',
                    'animated GIF is not accepted',
                    'aspect ratio must be below 200:1'):
            diag = classify(_Err(400, msg), sent_images=True)
            self.assertIs(diag.failure, ImageFailure.SHAPE_REJECTED, msg)
            self.assertFalse(diag.remember, msg)


# --------------------------------------------------------------------------- #
# The property that makes prose matching safe
# --------------------------------------------------------------------------- #
class TestStaleTableIsSafe(unittest.TestCase):

    def test_unrecognised_message_degrades_to_unknown(self):
        diag = classify(
            _Err(400, 'ERR_7731: constraint violated on field q'),
            sent_images=True)
        self.assertIs(diag.failure, ImageFailure.UNKNOWN)

    def test_unknown_never_remembers(self):
        # A provider rewording its errors must cost one extra round-trip, never
        # a persistent belief about a model. Every pattern table in this module
        # is allowed to go stale precisely because of this.
        for msg in ('some new wording nobody has seen',
                    'まったく新しいエラーです', ''):
            diag = classify(_Err(400, msg), sent_images=True)
            self.assertFalse(diag.remember, msg)

    def test_only_one_failure_class_can_ever_remember(self):
        remembering = set()
        for msg in ('input size exceed limit 2048x2048', 'text-only',
                    'multiple images', 'nonsense', 'content_filter'):
            diag = classify(_Err(400, msg), sent_images=True)
            if diag.remember:
                remembering.add(diag.failure)
        self.assertEqual(remembering, {ImageFailure.MODEL_NO_VISION})


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
class TestStatusExtraction(unittest.TestCase):

    def test_reads_nested_response(self):

        class Wrapped(Exception):

            class response:  # noqa: N801
                status_code = 400

        self.assertEqual(status_of(Wrapped()), 400)

    def test_does_not_scrape_digits_from_prose(self):
        # The predecessor accepted `'400' in str(exc)`, so a request id or a
        # pixel count containing those digits was enough to attribute a failure
        # to the images.
        self.assertIsNone(status_of(Exception('request 400123 timed out')))

    def test_missing_status_still_classifies_on_text(self):
        # Some SDK wrappers lose the status entirely; the prose is then all we
        # have, and it must still be usable.
        diag = classify(
            Exception('the model is text-only'), sent_images=True)
        self.assertIs(diag.failure, ImageFailure.MODEL_NO_VISION)


class TestEdgeParsing(unittest.TestCase):

    def test_parses_common_shapes(self):
        self.assertEqual(parse_max_edge('exceed limit 2048x2048'), 2048)
        self.assertEqual(parse_max_edge('exceeds limit 1024 x 768'), 768)
        self.assertEqual(parse_max_edge('max allowed size: 1568'), 1568)
        self.assertEqual(parse_max_edge('maximum width is 1000'), 1000)

    def test_rejects_out_of_range_noise(self):
        self.assertIsNone(parse_max_edge('exceed limit 99999x99999'))
        self.assertIsNone(parse_max_edge('no numbers here'))


class TestEdgeLadder(unittest.TestCase):

    def test_stated_ceiling_first_then_halving(self):
        self.assertEqual(edge_ladder(2048, 2560), [2048, 1280, 640])

    def test_without_a_stated_ceiling_it_just_halves(self):
        self.assertEqual(edge_ladder(None, 2048), [1024, 512])

    def test_a_ceiling_above_the_current_size_is_ignored(self):
        # A provider echoing a limit we are already under is not asking for a
        # smaller image; halving is still the only move left.
        self.assertNotIn(4096, edge_ladder(4096, 2048))

    def test_is_finite(self):
        self.assertLessEqual(len(edge_ladder(None, 300)), 2)


if __name__ == '__main__':
    unittest.main()
