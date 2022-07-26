import xmltodict
from pyOptional import Optional

from handlers.FileParserInterface import FileParserInterface, ParserResult
from utils.utils import listify, read_file_into_string


class MavenFileParser(FileParserInterface):
    def __init__(self) -> None:
        super().__init__("pom.xml")

    def parse(self, file, state: dict) -> ParserResult:
        pom_data = read_file_into_string(file)

        pom_data = pom_data.replace('<?xml version="1.0" encoding="UTF-8"?>', "")

        pom = xmltodict.parse(pom_data)

        optional_pom = Optional(pom)

        dependencies = []
        project_dependencies = (
            optional_pom.map(lambda val: val.get("project"))
            .map(lambda val: val.get("dependencies"))
            .map(lambda val: val.get("dependency"))
            .map(lambda val: listify(val))
        )
        dependency_management_dependencies = (
            optional_pom.map(lambda val: val.get("project"))
            .map(lambda val: val.get("dependencyManagement"))
            .map(lambda val: val.get("dependencies"))
            .map(lambda val: val.get("dependency"))
            .map(lambda val: listify(val))
        )

        if project_dependencies.is_present():
            dependencies += project_dependencies.get()

        if dependency_management_dependencies:
            dependencies += dependency_management_dependencies.get()

        return ParserResult(
            "Maven",
            list(
                map(
                    lambda val: "%s:%s" % (val["groupId"], val["artifactId"]),
                    dependencies,
                )
            ),
        )
