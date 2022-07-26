import re

from handlers.FileParserInterface import FileParserInterface, ParserResult
from utils.utils import read_file_into_string


class DockerFileParser(FileParserInterface):
    docker_pattern = re.compile("\s*from\s*(\S+)", re.IGNORECASE)

    def __init__(self) -> None:
        super().__init__("Dockerfile")

    def parse(self, file_path, state: dict) -> ParserResult:
        docker_data = read_file_into_string(file_path)

        lines = docker_data.splitlines()

        dependencies = []
        for line in lines:
            match = self.docker_pattern.match(line)
            if match and match.group(1):
                dependency_info = match.group(1)
                dependencies.append(f"docker-image:{dependency_info}")

        return ParserResult("Docker", dependencies)
