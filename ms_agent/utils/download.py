"""
Model download script for huggingface models.
This script downloads required models from Hugging Face for the application.
"""

import logging
import os

from huggingface_hub import snapshot_download

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configuration
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
REPO_IDS = ['ds4sd/DocumentFigureClassifier', 'ds4sd/docling-models']


def download_models():
    """Download all required models from Hugging Face."""
    logger.info(f'Starting download of {len(REPO_IDS)} models')

    for repo_id in REPO_IDS:
        logger.info(f'Downloading model: {repo_id}')
        try:
            model_path = snapshot_download(repo_id=repo_id)
            logger.info(f'Successfully downloaded {repo_id} to {model_path}')
        except Exception as e:
            logger.error(f'Failed to download {repo_id}: {str(e)}')
            raise


if __name__ == '__main__':
    download_models()
