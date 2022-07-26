import logging
import subprocess
from typing import List

from handlers.FileParserInterface import FileParserInterface, ParserResult
from model.issue import Issue


class ReadmeFileParser(FileParserInterface):

    def __init__(self) -> None:
        super().__init__("^\\./(?i:README)\\.[a-z]*$", True)
        self.has_readme_field = "hasReadme"
        self.readme_author_field = "readmeAuthor"
        self.readme_created_date_field = "readmeCreatedDate"

    def parse(self, file_path: str, state: dict) -> ParserResult:

        # use 'git' to pull info on who created the README
        output = subprocess.check_output(["git", "log", "--follow", '--format="%ae|%aI"', "--", file_path])

        # we need to pull the last entry from the output and split it on the pipe
        output_parts = output.decode('UTF-8').strip().replace('"', '').split("\n")[-1].strip().split('|')

        print(f"Output parts: {output_parts}")

        return ParserResult("Readme", metadata={
            self.has_readme_field: True,
            self.readme_author_field: output_parts[0],
            self.readme_created_date_field: output_parts[1],
        })

    def create_default_metadata(self) -> dict:
        return {
            self.has_readme_field: False,
            self.readme_author_field: "missing",
            self.readme_created_date_field: "missing"
        }
