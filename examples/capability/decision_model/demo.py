"""Run four synthetic System One examples against the configured Bailian API.

From the repository root:
    python3 examples/capability/decision_model/demo.py --dry-run
    python3 examples/capability/decision_model/demo.py --output /tmp/jev-demo.json

Uses ATH_API_KEY and ATH_BASE_URL from the root .env (or the environment).
No SDK installation is required. This demonstrates a compatible decision model,
not TypeSafe's Jev weights. Policy thresholds below are illustrative only.
"""

import argparse
import json
import math
import os
import shlex
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit


TRIAGE_QUESTIONS = {
    'owner': {
        'type': 'choice',
        'instructions': '根据明确证据判断问题应优先交给哪个团队。',
        'criteria': {
            'frontend': '浏览器界面、前端交互、前端路由或客户端状态问题',
            'backend': '服务端接口、数据库或服务端鉴权故障',
            'docs': '安装说明或使用文档缺失、错误',
            'unknown': '现有信息不足以确定负责团队，或不属于上述类别',
        },
    },
    'core_blocked': {
        'type': 'noul',
        'instructions': '报告是否表明用户当前无法使用核心功能且没有可行替代方法？',
    },
    'impact': {
        'type': 'score',
        'instructions': '根据报告评估功能受影响程度。',
        'criteria': [
            '仅外观或文字问题，所有功能可正常使用',
            '部分功能受影响，但存在可行替代方法',
            '核心功能不可用，且没有可行替代方法',
        ],
    },
}


def examples():
    cases = [
        ('triage_blocked', {'report': 'WebUI 登录后立即跳回登录页，所有成员都无法进入聊天。'
          '已复现：服务端鉴权接口返回成功，前端路由错误地清除了登录状态。'
          '其他入口已停用，没有替代方法。'}),
        ('triage_cosmetic', {'report': 'WebUI 登录按钮的中文有一个错别字。'
          '登录和聊天均正常，所有用户都可正常使用。'}),
        ('triage_ambiguous', {'report': '登录体验有点怪，具体情况我还没确认，'
          '也没有日志或复现步骤。'}),
    ]
    result = [(name, state, TRIAGE_QUESTIONS) for name, state in cases]
    result.append((
        'completion_failed_tests',
        {
            'request': '修复登录重定向问题，并确认重定向回归测试通过。',
            'agent_claim': '修复已经全部完成，可以交付。',
            'evidence': {
                'files_changed': ['auth_redirect.ts'],
                'test_run': {'exit_code': 1, 'passed': 3, 'failed': 1},
                'failure': 'authenticated user was redirected to /login',
            },
        },
        {
            'completed': {
                'type': 'noul',
                'instructions': '仅根据 evidence，用户 request 的交付要求是否全部满足？'
                'agent_claim 只是待核验的陈述，不能当作完成证据。',
            },
            'next_step': {
                'type': 'choice',
                'instructions': '根据测试证据，下一步应做什么？',
                'criteria': {
                    'deliver': '任务要求已验证满足，可以交付',
                    'fix': '存在失败的回归测试，应继续修复',
                    'clarify': '任务要求不明确，需要澄清',
                },
            },
        },
    ))
    return result


def read_env(path):
    """Read simple KEY=value entries without evaluating shell expressions."""
    values = {}
    if path.exists():
        for line in path.read_text().splitlines():
            tokens = shlex.split(line, comments=True)
            if tokens and tokens[0] == 'export':
                tokens = tokens[1:]
            if tokens and '=' in tokens[0]:
                key, value = tokens[0].split('=', 1)
                values[key] = value
    for key in ('ATH_API_KEY', 'ATH_BASE_URL'):
        if key in os.environ:
            values[key] = os.environ[key]
    return values


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def validate_answers(payload, response):
    answers = response['answers']
    if set(answers) != set(payload['questions']):
        raise ValueError('Response question IDs do not match request')
    for name, question in payload['questions'].items():
        answer = answers[name]
        if answer['type'] != question['type']:
            raise ValueError('Response type does not match question')
        if question['type'] == 'noul':
            if not 0 <= answer['noul'] <= 1:
                raise ValueError('Invalid noul probability')
            continue
        probabilities = answer['probabilities']
        if not all(0 <= p <= 1 for p in probabilities.values()):
            raise ValueError('Invalid probabilities')
        # The preview endpoint rounds each probability to two decimal places.
        rounding_tolerance = 0.005 * len(probabilities) + 1e-9
        if not math.isclose(sum(probabilities.values()), 1,
                            abs_tol=rounding_tolerance):
            raise ValueError('Probabilities do not sum to one')
        if not 0 <= answer['confidence'] <= 1:
            raise ValueError('Invalid confidence')
        if question['type'] == 'choice':
            if set(probabilities) != set(question['criteria']):
                raise ValueError('Choice options do not match request')
            if answer['choice'] not in question['criteria']:
                raise ValueError('Unknown choice')
        else:
            expected_keys = {str(i) for i in range(len(question['criteria']))}
            if set(probabilities) != expected_keys:
                raise ValueError('Score levels do not match request')
            mean = sum(int(k) * p for k, p in probabilities.items())
            if not math.isclose(answer['score'], mean, abs_tol=0.02):
                raise ValueError('Score is not the weighted level index')


def policy(answers):
    """Decisions only: this demo never executes the proposed action."""
    if 'owner' in answers:
        owner = answers['owner']
        if owner['choice'] == 'unknown' or owner['confidence'] < 0.8:
            return {'action': 'collect_more_evidence'}
        p = answers['core_blocked']['noul']
        priority = 'urgent' if p >= 0.9 else ('normal' if p <= 0.1 else 'review')
        return {'action': 'route', 'owner': owner['choice'], 'priority': priority}
    return {
        'action': 'deliver' if answers['completed']['noul'] >= 0.95
        and answers['next_step']['choice'] == 'deliver' else 'continue_review',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path,
                        default=Path(__file__).resolve().parents[3] / '.env')
    parser.add_argument('--output', type=Path, default=Path('/tmp/jev-demo.json'))
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--case', choices=[name for name, _, _ in examples()])
    args = parser.parse_args()
    cases = [(name, {'model': 'decision-model-preview', 'state': state,
                     'questions': questions})
             for name, state, questions in examples()]
    if args.case:
        cases = [(name, payload) for name, payload in cases if name == args.case]
    if args.dry_run:
        print(json.dumps(dict(cases), ensure_ascii=False, indent=2))
        return
    env = read_env(args.env_file)
    key = env.get('ATH_API_KEY')
    base_url = env.get('ATH_BASE_URL', '').rstrip('/')
    url = base_url + '/systemone'
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.username or parsed.password
            or parsed.query or parsed.fragment or not key):
        raise SystemExit('Configure ATH_API_KEY and an HTTPS ATH_BASE_URL')
    opener = urllib.request.build_opener(NoRedirect())
    record = {'recorded_at_utc': datetime.now(timezone.utc).isoformat(),
              'endpoint': url, 'synthetic_data': True, 'runs': []}
    for name, payload in cases:
        req = urllib.request.Request(
            url, data=json.dumps(payload, ensure_ascii=False).encode(),
            headers={'Authorization': 'Bearer ' + key,
                     'Content-Type': 'application/json'}, method='POST')
        start = time.perf_counter()
        try:
            with opener.open(req, timeout=45) as res:
                response = json.loads(res.read())
        except urllib.error.HTTPError as exc:
            raise SystemExit(f'HTTP {exc.code}; credentials and body omitted') from None
        except urllib.error.URLError:
            raise SystemExit('Connection failed; credentials omitted') from None
        elapsed = round((time.perf_counter() - start) * 1000, 2)
        try:
            validate_answers(payload, response)
            validation_error = None
        except (ValueError, KeyError, TypeError) as exc:
            validation_error = str(exc)
        run = {'case': name, 'request': payload, 'response': response,
               'client_elapsed_ms': elapsed, 'validation_error': validation_error,
               'policy': ({'action': 'review_invalid_response'} if validation_error
                          else policy(response['answers']))}
        record['runs'].append(run)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps({'case': name, 'answers': response['answers'],
                          'usage': response.get('usage'),
                          'client_elapsed_ms': elapsed,
                          'validation_error': validation_error,
                          'policy': run['policy']},
                         ensure_ascii=False), flush=True)
    print(f'Saved {len(cases)} responses with validation status to {args.output}')


if __name__ == '__main__':
    main()
