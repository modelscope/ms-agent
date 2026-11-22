"""Real model/API checks against an explicitly configured, isolated WebUI.

No credentials are read by this script. Configure the server's providers first.
Usage: python check_followup_real.py --base-url http://127.0.0.1:8000 --provider my-provider --models my-model
"""
import argparse
import asyncio
import httpx
import json
import time
from pathlib import Path
from uuid import uuid4


class Probe:

    def __init__(self, client, session):
        self.client, self.session = client, session
        self.events = []
        self.task = None

    async def watch(self):
        async with self.client.stream(
                'GET', f'/api/chat/sessions/{self.session}/events',
                timeout=None) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.startswith('data:'):
                    self.events.append(json.loads(line[5:]))

    def chunks(self):
        return [
            event['chunk'] for event in self.events if event['type'] == 'chunk'
        ]

    async def wait(self, predicate, seconds=100):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if predicate():
                return
            if self.task.done():
                await self.task
                raise AssertionError('Event stream closed')
            await asyncio.sleep(.05)
        errors = [chunk for chunk in self.chunks() if chunk['type'] == 'error']
        raise AssertionError(f'Timed out; model errors: {errors}')

    async def state(self):
        return await request(self.client, 'GET',
                             f'/api/chat/sessions/{self.session}/inputs')

    async def send(self, text, files=None):
        state = await self.state()
        return await request(
            self.client, 'POST', '/api/chat/inputs', {
                'session_id': self.session,
                'input_id': uuid4().hex,
                'expected_turn_id': state['turn_id'],
                'message': {
                    'role': 'user',
                    'content': text,
                    'files': files or []
                },
            })

    async def finished(self, expected_users):
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            state = await self.state()
            rows = await request(self.client, 'GET',
                                 f'/api/sessions/{self.session}/messages')
            if not state['running'] and not state['pending'] and sum(
                    row['role'] == 'user' for row in rows) == expected_users:
                return rows
            await asyncio.sleep(.15)
        raise AssertionError(f'Conversation did not finish: {state}')

    async def close(self):
        self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)


async def request(client, method, path, body=None):
    response = await client.request(method, path, json=body)
    response.raise_for_status()
    payload = response.json()
    assert payload['code'] == 0, payload.get('message')
    return payload['data']


async def mixed_inputs(client, model):
    session = await request(client, 'POST', '/api/sessions', {
        'title': f'Follow-up E2E: {model["name"]}',
        'model_id': model['id']
    })
    probe = Probe(client, session['id'])
    probe.task = asyncio.create_task(probe.watch())
    try:
        await request(client, 'PATCH', '/api/agent-settings',
                      {'follow_up_behavior': 'queue'})
        first = await probe.send(
            'Use the shell tool to run `sleep 8; printf STARTED_TOOL_DONE`. '
            'Wait for the real result, then report it briefly. Do not run any other tools.'
        )
        await probe.wait(lambda: any(chunk['type'] == 'step' and chunk[
            'meta'].get('status') == 'running' for chunk in probe.chunks()))
        queued = await probe.send(
            'This is the next task. Reply only QUEUED_DONE, without tools.')
        await request(client, 'PATCH', '/api/agent-settings',
                      {'follow_up_behavior': 'steer'})
        s1 = await probe.send(
            'Update this task: include STEER_ONE in the final reply. Do not start any more tools.'
        )
        s2 = await probe.send(
            'One more update to this task: also include STEER_TWO in the final reply.'
        )
        rows = await probe.finished(4)
        users = [row for row in rows if row['role'] == 'user']
        assert [row['message_id'] for row in users
                ] == [r['input']['input_id']
                      for r in (first, s1, s2, queued)], users
        assert len({row['turn_id'] for row in users[:3]}) == 1
        assert users[-1]['turn_id'] != users[0]['turn_id']
        replies = '\n'.join(row['content'] for row in rows
                            if row['role'] == 'assistant'
                            and row['turn_id'] == users[0]['turn_id'])
        assert 'STEER_ONE' in replies and 'STEER_TWO' in replies, replies
        assert rows[-1]['content'].strip() == 'QUEUED_DONE', rows[-1]
        delivered = [
            c['meta']['input_id'] for c in probe.chunks()
            if c['type'] == 'input'
        ]
        assert len(delivered) == len(set(delivered)) == 4, delivered
        # A new connection after completion must return the same canonical rows.
        async with client.stream(
            'GET', f'/api/chat/sessions/{session["id"]}/events') as response:
            async for line in response.aiter_lines():
                if line.startswith('data:'):
                    snapshot = json.loads(line[5:])
                    assert snapshot['type'] == 'snapshot' and snapshot[
                        'history'] == rows
                    break
        return {
            'case': 'mixed_queue_and_two_steers',
            'model': model['name'],
            'session_id': session['id'],
            'result': 'passed',
            'event_count': len(probe.events),
            'reply': replies
        }
    finally:
        await probe.close()


async def skip_unstarted(client, model):
    session = await request(
        client, 'POST', '/api/sessions', {
            'title': f'Unstarted tool: {model["name"]}',
            'model_id': model['id'],
            'reasoning_effort': 'off'
        })
    probe = Probe(client, session['id'])
    probe.task = asyncio.create_task(probe.watch())
    filename = f'should-not-exist-{uuid4().hex[:8]}.txt'
    try:
        await request(client, 'PATCH', '/api/agent-settings',
                      {'follow_up_behavior': 'steer'})
        await probe.send(
            f'Use the file_system write_file tool to write {filename}. '
            'Its content must be 300 numbered lines, each containing the line number '
            'and a distinct short sentence about a tree. Put the full text in the tool '
            'arguments. Do not use shell, scripts or agent tools. Call write_file now.'
        )
        await probe.wait(lambda: any(c['type'] == 'step' and c['meta'].get(
            'kind') == 'tool_composing' for c in probe.chunks()))
        await probe.send(
            'Cancel the file creation. Do not call any more tools. '
            'If the runtime says the tool was skipped, explicitly reply NOT_CREATED; '
            'do not claim that writing succeeded or assume any output.')
        rows = await probe.finished(2)
        skipped = [
            c for c in probe.chunks()
            if c['type'] == 'step' and c['meta'].get('status') == 'skipped'
        ]
        assert skipped, 'Steering did not arrive before tool dispatch'
        assert 'NOT_CREATED' in rows[-1]['content'], rows[-1]['content']
        response = await client.get(
            f'/api/projects/_default/workspace/files/{filename}')
        assert response.status_code == 404, 'The supposedly skipped write created a file'
        artifacts = await request(client, 'GET',
                                  f'/api/sessions/{session["id"]}/artifacts')
        assert all(item['path'] != filename for item in artifacts)
        return {
            'case': 'skip_unstarted_write',
            'model': model['name'],
            'session_id': session['id'],
            'result': 'passed',
            'reply': rows[-1]['content']
        }
    finally:
        await probe.close()


async def image_followup(client, model):
    """A real vision request delivered as steering, then reloaded as history."""
    from io import BytesIO
    from PIL import Image, ImageDraw
    image = Image.new('RGB', (320, 240), '#1264d7')
    ImageDraw.Draw(image).rectangle((40, 60, 280, 180), fill='#ff3b30')
    encoded = BytesIO()
    image.save(encoded, format='PNG')
    response = await client.post(
        '/api/projects/_default/workspace/files/upload',
        files={
            'file': ('followup-colors.png', encoded.getvalue(), 'image/png')
        },
        data={'path': 'user_files/followup-colors.png'})
    response.raise_for_status()
    file = response.json()['data']
    session = await request(client, 'POST', '/api/sessions', {
        'title': 'Image follow-up',
        'model_id': model['id']
    })
    probe = Probe(client, session['id'])
    probe.task = asyncio.create_task(probe.watch())
    try:
        await request(client, 'PATCH', '/api/agent-settings',
                      {'follow_up_behavior': 'steer'})
        await probe.send('Use shell to run sleep 8, then reply DONE.')
        await probe.wait(lambda: any(c['type'] == 'step' and c['meta'].get(
            'status') == 'running' for c in probe.chunks()))
        await probe.send(
            'For this task, instead describe the two main colors and the shape in the attached image. '
            'Use English, no tools, and report only what you actually see.',
            [{
                'name': 'followup-colors.png',
                'path': file['path'],
                'type': 'image/png'
            }])
        rows = await probe.finished(2)
        reply = rows[-1]['content'].lower()
        assert all(word in reply for word in ('red', 'blue', 'rectang')), reply
        users = [row for row in rows if row['role'] == 'user']
        assert users[-1]['files'][0]['path'] == file['path']
        assert users[0]['turn_id'] == users[-1]['turn_id']
        return {
            'case': 'image_steering',
            'model': model['name'],
            'session_id': session['id'],
            'result': 'passed',
            'reply': rows[-1]['content']
        }
    finally:
        await probe.close()


async def main(args):
    results = []
    async with httpx.AsyncClient(base_url=args.base_url, timeout=45) as client:
        models = await request(client, 'GET', '/api/models')
        for name in args.models:
            model = next(
                m for m in models
                if m['name'] == name and m['provider_id'] == args.provider)
            started = time.monotonic()
            try:
                check = {
                    'mixed': mixed_inputs,
                    'skip': skip_unstarted,
                    'image': image_followup
                }[args.case]
                result = await check(client, model)
            except Exception as exc:
                result = {
                    'case': args.case,
                    'model': name,
                    'result': 'failed',
                    'error': str(exc)
                }
            result['elapsed_s'] = round(time.monotonic() - started, 2)
            results.append(result)
            print(json.dumps(result, ensure_ascii=False), flush=True)
            Path(args.output).write_text(
                json.dumps(results, ensure_ascii=False, indent=2))
        await request(client, 'PATCH', '/api/agent-settings',
                      {'follow_up_behavior': 'queue'})
    if any(result['result'] != 'passed' for result in results):
        raise SystemExit(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--provider', required=True)
    parser.add_argument(
        '--case', choices=['mixed', 'skip', 'image'], default='mixed')
    parser.add_argument('--models', nargs='+', required=True)
    parser.add_argument(
        '--output', default='/tmp/ms-agent-followup-real-results.json')
    asyncio.run(main(parser.parse_args()))
