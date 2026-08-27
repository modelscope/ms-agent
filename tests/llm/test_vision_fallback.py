# Copyright (c) ModelScope Contributors. All rights reserved.
"""The recovery ladder, and what is allowed to be remembered.

The predecessor had one move for every failure that touched an image — throw the
pictures away and record the model as blind — so the cheapest problem in the set
(a picture a few hundred pixels too wide) was "fixed" by permanently disabling a
working model. :class:`TestTheOutage` reproduces that exact sequence end to end
and pins the new behaviour.

Preserved from the previous suite: the streaming first-chunk cases (gateways that
answer 200 and then reject inside the stream) and the transport-wiring case (a
named-argument collision that took a whole transport offline).
"""
import base64
import io
import os
import tempfile
import unittest

from ms_agent.llm import multimodal as M
from ms_agent.llm import vision as V

try:
    from PIL import Image as _PIL  # noqa: N812
except ImportError:  # pragma: no cover
    _PIL = None


class _Boom(Exception):

    def __init__(self, status=400, msg='bad request'):
        super().__init__(msg)
        self.status_code = status


#: ModelScope Qwen3-VL-8B-Instruct, 2026-08-21, verbatim.
SIZE_400 = ("Error code: 400 - {'error': {'message': 'input size exceed limit "
            "2048x2048,current input:(1183,2560)'}}")
#: DashScope compatible-mode, a text-only qwen model, 2026-08-18, verbatim.
CAPABILITY_400 = ('<400> InternalError.Algo.InvalidParameter: The provided '
                  'messages input is invalid. The error info is [Unexpected '
                  'item type in content.]')

IMG_MESSAGES = [{
    'role':
    'user',
    'content': [
        {
            'type': 'text',
            'text': 'Image 1: a.png'
        },
        {
            'type': 'image_url',
            'image_url': {
                'url': 'data:image/png;base64,AA'
            }
        },
        {
            'type': 'text',
            'text': 'what is this'
        },
    ],
}]


def _payload(size=(1183, 2560)):
    """A message list carrying one REAL image, so shrinking can do something."""
    if _PIL is None:
        return IMG_MESSAGES
    buf = io.BytesIO()
    _PIL.new('RGB', size, 'navy').save(buf, 'PNG')
    data = base64.b64encode(buf.getvalue()).decode()
    return [{
        'role':
        'user',
        'content': [
            {
                'type': 'text',
                'text': 'Image 1: poster.png'
            },
            {
                'type': 'image_url',
                'image_url': {
                    'url': f'data:image/png;base64,{data}'
                }
            },
            {
                'type': 'text',
                'text': '图里有什么？'
            },
        ],
    }]


def _edge_of(messages):
    block = messages[0]['content'][1]
    raw, _ = M._read_image_block(block)
    with _PIL.open(io.BytesIO(raw)) as img:
        return max(img.size)


class _MemoCase(unittest.TestCase):
    """Named for history: there is no memo any more, which is the point."""


# --------------------------------------------------------------------------- #
# The outage, end to end
# --------------------------------------------------------------------------- #
class TestTheOutage(_MemoCase):
    """One oversized poster used to cost a healthy model its eyesight."""

    def setUp(self):
        super().setUp()
        if _PIL is None:
            self.skipTest('Pillow unavailable')

    def test_oversized_image_is_shrunk_not_disowned(self):
        seen = []

        def create(messages, **kw):
            edge = _edge_of(messages)
            seen.append(edge)
            if edge > 2048:
                raise _Boom(400, SIZE_400)
            return 'ok'

        out = V.create_with_vision_fallback(
            create,
            base_url='https://api-inference.modelscope.cn/v1',
            model='Qwen/Qwen3-VL-8B-Instruct',
            messages=_payload(),
            sent_images=True,
            max_edge=2560)

        self.assertEqual(out, 'ok')
        self.assertEqual(len(seen), 2, 'exactly one retry')
        self.assertGreater(seen[0], 2048)
        self.assertLessEqual(seen[1], 2048, 'the stated ceiling was used')
        # The heart of it: the images survived the recovery.
        self.assertTrue(M.has_image_blocks(_payload()[0]['content']))

    def test_images_survive_the_recovery(self):
        """The retry must still carry pixels, not a text placeholder."""
        captured = []

        def create(messages, **kw):
            captured.append(messages)
            if _edge_of(messages) > 2048:
                raise _Boom(400, SIZE_400)
            return 'ok'

        V.create_with_vision_fallback(
            create,
            base_url='u',
            model='m',
            messages=_payload(),
            sent_images=True,
            max_edge=2560)
        self.assertTrue(
            M.has_image_blocks(captured[-1][0]['content']),
            'a size complaint must not cost the user their image')


# --------------------------------------------------------------------------- #
# The ladder, per diagnosis
# --------------------------------------------------------------------------- #
class TestLadder(_MemoCase):

    def _run(self, failing_message, *, accept, messages=None, max_edge=2048):
        """Drive the fallback with a client that accepts once ``accept`` holds."""
        attempts = []

        def create(messages, **kw):
            attempts.append(messages)
            if not accept(messages):
                raise _Boom(400, failing_message)
            return 'ok'

        out = V.create_with_vision_fallback(
            create,
            base_url='u',
            model='m',
            messages=messages if messages is not None else IMG_MESSAGES,
            sent_images=True,
            max_edge=max_edge)
        return out, attempts

    def test_capability_refusal_drops_images_and_is_remembered(self):
        out, attempts = self._run(
            CAPABILITY_400,
            accept=lambda m: not M.has_image_blocks(m[0]['content']))
        self.assertEqual(out, 'ok')
        self.assertEqual(len(attempts), 2)

    def test_unknown_refusal_drops_images_but_is_not_remembered(self):
        # A provider rewording its errors must not be able to produce a lasting
        # conclusion about a model.
        out, _ = self._run(
            'ERR_9912: constraint violated',
            accept=lambda m: not M.has_image_blocks(m[0]['content']))
        self.assertEqual(out, 'ok')

    def test_shape_complaint_thins_the_batch_first(self):
        if _PIL is None:
            self.skipTest('Pillow unavailable')
        two = _payload((64, 64))
        two[0]['content'].extend(
            [two[0]['content'][0], two[0]['content'][1]])  # a second image

        def accept(messages):
            imgs = [
                b for b in messages[0]['content']
                if b.get('type') == 'image_url'
            ]
            return len(imgs) <= 1

        out, attempts = self._run(
            'you may send at most 1 image per request',
            accept=accept,
            messages=two)
        self.assertEqual(out, 'ok')
        # It kept a picture rather than throwing them all away.
        self.assertTrue(M.has_image_blocks(attempts[-1][0]['content']))

    def test_unrelated_failures_are_re_raised_untouched(self):
        calls = []

        def create(messages, **kw):
            calls.append(1)
            raise _Boom(400, 'blocked by content_filter')

        with self.assertRaises(_Boom):
            V.create_with_vision_fallback(
                create,
                base_url='u',
                model='m',
                messages=IMG_MESSAGES,
                sent_images=True)
        self.assertEqual(len(calls), 1, 'no recovery should be attempted')

    def test_exhausted_ladder_reraises_the_original_error(self):
        original = _Boom(400, SIZE_400)

        def create(messages, **kw):
            raise original

        with self.assertRaises(_Boom) as ctx:
            V.create_with_vision_fallback(
                create,
                base_url='u',
                model='m',
                messages=_payload() if _PIL else IMG_MESSAGES,
                sent_images=True,
                max_edge=2560)
        self.assertIs(ctx.exception, original)
        # Nothing was learned, so nothing may be recorded.

    def test_no_images_means_no_recovery(self):
        def create(messages, **kw):
            raise _Boom(400, CAPABILITY_400)

        with self.assertRaises(_Boom):
            V.create_with_vision_fallback(
                create,
                base_url='u',
                model='m',
                messages=[{
                    'role': 'user',
                    'content': 'plain'
                }],
                sent_images=False)

    def test_happy_path_is_a_passthrough(self):
        def create(messages, **kw):
            return 'fine'

        self.assertEqual(
            V.create_with_vision_fallback(
                create,
                base_url='u',
                model='m',
                messages=IMG_MESSAGES,
                sent_images=True), 'fine')


# --------------------------------------------------------------------------- #
# Memory
# --------------------------------------------------------------------------- #
class TestResolveMaxEdge(unittest.TestCase):

    class _Spec:

        def __init__(self, edge):
            self.max_image_edge = edge

    def test_default_when_provider_says_nothing(self):
        self.assertEqual(
            V.resolve_max_edge(self._Spec(0)), M.VisionOptions.max_edge)

    def test_provider_may_widen(self):
        self.assertEqual(V.resolve_max_edge(self._Spec(2576)), 2576)

    def test_provider_may_not_narrow(self):
        # A table that could narrow would turn "we forgot to update a provider"
        # into failed requests.
        self.assertEqual(
            V.resolve_max_edge(self._Spec(512)), M.VisionOptions.max_edge)

    def test_explicit_user_value_wins(self):
        self.assertEqual(V.resolve_max_edge(self._Spec(2576), 1024), 1024)


# --------------------------------------------------------------------------- #
# Streaming (preserved)
# --------------------------------------------------------------------------- #
class TestStreamTimeRefusal(_MemoCase):
    """A 400 that arrives on the FIRST CHUNK, not out of ``create()``.

    Aliyun-family gateways answer 200 and then put the rejection in the stream.
    Guarding only ``create()`` let that error bypass recovery entirely.
    """

    @staticmethod
    def _streaming_create(reject_images=True):
        seen = []

        def create(messages, **kw):
            has_img = any(
                M.has_image_blocks(m.get('content')) for m in messages
                if isinstance(m, dict))
            seen.append(has_img)

            def gen():
                if has_img and reject_images:
                    raise _Boom(400, CAPABILITY_400)
                yield 'chunk-1'
                yield 'chunk-2'

            return gen()

        return create, seen

    def test_first_chunk_refusal_is_repaired_and_remembered(self):
        create, seen = self._streaming_create()
        stream = V.create_with_vision_fallback(
            create,
            base_url='u',
            model='m',
            messages=IMG_MESSAGES,
            sent_images=True)
        self.assertEqual(list(stream), ['chunk-1', 'chunk-2'])
        self.assertEqual(seen, [True, False])

    def test_unrelated_stream_error_reraises_and_does_not_remember(self):
        original = _Boom(400, 'Model id : X , has no provider supported')

        def create(messages, **kw):

            def gen():
                raise original
                yield  # pragma: no cover

            return gen()

        stream = V.create_with_vision_fallback(
            create,
            base_url='u',
            model='m',
            messages=IMG_MESSAGES,
            sent_images=True)
        with self.assertRaises(_Boom) as ctx:
            list(stream)
        self.assertIs(ctx.exception, original)

    def test_failure_after_the_first_chunk_is_not_retried(self):
        """Output already reached the user; restarting would duplicate it."""
        calls = []

        def create(messages, **kw):
            calls.append(1)

            def gen():
                yield 'chunk-1'
                raise _Boom(400, CAPABILITY_400)

            return gen()

        stream = V.create_with_vision_fallback(
            create,
            base_url='u',
            model='m',
            messages=IMG_MESSAGES,
            sent_images=True)
        got = []
        with self.assertRaises(_Boom):
            for item in stream:
                got.append(item)
        self.assertEqual(got, ['chunk-1'])
        self.assertEqual(len(calls), 1)

    def test_an_accepted_but_empty_stream_is_not_evidence(self):
        """"It did not error" is weaker than "it answered"."""

        def create(messages, **kw):
            has_img = M.has_image_blocks(messages[0]['content'])

            def gen():
                if has_img:
                    raise _Boom(400, CAPABILITY_400)
                return
                yield  # pragma: no cover

            return gen()

        stream = V.create_with_vision_fallback(
            create,
            base_url='u',
            model='m',
            messages=IMG_MESSAGES,
            sent_images=True)
        self.assertEqual(list(stream), [])

    def test_non_streaming_result_is_untouched(self):

        def create(messages, **kw):
            return 'plain-response'

        self.assertEqual(
            V.create_with_vision_fallback(
                create,
                base_url='u',
                model='m',
                messages=IMG_MESSAGES,
                sent_images=True), 'plain-response')


# --------------------------------------------------------------------------- #
# Transport wiring (preserved)
# --------------------------------------------------------------------------- #
class TestTransportWiring(_MemoCase):
    """Named arguments of the wrapper must not collide with API params.

    A transport that leaves ``model`` in the dict it splats raises
    ``TypeError: got multiple values for keyword argument 'model'`` on EVERY
    call — a total outage of that transport, not a vision-only edge case.
    """

    def _call(self, transport_params):
        seen = {}

        def factory(messages, **kw):
            seen.update(kw)
            seen['messages'] = messages
            assert 'model' in seen, 'the API call was made without a model'
            return 'ok'

        params = dict(transport_params)
        rest = {
            k: v
            for k, v in params.items() if k not in ('model', 'messages')
        }
        out = V.create_with_vision_fallback(
            lambda messages, **kw: factory(
                messages, model=params['model'], **kw),
            base_url='https://example/v1',
            model=params['model'],
            messages=params['messages'],
            sent_images=False,
            **rest)
        return out, seen

    def test_anthropic_shaped_params_do_not_collide(self):
        out, seen = self._call({
            'model': 'claude-x',
            'messages': IMG_MESSAGES,
            'max_tokens': 1024,
            'thinking': {
                'type': 'disabled',
                'budget_tokens': 1024
            },
            'system': 'be brief',
        })
        self.assertEqual(out, 'ok')
        self.assertEqual(seen['model'], 'claude-x')
        self.assertEqual(seen['max_tokens'], 1024)
        self.assertEqual(seen['system'], 'be brief')
        self.assertEqual(seen['messages'], IMG_MESSAGES)

    def test_real_anthropic_transport_builds_a_valid_call(self):
        """End-to-end through AnthropicMessagesTransport._call_llm itself."""
        from ms_agent.llm.transport import anthropic_messages as AM
        from ms_agent.llm.utils import Message

        calls = []

        class _Messages:

            def create(self, **kw):
                calls.append(kw)
                return 'created'

            def stream(self, **kw):
                calls.append(kw)
                return 'streamed'

        class _Client:
            base_url = 'https://api.deepseek.com/anthropic'
            messages = _Messages()

        transport = AM.AnthropicMessagesTransport.__new__(
            AM.AnthropicMessagesTransport)
        transport.client = _Client()
        transport.model = 'deepseek-v4-pro'
        transport._vision = M.VisionOptions()
        transport._vision_supported = False
        transport._last_deliveries = []

        out = transport._call_llm([Message(role='user', content='hi')],
                                  tools=None,
                                  stream=False)

        self.assertEqual(out, 'created')
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]['model'], 'deepseek-v4-pro')
        self.assertEqual(calls[0]['messages'][0]['role'], 'user')


class TestStripImages(unittest.TestCase):

    def test_replaces_image_blocks_and_keeps_labels(self):
        out, changed = V.strip_images_from_messages(IMG_MESSAGES)
        self.assertTrue(changed)
        body = out[0]['content']
        self.assertIsInstance(body, str)
        self.assertIn('Image 1: a.png', body)  # the label survives
        self.assertIn('what is this', body)  # so does the question
        self.assertNotIn('base64', body)  # the pixels do not
        self.assertIn('Do not guess', body)
        # Advice this path can only give when the switch is ALREADY on.
        self.assertNotIn('Settings', body)

    def test_text_only_is_untouched(self):
        msgs = [{'role': 'user', 'content': 'plain'}]
        out, changed = V.strip_images_from_messages(msgs)
        self.assertFalse(changed)
        self.assertEqual(out, msgs)


if __name__ == '__main__':
    unittest.main()


class TestDegradeReporting(_MemoCase):
    """The delivery record must reflect what the ENDPOINT decided, not what the
    formatter intended. It is written before the request goes out, so left
    uncorrected it would read "delivered" for precisely the requests that were
    refused — and that record is what the user's badge is drawn from."""

    def _run(self, message):
        seen = []

        def create(messages, **kw):
            if M.has_image_blocks(messages[0]['content']):
                raise _Boom(400, message)
            return 'ok'

        V.create_with_vision_fallback(
            create,
            base_url='u',
            model='m',
            messages=IMG_MESSAGES,
            sent_images=True,
            on_degrade=seen.append)
        return seen

    def test_capability_refusal_reports_endpoint_rejected(self):
        self.assertEqual(self._run(CAPABILITY_400),
                         [V.REASON_ENDPOINT_REJECTED])

    def test_size_failure_reports_its_own_reason(self):
        # "Too large" and "this model refuses images" are different sentences
        # with different remedies; only the latter is worth a retry button.
        self.assertEqual(self._run(SIZE_400), [M.REASON_TOO_LARGE])

    def test_success_reports_nothing(self):
        seen = []
        V.create_with_vision_fallback(
            lambda messages, **kw: 'ok',
            base_url='u',
            model='m',
            messages=IMG_MESSAGES,
            sent_images=True,
            on_degrade=seen.append)
        self.assertEqual(seen, [])

    def test_a_reporting_failure_cannot_break_the_turn(self):

        def angry(reason):
            raise RuntimeError('nope')

        def create(messages, **kw):
            if M.has_image_blocks(messages[0]['content']):
                raise _Boom(400, CAPABILITY_400)
            return 'ok'

        out = V.create_with_vision_fallback(
            create,
            base_url='u',
            model='m',
            messages=IMG_MESSAGES,
            sent_images=True,
            on_degrade=angry)
        self.assertEqual(out, 'ok')
