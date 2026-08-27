# Copyright (c) ModelScope Contributors. All rights reserved.
"""Telling the model that what it can do changed since the earlier turns.

Two measured failures, both from the same blind spot — a conversation records
neither which model answered a turn nor what it was permitted to receive:

* after a switch from a vision model to a text-only one, the new model saw the
  images marked absent next to a detailed description in its own voice and
  retracted the description as a hallucination;
* with the SAME model and only the image switch turned off, a model that had
  just read one picture described the next one from its filename.
"""
import tempfile
import unittest

from ms_agent.prompting.model_switch import (MODEL_SWITCH_MARKER,
                                             capability_signature,
                                             render_capability_change_notice)
from ms_agent.session.session_log import SessionLog

VL_ON = capability_signature('qwen3-vl', True)
VL_OFF = capability_signature('qwen3-vl', False)
GLM_ON = capability_signature('glm-5.2', True)


class TestWhenItFires(unittest.TestCase):

    def test_silent_when_nothing_moved(self):
        self.assertIsNone(render_capability_change_notice(VL_ON, VL_ON))

    def test_fires_on_a_model_change(self):
        text = render_capability_change_notice(VL_ON, GLM_ON)
        self.assertIn('qwen3-vl', text)
        self.assertIn('glm-5.2', text)

    def test_fires_on_a_switch_change_with_the_same_model(self):
        # The case a model-only notice missed entirely: same model, but it may
        # no longer be shown pictures.
        text = render_capability_change_notice(VL_ON, VL_OFF)
        self.assertIsNotNone(text)
        self.assertIn('now off', text)

    def test_says_which_way_the_switch_went(self):
        self.assertIn('now on',
                      render_capability_change_notice(VL_OFF, VL_ON))

    def test_reports_both_when_both_moved(self):
        text = render_capability_change_notice(VL_ON, capability_signature(
            'glm-5.2', False))
        self.assertIn('glm-5.2', text)
        self.assertIn('now off', text)

    def test_stays_short(self):
        # It is replayed on every later request for the rest of the session, so
        # length is a recurring cost, not a one-off.
        for a, b in ((VL_ON, GLM_ON), (VL_ON, VL_OFF)):
            self.assertLess(len(render_capability_change_notice(a, b).split()),
                            60)


class TestWhatItSays(unittest.TestCase):

    def setUp(self):
        self.text = render_capability_change_notice(VL_ON, GLM_ON)

    def test_is_a_system_reminder(self):
        self.assertTrue(self.text.startswith('<system-reminder>'))
        self.assertTrue(self.text.rstrip().endswith('</system-reminder>'))
        self.assertIn(MODEL_SWITCH_MARKER, self.text)

    def test_defends_the_earlier_turns(self):
        self.assertIn('do not retract them', self.text)
        self.assertIn('treat them as sound', self.text)

    def test_does_not_ask_the_model_to_announce_it(self):
        self.assertIn('Do not mention this unless', self.text)


class TestSignature(unittest.TestCase):

    def test_distinguishes_both_axes(self):
        self.assertNotEqual(VL_ON, VL_OFF)
        self.assertNotEqual(VL_ON, GLM_ON)

    def test_round_trips_across_reopen(self):
        d = tempfile.mkdtemp(prefix='msa-sw-')
        log = SessionLog(d, session_key='s1')
        self.assertEqual(log.active_model, '')
        log.active_model = VL_ON
        self.assertEqual(SessionLog(d, session_key='s1').active_model, VL_ON)


if __name__ == '__main__':
    unittest.main()
