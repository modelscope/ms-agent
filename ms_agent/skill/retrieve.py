# Copyright (c) Alibaba, Inc. and its affiliates.
from typing import Dict, List, Optional, Tuple

from ms_agent.utils.logger import logger

from .schema import SkillSchema


class Retriever:
    """
    Skill retriever for finding the most relevant skills based on queries.

    Supports both keyword-based and semantic-based retrieval methods.

    Attributes:
        skills: Dictionary of loaded skills (skill_id@version -> SkillSchema)
        top_k: Number of top results to return (default: 3)
    """

    def __init__(self, skills: Dict[str, SkillSchema], top_k: int = 3):
        """
        Initialize the retriever.

        Args:
            skills: Dictionary of loaded skills
            top_k: Number of top results to return
        """
        self.skills = skills
        self.top_k = top_k
        logger.info(
            f'Retriever initialized with {len(skills)} skills, top_k={top_k}')

    def retrieve(
            self,
            query: str,
            method: str = 'semantic',
            top_k: Optional[int] = None
    ) -> List[Tuple[str, SkillSchema, float]]:
        """
        Retrieve the most relevant skills based on query.

        Args:
            query: Search query string
            method: Retrieval method ("keyword" or "semantic")
            top_k: Number of results to return (overrides default if provided)

        Returns:
            List of tuples (skill_key, SkillSchema, score) sorted by relevance
        """

        k = top_k or self.top_k

        if method == 'keyword':
            return self._keyword_retrieve(query, k)
        elif method == 'semantic':
            return self._semantic_retrieve(query, k)
        else:
            logger.warning(
                f'Unknown retrieval method: {method}, using `semantic` by default.'
            )
            return self._keyword_retrieve(query, k)

    def _keyword_retrieve(self, query: str,
                          top_k: int) -> List[Tuple[str, SkillSchema, float]]:
        """
        Keyword-based retrieval using simple text matching.

        Searches in skill_id, name, and description fields.

        Args:
            query: Search query string
            top_k: Number of results to return

        Returns:
            List of tuples (skill_key, SkillSchema, score) sorted by score
        """
        query_lower = query.lower()
        query_terms = set(query_lower.split())

        results = []

        for skill_key, skill in self.skills.items():
            score = 0.0

            # Search in skill_id (weight: 3.0)
            if query_lower in skill.skill_id.lower():
                score += 3.0

            # Search in name (weight: 2.0)
            if query_lower in skill.name.lower():
                score += 2.0

            # Search in description (weight: 1.0)
            if query_lower in skill.description.lower():
                score += 1.0

            # Term-based matching in description
            desc_lower = skill.description.lower()
            desc_terms = set(desc_lower.split())
            common_terms = query_terms.intersection(desc_terms)
            score += len(common_terms) * 0.5

            # Tag matching (weight: 1.5)
            for tag in skill.tags:
                if query_lower in tag.lower():
                    score += 1.5

            if score > 0:
                results.append((skill_key, skill, score))

        # Sort by score (descending) and return top_k
        results.sort(key=lambda x: x[2], reverse=True)

        logger.info(
            f"Keyword retrieval found {len(results)} matches for query: '{query}'"
        )
        return results[:top_k]

    def _semantic_retrieve(self, query: str,
                           top_k: int) -> List[Tuple[str, SkillSchema, float]]:
        """
        Semantic-based retrieval using text similarity.

        Currently uses a simple TF-IDF-like approach.
        Can be extended with embedding-based similarity in the future.

        Args:
            query: Search query string
            top_k: Number of results to return

        Returns:
            List of tuples (skill_key, SkillSchema, score) sorted by score
        """
        query_lower = query.lower()
        query_terms = query_lower.split()

        results = []

        for skill_key, skill in self.skills.items():
            # Combine all text fields for semantic matching
            combined_text = ' '.join([
                skill.skill_id, skill.name, skill.description,
                ' '.join(skill.tags)
            ]).lower()

            # Calculate similarity score
            score = self._calculate_similarity(query_terms, combined_text)

            results.append((skill_key, skill, score))

        # Sort by score (descending) and return top_k
        results.sort(key=lambda x: x[2], reverse=True)

        logger.info(
            f"Semantic retrieval found {len(results)} matches for query: '{query}'"
        )
        return results[:top_k]

    def _calculate_similarity(self, query_terms: List[str],
                              text: str) -> float:
        """
        Calculate similarity score between query terms and text.

        Uses a simple term frequency approach with position weighting.

        Args:
            query_terms: List of query terms
            text: Text to compare against

        Returns:
            Similarity score
        """
        score = 0.0
        text_terms = text.split()

        for query_term in query_terms:
            # Exact match
            if query_term in text:
                score += 2.0

            # Partial match
            for text_term in text_terms:
                if query_term in text_term or text_term in query_term:
                    score += 1.0

        # Normalize by query length
        if len(query_terms) > 0:
            score = score / len(query_terms)

        return score

    def retrieve_by_id(self, skill_id: str) -> Optional[SkillSchema]:
        """
        Retrieve a skill by exact skill_id match.

        Args:
            skill_id: Skill ID to search for

        Returns:
            SkillSchema if found, None otherwise
        """
        for skill_key, skill in self.skills.items():
            if skill.skill_id == skill_id:
                logger.info(f'Found skill by ID: {skill_id}')
                return skill

        logger.warning(f'Skill not found with ID: {skill_id}')
        return None

    def retrieve_by_name(self, name: str) -> List[SkillSchema]:
        """
        Retrieve skills by exact or partial name match.

        Args:
            name: Skill name to search for

        Returns:
            List of matching SkillSchema objects
        """
        name_lower = name.lower()
        results = []

        for skill in self.skills.values():
            if name_lower in skill.name.lower():
                results.append(skill)

        logger.info(f"Found {len(results)} skills matching name: '{name}'")
        return results

    def retrieve_by_tags(self, tags: List[str]) -> List[SkillSchema]:
        """
        Retrieve skills by tags.

        Args:
            tags: List of tags to search for

        Returns:
            List of matching SkillSchema objects
        """
        tags_lower = [tag.lower() for tag in tags]
        results = []

        for skill in self.skills.values():
            skill_tags_lower = [tag.lower() for tag in skill.tags]
            if any(tag in skill_tags_lower for tag in tags_lower):
                results.append(skill)

        logger.info(f'Found {len(results)} skills matching tags: {tags}')
        return results

    def update_skills(self, skills: Dict[str, SkillSchema]) -> None:
        """
        Update the skills dictionary.

        Args:
            skills: New skills dictionary
        """
        self.skills = skills
        logger.info(f'Updated retriever with {len(skills)} skills')

    def set_top_k(self, top_k: int) -> None:
        """
        Update the default top_k value.

        Args:
            top_k: New top_k value
        """
        self.top_k = top_k
        logger.info(f'Updated top_k to {top_k}')


def create_retriever(skills: Dict[str, SkillSchema],
                     top_k: int = 3) -> Retriever:
    """
    Convenience function to create a Retriever instance.

    Args:
        skills: Dictionary of loaded skills
        top_k: Number of top results to return

    Returns:
        Retriever instance
    """
    return Retriever(skills=skills, top_k=top_k)
