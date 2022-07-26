import re

from handlers.FileParserInterface import FileParserInterface, ParserResult
from utils.utils import read_file_into_string


class GemFileParser(FileParserInterface):
    gem_pattern = re.compile("\s*(.*) \(.*\)")

    def __init__(self) -> None:
        super().__init__("Gemfile.lock")

    def parse(self, file, state: dict) -> ParserResult:
        gemfile_data = read_file_into_string(file)

        lines = gemfile_data.splitlines()

        dependencies = []
        for line in lines:
            match = self.gem_pattern.match(line)
            if match and match.group(1):
                dependency_info = match.group(1)
                dependencies.append(dependency_info)

        return ParserResult("Gem", dependencies)
