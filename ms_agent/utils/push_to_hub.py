# Copyright (c) ModelScope Contributors. All rights reserved.
import base64
import mimetypes
import os
import re
import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Optional, Tuple

import json
import requests
from ms_agent.utils.logger import get_logger
from ms_agent.utils.utils import (get_files_from_dir, is_package_installed,
                                  text_hash)

logger = get_logger()


class PushToHub(ABC):
    """
    The abstract base class for pushing files to a remote hub (e.g., GitHub).
    """

    def __init__(self, *args, **kwargs):
        ...

    @abstractmethod
    def push(self, *args, **kwargs):
        """Push files to the remote hub."""
        raise NotImplementedError('Subclasses must implement the push method.')


class PushToGitHub(PushToHub):

    GITHUB_API_URL = 'https://api.github.com'

    def __init__(self,
                 user_name: str,
                 repo_name: str,
                 token: str,
                 visibility: Optional[str] = 'public',
                 description: Optional[str] = None):
        """
        Initialize the `PushToGitHub` class with authentication.

        Args:
            user_name (str): GitHub username.
            repo_name (str): Name of the repository to create or use.
                If the repository already exists, it will be used for pushing files.
            token (str): GitHub personal access token with repo permissions.
                Access token can be generated from GitHub settings under Developer settings -> Personal access tokens.
                Refer to `https://github.com/settings/tokens` for details.
            visibility (str, optional): Visibility of the repository, either "public" or "private".
                Defaults to "public". It's available for creating the repository.
            description (str, optional): Description of the repository. Defaults to a generic message.

        Raises:
            ValueError: If the token is empty.
            RuntimeError: If there is an issue with the GitHub API.

        Examples:
            >>> push_to_github = PushToGitHub(
            ...     user_name="your_username",
            ...     repo_name="your_repo_name",
            ...     token="your_personal_access_token",
            ...     visibility="public",
            ...     description="My awesome repository"
            ... )
            >>> push_to_github.push(folder_path="/path/to/your_dir", branch="main", commit_message="Initial commit")
        """
        super().__init__()

        if not all([user_name, repo_name, token]):
            raise ValueError(
                'GitHub username, repository name, and token must be provided.'
            )

        self.user_name = user_name
        self.repo_name = repo_name
        self.token = token
        self.visibility = visibility
        self.description = description

        # Create a session and set authentication headers
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'token {self.token}',
            'Accept': 'application/vnd.github.v3+json',
        })

        self._check_auth()
        self._create_github_repo(
            repo_name=self.repo_name,
            visibility=self.visibility,
            description=self.description,
        )

    def _check_auth(self):
        """
        Check if the authentication with GitHub is successful.
        Raises:
            RuntimeError: If authentication fails.
        """
        user_data_resp = self.session.get(f'{self.GITHUB_API_URL}/user')
        if user_data_resp.status_code != 200 or user_data_resp.json(
        )['login'] != self.user_name:
            raise RuntimeError(
                'Authentication failed! Please check your username and Personal Access Token.'
            )

    def _create_github_repo(
        self,
        repo_name: str,
        visibility: Optional[str] = 'public',
        description: Optional[str] = None,
    ):
        """
        Create a new GitHub repository.

        Args:
            repo_name (str): Name of the repository to create.
            visibility (str, optional): Visibility of the repository, either "public" or "private".
                Defaults to "public".
            description (str, optional): Description of the repository. Defaults to a generic message.

        Returns:
            dict: The JSON response from the GitHub API containing repository details if successful.
        """

        if not repo_name:
            raise ValueError('Repository name cannot be empty.')

        if visibility not in ['public', 'private']:
            raise ValueError(
                "Visibility must be either 'public' or 'private'.")

        if description is None:
            description = f'Repository - `{repo_name}` created by MS-Agent.'

        # Create the first commit with README
        url = f'{self.GITHUB_API_URL}/user/repos'
        payload = {
            'name': repo_name,
            'description': description,
            'private': visibility == 'private',
            'auto_init': True
        }
        response = self.session.post(url, json=payload)
        if response.status_code == 201:
            logger.info(
                f"Successfully created and initialized repository: {response.json()['html_url']}"
            )
            return response.json()
        elif response.status_code == 422:
            error_message = response.json().get('errors',
                                                [{}])[0].get('message', '')
            if 'name already exists' in error_message:
                logger.info(
                    f"Repository '{repo_name}' already exists. Will attempt to upload files to it."
                )
                return None
            else:
                raise ValueError(
                    f'Validation error (422) while creating repository: {response.json()}'
                )
        else:
            logger.error(response.json())
            raise RuntimeError(
                f'Failed to create repository: {response.status_code}')

    def _upload_files(self,
                      files_to_upload: List[Path],
                      work_dir: Path,
                      path_in_repo: Optional[str] = None,
                      branch: Optional[str] = 'main',
                      commit_message: Optional[str] = None) -> None:
        """
        Upload multiple files to a GitHub repository in a single commit.

        Args:
            files_to_upload (List[Path]): List of file paths to upload.
            work_dir (Path): The working directory where the files are located.
            path_in_repo (Optional[str]): The relative path in the repository where files should be stored.
                Defaults to the root of the repository.
            branch (Optional[str]): The branch to push changes to. Defaults to "main".
            commit_message (Optional[str]): The commit message for the upload. Defaults to a generic message.

        Raises:
            RuntimeError: If there is an issue with the GitHub API or if the branch does not exist.
        """
        # 1. Get the latest commit SHA and tree SHA for the 'main' branch
        ref_url = f'{self.GITHUB_API_URL}/repos/{self.user_name}/{self.repo_name}/git/refs/heads/{branch}'
        ref_response = self.session.get(ref_url)
        ref_response.raise_for_status()

        ref_data = ref_response.json()
        latest_commit_sha = ref_data['object']['sha']

        commit_url = f'{self.GITHUB_API_URL}/repos/{self.user_name}/{self.repo_name}/git/commits/{latest_commit_sha}'
        commit_response = self.session.get(commit_url)
        commit_response.raise_for_status()
        base_tree_sha = commit_response.json()['tree']['sha']

        logger.info(
            f"Found '{branch}' branch, latest commit: {latest_commit_sha[:7]}")

        # 2. Create a blob for each file
        blobs = []
        logger.info('Processing files...')
        repo_base_path = Path(path_in_repo or '')

        for full_path in files_to_upload:

            file_relative_path: str = str(
                full_path.relative_to(work_dir)).replace('\\', '/')

            mime_type, _ = mimetypes.guess_type(full_path)
            is_binary = not (mime_type and mime_type.startswith('text/')
                             ) if mime_type else False

            with open(full_path, 'rb') as f:
                content_bytes = f.read()

            if is_binary:
                content = base64.b64encode(content_bytes).decode('utf-8')
                encoding = 'base64'
            else:
                try:
                    content = content_bytes.decode('utf-8')
                    encoding = 'utf-8'
                except UnicodeDecodeError:
                    content = base64.b64encode(content_bytes).decode('utf-8')
                    encoding = 'base64'

            blob_url = f'{self.GITHUB_API_URL}/repos/{self.user_name}/{self.repo_name}/git/blobs'
            blob_payload = {'content': content, 'encoding': encoding}

            response = self.session.post(
                blob_url, data=json.dumps(blob_payload))
            response.raise_for_status()

            remote_path = repo_base_path / file_relative_path
            remote_path_str = str(remote_path).replace('\\', '/')

            blobs.append({
                'path': remote_path_str,
                'mode': '100644',
                'type': 'blob',
                'sha': response.json()['sha']
            })
            logger.info(
                f"  - Local: '{str(full_path)}'  ->  Remote: '{remote_path_str}'"
            )

        # 3. Create a tree object
        tree_url = f'{self.GITHUB_API_URL}/repos/{self.user_name}/{self.repo_name}/git/trees'
        tree_payload = {'tree': blobs, 'base_tree': base_tree_sha}

        response = self.session.post(tree_url, data=json.dumps(tree_payload))
        response.raise_for_status()
        tree_sha = response.json()['sha']

        # 4. Create a commit
        commit_url = f'{self.GITHUB_API_URL}/repos/{self.user_name}/{self.repo_name}/git/commits'
        commit_payload = {
            'message': commit_message
            or f"Upload files to '{path_in_repo or '/'}'",
            'tree': tree_sha,
            'parents': [latest_commit_sha]
        }
        response = self.session.post(
            commit_url, data=json.dumps(commit_payload))
        response.raise_for_status()
        new_commit_sha = response.json()['sha']
        logger.info(f'Commit created: {new_commit_sha[:7]}')

        # 5. Update the branch reference
        ref_payload = {'sha': new_commit_sha}
        response = self.session.patch(ref_url, data=json.dumps(ref_payload))
        response.raise_for_status()

        logger.info(f"Branch '{branch}' successfully points to the new commit")

    def push(self,
             folder_path: str,
             path_in_repo: Optional[str] = None,
             branch: Optional[str] = 'main',
             commit_message: Optional[str] = None,
             exclude: Optional[List[str]] = None,
             **kwargs) -> None:
        """
        Push files from a local directory to the GitHub repository.

        Args:
            folder_path (str): The local directory containing files to upload.
            path_in_repo (Optional[str]):
                The relative path in the repository where files should be stored.
                Defaults to the root of the repository.
            branch (Optional[str]): The branch to push changes to. Defaults to "main".
            commit_message (Optional[str]):
                The commit message for the upload. Defaults to a generic message.
            exclude (Optional[List[str]]):
                List of regex patterns to exclude files from upload. Defaults to hidden files, logs, and __pycache__.

        Raises:
            RuntimeError: If there is an issue with the GitHub API or if the branch does not exist.
        """

        # Get available files without hidden files, logs and __pycache__
        if exclude is None:
            exclude = [r'(^|/)\..*', r'\.log$', r'~$', r'__pycache__/']
        files = get_files_from_dir(folder_path=folder_path, exclude=exclude)

        if not files:
            logger.warning('No files to upload, pushing skipped.')
            return

        self._upload_files(
            files_to_upload=files,
            work_dir=Path(folder_path),
            path_in_repo=path_in_repo,
            branch=branch,
            commit_message=commit_message,
        )

        logger.info(
            f'Successfully pushed files to '
            f"https://github.com/{self.user_name}/{self.repo_name}/tree/{branch}/{path_in_repo or ''}"
        )


class PushToModelScope(PushToHub):
    """
    Push files to ModelScope repository.
    """

    def __init__(
        self,
        token: str,
    ):
        """
        Initialize the `PushToModelScope` with authentication.

        Args:
            token (str): ModelScope access token with permissions to push to the repository.
                You can get the token from your ModelScope account settings.
                Refer to `https://modelscope.cn/my/myaccesstoken`
        """

        if not is_package_installed('modelscope'):
            raise ImportError(
                'ModelScope package is not installed. Please install it with `pip install modelscope`.'
            )

        from modelscope.hub.api import HubApi
        from modelscope.hub.api import get_endpoint

        self.api = HubApi()
        self.token = token
        self.endpoint = get_endpoint()

        super().__init__()

    @staticmethod
    def _preprocess(folder_path: str,
                    path_in_repo_url: str,
                    add_powered_by: bool = True) -> 'Tuple[str, str]':

        report_filename = 'report.md'
        file_path = os.path.join(folder_path, report_filename)
        file_path_hash: str = text_hash(text=file_path, keep_n_chars=8)
        new_report_filename: str = f'report_{file_path_hash}.md'
        current_cache_path: str = os.path.join(folder_path, '.cache')
        os.makedirs(current_cache_path, exist_ok=True)
        new_file_path = os.path.join(current_cache_path, new_report_filename)

        if not os.path.exists(file_path):
            logger.warning(
                f'The report file: {file_path} does not exist. Skipping preprocessing.'
            )
            return '', ''

        try:
            shutil.copy(file_path, new_file_path)
        except Exception as e:
            logger.error(f'Error copying the report file: {e}')
            return '', ''

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                if add_powered_by and not content.lstrip().startswith(
                        '<span style='):
                    content = """<span style="color: darkgreen; font-weight: bold; font-family: monospace;
                    ">Powered by [MS-Agent](https://github.com/modelscope/ms-agent) |
                    [DocResearch](https://github.com/modelscope/ms-agent/blob/main/projects/doc_research/README.md)
                    </span>""" + '\n\n' + content

            pattern = r'!\[(.*?)\]\((resources/.*?)\)'
            replacement = rf'![\1]({path_in_repo_url}\2)'
            new_content, count = re.subn(pattern, replacement, content)

            if count > 0:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(new_content)
                logger.info(
                    f"Preprocessed {count} 'resources/' links in {file_path}.")
            else:
                logger.info(
                    f'No "resources/" links found in {file_path}. No changes made.'
                )

        except IOError as e:
            logger.error(f'Error reading or writing the report file: {e}')
            return '', ''
        except Exception as e:
            logger.error(
                f'Unexpected error during preprocessing of PushToModelScope: {e}'
            )
            return '', ''

        return file_path, new_file_path

    @staticmethod
    def _postprocess(report_file_path: str, report_file_path_in_cache: str):

        try:
            shutil.move(report_file_path_in_cache, report_file_path)
            shutil.rmtree(
                os.path.dirname(report_file_path_in_cache), ignore_errors=True)
        except FileNotFoundError:
            logger.warning(
                f'The backup file of report: {report_file_path_in_cache} does not exist.'
            )

    def push(
        self,
        *,
        repo_id: str,
        folder_path: str,
        path_in_repo: Optional[str] = None,
        repo_type: Optional[str] = 'model',
        commit_message: Optional[str] = None,
        exclude: Optional[List[str]] = None,
        add_powered_by: Optional[bool] = True,
    ):
        """
        Push files from a local directory to the ModelScope repository.

        Args:
            repo_id (str): The ModelScope repository ID in the format 'namespace/repo_name'.
                For example, 'my_namespace/my_model'.
            folder_path (str): The local directory containing files to upload.
            path_in_repo (Optional[str]): The relative path in the repository where files should be stored.
                Defaults to the root of the repository.
            repo_type (Optional[str]): Type of the repository, either 'model' or 'dataset'. Defaults to 'model'.
            commit_message (Optional[str]): The commit message for the upload. Defaults to a generic message.
            exclude (Optional[List[str]]): List of regex patterns to exclude files from upload. Defaults to None.
        """
        path_in_repo_replace = f'{path_in_repo.rstrip("/")}/' if path_in_repo else ''
        path_in_repo_url: str = f'{self.endpoint}/{repo_type}s/{repo_id}/resolve/master/{path_in_repo_replace}'
        origin_report, backup_report = self._preprocess(
            folder_path=folder_path,
            path_in_repo_url=path_in_repo_url,
            add_powered_by=add_powered_by,
        )

        try:
            self.api.upload_folder(
                repo_id=repo_id,
                folder_path=folder_path,
                path_in_repo=path_in_repo,
                commit_message=commit_message or f'Upload files to {repo_id}',
                token=self.token,
                ignore_patterns=exclude,
                revision='master',
            )
            target_url: str = f'{self.endpoint}/{repo_type}s/{repo_id}/files'
            logger.info(
                f'Successfully pushed files to ModelScope: {target_url}')
        except Exception as e:
            logger.error(f'Failed to push files to ModelScope: {e}')
        finally:
            if origin_report and backup_report:
                self._postprocess(
                    report_file_path=origin_report,
                    report_file_path_in_cache=backup_report,
                )


class PushToHuggingFace(PushToHub):

    def __init__(self, token: str):
        """
        Initialize the `PushToHuggingFace` with authentication.

        Args:
            token (str): HuggingFace access token with permissions to push to the repository.
                Refer to: https://huggingface.co/docs/huggingface_hub/quick-start#authentication
        """

        if not is_package_installed('huggingface_hub'):
            raise ImportError(
                'The `huggingface-hub` package is not installed. Please install it with `pip install huggingface-hub`.'
            )

        from huggingface_hub import HfApi

        self.api = HfApi()
        self.token = token

        super().__init__()

    def push(
        self,
        *,
        repo_id: str,
        folder_path: str,
        path_in_repo: Optional[str] = None,
        repo_type: Optional[str] = 'model',
        commit_message: Optional[str] = None,
        exclude: Optional[List[str]] = None,
        revision: Optional[str] = 'main',
    ):
        """
        Push files from a local directory to the HuggingFace repository.

        Args:
            repo_id (str): The HuggingFace repository ID in the format 'namespace/repo_name'.
                For example, 'my_namespace/my_model'.
            folder_path (str): The local directory containing files to upload.
            path_in_repo (Optional[str]): The relative path in the repository where files should be stored.
                Defaults to the root of the repository.
            repo_type (Optional[str]): Type of the repository, either 'model' or 'dataset'. Defaults to 'model'.
            commit_message (Optional[str]): The commit message for the upload. Defaults to a generic message.
            exclude (Optional[List[str]]): List of regex patterns to exclude files from upload. Defaults to None.
            revision (Optional[str]): The revision to push changes to. Defaults to "main".
        """
        if not repo_id:
            raise ValueError('Repository ID cannot be empty.')

        if repo_type not in ['model', 'dataset']:
            raise ValueError(
                "Repository type must be either 'model' or 'dataset'.")

        try:
            self.api.upload_folder(
                repo_id=repo_id,
                folder_path=folder_path,
                path_in_repo=path_in_repo,
                commit_message=commit_message,
                token=self.token,
                repo_type=repo_type,
                ignore_patterns=exclude,
                revision=revision,
            )

            repo_type_in_url: str = '' if repo_type == 'model' else 'datasets/'
            logger.info(
                f'Successfully pushed files to '
                f'https://huggingface.co/{repo_type_in_url}{repo_id}/tree/main/{path_in_repo or ""}'
            )
        except Exception as e:
            logger.error(
                f'Failed to push files to {repo_id} on HuggingFace: {e}')
            raise e
