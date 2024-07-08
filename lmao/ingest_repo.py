import os
import json
import logging
from git import Repo, GitCommandError
from datetime import datetime
import argparse
from typing import List, Dict, Any

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("gitlab_ingestor.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def is_valid_file(file_path: str) -> bool:
    """
    Check if the file has a valid extension.

    Args:
        file_path (str): Path to the file.

    Returns:
        bool: True if the file has a valid extension, False otherwise.
    """
    valid_extensions = ['.py', '.ipynb', '.yaml', '.yml']
    return any(file_path.endswith(ext) for ext in valid_extensions)

class GitLabIngestor:
    def __init__(self, gitlab_token: str, local_repo_base_path: str, output_base_path: str, batch_size: int = 100) -> None:
        """
        Initialize the GitLabIngestor.

        Args:
            gitlab_token (str): GitLab personal access token.
            local_repo_base_path (str): Local base path to store repositories.
            output_base_path (str): Base path to store output JSON files.
            batch_size (int, optional): Number of commits per JSON file. Defaults to 100.
        """
        self.gitlab_token = gitlab_token
        self.local_repo_base_path = local_repo_base_path
        self.output_base_path = output_base_path
        self.batch_size = batch_size
        logger.info("GitLabIngestor initialized with batch size %d", batch_size)

    def process_repository(self, repo_url: str) -> None:
        """
        Process a single GitLab repository.

        Args:
            repo_url (str): URL of the GitLab repository.
        """
        repo_name = repo_url.split("/")[-1].replace(".git", "")
        repo_url = repo_url.replace('https://', f"https://oauth2:{self.gitlab_token}@")
        
        local_repo_path = os.path.join(self.local_repo_base_path, repo_name)
        output_repo_path = os.path.join(self.output_base_path, repo_name)
        logger.info("Processing repository: %s", repo_name)

        # Create output directory if it doesn't exist
        os.makedirs(output_repo_path, exist_ok=True)

        try:
            # Clone the repository if it doesn't exist locally
            if not os.path.exists(local_repo_path):
                logger.debug("Cloning repository %s to %s", repo_url, local_repo_path)
                Repo.clone_from(repo_url, local_repo_path)
            else:
                logger.debug("Repository %s already exists locally", repo_name)
                repo = Repo(local_repo_path)
                repo.remotes.origin.pull()

            # Open the repository
            repo = Repo(local_repo_path)

            # Fetch all branches
            logger.debug("Fetching all branches for repository %s", repo_name)
            repo.git.fetch("--all")

            # Iterate over all branches (local and remote)
            branches = [ref.name for ref in repo.refs]
            for branch_name in branches:
                repo.git.checkout(branch_name, force=True)
                logger.info("Processing branch: %s", branch_name)

                # Iterate over all files in the branch
                for file_path in repo.git.ls_files().split('\n'):
                    if file_path and is_valid_file(file_path):
                        self.process_file(repo, repo_name, branch_name, file_path, output_repo_path)
        except GitCommandError as e:
            logger.error("Git command error: %s", e)
        except Exception as e:
            logger.error("Unexpected error: %s", e)

    def process_file(self, repo: Repo, repo_name: str, branch_name: str, file_path: str, output_repo_path: str) -> None:
        """
        Process a single file in a repository branch.

        Args:
            repo (Repo): Git repository object.
            repo_name (str): Name of the repository.
            branch_name (str): Name of the branch.
            file_path (str): Path to the file in the repository.
            output_repo_path (str): Path to store the output JSON file.
        """
        logger.info("Processing file: %s", file_path)
        try:
            file_content = repo.git.show(f"{branch_name}:{file_path}")

            commit_history = []
            for commit in repo.iter_commits(branch_name, paths=file_path):
                diffs = []
                if commit.parents:
                    parent_commit = commit.parents[0]
                    diffs = parent_commit.diff(commit, paths=file_path, create_patch=True)
                
                commit_data = {
                    "id": commit.hexsha,
                    "short_id": commit.hexsha[:7],
                    "title": commit.summary,
                    "author_name": commit.author.name,
                    "author_email": commit.author.email,
                    "created_at": datetime.fromtimestamp(commit.committed_date).isoformat(),
                    "message": commit.message.strip(),
                    "diff": [
                        {
                            "old_path": diff.a_path,
                            "new_path": diff.b_path,
                            "diff": diff.diff.decode("utf-8", errors="ignore")
                        } for diff in diffs
                    ]
                }
                commit_history.append(commit_data)

            file_data = {
                "repository": repo_name,
                "branch": branch_name,
                "path": file_path,
                "content": file_content,
                "commit_history": commit_history
            }

            # Save to JSON file with surrogate handling
            json_file_path = os.path.join(output_repo_path, f"{branch_name.replace('/', '_')}_{file_path.replace('/', '_')}.json")
            self.json_dump_with_surrogate_handling(file_data, json_file_path)
            
            logger.info(f"Generated JSON for {file_path} in branch {branch_name}")
        except GitCommandError as e:
            logger.error("Git command error while processing file %s: %s", file_path, e)
        except Exception as e:
            logger.error("Unexpected error while processing file %s: %s", file_path, e)

    def json_dump_with_surrogate_handling(self, data: Any, file_path: str) -> None:
        """
        Dump JSON data to a file with surrogate handling.

        Args:
            data (Any): Data to be dumped to JSON.
            file_path (str): Path to the output JSON file.
        """
        try:
            with open(file_path, 'w', encoding='utf-8', errors='surrogateescape') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except UnicodeEncodeError as e:
            logger.error(f"UnicodeEncodeError encountered: {e}")
            logger.info("Attempting to handle surrogate characters...")
            
            # Convert surrogate pairs to Unicode characters
            def handle_surrogate_chars(obj: Any) -> Any:
                if isinstance(obj, str):
                    return obj.encode('utf-16', 'surrogatepass').decode('utf-16')
                elif isinstance(obj, dict):
                    return {handle_surrogate_chars(k): handle_surrogate_chars(v) for k, v in obj.items()}
                elif isinstance(obj, list):
                    return [handle_surrogate_chars(item) for item in obj]
                return obj
            
            cleaned_data = handle_surrogate_chars(data)
            
            with open(file_path, 'w', encoding='utf-8', errors='surrogateescape') as f:
                json.dump(cleaned_data, f, ensure_ascii=False, indent=4)
            
            logger.info("JSON data written successfully after handling surrogate characters.")
        except Exception as e:
            logger.error("Unexpected error while writing JSON data: %s", e)

    def process_repositories(self, repo_urls: List[str]) -> None:
        """
        Process multiple GitLab repositories.

        Args:
            repo_urls (List[str]): List of GitLab repository URLs.
        """
        for repo_url in repo_urls:
            self.process_repository(repo_url)

def main() -> None:
    """
    Main function to parse arguments and start the GitLabIngestor.
    """
    parser = argparse.ArgumentParser(description="Export GitLab repositories to JSON files.")
    parser.add_argument("--gitlab_token", type=str, required=True, help="GitLab personal access token")
    parser.add_argument("--local_repo_base_path", type=str, required=True, help="Local base path to store repositories")
    parser.add_argument("--output_base_path", type=str, required=True, help="Base path to store output JSON files")
    parser.add_argument("--repo_urls", type=str, nargs="+", required=True, help="List of GitLab repository URLs")
    parser.add_argument("--batch_size", type=int, default=100, help="Number of commits per JSON file")

    args = parser.parse_args()

    ingestor = GitLabIngestor(
        args.gitlab_token,
        args.local_repo_base_path,
        args.output_base_path,
        args.batch_size,
    )

    ingestor.process_repositories(args.repo_urls)

if __name__ == "__main__":
    main()