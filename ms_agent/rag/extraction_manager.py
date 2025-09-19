import os
from typing import Any, Dict, List, Optional, Tuple

from ms_agent.rag.extraction import HierarchicalKeyInformationExtraction
from ms_agent.rag.schema import KeyInformation
from ms_agent.utils.logger import get_logger

logger = get_logger()

try:
    import ray  # type: ignore
    _RAY_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    ray = None  # type: ignore
    _RAY_AVAILABLE = False
    logger.warning(
        'Ray is not available. Install it for faster information extraction:\n'
        '    pip install \"ray[default]\"\n'
        'Program will run without acceleration.')


class InformationExtractionManager:
    """
    Optimized key information extraction with optional Ray acceleration.
    """

    def __init__(self,
                 verbose: bool = False,
                 use_ray: bool = False,
                 ray_num_workers: Optional[int] = None,
                 ray_cpus_per_task: float = 1.0):
        self._verbose = verbose
        self._use_ray = use_ray and _RAY_AVAILABLE
        self._ray_num_workers = ray_num_workers
        self._ray_cpus_per_task = ray_cpus_per_task

    def extract(
        self, urls_or_files: List[str]
    ) -> Tuple[List[KeyInformation], Dict[str, str]]:
        """
        Extract key information from URLs or files.

        Args:
            urls_or_files: List of URLs or file paths to process

        Returns:
            Tuple of (key_info_list, resource_map)
        """
        # Try Ray extraction if enabled and we have multiple files
        if self._use_ray and len(urls_or_files) > 1:
            try:
                return self._extract_with_ray(urls_or_files)
            except Exception as e:
                logger.warning(
                    f'Ray extraction failed, falling back to sequential: {e}')

        # Use sequential extraction if Ray is disabled or failed
        if not _RAY_AVAILABLE:
            logger.warning(
                'Ray is not available, falling back to sequential extraction.')
        return self._extract_sequential(urls_or_files)

    def _extract_sequential(
        self, urls_or_files: List[str]
    ) -> Tuple[List[KeyInformation], Dict[str, str]]:
        """Sequential extraction using the original implementation."""
        extractor = HierarchicalKeyInformationExtraction(
            urls_or_files=urls_or_files, verbose=self._verbose)
        key_info_list = extractor.extract()

        return key_info_list, extractor.all_ref_items

    def _extract_with_ray(
        self, urls_or_files: List[str]
    ) -> Tuple[List[KeyInformation], Dict[str, str]]:
        """Ray-accelerated extraction."""
        if not ray.is_initialized():
            ray.init(
                ignore_reinit_error=True,
                include_dashboard=False,
                log_to_driver=False)

        # Determine optimal worker count
        max_workers = self._ray_num_workers or min(
            len(urls_or_files), (os.cpu_count() or 4))
        max_workers = max(1, max_workers)

        # Partition URLs/files among workers: should be balanced
        partitions: List[List[str]] = [[] for _ in range(max_workers)]
        for idx, url_file in enumerate(urls_or_files):
            partitions[idx % max_workers].append(url_file)

        # Create actors and dispatch tasks
        actors = [
            _ExtractionWorker.options(num_cpus=self._ray_cpus_per_task).remote(
                urls_or_files=partitions[i], verbose=self._verbose)
            for i in range(max_workers)
        ]

        futures = []
        for exraction_actor in actors:
            futures.append(exraction_actor.process_partition.remote())

        results: List[Tuple[List[KeyInformation],
                            Dict[str, str]]] = ray.get(futures)

        # Merge results
        merged_infos: List[KeyInformation] = []
        merged_resource_map: Dict[str, str] = {}

        for infos, res_map in results:
            merged_infos.extend(infos)
            merged_resource_map.update(res_map)

        return merged_infos, merged_resource_map


if _RAY_AVAILABLE:

    @ray.remote  # type: ignore
    class _ExtractionWorker:
        """Ray worker for parallel extraction processing."""

        def __init__(self, urls_or_files: List[str], verbose: bool = False):
            self._verbose = verbose
            self._urls_or_files = urls_or_files
            self.extractor = HierarchicalKeyInformationExtraction(
                urls_or_files=self._urls_or_files, verbose=verbose)

        def process_partition(
                self) -> Tuple[List[KeyInformation], Dict[str, str]]:
            """Process a partition of URLs/files and return extracted information."""
            try:
                key_info_list_partition = self.extractor.extract()
                resource_map_partition = self.extractor.all_ref_items
                return key_info_list_partition, resource_map_partition

            except Exception as e:
                logger.error(f'Worker failed to process partition: {e}')
                return [], {}


def extract_key_information(
    urls_or_files: List[str],
    use_ray: bool = False,
    verbose: bool = False,
    ray_num_workers: Optional[int] = None,
    ray_cpus_per_task: float = 1.0
) -> Tuple[List[KeyInformation], Dict[str, str]]:
    """
    High-level function to extract key information with optional Ray acceleration.

    Args:
        urls_or_files: List of URLs or file paths to process
        use_ray: Whether to use Ray for acceleration
        verbose: Enable verbose logging
        ray_num_workers: Number of Ray workers (auto if None)
        ray_cpus_per_task: CPU allocation per Ray task

    Returns:
        Tuple of (key_info_list, resource_map)
    """
    extractor = InformationExtractionManager(
        verbose=verbose,
        use_ray=use_ray,
        ray_num_workers=ray_num_workers,
        ray_cpus_per_task=ray_cpus_per_task)

    return extractor.extract(urls_or_files)
