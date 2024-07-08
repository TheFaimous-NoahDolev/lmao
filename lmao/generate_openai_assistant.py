import os
import time
import json
import argparse
from typing import List
from openai import OpenAI
from pathlib import Path

# Cache file path
CACHE_FILE_PATH = "uploaded_file_ids.json"

def load_cached_file_ids() -> List[str]:
    """Load cached file IDs from a JSON file.

    Returns:
        List[str]: A list of cached file IDs.
    """
    if os.path.exists(CACHE_FILE_PATH):
        with open(CACHE_FILE_PATH, "r") as cache_file:
            return json.load(cache_file)
    return []

def save_cached_file_ids(file_ids: List[str]) -> None:
    """Save file IDs to a cache file.

    Args:
        file_ids (List[str]): A list of file IDs to be cached.
    """
    with open(CACHE_FILE_PATH, "w") as cache_file:
        json.dump(file_ids, cache_file)

def upload_files_to_vector_store(file_paths: List[str], client: OpenAI, max_retries: int = 2) -> List[str]:
    """Upload files to the vector store and cache the file IDs.

    Args:
        file_paths (List[str]): A list of file paths to be uploaded.
        client (OpenAI): The OpenAI client instance.
        max_retries (int, optional): Maximum number of retries for each file. Defaults to 3.

    Returns:
        List[str]: A list of uploaded file IDs.
    """
    cached_file_ids = load_cached_file_ids()
    file_ids = cached_file_ids.copy()
    for file_path in file_paths:
        if file_path in cached_file_ids:
            print(f"Skipping already uploaded file: {file_path}")
            continue

        retries = 0
        while retries < max_retries:
            try:
                with open(file_path, "rb") as file:
                    response = client.files.create(file=file, purpose="assistants")
                    file_ids.append(response.id)
                    print(f"Uploaded file ID: {response.id}")
                break
            except Exception as e:
                retries += 1
                print(f"Failed to upload {file_path}. Attempt {retries}/{max_retries}. Error: {e}")
                time.sleep(1)  # Wait before retrying

        if retries == max_retries:
            print(f"Failed to upload {file_path} after {max_retries} attempts. Skipping.")

    save_cached_file_ids(file_ids)
    return file_ids

def create_vector_store_with_files(file_ids: List[str], client: OpenAI) -> str:
    """Create a vector store and add files to it.

    Args:
        file_ids (List[str]): A list of file IDs to be added to the vector store.
        client (OpenAI): The OpenAI client instance.

    Returns:
        str: The ID of the created vector store.
    """
    vector_store = client.beta.vector_stores.create(name="FiredNoah_Vector_Store")
    vector_store_id = vector_store.id
    print(f"Created vector store ID: {vector_store_id}")

    # Chunk the file_ids into batches of 500
    for i in range(0, len(file_ids), 500):
        batch_file_ids = file_ids[i:i+500]
        batch_add = client.beta.vector_stores.file_batches.create_and_poll(
            vector_store_id=vector_store_id,
            file_ids=batch_file_ids
        )
        time.sleep(1)  # Wait for the batch process to complete
        print(f"Batch add status: {batch_add.status}")
    
    return vector_store_id

def create_assistant_with_vector_store(vector_store_id: str, client: OpenAI, assistant_name: str) -> str:
    """Create an OpenAI assistant with the vector store.

    Args:
        vector_store_id (str): The ID of the vector store to be used by the assistant.
        client (OpenAI): The OpenAI client instance.
        assistant_name (str): The name of the assistant.

    Returns:
        str: The ID of the created assistant.
    """
    instructions = f"""
    Your name is {assistant_name}. You are a data scientist who works on clinical research. You do clinical research projects. You know Python, statistics, machine learning, and deep learning. You've written a lot of code which is accessible using the File Search functionality.

    When a user asks you for information, follow these steps:
    1. Check your file store to see if you have anything relevant to the question.
    2. If you find relevant information, provide it to the user.
    3. If you don't find relevant information, say "I am not sure I've actually done that but here is my suggestion" and then answer the question based on your knowledge and expertise.

    Example interactions:
    User: "Do you have any code for data preprocessing?"
    {assistant_name}: "Yes, I generally use the load_data function for initial data preprocessing. Here is what it looks like my file store: [provide relevant code]."

    User: "Which project did you use a computer vision model for?"
    {assistant_name}: "I am not sure I've actually done that but here is my suggestion: You can start by using a convolutional neural network (CNN) for image classification. Here is a basic example: [provide example code]."
    """
    
    assistant = client.beta.assistants.create(
        name=assistant_name,
        instructions=instructions,
        tools=[{"type": "file_search"}],
        tool_resources={"file_search": {"vector_store_ids": [vector_store_id]}},
        model="gpt-4o"
    )
    print(f"Created assistant ID: {assistant.id}")
    return assistant.id

def main(base_path: str, api_key: str, assistant_name: str) -> None:
    """Main function to execute the process of uploading files, creating a vector store, and creating an assistant.

    Args:
        base_path (str): The base path to search for files to be uploaded.
        api_key (str): The OpenAI API key.
        assistant_name (str): The name of the assistant.
    """
    # Initialize the OpenAI client with the provided API key
    client = OpenAI(api_key=api_key)

    # List of file paths to be uploaded
    file_paths = [str(file) for file in Path(base_path).rglob('*.json')]  # Replace with your actual file paths

    # Upload files to the vector store
    file_ids = upload_files_to_vector_store(file_paths, client)

    # Create a vector store and add the uploaded files to it
    vector_store_id = create_vector_store_with_files(file_ids, client)

    # Create an assistant with the vector store
    assistant_id = create_assistant_with_vector_store(vector_store_id, client, assistant_name)

    print(f"Assistant with ID {assistant_id} is ready to use.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Upload files to OpenAI vector store and create an assistant.")
    parser.add_argument("--base_path", type=str, help="The base path to search for files to be uploaded.")
    parser.add_argument("--api_key", type=str, help="The OpenAI API key.")
    parser.add_argument("--assistant_name", type=str, help="The name of the assistant.")
    args = parser.parse_args()
    main(args.base_path, args.api_key, args.assistant_name)