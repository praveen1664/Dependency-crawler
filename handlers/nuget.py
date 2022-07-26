import xmltodict
import logging
from pyOptional import Optional

from handlers.FileParserInterface import FileParserInterface, ParserResult
from utils.utils import listify, read_file_into_string


class NugetFileParser(FileParserInterface):
    def __init__(self) -> None:
        super().__init__(".*[.]csproj$")

    def parse(self, file_path, state: dict) -> ParserResult:
        dependencies = []
        project_file_data = read_file_into_string(file_path)

        project = xmltodict.parse(project_file_data)

        optional_project = Optional(project.get("Project"))

        if not optional_project.is_present():
            logging.info("No project tag in file: %s" % file_path.download_url)
            return ParserResult("NuGet", dependencies)

        item_groups = optional_project.map(lambda val: val.get("ItemGroup")).map(
            lambda val: listify(val)
        )

        if not item_groups.is_present():
            return ParserResult("NuGet", dependencies)

        for item_group in item_groups.get():
            if item_group and "PackageReference" in item_group:
                dependencies += self.process_c_sharp_item_group(item_group)

        return ParserResult("NuGet", dependencies)

    def process_c_sharp_item_group(self, item_group):
        dependencies = []
        package_refs = listify(item_group["PackageReference"])
        for package_ref in package_refs:
            dependency_info = package_ref.get("@Include")

            if not dependency_info:
                dependency_info = package_ref.get("@Update")

            if not dependency_info:
                logging.info("missing dependency info")
                continue

            dependencies.append(dependency_info)

        return dependencies
