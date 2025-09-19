from typing import Dict, List, Optional

from pydantic import BaseModel, Field
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()


class ResearchProgress(BaseModel):
    """Model for tracking research progress."""

    current_depth: int
    total_depth: int
    current_breadth: int
    total_breadth: int
    current_query: Optional[str] = None
    total_queries: int
    completed_queries: int


class ResearchResult(BaseModel):
    """Model for research results."""

    learnings: List[str] = Field(default_factory=list)
    visited_urls: List[str] = Field(default_factory=list)
    resource_map: Dict[str, str] = Field(default_factory=dict)


class ResearchRequest(BaseModel):
    """Request model for research API."""

    query: str = Field(..., description='Research query')
    depth: int = Field(default=2, ge=1, le=5, description='Research depth')
    breadth: int = Field(
        default=4, ge=1, le=10, description='Research breadth')


class ResearchResponse(BaseModel):
    """Response model for research API."""

    success: bool
    answer: str
    learnings: List[str]
    visited_urls: List[str]


class LearningsResponse(BaseModel):
    """Response model for processed search results."""

    learnings: List[str] = Field(
        ..., description='List of learnings extracted from search results')
    follow_up_questions: List[str] = Field(
        ..., description='List of follow-up questions for further research')


class ProgressTracker:
    """Track and display research progress."""

    def __init__(self):
        self.progress: Optional[Progress] = None
        self.task_id: Optional[int] = None

    def __enter__(self):
        self.progress = Progress(
            SpinnerColumn(),
            TextColumn('[progress.description]{task.description}'),
            console=console)
        self.progress.__enter__()
        self.task_id = self.progress.add_task(
            'Starting research...', total=None)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.progress:
            self.progress.__exit__(exc_type, exc_val, exc_tb)

    def update_progress(self, research_progress: ResearchProgress) -> None:
        """Update the progress display."""
        if self.progress and self.task_id is not None:
            description = (
                f'Depth: {research_progress.current_depth}/{research_progress.total_depth}, '
                f'Breadth: {research_progress.current_breadth}/{research_progress.total_breadth}, '
                f'Queries: {research_progress.completed_queries}/{research_progress.total_queries}'
            )
            if research_progress.current_query:
                description += f' - {research_progress.current_query[:50]}...'

            self.progress.update(self.task_id, description=description)
