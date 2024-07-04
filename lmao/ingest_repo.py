import os
import git
import json
from git import Repo
from datetime import datetime
import argparse
from typing import List, Dict, Any


class GitLabIngestor:
    def __init__(
        self, gitlab_token: str, local_repo_base_path: str, output_base_path: str, batch_size: int = 100
    ) -> None:
        """
        Initialize the GitLabIngestor with necessary parameters.

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

    def process_repository(self, repo_url: str) -> None:
        """
        Process a single GitLab repository and export its commits to JSON files.

        Args:
            repo_url (str): URL of the GitLab repository.
        """
        repo_name = repo_url.split("/")[-1].replace(".git", "")
        local_repo_path = os.path.join(self.local_repo_base_path, repo_name)
        output_repo_path = os.path.join(self.output_base_path, repo_name)

        # Create output directory if it doesn't exist
        os.makedirs(output_repo_path, exist_ok=True)

        # Clone the repository if it doesn't exist locally
        if not os.path.exists(local_repo_path):
            Repo.clone_from(repo_url, local_repo_path)

        # Open the repository
        repo = Repo(local_repo_path)

        # Fetch all branches
        repo.git.fetch("--all")

        # Iterate over all branches
        for branch in repo.branches:
            repo.git.checkout(branch)
            branch_name = branch.name

            # Initialize batch variables
            batch: List[Dict[str, Any]] = []
            batch_index = 0

            # Iterate over all commits in the branch
            for commit in repo.iter_commits(branch):
                commit_data = {
                    "repository": repo_name,
                    "branch": branch_name,
                    "commit_hash": commit.hexsha,
                    "author": commit.author.name,
                    "author_email": commit.author.email,
                    "date": datetime.fromtimestamp(commit.committed_date).isoformat(),
                    "message": commit.message.strip(),
                    "diffs": [],
                }

                # Get the diff from the previous commit
                if commit.parents:
                    parent_commit = commit.parents[0]
                    diffs = parent_commit.diff(commit, create_patch=True)
                    for diff in diffs:
                        commit_data["diffs"].append(
                            {
                                "file_path": diff.b_path,
                                "diff": diff.diff.decode("utf-8", errors="ignore"),
                            }
                        )

                # Add commit data to the batch
                batch.append(commit_data)

                # Check if the batch size is reached
                if len(batch) >= self.batch_size:
                    self._export_batch(
                        output_repo_path, branch_name, batch, batch_index
                    )
                    batch = []
                    batch_index += 1

            # Export any remaining commits in the batch
            if batch:
                self._export_batch(output_repo_path, branch_name, batch, batch_index)

        print(f"Data export completed for repository {repo_name}.")

    def _export_batch(self, output_repo_path: str, branch_name: str, batch: List[Dict[str, Any]], batch_index: int) -> None:
        """
        Export a batch of commits to a JSON file.

        Args:
            output_repo_path (str): Path to store the output JSON files.
            branch_name (str): Name of the branch.
            batch (List[Dict[str, Any]]): List of commit data.
            batch_index (int): Index of the batch.
        """
        batch_file_path = os.path.join(
            output_repo_path, f"{branch_name}_batch_{batch_index}.json"
        )
        with open(batch_file_path, "w", encoding="utf-8") as f:
            json.dump(batch, f, ensure_ascii=False, indent=4)
        print(
            f"Exported batch {batch_index} for branch {branch_name} to {batch_file_path}"
        )

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
    Main function to parse arguments and initiate the GitLabIngestor.
    """
    parser = argparse.ArgumentParser(
        description="Export GitLab repositories to JSON files."
    )
    parser.add_argument(
        "--gitlab_token", type=str, required=True, help="GitLab personal access token"
    )
    parser.add_argument(
        "--local_repo_base_path",
        type=str,
        required=True,
        help="Local base path to store repositories",
    )
    parser.add_argument(
        "--output_base_path",
        type=str,
        required=True,
        help="Base path to store output JSON files",
    )
    parser.add_argument(
        "--repo_urls",
        type=str,
        nargs="+",
        required=True,
        help="List of GitLab repository URLs",
    )
    parser.add_argument(
        "--batch_size", type=int, default=100, help="Number of commits per JSON file"
    )

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