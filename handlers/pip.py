import re

from handlers.FileParserInterface import FileParserInterface, ParserResult
from utils.utils import read_file_into_string


class PipFileParser(FileParserInterface):
    requirements_pattern = re.compile("^(.+?)(==(.*))?$")

    def __init__(self) -> None:
        super().__init__("requirements.txt")

    def parse(self, file, state: dict) -> ParserResult:
        requirements_data = read_file_into_string(file)
        lines = requirements_data.splitlines()

        dependencies = []
        for line in lines:
            match = self.requirements_pattern.match(line)
            if match and match.group(1):
                dependency_info = match.group(1)
                dependencies.append(dependency_info)
        return ParserResult("PIP", dependencies)
