"""Provider-independent request validation and typed probabilistic answers."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any, Protocol


class DecisionError(ValueError):
    """A decision could not be used; contains no provider credentials/body."""


@dataclass(frozen=True)
class DecisionCapabilities:
    types: tuple[str, ...] = ('noul', 'choice', 'score')
    max_questions: int = 16
    max_options: int = 255
    max_input_chars: int = 64000


@dataclass(frozen=True)
class DecisionRequest:
    state: dict[str, Any]
    questions: dict[str, dict[str, Any]]
    request_id: str = ''

    def validate(self, caps: DecisionCapabilities) -> None:
        if not isinstance(self.state, dict) or not isinstance(
                self.questions, dict):
            raise DecisionError(
                'Decision state and questions must be JSON objects')
        if not self.questions or len(self.questions) > caps.max_questions:
            raise DecisionError('Invalid number of decision questions')
        try:
            encoded = json.dumps(
                {
                    'state': self.state,
                    'questions': self.questions
                },
                ensure_ascii=False,
                allow_nan=False)
        except (ValueError, TypeError):
            raise DecisionError(
                'Decision input must be finite JSON data') from None
        if len(encoded) > caps.max_input_chars:
            raise DecisionError('Decision input exceeds the configured limit')
        for key, q in self.questions.items():
            if not isinstance(key, str) or not key or not isinstance(q, dict):
                raise DecisionError('Invalid decision question')
            kind = q.get('type')
            if kind not in caps.types or not isinstance(
                    q.get('instructions'), str):
                raise DecisionError('Unsupported decision question type')
            if kind == 'noul':
                continue
            criteria = q.get('criteria')
            if (kind == 'choice' and not isinstance(criteria, dict)
                    or kind == 'score' and not isinstance(criteria, list)):
                raise DecisionError('Invalid decision criteria')
            if not 2 <= len(criteria) <= caps.max_options:
                raise DecisionError('Invalid number of decision options')
            if isinstance(criteria, dict) and not all(
                    isinstance(k, str) and k for k in criteria):
                raise DecisionError(
                    'Decision option IDs must be nonempty strings')
            values = criteria.values() if isinstance(criteria,
                                                     dict) else criteria
            if not all(isinstance(v, str) and v for v in values):
                raise DecisionError('Decision options need descriptions')


def _prob(value: Any) -> float:
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or not 0 <= value <= 1):
        raise DecisionError('Invalid decision probability')
    return float(value)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise DecisionError('Duplicate key in decision response')
        result[key] = value
    return result


@dataclass(frozen=True)
class DecisionResponse:
    answers: dict[str, dict[str, Any]]
    model: str = ''
    usage: dict = field(default_factory=dict)
    elapsed_ms: float = 0

    @classmethod
    def parse(cls, body: str, request: DecisionRequest, *, elapsed_ms=0):
        try:
            raw = json.loads(body, object_pairs_hook=unique_object)
            answers = raw['answers']
            if set(answers) != set(request.questions):
                raise DecisionError('Decision question IDs do not match')
            for key, question in request.questions.items():
                answer = answers[key]
                if answer['type'] != question['type']:
                    raise DecisionError('Decision answer type does not match')
                if answer['type'] == 'noul':
                    _prob(answer['noul'])
                    continue
                probabilities = answer['probabilities']
                criteria = question['criteria']
                expected = set(criteria) if isinstance(criteria, dict) else {
                    str(i)
                    for i in range(len(criteria))
                }
                if set(probabilities) != expected:
                    raise DecisionError('Decision options do not match')
                values = [_prob(p) for p in probabilities.values()]
                # System One preview rounds distributions to two decimal places.
                if abs(sum(values) - 1) > 0.005 * len(values) + 1e-9:
                    raise DecisionError('Invalid decision distribution')
                if 'confidence' in answer:
                    _prob(answer['confidence'])
                if answer['type'] == 'choice':
                    if answer['choice'] not in expected:
                        raise DecisionError('Unknown decision choice')
                    if probabilities[answer['choice']] + 0.01 < max(values):
                        raise DecisionError(
                            'Decision choice conflicts with its distribution')
                else:
                    mean = sum(int(k) * v for k, v in probabilities.items())
                    score = answer['score']
                    tolerance = 0.005 * sum(range(len(values))) + 0.01
                    if (isinstance(score, bool)
                            or not isinstance(score, (int, float))
                            or not math.isfinite(score)
                            or not 0 <= score <= len(values) - 1
                            or abs(score - mean) > tolerance):
                        raise DecisionError('Invalid decision score')
            usage = raw.get('usage', {})
            return cls(answers, str(raw.get('model', '')),
                       usage if isinstance(usage, dict) else {}, elapsed_ms)
        except DecisionError:
            raise
        except (ValueError, TypeError, KeyError, AttributeError):
            raise DecisionError('Malformed decision response') from None


class DecisionClient(Protocol):
    capabilities: DecisionCapabilities

    async def decide(self,
                     request: DecisionRequest,
                     *,
                     timeout: float = 5) -> DecisionResponse:
        ...

    async def aclose(self) -> None:
        ...
