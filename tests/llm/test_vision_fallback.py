# Copyright (c) ModelScope Contributors. All rights reserved.
"""Image-refusal attribution and the one-shot fallback.

The behaviour under test was shaped by a seven-provider sweep (2026-08):
DashScope is the ONLY provider that hard-400s on image content, and its message
("Unexpected item type in content") names neither image nor multimodal nor
vision — so keyword matching cannot work. Meanwhile a 400 on an image-carrying
request also covers model-not-found and auth, so the status code alone cannot
decide either. Hence: retry wide, blacklist only on a retry that SUCCEEDS.
"""
import unittest

from ms_agent.llm import vision as V


class _Boom(Exception):

    def __init__(self, status=400, msg='bad request'):
        super().__init__(msg)
        self.status_code = status


IMG_MESSAGES = [{
    'role': 'user',
    'content': [
        {'type': 'text', 'text': 'Image 1: a.png'},
        {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,AA'}},
        {'type': 'text', 'text': 'what is this'},
    ],
}]


class TestIsImageRefusal(unittest.TestCase):

    def test_requires_images_on_the_wire(self):
        # A 400 with no images in the request is somebody else's problem.
        self.assertFalse(V.is_image_refusal(_Boom(400), sent_images=False))
        self.assertTrue(V.is_image_refusal(_Boom(400), sent_images=True))

    def test_only_400(self):
        for status in (401, 404, 429, 500, 503):
            self.assertFalse(
                V.is_image_refusal(_Boom(status), sent_images=True),
                f'{status} must not be attributed to images')

    def test_status_from_nested_response(self):

        class Wrapped(Exception):

            class response:  # noqa: N801
                status_code = 400

        self.assertTrue(V.is_image_refusal(Wrapped(), sent_images=True))

    def test_falls_back_to_text_when_status_is_lost(self):
        self.assertTrue(
            V.is_image_refusal(Exception('Error code: 400 - oops'),
                               sent_images=True))
        self.assertFalse(
            V.is_image_refusal(Exception('some transport hiccup'),
                               sent_images=True))


class TestStripImages(unittest.TestCase):

    def test_replaces_image_blocks_and_keeps_labels(self):
        out, changed = V.strip_images_from_messages(IMG_MESSAGES)
        self.assertTrue(changed)
        body = out[0]['content']
        self.assertIsInstance(body, str)
        self.assertIn('Image 1: a.png', body)      # the label survives
        self.assertIn('what is this', body)        # so does the question
        self.assertNotIn('base64', body)           # the pixels do not
        # The reason and the remedy are both present, so the model can explain
        # itself instead of answering "please upload the image".
        self.assertIn('Settings', body)

    def test_text_only_is_untouched(self):
        msgs = [{'role': 'user', 'content': 'plain'}]
        out, changed = V.strip_images_from_messages(msgs)
        self.assertFalse(changed)
        self.assertEqual(out, msgs)


class TestCreateWithVisionFallback(unittest.TestCase):

    def setUp(self):
        V.MODELS_REFUSING_IMAGES.clear()

    def test_happy_path_is_a_passthrough(self):
        calls = []

        def create(messages, **kw):
            calls.append(messages)
            return 'ok'

        got = V.create_with_vision_fallback(
            create, base_url='u', model='m', messages=IMG_MESSAGES,
            sent_images=True)
        self.assertEqual(got, 'ok')
        self.assertEqual(len(calls), 1)
        self.assertFalse(V.MODELS_REFUSING_IMAGES)

    def test_image_refusal_retries_without_images_and_remembers(self):
        seen = []

        def create(messages, **kw):
            seen.append(messages)
            if len(seen) == 1:
                raise _Boom(400, 'Unexpected item type in content.')
            return 'recovered'

        got = V.create_with_vision_fallback(
            create, base_url='u', model='m', messages=IMG_MESSAGES,
            sent_images=True)
        self.assertEqual(got, 'recovered')
        self.assertEqual(len(seen), 2)
        self.assertIsInstance(seen[1][0]['content'], str)
        self.assertIn(('u', 'm'), V.MODELS_REFUSING_IMAGES)

    def test_unrelated_400_does_not_blacklist_and_reraises_the_original(self):
        """Regression: ModelScope answers "Model id ... has no provider
        supported" with a 400. Attributing that to images wasted a round-trip
        AND permanently stopped sending images to a model whose real problem was
        that it did not exist."""
        original = _Boom(400, 'Model id : X , has no provider supported')

        def create(messages, **kw):
            raise original

        with self.assertRaises(_Boom) as ctx:
            V.create_with_vision_fallback(
                create, base_url='u', model='m', messages=IMG_MESSAGES,
                sent_images=True)
        self.assertIs(ctx.exception, original)  # the real error, not the retry's
        self.assertFalse(V.MODELS_REFUSING_IMAGES)

    def test_known_refuser_skips_the_doomed_first_attempt(self):
        V.note_refusal('u', 'm')
        seen = []

        def create(messages, **kw):
            seen.append(messages)
            return 'ok'

        V.create_with_vision_fallback(
            create, base_url='u', model='m', messages=IMG_MESSAGES,
            sent_images=True)
        self.assertEqual(len(seen), 1)
        self.assertIsInstance(seen[0][0]['content'], str)

    def test_non_image_error_propagates_untouched(self):

        def create(messages, **kw):
            raise _Boom(429, 'rate limited')

        with self.assertRaises(_Boom):
            V.create_with_vision_fallback(
                create, base_url='u', model='m', messages=IMG_MESSAGES,
                sent_images=True)
        self.assertFalse(V.MODELS_REFUSING_IMAGES)


class TestResolveSupportsVision(unittest.TestCase):

    def setUp(self):
        V.MODELS_REFUSING_IMAGES.clear()

    def test_explicit_switch_wins(self):
        from omegaconf import OmegaConf
        on = OmegaConf.create({'llm': {'supports_vision': True}})
        off = OmegaConf.create({'llm': {'supports_vision': False}})
        self.assertTrue(V.resolve_supports_vision(on))
        self.assertFalse(V.resolve_supports_vision(off))

    def test_quoted_false_is_honoured(self):
        """`supports_vision: "false"` is a common YAML slip; bare bool() would
        read it as ON, i.e. exactly the opposite of what was asked."""
        from omegaconf import OmegaConf
        cfg = OmegaConf.create({'llm': {'supports_vision': 'false'}})
        self.assertFalse(V.resolve_supports_vision(cfg))
        cfg = OmegaConf.create({'llm': {'supports_vision': 'yes'}})
        self.assertTrue(V.resolve_supports_vision(cfg))

    def test_observed_refusal_overrides_an_explicit_yes(self):
        from omegaconf import OmegaConf
        cfg = OmegaConf.create({'llm': {'supports_vision': True}})
        V.note_refusal('u', 'm')
        self.assertFalse(
            V.resolve_supports_vision(cfg, model='m', base_url='u'))

    def test_unset_is_off_even_when_the_provider_declares_vision(self):
        """Two states, default OFF — the provider's capability is NOT evidence.

        Nine of ten registry entries declare ``vision``, so consulting the spec
        made "nobody has said" mean "send images" and the switch's OFF position
        describe a state the runtime never used. Vision is a property of the
        model (ModelScope serves Qwen3-VL and the text-only Qwen3-235B through
        one provider entry), so only the per-model switch turns it on.
        """
        from omegaconf import OmegaConf
        from ms_agent.llm.spec import get_registry
        cfg = OmegaConf.create({'llm': {'model': 'x'}})
        for provider in ('dashscope', 'modelscope', 'kimi', 'openai'):
            spec = get_registry().get(provider)
            self.assertFalse(
                V.resolve_supports_vision(cfg, spec=spec),
                f'{provider}: unset must stay OFF regardless of its caps')
        self.assertFalse(V.resolve_supports_vision(cfg, spec=None))

    def test_only_the_switch_turns_images_on(self):
        from omegaconf import OmegaConf
        from ms_agent.llm.spec import get_registry
        spec = get_registry().get('dashscope')
        on = OmegaConf.create({'llm': {'supports_vision': True}})
        self.assertTrue(V.resolve_supports_vision(on, spec=spec))


class TestDisabledReason(unittest.TestCase):
    """Which explanation the model is handed when the pixels are absent."""

    def setUp(self):
        V.MODELS_REFUSING_IMAGES.clear()

    def tearDown(self):
        V.MODELS_REFUSING_IMAGES.clear()

    def test_switch_off_points_at_the_switch(self):
        reason = V.disabled_reason('u', 'm')
        self.assertIn('Settings', reason)
        self.assertNotIn('rejected image input', reason)

    def test_endpoint_refusal_does_not_point_at_the_switch(self):
        """Regression: telling a user who already enabled the switch to enable
        it is the single most confusing thing this feature can say."""
        V.note_refusal('u', 'm')
        reason = V.disabled_reason('u', 'm')
        self.assertIn('rejected image input', reason)
        self.assertNotIn('Settings → Models', reason)


class TestStreamTimeRefusal(unittest.TestCase):
    """A 400 that arrives on the FIRST CHUNK, not out of ``create()``.

    Aliyun-family gateways answer 200 and then put the rejection in the stream.
    Guarding only ``create()`` let that error bypass the retry entirely: no
    repair, no blacklist, raw provider error to the user.
    """

    def setUp(self):
        V.MODELS_REFUSING_IMAGES.clear()

    def tearDown(self):
        V.MODELS_REFUSING_IMAGES.clear()

    @staticmethod
    def _streaming_create(reject_images: bool = True):
        """A client that returns fine and only fails while being consumed."""
        seen = []

        def create(messages, **kw):
            has_img = any(
                V.multimodal.has_image_blocks(m.get('content'))
                for m in messages if isinstance(m, dict))
            seen.append(has_img)

            def gen():
                if has_img and reject_images:
                    raise _Boom(400, 'Unexpected item type in content.')
                yield 'chunk-1'
                yield 'chunk-2'

            return gen()

        return create, seen

    def test_first_chunk_refusal_is_repaired_and_remembered(self):
        create, seen = self._streaming_create()
        stream = V.create_with_vision_fallback(
            create, base_url='u', model='m', messages=IMG_MESSAGES,
            sent_images=True)
        self.assertEqual(list(stream), ['chunk-1', 'chunk-2'])
        self.assertEqual(seen, [True, False])  # with images, then without
        self.assertIn(('u', 'm'), V.MODELS_REFUSING_IMAGES)

    def test_unrelated_stream_error_reraises_and_does_not_blacklist(self):
        """The retry fails too -> the images were not the cause."""
        original = _Boom(400, 'Model id : X , has no provider supported')

        def create(messages, **kw):
            def gen():
                raise original
                yield  # pragma: no cover
            return gen()

        stream = V.create_with_vision_fallback(
            create, base_url='u', model='m', messages=IMG_MESSAGES,
            sent_images=True)
        with self.assertRaises(_Boom) as ctx:
            list(stream)
        self.assertIs(ctx.exception, original)
        self.assertFalse(V.MODELS_REFUSING_IMAGES)

    def test_failure_after_the_first_chunk_is_not_retried(self):
        """Output already reached the user; restarting would duplicate it."""
        calls = []

        def create(messages, **kw):
            calls.append(1)

            def gen():
                yield 'chunk-1'
                raise _Boom(400, 'Unexpected item type in content.')

            return gen()

        stream = V.create_with_vision_fallback(
            create, base_url='u', model='m', messages=IMG_MESSAGES,
            sent_images=True)
        got = []
        with self.assertRaises(_Boom):
            for item in stream:
                got.append(item)
        self.assertEqual(got, ['chunk-1'])
        self.assertEqual(len(calls), 1)  # no retry
        self.assertFalse(V.MODELS_REFUSING_IMAGES)

    def test_non_streaming_result_is_untouched(self):
        def create(messages, **kw):
            return 'plain-response'

        self.assertEqual(
            V.create_with_vision_fallback(
                create, base_url='u', model='m', messages=IMG_MESSAGES,
                sent_images=True), 'plain-response')


class TestTransportWiring(unittest.TestCase):
    """The wrapper's named arguments must not collide with the API params.

    ``create_with_vision_fallback`` takes ``model`` and ``messages`` as named
    arguments and forwards everything else to the factory. A transport that also
    leaves those keys in the dict it splats raises
    ``TypeError: got multiple values for keyword argument 'model'`` on EVERY
    call — a total outage of that transport, not a vision-only edge case. It
    reached a real endpoint before it was caught, so it is pinned here for both
    transport families.
    """

    def setUp(self):
        V.MODELS_REFUSING_IMAGES.clear()

    def _call(self, transport_params):
        """Drive the wrapper the way a transport does and return the API kwargs."""
        seen = {}

        def factory(messages, **kw):
            seen.update(kw)
            seen['messages'] = messages
            # Mimic a real client: it needs `model` named in the call.
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
        # model survives to the API call, and the other params are untouched.
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
        transport.vision = None
        transport.vision_supported = False

        out = transport._call_llm(
            [Message(role='user', content='hi')], tools=None, stream=False)

        self.assertEqual(out, 'created')
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]['model'], 'deepseek-v4-pro')
        self.assertEqual(calls[0]['messages'][0]['role'], 'user')


if __name__ == '__main__':
    unittest.main()
