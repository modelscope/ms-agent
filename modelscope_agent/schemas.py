from typing import Dict, List, Union

from modelscope_agent.constants import DEFAULT_SEND_TO
from pydantic import BaseModel


class Message(BaseModel):
    """
    Message: message information
    """
    role: str = 'user'  # user, assistant, system, tool
    content: str = ''
    sent_from: str = ''
    send_to: Union[str, List[str]] = DEFAULT_SEND_TO


class Document(BaseModel):
    """
    Document: Record User uploaded document information
    """
    url: str
    time: str
    source: str
    raw: List
    title: str
    topic: str
    checked: bool
    session: List


class AgentAttr(BaseModel):
    """
    AgentAttr: Record Agent information
    """
    session: str = ''
    uuid: str = ''
    history: List[Message] = []

    knowledge: str = ''  # in case retrieval cost is much higher than storage


class CodeCell(BaseModel):
    code: str = ''
    result: str = ''


class TaskResult(BaseModel):
    """Result of taking a task, with result and is_success required to be filled"""

    code: str = ''
    result: str


class Task(BaseModel):
    task_id: str = ''
    dependent_task_ids: List[str] = []  # Tasks prerequisite to this Task
    instruction: str = ''
    task_type: str = ''
    code: str = ''
    result: str = ''
    is_finished: bool = False
    code_cells: List[CodeCell] = []

    def reset(self):
        self.code = ''
        self.result = ''
        self.is_success = False
        self.is_finished = False

    def update_task_result(self, task_result: TaskResult):
        self.code = task_result.code
        self.result = task_result.result
        self.is_success = task_result.is_success

    def append_code_cell(self, code_cell: CodeCell):
        self.code_cells.append(code_cell)


class Plan(BaseModel):
    goal: str
    context: str = ''
    tasks: List[Task] = []
    task_map: Dict[str, Task] = {}
    current_task_id: str = ''

    def _topological_sort(self, tasks: List[Task]):
        task_map = {task.task_id: task for task in tasks}
        dependencies = {
            task.task_id: set(task.dependent_task_ids)
            for task in tasks
        }
        sorted_tasks = []
        visited = set()

        def visit(task_id):
            if task_id in visited:
                return
            visited.add(task_id)
            for dependent_id in dependencies.get(task_id, []):
                visit(dependent_id)
            sorted_tasks.append(task_map[task_id])

        for task in tasks:
            visit(task.task_id)

        return sorted_tasks

    def add_tasks(self, tasks: List[Task]):
        """
        Integrates new tasks into the existing plan, ensuring dependency order is maintained.

        This method performs two primary functions based on the current state of the task list:
        1. If there are no existing tasks, it topologically sorts the provided tasks to ensure
        correct execution order based on dependencies, and sets these as the current tasks.
        2. If there are existing tasks, it merges the new tasks with the existing ones. It maintains
        any common prefix of tasks (based on task_id and instruction) and appends the remainder
        of the new tasks. The current task is updated to the first unfinished task in this merged list.

        Args:
            tasks (List[Task]): A List of tasks (may be unordered) to add to the plan.

        Returns:
            None: The method updates the internal state of the plan but does not return anything.
        """
        if not tasks:
            return

        # Topologically sort the new tasks to ensure correct dependency order
        new_tasks = self._topological_sort(tasks)

        if not self.tasks:
            # If there are no existing tasks, set the new tasks as the current tasks
            self.tasks = new_tasks

        else:
            # Find the length of the common prefix between existing and new tasks
            prefix_length = 0
            for old_task, new_task in zip(self.tasks, new_tasks):
                if old_task.task_id != new_task.task_id or old_task.instruction != new_task.instruction:
                    break
                prefix_length += 1

            # Combine the common prefix with the remainder of the new tasks
            final_tasks = self.tasks[:prefix_length] + new_tasks[prefix_length:]
            self.tasks = final_tasks

        # Update current_task_id to the first unfinished task in the merged list
        self._update_current_task()

        # Update the task map for quick access to tasks by ID
        self.task_map = {task.task_id: task for task in self.tasks}

    def reset_task(self, task_id: str):
        """
        Clear code and result of the task based on task_id, and set the task as unfinished.

        Args:
            task_id (str): The ID of the task to be reset.

        Returns:
            None
        """
        if task_id in self.task_map:
            task = self.task_map[task_id]
            task.reset()

    def replace_task(self, new_task: Task):
        """
        Replace an existing task with the new input task based on task_id, and reset all tasks depending on it.

        Args:
            new_task (Task): The new task that will replace an existing one.

        Returns:
            None
        """
        assert new_task.task_id in self.task_map
        # Replace the task in the task map and the task list
        self.task_map[new_task.task_id] = new_task
        for i, task in enumerate(self.tasks):
            if task.task_id == new_task.task_id:
                self.tasks[i] = new_task
                break

        # Reset dependent tasks
        for task in self.tasks:
            if new_task.task_id in task.dependent_task_ids:
                self.reset_task(task.task_id)

    def append_task(self, new_task: Task):
        """
        Append a new task to the end of existing task sequences

        Args:
            new_task (Task): The new task to be appended to the existing task sequence

        Returns:
            None
        """
        assert not self.has_task_id(
            new_task.task_id
        ), 'Task already in current plan, use replace_task instead'

        assert all([
            self.has_task_id(dep_id) for dep_id in new_task.dependent_task_ids
        ]), 'New task has unknown dependencies'

        # Existing tasks do not depend on the new task, it's fine to put it to the end of the sorted task sequence
        self.tasks.append(new_task)
        self.task_map[new_task.task_id] = new_task
        self._update_current_task()

    def has_task_id(self, task_id: str) -> bool:
        return task_id in self.task_map

    def _update_current_task(self):
        current_task_id = ''
        for task in self.tasks:
            if not task.is_finished:
                current_task_id = task.task_id
                break
        self.current_task_id = current_task_id  # all tasks finished

    @property
    def current_task(self) -> Task:
        """Find current task to execute

        Returns:
            Task: the current task to be executed
        """
        return self.task_map.get(self.current_task_id, None)

    def finish_current_task(self):
        """Finish current task, set Task.is_finished=True, set current task to next task"""
        if self.current_task_id:
            self.current_task.is_finished = True
            self._update_current_task()  # set to next task

    def get_finished_tasks(self) -> List[Task]:
        """return all finished tasks in correct linearized order
        Returns:
            List[Task]: List of finished tasks
        """
        return [task for task in self.tasks if task.is_finished]
