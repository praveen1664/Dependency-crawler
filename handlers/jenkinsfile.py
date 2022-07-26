import re

from handlers.FileParserInterface import FileParserInterface, ParserResult
from utils.utils import read_file_into_string, prefix_var


class JenkinsFileParser(FileParserInterface):
    gl_pattern = "gl[A-Z\\d][A-Za-z\\d]*"

    def __init__(self) -> None:
        super().__init__("Jenkinsfile")
        self.iac_functions = [
            "glFortifyScan",
            "glTwistlockScan",
            "glDockerImageBuildPush",
            "glArtifactoryDockerPromote"
        ]

    def parse(self, file_path, state: dict) -> ParserResult:
        jenkins_data = read_file_into_string(file_path)
        gl_functions = re.findall(self.gl_pattern, jenkins_data)
        metadata = {"hasJenkinsFile": True}
        for function_name in self.iac_functions:
            metadata[prefix_var("uses", function_name)] = function_name in gl_functions

        return ParserResult("Jenkins", dependencies=gl_functions, metadata=metadata)

    def create_default_metadata(self) -> dict:
        default_metadata = {"hasJenkinsFile": False}
        for function_name in self.iac_functions:
            default_metadata[prefix_var("uses", function_name)] = False

        return default_metadata
