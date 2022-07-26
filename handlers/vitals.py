import functools
import logging
import re
import subprocess
from typing import List

from handlers.FileParserInterface import FileParserInterface, ParserResult
from model.issue import Issue
import yaml


class VitalsFileParser(FileParserInterface):
    accepted_apiVersions = ["v1"]
    accepted_component_types = ["code", "database", "db", "infrastructure", "config", "policy", "iac", "other", "docs"]
    accepted_askId_regexes = ("^poc$", "^POC$", "^UHGWM110-\d{6}$", "^AIDE_\d+$", "null")

    accepted_askId_patterns = list(map(re.compile, accepted_askId_regexes))

    def has_valid_api_version(self, yaml):
        test = "apiVersion" in yaml \
               and yaml["apiVersion"] is not None \
               and yaml["apiVersion"] in self.accepted_apiVersions \
               and yaml["apiVersion"] != "~"
        if not test:
            logging.error("bad apiVersion")
        return test

    def has_valid_metadata(self, yaml):
        test = "metadata" in yaml and yaml["metadata"] is not None and isinstance(yaml["metadata"], dict)
        if not test:
            logging.error("bad metadata")
        return test

    def has_valid_ask_id(self, yaml):
        try:
            if yaml["metadata"]["askId"] is None:
                return True

            if isinstance(yaml['metadata']['askId'], list):
                logging.info(f"handling list of askIds {yaml['metadata']['askId']}")
                return functools.reduce(
                    lambda a, b: a and any([pattern.match(b) for pattern in self.accepted_askId_patterns]),
                    yaml["metadata"]["askId"], True)

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
            if "componentType" not in yaml['metadata']:
                logging.error("bad componentType: missing in metadata")
                return False

            component_type = yaml['metadata']['componentType']
            test = component_type is not None and component_type.lower() in self.accepted_component_types
            if not test:
                logging.error(f"bad componentType: {component_type}")
            return test
        except:
            logging.error("bad componentType missing or couldn't parse")
            return False


    # We are not enforcing all these fields yet
    def has_required_fields(self, yaml):
        if "apiVersion" not in yaml:
            logging.error("bad vitals file: missing apiVersion")
            return False
        elif "metadata" not in yaml:
            logging.error("bad vitals file: missing metadata")
            return False
        elif "askId" not in yaml["metadata"]:
            logging.error("bad vitals file: missing askId in metadata")
            return False
        elif "caAgileId" not in yaml["metadata"]:
            logging.error("bad vitals file: missing caAgileId in metadata")
            return False
        elif "projectKey" not in yaml["metadata"]:
            logging.error("bad vitals file: missing projectKey in metadata")
            return False
        elif "projectFriendlyName" not in yaml["metadata"]:
            logging.error("bad vitals file: missing projectFriendlyName in metadata")
            return False
        elif "componentType" not in yaml["metadata"]:
            logging.error("bad vitals file: missing componentType in metadata")
            return False
        elif "targetQG" not in yaml["metadata"]:
            logging.error("bad vitals file: missing targetQG in metadata")
            return False

    rules = [
        has_valid_api_version,
        has_valid_metadata,
        has_valid_ask_id,
        has_valid_component_type
    ]

    def __init__(self) -> None:
        super().__init__("^\\./vitals\\.(yml|yaml)$", True)
        self.has_vitals_field = "hasVitalsFile"
        self.has_valid_vitals_field = "hasValidVitalsFile"
        self.vitals_author_field = "vitalsFileAuthor"
        self.vitals_created_date_field = "vitalsFileCreatedDate"
        self.vitals_ask_id = "vitalsFileAskId"
        self.vitals_ca_agile_id = "vitalsFileCaAgileId"
        self.vitals_project_friendly_name = "vitalsFileProjectFriendlyName"
        self.vitals_target_quality_gate = "vitalsFileTargetQualityGate"
        self.vitals_project_key = "vitalsFileProjectKey"
        self.vitals_component_type = "vitalsFileComponentType"

    def parse(self, file_path: str, state: dict) -> ParserResult:

        # use 'git' to pull info on who created the vitals.yaml
        output = subprocess.check_output(["git", "log", "--follow", '--format="%ae|%aI"', "--", file_path])

        # we need to pull the last entry from the output and split it on the pipe
        output_parts = output.decode('UTF-8').strip().replace('"', '').split("\n")[-1].strip().split('|')
        valid_vitals, vitals = self.check_vitals(file_path)

        logging.info(f"{file_path} is valid vitals.yaml: {valid_vitals}")
        has_ask_id = 'metadata' in vitals and vitals['metadata'] is not None and 'askId' in vitals['metadata']
        has_ca_agile_id = 'metadata' in vitals and vitals['metadata'] is not None and 'caAgileId' in vitals['metadata']
        has_project_friendly_name = 'metadata' in vitals and vitals['metadata'] is not None and 'projectFriendlyName' in vitals['metadata']
        has_target_quality_gate = 'metadata' in vitals and vitals['metadata'] is not None and 'targetQG' in vitals['metadata']
        has_project_key = 'metadata' in vitals and vitals['metadata'] is not None and 'projectKey' in vitals['metadata']
        has_component_type = 'metadata' in vitals and vitals['metadata'] is not None and 'componentType' in vitals['metadata']

        key = str(vitals['metadata']['projectKey']) if has_project_key else "missing"
        state["sonar_key"] = key

        return ParserResult("Vitals", metadata={
            self.has_vitals_field: True,
            self.has_valid_vitals_field: valid_vitals,
            self.vitals_author_field: output_parts[0],
            self.vitals_created_date_field: output_parts[1],
            self.vitals_ask_id: str(vitals['metadata']['askId']) if has_ask_id else "missing",
            self.vitals_ca_agile_id: str(vitals['metadata']['caAgileId']) if has_ca_agile_id else "missing",
            self.vitals_project_friendly_name: str(vitals['metadata']['projectFriendlyName']) if has_project_friendly_name else "missing",
            self.vitals_target_quality_gate: str(vitals['metadata']['targetQG']) if has_target_quality_gate else "missing",
            self.vitals_project_key: key,
            self.vitals_component_type: str(vitals['metadata']['componentType']) if has_component_type else "missing"
        })

    def check_vitals(self, file_path):
        valid_vitals_file = False
        vitals_file = {}
        with open(file_path, "r") as file:
            try:
                vitals_file = yaml.safe_load(file)

                valid_vitals_file = all([rule(self, vitals_file) for rule in self.rules])
            except Exception:
                logging.exception("Exception when parsing vitals")
        return valid_vitals_file, vitals_file

    def create_postcrawl_issues(
            self, repo, dependencies, issues, metadata
    ) -> List[Issue]:
        if (
                self.has_vitals_field not in metadata
                or not metadata[self.has_vitals_field]
        ):
            logging.info("No vitals.yaml found")
            metadata[self.has_vitals_field] = False
            issues.append(
                Issue(
                    "missing_vitals_file",
                    "Missing Vitals.yaml",
                    "No vitals.yaml present in repository",
                )
            )

        return issues

    def create_default_metadata(self) -> dict:
        return {
            self.has_vitals_field: False,
            self.has_valid_vitals_field: False,
            self.vitals_author_field: "missing",
            self.vitals_created_date_field: "missing",
            self.vitals_ask_id: "missing",
            self.vitals_ca_agile_id: "missing",
            self.vitals_project_friendly_name: "missing",
            self.vitals_target_quality_gate: "missing",
            self.vitals_project_key: "missing",
            self.vitals_component_type: "missing"
        }
