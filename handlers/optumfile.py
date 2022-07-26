import functools
import logging
import re
import subprocess
from typing import List

from handlers.FileParserInterface import FileParserInterface, ParserResult
from model.issue import Issue
import yaml


class OrgfileParser(FileParserInterface):

    accepted_component_types = ["code", "database", "db", "infrastructure", "config", "policy", "iac", "other", "docs"]
    accepted_askId_regexes = ("^poc$", "^POC$", "^UHGWM110-\d{6}$", "^AIDE_\d+$")

    accepted_askId_patterns = list(map(re.compile, accepted_askId_regexes))

    def has_valid_api_version(self, yaml):
        test = "apiVersion" in yaml
        if not test:
            logging.error("bad apiVersion")
        return test

    def has_valid_metadata(self, yaml):
        test = "metadata" in yaml
        if not test:
            logging.error("bad metadata")
        return test

    def has_valid_ask_id(self, yaml):
        if "askId" not in yaml["metadata"] or yaml["metadata"]["askId"] is None:
            return True

        if isinstance(yaml['metadata']['askId'], list):
            all_ask_ids_valid = functools.reduce(
                lambda a, b: a and any([pattern.match(b) for pattern in self.accepted_askId_patterns]),
                yaml["metadata"]["askId"], True)
            if not all_ask_ids_valid:
                logging.error("bad askid: one of the askids present isn't valid")
            return all_ask_ids_valid

        try:
            match_results = [pattern.match(yaml['metadata']['askId']) for pattern in self.accepted_askId_patterns]
            test = any(match_results)
            if not test:
                logging.error(f"bad askId: {yaml['metadata']['askId']} {match_results}")
            return test
        except:
            logging.error("bad askId - missing or couldn't parse")
            return False

    def has_valid_component_type(self, yaml):
        try:
            component_type = yaml['metadata']['componentType']
            test = component_type is not None and component_type.lower() in self.accepted_component_types
            if not test:
                logging.error(f"bad componentType: {component_type}")
            return test
        except:
            logging.error("bad componentType missing or couldn't parse")
            return False

    rules = [
        has_valid_api_version,
        has_valid_metadata,
        has_valid_ask_id,
        has_valid_component_type
    ]

    def __init__(self) -> None:
        super().__init__("^\\./Orgfile\\.(yml|yaml)$", True)
        self.has_Orgfile_field = "hasOrgfile"
        self.has_valid_Orgfile_field = "hasValidOrgfile"
        self.Orgfile_author_field = "OrgfileAuthor"
        self.Orgfile_created_date_field = "OrgfileCreatedDate"
        self.Orgfile_ask_id = "OrgfileAskId"
        self.Orgfile_ca_agile_id = "OrgfileCaAgileId"
        self.Orgfile_project_friendly_name = "OrgfileProjectFriendlyName"
        self.Orgfile_target_quality_gate = "OrgfileTargetQualityGate"
        self.Orgfile_project_key = "OrgfileProjectKey"
        self.Orgfile_component_type = "OrgfileComponentType"

    def parse(self, file_path: str, state: dict) -> ParserResult:

        # use 'git' to pull info on who created the Orgfile
        output = subprocess.check_output(["git", "log", "--follow", '--format="%ae|%aI"', "--", file_path])

        # we need to pull the last entry from the output and split it on the pipe
        output_parts = output.decode('UTF-8').strip().replace('"', '').split("\n")[-1].strip().split('|')
        valid_Orgfile, Orgfile = self.check_Orgfile(file_path)

        logging.info(f"{file_path} is valid Orgfile: {valid_Orgfile}")
        has_ask_id = 'metadata' in Orgfile and Orgfile['metadata'] is not None and 'askId' in Orgfile['metadata']
        has_ca_agile_id = 'metadata' in Orgfile and Orgfile['metadata'] is not None and 'caAgileId' in Orgfile['metadata']
        has_project_friendly_name = 'metadata' in Orgfile and Orgfile['metadata'] is not None and 'projectFriendlyName' in Orgfile['metadata']
        has_target_quality_gate = 'metadata' in Orgfile and Orgfile['metadata'] is not None and 'targetQG' in Orgfile['metadata']
        has_component_type = 'metadata' in Orgfile and Orgfile['metadata'] is not None and 'componentType' in Orgfile['metadata']
        has_project_key = 'metadata' in Orgfile and Orgfile['metadata'] is not None and 'projectKey' in Orgfile['metadata']

        key = str(Orgfile['metadata']['projectKey']) if has_project_key else "missing"
        if not state.get("sonar_key"):
            state["sonar_key"] = key

        return ParserResult("Orgfile", metadata={
            self.has_Orgfile_field: True,
            self.has_valid_Orgfile_field: valid_Orgfile,
            self.Orgfile_author_field: output_parts[0],
            self.Orgfile_created_date_field: output_parts[1],
            self.Orgfile_ask_id: str(Orgfile['metadata']['askId']) if has_ask_id else "missing",
            self.Orgfile_ca_agile_id: str(Orgfile['metadata']['caAgileId']) if has_ca_agile_id else "missing",
            self.Orgfile_project_friendly_name: str(Orgfile['metadata']['projectFriendlyName']) if has_project_friendly_name else "missing",
            self.Orgfile_target_quality_gate: str(Orgfile['metadata']['targetQG']) if has_target_quality_gate else "missing",
            self.Orgfile_project_key: key,
            self.Orgfile_component_type: str(Orgfile['metadata']['componentType']) if has_component_type else "missing"
        })

    def check_Orgfile(self, file_path):
        valid_Orgfile = False
        Orgfile = {}
        with open(file_path, "r") as file:
            try:
                Orgfile = yaml.safe_load(file)

                valid_Orgfile = all([rule(self, Orgfile) for rule in self.rules])

            except Exception:
                logging.exception("Exception when parsing Orgfile")
        return valid_Orgfile, Orgfile

    def create_postcrawl_issues(
        self, repo, dependencies, issues, metadata
    ) -> List[Issue]:
        if (
            self.has_Orgfile_field not in metadata
            or not metadata[self.has_Orgfile_field]
        ):
            logging.info("No Orgfile found")
            metadata[self.has_Orgfile_field] = False
            issues.append(
                Issue(
                    "missing_Org_file",
                    "Missing Orgfile",
                    "No Orgfile present in repository",
                )
            )

        return issues

    def create_default_metadata(self) -> dict:
        return {
            self.has_Orgfile_field: False,
            self.has_valid_Orgfile_field: False,
            self.Orgfile_author_field: "missing",
            self.Orgfile_created_date_field: "missing",
            self.Orgfile_ask_id: "missing",
            self.Orgfile_ca_agile_id: "missing",
            self.Orgfile_project_friendly_name: "missing",
            self.Orgfile_target_quality_gate: "missing",
            self.Orgfile_project_key: "missing",
            self.Orgfile_component_type: "missing"
        }
