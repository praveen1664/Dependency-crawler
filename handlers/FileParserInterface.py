import os
import re

from typing import List

from model.issue import Issue


class ParserResult:
    def __init__(
        self,
        framework: str = None,
        dependencies: List[str] = None,
        metadata: dict = None,
        issues: List[Issue] = None,
    ):
        if framework is None:
            framework = "Unknown"
        if dependencies is None:
            dependencies = []
        if metadata is None:
            metadata = {}
        if issues is None:
            issues = []

        self.framework = framework
        self.dependencies = dependencies.copy()
        self.metadata = metadata.copy()
        self.issues = issues.copy()


class FileParserInterface:
    def __init__(self, file_pattern: str, match_whole_path = False) -> None:
        self.file_pattern = re.compile(file_pattern)
        self.match_whole_path = match_whole_path

    def parse(self, file_path: str, state: dict) -> ParserResult:
        return ParserResult()

    def will_parse(self, file_path: str):
        if "node_modules" in file_path:
            return False

        if self.match_whole_path:
            return self.file_pattern.match(file_path)
        else:
            file_name = os.path.basename(file_path)
            return self.file_pattern.match(file_name)

    def create_postcrawl_issues(
        self, repo, dependencies, issues, metadata
    ) -> List[Issue]:
        return []

    def create_default_metadata(self) -> dict:
        return {}
