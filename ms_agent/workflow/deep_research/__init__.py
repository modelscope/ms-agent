from .principle import (BSGMatrixPrinciple, MECEPrinciple, ParetoPrinciple,
                        Principle, PyramidPrinciple, SWOTPrinciple,
                        ValueChainPrinciple)
from .research_workflow import ResearchWorkflow


def __getattr__(name: str):
    if name == 'ResearchWorkflowBeta':
        from .research_workflow_beta import ResearchWorkflowBeta
        return ResearchWorkflowBeta
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')


__all__ = [
    'BSGMatrixPrinciple',
    'MECEPrinciple',
    'ParetoPrinciple',
    'Principle',
    'PyramidPrinciple',
    'ResearchWorkflow',
    'ResearchWorkflowBeta',
    'SWOTPrinciple',
    'ValueChainPrinciple',
]
