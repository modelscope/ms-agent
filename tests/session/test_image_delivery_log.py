# Copyright (c) ModelScope Contributors. All rights reserved.
"""Delivery outcomes survive in an append-only log.

A turn's row is written BEFORE its request goes out, so what became of its
images cannot be in it. Rewriting an append-only log is not an option, so the
outcome arrives as its own record and is folded back onto the attachment when
the log is read. Everything downstream — context assembly for the next request,
history replay in the UI — then sees an ordinary field and needs to know nothing
about any of this.
"""
import tempfile
import unittest
from pathlib import Path

from ms_agent.session.session_log import SessionLog


class TestImageDeliveryRecord(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix='msa-log-')
        self.log = SessionLog(self.dir, session_key='s1')
        self.log.append({
            'role': 'user',
            'content': 'look',
            'attachments': [{'type': 'image', 'path': 'user_files/a.png'}],
        })

    def _reload(self):
        return SessionLog(self.dir, session_key='s1').get_all_messages()

    def test_outcome_is_folded_onto_the_attachment(self):
        self.log.record_image_delivery([{
            'path': 'user_files/a.png',
            'state': 'degraded',
            'reason': 'switch_off',
        }])
        rows = self._reload()
        self.assertEqual(len(rows), 1, 'the note is not itself a message')
        self.assertEqual(rows[0]['attachments'][0]['delivery'], 'degraded')

    def test_record_is_not_replayed_as_a_message(self):
        self.log.record_image_delivery([{
            'path': 'user_files/a.png',
            'state': 'delivered'
        }])
        rows = self._reload()
        # A stray empty user turn in the model's context would be worse than no
        # record at all.
        self.assertEqual([r['role'] for r in rows], ['user'])

    def test_first_outcome_wins(self):
        # The stored value means "what this turn was answered with", so a later
        # request under a different setting must not rewrite history.
        self.log.record_image_delivery([{
            'path': 'user_files/a.png',
            'state': 'delivered'
        }])
        self.log.record_image_delivery([{
            'path': 'user_files/a.png',
            'state': 'degraded'
        }])
        self.assertEqual(self._reload()[0]['attachments'][0]['delivery'],
                         'delivered')

    def test_unmatched_path_is_dropped_quietly(self):
        self.log.record_image_delivery([{
            'path': 'user_files/gone.png',
            'state': 'degraded'
        }])
        rows = self._reload()
        self.assertNotIn('delivery', rows[0]['attachments'][0])

    def test_empty_record_writes_nothing(self):
        path = Path(self.dir) / 's1.jsonl'
        before = path.read_text()
        self.log.record_image_delivery([])
        self.assertEqual(path.read_text(), before)


if __name__ == '__main__':
    unittest.main()


class TestDeliveryIsMonotonic(unittest.TestCase):
    """"Has the model ever received this picture", not "what happened on the
    turn it was attached to".

    Measured with the per-turn reading: an image attached while the switch was
    off, then shown once it was on, kept a permanent "degraded". A text-only
    model arriving later was told the picture had never been seen — and
    retracted a correct description of it as a hallucination.
    """

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix='msa-log-')
        self.log = SessionLog(self.dir, session_key='s1')
        self.log.append({
            'role': 'user',
            'content': 'look',
            'attachments': [{'type': 'image', 'path': 'user_files/a.png'}],
        })

    def _state(self):
        rows = SessionLog(self.dir, session_key='s1').get_all_messages()
        return rows[0]['attachments'][0].get('delivery')

    def test_degraded_then_delivered_upgrades(self):
        self.log.record_image_delivery([{'path': 'user_files/a.png',
                                         'state': 'degraded'}])
        self.log.record_image_delivery([{'path': 'user_files/a.png',
                                         'state': 'delivered'}])
        self.assertEqual(self._state(), 'delivered')

    def test_delivered_then_degraded_stays_delivered(self):
        self.log.record_image_delivery([{'path': 'user_files/a.png',
                                         'state': 'delivered'}])
        self.log.record_image_delivery([{'path': 'user_files/a.png',
                                         'state': 'degraded'}])
        self.assertEqual(self._state(), 'delivered')
