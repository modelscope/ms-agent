# Copyright (c) Alibaba, Inc. and its affiliates.
from abc import ABC, abstractmethod
import json
import base64
import mimetypes
from pathlib import Path
from typing import Optional, List
import requests

from ms_agent.utils.logger import get_logger
from ms_agent.utils.utils import get_files_from_dir

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
        raise NotImplementedError("Subclasses must implement the push method.")


class PushToGitHub(PushToHub):

    GITHUB_API_URL = "https://api.github.com"

    def __init__(self,
                 user_name: str,
                 repo_name: str,
                 token: str,
                 visibility: Optional[str] = "public",
                 description: Optional[str] = None):
        """
        Initialize the GitHub pusher with authentication.

        Args:
            user_name (str): GitHub username.
            repo_name (str): Name of the repository to create or use.
            token (str): GitHub personal access token with repo permissions.
                Access token can be generated from GitHub settings under Developer settings -> Personal access tokens.
                Refer to `https://github.com/settings/tokens` for details.
            visibility (str, optional): Visibility of the repository, either "public" or "private".
                Defaults to "public".
            description (str, optional): Description of the repository. Defaults to a generic message.

        Raises:
            ValueError: If the token is empty.
            RuntimeError: If there is an issue with the GitHub API.
        """
        super().__init__()

        if not all([user_name, repo_name, token]):
            raise ValueError("GitHub username, repository name, and token must be provided.")

        self.user_name = user_name
        self.repo_name = repo_name
        self.token = token
        self.visibility = visibility
        self.description = description

        # Create a session and set authentication headers
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"token {self.token}",
            "Accept": "application/vnd.github.v3+json",
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
        user_data_resp = self.session.get(f"{self.GITHUB_API_URL}/user")
        if user_data_resp.status_code != 200 or user_data_resp.json()['login'] != self.user_name:
            raise RuntimeError("❌ Authentication failed! Please check your username and Personal Access Token.")


    def _create_github_repo(self,
                            repo_name: str,
                            visibility: Optional[str] = "public",
                            description: Optional[str] = None,
                            ):
        """
        Create a new GitHub repository.

        Args:
            repo_name (str): Name of the repository to create.
            visibility (str, optional): Visibility of the repository, either "public" or "private". Defaults to "public".
            description (str, optional): Description of the repository. Defaults to a generic message.

        Returns:
            dict: The JSON response from the GitHub API containing repository details if successful.
        """

        if not repo_name:
            raise ValueError("Repository name cannot be empty.")

        if visibility not in ["public", "private"]:
            raise ValueError("Visibility must be either 'public' or 'private'.")

        if description is None:
            description = f"Repository - `{repo_name}` created by MS-Agent."

        # Create the first commit with README
        url = f"{self.GITHUB_API_URL}/user/repos"
        payload = {
            "name": repo_name,
            "description": description,
            "private": visibility == "private",
            "auto_init": True
        }
        response = self.session.post(url, data=json.dumps(payload))
        if response.status_code == 201:
            logger.info(f"✅ Successfully created and initialized repository: {response.json()['html_url']}")
            return response.json()
        elif response.status_code == 422:
            error_message = response.json().get('errors', [{}])[0].get('message', '')
            if "name already exists" in error_message:
                logger.info(f"⚠️ Repository '{repo_name}' already exists. Will attempt to upload files to it.")
                return None
            else:
                raise ValueError(f"Validation error (422) while creating repository: {response.json()}")
        else:
            logger.error(response.json())
            raise RuntimeError(f"❌ Failed to create repository: {response.status_code}")

    def _upload_files(self,
                      files_to_upload: List[Path],
                      work_dir: Path,
                      path_in_repo: Optional[str] = None,
                      branch: Optional[str] = "main") -> None:
        """
        Upload multiple files to a GitHub repository in a single commit.

        Args:
            files_to_upload (List[Path]): List of file paths to upload.
            work_dir (Path): The working directory where the files are located.
            path_in_repo (Optional[str]): The relative path in the repository where files should be stored.
                Defaults to the root of the repository.
            branch (Optional[str]): The branch to push changes to. Defaults to "main".

        Raises:
            RuntimeError: If there is an issue with the GitHub API or if the branch does not exist.
        """
        # 1. Get the latest commit SHA and tree SHA for the 'main' branch
        ref_url = f"{self.GITHUB_API_URL}/repos/{self.user_name}/{self.repo_name}/git/refs/heads/{branch}"
        ref_response = self.session.get(ref_url)
        ref_response.raise_for_status()

        ref_data = ref_response.json()
        latest_commit_sha = ref_data['object']['sha']

        commit_url = f"{self.GITHUB_API_URL}/repos/{self.user_name}/{self.repo_name}/git/commits/{latest_commit_sha}"
        commit_response = self.session.get(commit_url)
        commit_response.raise_for_status()
        base_tree_sha = commit_response.json()['tree']['sha']

        logger.info(f"✅ Found '{branch}' branch, latest commit: {latest_commit_sha[:7]}")

        # 2. Create a blob for each file
        blobs = []
        logger.info("Processing files...")
        repo_base_path = Path(path_in_repo or "")

        for full_path in files_to_upload:

            file_relative_path: str = str(full_path.relative_to(work_dir)).replace("\\", "/")

            mime_type, _ = mimetypes.guess_type(full_path)
            is_binary = not (mime_type and mime_type.startswith('text/')) if mime_type else False

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

            blob_url = f"{self.GITHUB_API_URL}/repos/{self.user_name}/{self.repo_name}/git/blobs"
            blob_payload = {"content": content, "encoding": encoding}

            response = self.session.post(blob_url, data=json.dumps(blob_payload))
            response.raise_for_status()

            remote_path = repo_base_path / file_relative_path
            remote_path_str = str(remote_path).replace("\\", "/")

            blobs.append({
                "path": remote_path_str,
                "mode": "100644", "type": "blob", "sha": response.json()['sha']
            })
            logger.info(f"  - Local: '{str(full_path)}'  ->  Remote: '{remote_path_str}'")

        # 3. Create a tree object
        tree_url = f"{self.GITHUB_API_URL}/repos/{self.user_name}/{self.repo_name}/git/trees"
        tree_payload = {"tree": blobs, "base_tree": base_tree_sha}

        response = self.session.post(tree_url, data=json.dumps(tree_payload))
        response.raise_for_status()
        tree_sha = response.json()['sha']

        # 4. Create a commit
        commit_url = f"{self.GITHUB_API_URL}/repos/{self.user_name}/{self.repo_name}/git/commits"
        commit_payload = {
            "message": f"feat: Upload report to '{path_in_repo or '/'}'",
            "tree": tree_sha,
            "parents": [latest_commit_sha]
        }
        response = self.session.post(commit_url, data=json.dumps(commit_payload))
        response.raise_for_status()
        new_commit_sha = response.json()['sha']
        logger.info(f"✅ Commit created: {new_commit_sha[:7]}")

        # 5. Update the branch reference
        ref_payload = {"sha": new_commit_sha}
        response = self.session.patch(ref_url, data=json.dumps(ref_payload))
        response.raise_for_status()

        logger.info(f"✅ Branch '{branch}' successfully points to the new commit")

    def push(self,
             target_dir: str,
             exclude: Optional[List[str]] = None,
             path_in_repo: Optional[str] = None,
             branch: Optional[str] = "main",
             **kwargs) -> None:
        """
        Push files from a local directory to the GitHub repository.

        Args:
            target_dir (str): The local directory containing files to upload.
            exclude (Optional[List[str]]):
                List of regex patterns to exclude files from upload. Defaults to hidden files, logs, and __pycache__.
            path_in_repo (Optional[str]):
                The relative path in the repository where files should be stored.
                Defaults to the root of the repository.
            branch (Optional[str]): The branch to push changes to. Defaults to "main".

        Raises:
            RuntimeError: If there is an issue with the GitHub API or if the branch does not exist.
        """

        # Get available files without hidden files, logs and __pycache__
        if exclude is None:
            exclude = [r'(^|/)\..*', r'\.log$', r'~$', r'__pycache__/']
        files = get_files_from_dir(target_dir=target_dir, exclude=exclude)

        if not files:
            logger.warning("No files to upload, pushing skipped.")
            return

        self._upload_files(
            files_to_upload=files,
            work_dir=Path(target_dir),
            path_in_repo=path_in_repo,
            branch=branch,
        )

        logger.info(f"✅ Successfully pushed files to '{self.user_name}/{self.repo_name}' on branch '{branch}'.")
