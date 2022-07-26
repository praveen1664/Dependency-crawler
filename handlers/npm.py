import json

from handlers.FileParserInterface import FileParserInterface, ParserResult
from utils.utils import read_file_into_string


class NpmFileParser(FileParserInterface):
    def __init__(self) -> None:
        super().__init__("package.json")

    def parse(self, file, state: dict) -> ParserResult:
        package_data = read_file_into_string(file)
        package = json.loads(package_data)

        dependencies = []
        base_dependencies = package.get("dependencies")
        dev_dependencies = package.get("devDependencies")

        if base_dependencies:
            dependencies += base_dependencies

        if dev_dependencies:
            dependencies += dev_dependencies

        return ParserResult("NPM", dependencies)
