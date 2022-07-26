import logging
import os
from typing import List

import requests

from requests.auth import HTTPBasicAuth

from handlers.FileParserInterface import FileParserInterface, ParserResult


class SonarParser(FileParserInterface):

    def __init__(self) -> None:
        super().__init__("^\\./(Orgfile|vitals)\\.ya?ml$", True)

        self.exists_in_sonar = "existsInSonar"
        self.sonar_blocker_violations = "sonarBlockerViolations"
        self.sonar_critical_violations = "sonarCriticalViolations"
        self.sonar_line_coverage = "sonarLineCoverage"
        self.sonar_lines_to_cover = "sonarLinesToCover"
        self.sonar_quality_gate = "sonarQualityGate"

    def parse(self, file_path: str, state: dict) -> ParserResult:
        metadata = state.get("sonar_data", {})
        if not metadata:
            key = state.get("sonar_key")
            metadata.update(self.get_sonar_measures(key))
            if metadata.get("existsInSonar"):
                metadata.update(self.get_sonar_quality_gate(key))

            state["sonar_data"] = metadata

        return ParserResult("Sonar", metadata=metadata)

    def get_sonar_measures(self, component_key: str) -> dict:

        if not component_key or component_key == "missing":
            return self.create_default_metadata()

        response = requests.get(
            url="https://sonar.Org.com/api/measures/component",
            params={"component": component_key,
                    "metricKeys": "line_coverage,blocker_violations,critical_violations,lines_to_cover"},
            headers={"Content-Type": "application/x-www-form-urlencoded",
                     "Accept": "application/json"},
            auth=HTTPBasicAuth(os.environ.get("SONAR_TOKEN"), "")
        )

        # handle the case where the component_key is not found
        if response.status_code == 404:
            logging.info(
                f"received {response.status_code} from sonar when retrieving measures for component {component_key!r}.")
            return self.create_default_metadata()

        # raise exception for any other non-200 response
        response.raise_for_status()

        metrics = {o["metric"]: o["value"] for o in response.json()["component"]["measures"] if
                   o.get("value") is not None}

        return {
            self.exists_in_sonar: True,
            self.sonar_blocker_violations: str(metrics["blocker_violations"]) if "blocker_violations" in metrics else "missing",
            self.sonar_critical_violations: str(metrics["critical_violations"]) if "critical_violations" in metrics else "missing",
            self.sonar_line_coverage: str(metrics["line_coverage"]) if "line_coverage" in metrics else "missing",
            self.sonar_lines_to_cover: str(metrics["lines_to_cover"]) if "lines_to_cover" in metrics else "missing"
        }

    def get_sonar_quality_gate(self, project_key: str) -> dict:

        if not project_key or project_key == "missing":
            return self.create_default_metadata()

        response = requests.get(
            url="https://sonar.Org.com/api/qualitygates/get_by_project",
            params={"project": project_key},
            headers={"Content-Type": "application/x-www-form-urlencoded",
                     "Accept": "application/json"},
            auth=HTTPBasicAuth(os.environ.get("SONAR_TOKEN"), "")
        )

        # handle the case where the project_key is not found
        if response.status_code == 404:
            return self.create_default_metadata()

        # raise exception for any other non-200 response
        response.raise_for_status()

        return {
            self.sonar_quality_gate: response.json()["qualityGate"]["name"]
        }

    def create_default_metadata(self) -> dict:
        return {
            self.exists_in_sonar: False,
            self.sonar_blocker_violations: "missing",
            self.sonar_critical_violations: "missing",
            self.sonar_line_coverage: "missing",
            self.sonar_lines_to_cover: "missing",
            self.sonar_quality_gate: "missing"
        }
