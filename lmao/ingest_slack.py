import os
import json
import base64
import requests
import argparse
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from tenacity import retry, wait_exponential, stop_after_attempt
from typing import List, Dict, Optional


class SlackIngestor:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        output_dir: str,
        max_messages_per_file: int,
    ):
        """
        Initialize the SlackIngestor with necessary credentials and configurations.

        Args:
            client_id (str): Slack Client ID.
            client_secret (str): Slack Client Secret.
            refresh_token (str): Slack Refresh Token.
            output_dir (str): Output directory for saved messages.
            max_messages_per_file (int): Maximum number of messages per file.
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.output_dir = output_dir
        self.max_messages_per_file = max_messages_per_file
        self.client = None
        self.headers = None

    def refresh_access_token(self) -> None:
        """
        Refresh the Slack access token using the provided client ID, client secret, and refresh token.
        """
        url = "https://slack.com/api/oauth.v2.access"
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token,
        }
        response = requests.post(url, data=data)
        response_data = response.json()
        if response_data.get("ok"):
            new_access_token = response_data["access_token"]
            new_refresh_token = response_data["refresh_token"]
            # Update your environment variables or secure storage
            os.environ["SLACK_ACCESS_TOKEN"] = new_access_token
            os.environ["SLACK_REFRESH_TOKEN"] = new_refresh_token
            self.client = WebClient(token=new_access_token)
            self.headers = {"Authorization": f"Bearer {new_access_token}"}
        else:
            print("Failed to refresh token:", response_data)

    @retry(
        wait=wait_exponential(multiplier=1, min=4, max=10), stop=stop_after_attempt(5)
    )
    def fetch_conversations(self) -> List[Dict]:
        """
        Fetch the list of conversations (channels) from Slack.

        Returns:
            List[Dict]: List of conversations.
        """
        try:
            result = self.client.conversations_list()
            return result["channels"]
        except SlackApiError as e:
            print(f"Error fetching conversations: {e}")
            raise

    @retry(
        wait=wait_exponential(multiplier=1, min=4, max=10), stop=stop_after_attempt(5)
    )
    def fetch_messages(self, channel_id: str) -> List[Dict]:
        """
        Fetch the list of messages from a specific Slack channel.

        Args:
            channel_id (str): ID of the Slack channel.

        Returns:
            List[Dict]: List of messages.
        """
        try:
            result = self.client.conversations_history(channel=channel_id)
            return result["messages"]
        except SlackApiError as e:
            print(f"Error fetching messages for channel {channel_id}: {e}")
            raise

    def download_and_encode_file(self, file_url: str) -> Optional[str]:
        """
        Download a file from a URL and encode it in base64.

        Args:
            file_url (str): URL of the file to download.

        Returns:
            Optional[str]: Base64 encoded file content, or None if the download failed.
        """
        response = requests.get(file_url, headers=self.headers, stream=True)
        if response.status_code == 200:
            return base64.b64encode(response.content).decode("utf-8")
        else:
            print(f"Failed to download file from {file_url}")
            return None

    def save_messages_to_file(self, messages: List[Dict], file_index: int) -> None:
        """
        Save a list of messages to a JSON file.

        Args:
            messages (List[Dict]): List of messages to save.
            file_index (int): Index of the file (used in the filename).
        """
        file_name = os.path.join(self.output_dir, f"slack_messages_{file_index}.json")
        with open(file_name, "w") as f:
            json.dump(messages, f, indent=4)
        print(f"Saved {len(messages)} messages to {file_name}")

    def ingest(self) -> None:
        """
        Main function to download Slack messages and files, and save them to JSON files.
        """
        # Refresh the access token initially
        self.refresh_access_token()

        conversations = self.fetch_conversations()
        all_messages = []
        file_index = 1

        for conversation in conversations:
            channel_id = conversation["id"]
            channel_name = conversation["name"]
            messages = self.fetch_messages(channel_id)
            for message in messages:
                message_data = {
                    "channel_id": channel_id,
                    "channel_name": channel_name,
                    "user": message.get("user"),
                    "text": message.get("text"),
                    "timestamp": message.get("ts"),
                }
                if "files" in message:
                    for file_info in message["files"]:
                        file_url = file_info["url_private"]
                        file_type = file_info["filetype"]
                        if file_info["mimetype"].startswith("image/"):
                            encoded_image = self.download_and_encode_file(file_url)
                            if encoded_image:
                                message_data["image"] = {
                                    "filename": file_info["name"],
                                    "filetype": file_type,
                                    "data": encoded_image,
                                }
                        elif file_info["mimetype"] == "text/plain":
                            encoded_text = self.download_and_encode_file(file_url)
                            if encoded_text:
                                message_data["text_snippet"] = {
                                    "filename": file_info["name"],
                                    "filetype": file_type,
                                    "data": encoded_text,
                                }
                all_messages.append(message_data)
                if len(all_messages) >= self.max_messages_per_file:
                    self.save_messages_to_file(all_messages, file_index)
                    all_messages = []
                    file_index += 1

        # Save any remaining messages
        if all_messages:
            self.save_messages_to_file(all_messages, file_index)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download Slack messages and files.")
    parser.add_argument("--client_id", required=True, help="Slack Client ID")
    parser.add_argument("--client_secret", required=True, help="Slack Client Secret")
    parser.add_argument("--refresh_token", required=True, help="Slack Refresh Token")
    parser.add_argument(
        "--output_dir", required=True, help="Output directory for saved messages"
    )
    parser.add_argument(
        "--max_messages_per_file",
        type=int,
        default=1000,
        help="Maximum number of messages per file",
    )
    args = parser.parse_args()

    ingestor = SlackIngestor(
        args.client_id,
        args.client_secret,
        args.refresh_token,
        args.output_dir,
        args.max_messages_per_file,
    )
    ingestor.ingest()
