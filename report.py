from dotenv import load_dotenv

load_dotenv()

import json
import logging
import os
import arrow
from datetime import datetime, timezone, timedelta
from time import time
from multiprocessing import Pool
from utils.utils import prefix_var

from azure.servicebus import ServiceBusClient, ServiceBusMessage, TransportType
from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions
from azure.storage.queue import QueueClient
from github import Github

from clients.gremlin import gremlin, execute_gremlin_query
from utils.rate_limiter import rate_limited_retry

from helpers import report_to_csv_buffer, send_mail

logging.basicConfig(
    format="%(process)s %(asctime)s %(levelname)-8s %(message)s",
    level=logging.DEBUG,
    datefmt="%Y-%m-%d %H:%M:%S",
)

github_base_url = "https://github.com/api/v3"

stale_repo_retention_days = int(os.environ.setdefault("STALE_REPO_RETENTION_DAYS", "3"))
token = os.environ["GITHUB_API_TOKEN"]
cosmos_graph_primary_key = os.environ["COSMOS_GRAPH_PRIMARY_KEY"]
number_of_processes = int(os.environ.setdefault("NUMBER_OF_PROCESSES", "12"))
storage_account_connection_string = os.environ["STORAGE_ACCOUNT_CONNECTION_STRING"]
storage_account_access_key = os.environ["STORAGE_ACCOUNT_ACCESS_KEY"]

servicebus_conection_string = os.environ["SERVICEBUS_CONNECTION_STRING"]
servicebus_topic_name = "Dependency-reports"

github = Github(token, base_url=github_base_url, per_page=100)
gremlin_client = None


def initialize_worker():
    global github
    global gremlin_client
    logging.info("Initializing worker clients")
    github = Github(token, base_url=github_base_url, per_page=100)
    gremlin_client = gremlin()


@rate_limited_retry(github)
def get_all_orgs():
    orgs = []
    try:
        all_orgs = github.get_organizations()
        for org in all_orgs:
            logging.info(f"will process org: {org}")
            orgs.append(org.login)

        logging.info(f"Will process {len(orgs)} organizations")
        return orgs
    except:
        logging.exception(f"Exception when getting all the orgs")
        return orgs


def worker(org):
    global github
    global gremlin_client

    logging.info(f"processing {org}")

    org_id = f"github-organization.{org}"

    bad_files = execute_gremlin_query(
        gremlin_client,
        "g.V(org).out('is in github org').has('hasValidfile', false).count()",
        {"org": org_id}
    )[0] + execute_gremlin_query(
        gremlin_client,
        "g.V(org).out('is github org for').has('hasValidfile', false).count()",
        {"org": org_id}
    )[0]

    good_files = execute_gremlin_query(
        gremlin_client,
        "g.V(org).out('is in github org').has('hasValidfile', true).count()",
        {"org": org_id},
    )[0] + execute_gremlin_query(
        gremlin_client,
        "g.V(org).out('is github org for').has('hasValidfile', true).count()",
        {"org": org_id},
    )[0]

    missing_files = execute_gremlin_query(
        gremlin_client,
        "g.V(org).out('is in github org').not(has('hasValidfile')).count()",
        {"org": org_id},
    )[0] + execute_gremlin_query(
        gremlin_client,
        "g.V(org).out('is github org for').not(has('hasValidfile')).count()",
        {"org": org_id},
    )[0]

    private_repos = execute_gremlin_query(
        gremlin_client,
        "g.V(org).out('is in github org').has('isPrivate', true).count()",
        {"org": org_id},
    )[0] + execute_gremlin_query(
        gremlin_client,
        "g.V(org).out('is github for org').has('isPrivate', true).count()",
        {"org": org_id},
    )[0]

    public_repos = execute_gremlin_query(
        gremlin_client,
        "g.V(org).out('is in github org').has('isPrivate', false).count()",
        {"org": org_id},
    )[0] + execute_gremlin_query(
        gremlin_client,
        "g.V(org).out('is github org for').has('isPrivate', false).count()",
        {"org": org_id},
    )[0]

    repos = execute_gremlin_query(
        gremlin_client,
        "g.V(org).out('is in github org')",
        {"org": org_id},
    ) + execute_gremlin_query(
        gremlin_client,
        "g.V(org).out('is github org for')",
        {"org": org_id},
    )

    omitted_repo_count = 0
    mapped_repos = []
    for repo in repos:
        need_rescan = False
        repo_name = repo["properties"]["name"][0]["value"]
        mapped_repo = {
            "name": repo_name
        }

        last_scan_date = arrow.get(repo["properties"]["lastScanned"][0]["value"])
        scan_time_difference = arrow.utcnow() - last_scan_date

        if scan_time_difference.days > stale_repo_retention_days:
            logging.info(f"Omitting {repo_name} because it was last seen over {stale_repo_retention_days} days ago")
            omitted_repo_count += 1
            continue

        key_properties = [  # will trigger a rescan if absent ONLY PUT VALUES HERE IF EVERY REPO WILL HAVE THIS
            # from Dependency.py
            "isPrivate",
            "isArchived",
            "isForked",
            "branchCount"
        ]

        additional_properties = [  # will not trigger a rescan if absent
            # from Dependency.py
            "lastCommitter",
            "lastCommitDate",
            "mostFrequentCommitter",
            "hasReadme",
            "readmeAuthor",
            "readmeCreatedDate",
            "hasJenkinsFile",
            "usesGlFortifyScan",
            "usesGlTwistlockScan",
            "usesGlDockerImageBuildPush",
            "usesGlArtifactoryDockerPromote",
            "existsInSonar",
            "sonarBlockerViolations",
            "sonarCriticalViolations",
            "sonarLineCoverage",
            "sonarLinesToCover",
            "sonarQualityGate",
            # from orthus.py
            "defaultBranchName",  # Some repos don't have default branches, these repos are empty or 404
            "defaultBranchDismissesStaleReviews",
            "defaultBranchIsAdminEnforced",
            "defaultBranchRequiresApprovingReviews",
            "defaultBranchRequiresJenkinsStatusChecks",
            "defaultBranchRequiresStrictStatusChecks",
            "defaultBranchRequiresStatusChecks",
            "defaultBranchHasNoReviewDismissalAllowances",
            "protectedBranchRuleCount",
            "languageCount",
            "prCount"
        ]

        list_properties = [
            "languages"
        ]

        vitals_or_file_properties = [  # Inner properties for vitals/files. These do not trigger rescan
            "askId",
            "caAgileId",
            "componentType",
            "projectFriendlyName",
            "projectKey",
            "targetQualityGate"
        ]

        if "branchCount" in repo["properties"] and not isinstance(repo["properties"]["branchCount"][0]["value"], int):
            try:
                repo["properties"]["branchCount"][0]["value"] = int(repo["properties"]["branchCount"][0]["value"])
            except ValueError:
                repo["properties"]["branchCount"][0]["value"] = -1
                need_rescan = True

        for property_name in key_properties:
            if property_name in repo["properties"]:
                if property_name != "isPrivate":
                    mapped_repo[property_name] = repo["properties"][property_name][0]["value"]
                else:
                    mapped_repo["private"] = repo["properties"][property_name][0]["value"]
            else:
                logging.error(f"missing {property_name} for repo, {org}/{repo_name}")
                need_rescan = True

        for property_name in additional_properties:
            if property_name in repo["properties"]:
                mapped_repo[property_name] = repo["properties"][property_name][0]["value"]

        for property_name in list_properties:
            if property_name in repo["properties"]:
                mapped_repo[property_name] = [element["value"] for element in repo["properties"][property_name]]

        has_valid_vitals_file = False
        has_valid_file = False
        has_file = "hasfile" in repo["properties"] and (
                repo["properties"]["hasfile"][0]["value"] == "true" or repo["properties"]["hasfile"][0][
            "value"] is True)
        mapped_repo["hasfile"] = has_file
        if has_file:
            try:
                has_valid_file = repo["properties"]["hasValidfile"][0]["value"]
                mapped_repo["hasValidfile"] = has_valid_file

                if has_valid_file:
                    valid_author = "fileAuthor" in repo["properties"]
                    if valid_author:
                        mapped_repo["fileOwner"] = repo["properties"]["fileAuthor"][0]["value"].strip('"')
                    else:
                        logging.error(f"missing fileOwner for repo, {repo_name}")
                        mapped_repo["fileOwner"] = "missing-scan-error"
                        need_rescan = True

                    valid_created_date = "fileCreatedDate" in repo["properties"]
                    if valid_created_date:
                        mapped_repo["fileCreatedDate"] = repo["properties"]["fileCreatedDate"][0][
                            "value"].strip('"')
                    else:
                        logging.error(f"missing fileCreatedDate for repo, {repo_name}")
                        mapped_repo["fileCreatedDate"] = "missing-scan-error"
                        need_rescan = True
            except (IndexError, KeyError):
                need_rescan = True

        # Both "haVitalsFile" and "hasVitalsFile" must be checked and considered synonymous due to a typo.
        if "haVitalsFile" not in repo["properties"] and "hasVitalsFile" not in repo["properties"]:
            need_rescan = True

        has_vitals_file = "haVitalsFile" in repo["properties"] and (
                repo["properties"]["haVitalsFile"][0]["value"] == "true" or repo["properties"]["haVitalsFile"][0][
            "value"] is True)
        has_vitals_file |= "hasVitalsFile" in repo["properties"] and (
                repo["properties"]["hasVitalsFile"][0]["value"] == "true" or repo["properties"]["hasVitalsFile"][0][
            "value"] is True)
        mapped_repo["hasVitalsFile"] = has_vitals_file
        if has_vitals_file:
            try:
                has_valid_vitals_file = repo["properties"]["hasValidVitalsFile"][0]["value"]
                mapped_repo["hasValidVitalsFile"] = has_valid_vitals_file

                if has_valid_vitals_file:
                    valid_author = "vitalsFileAuthor" in repo["properties"]
                    if valid_author:
                        mapped_repo["vitalsFileAuthor"] = repo["properties"]["vitalsFileAuthor"][0]["value"].strip('"')
                    else:
                        logging.error(f"missing vitalsFileAuthor for repo, {repo_name}")
                        mapped_repo["vitalsFileAuthor"] = "missing-scan-error"
                        need_rescan = True

                    valid_created_date = "vitalsFileCreatedDate" in repo["properties"]
                    if valid_created_date:
                        mapped_repo["vitalsFileCreatedDate"] = repo["properties"]["vitalsFileCreatedDate"][0][
                            "value"].strip('"')
                    else:
                        logging.error(f"missing vitalsFileCreatedDate for repo, {repo_name}")
                        mapped_repo["vitalsFileCreatedDate"] = "missing-scan-error"
                        need_rescan = True
            except (IndexError, KeyError):
                need_rescan = True

        for property_name in vitals_or_file_properties:
            value = "missing"
            try:
                vitals_key = prefix_var("vitalsFile", property_name)
                file_key = prefix_var("file", property_name)
                if (has_valid_vitals_file
                        and vitals_key in repo["properties"]
                        and repo["properties"][vitals_key][0]["value"]  # not null or empty string
                        and repo["properties"][vitals_key][0]["value"] != "missing"):
                    value = repo["properties"][vitals_key][0]["value"]
                elif (has_valid_file
                        and file_key in repo["properties"]
                        and repo["properties"][file_key][0]["value"]  # not null or empty string
                        and repo["properties"][file_key][0]["value"] != "missing"):
                    value = repo["properties"][file_key][0]["value"]
            except (IndexError, KeyError):
                pass
            mapped_repo[property_name] = value

        if need_rescan:
            logging.error(f"bad scan results for repo: {repo_name} - resetting hash to trigger rescan")
            execute_gremlin_query(
                gremlin_client,
                "g.V(id).has('pk',pk).property('hash', 'reset')",
                {"id": repo["id"], "pk": repo["properties"]["pk"][0]["value"]},
            )
        mapped_repos.append(mapped_repo)

    return {
        org: {
            "validfileCount": good_files,
            "invalidfileCount": bad_files,
            "missingfileCount": missing_files,
            "publicRepositoryCount": public_repos,
            "privateRepositoryCount": private_repos,
            "omittedRepositoryCount": omitted_repo_count,
            "repositories": mapped_repos
        }
    }


def get_blob_sas(account_name, account_key, container_name, blob_name):
    sas_blob = generate_blob_sas(account_name=account_name,
                                 container_name=container_name,
                                 blob_name=blob_name,
                                 account_key=account_key,
                                 permission=BlobSasPermissions(read=True),
                                 expiry=datetime.utcnow() + timedelta(days=31))
    url = f'https://{account_name}.blob.core.windows.net/{container_name}/{blob_name}?{sas_blob}'

    return url


def main():
    start_time = time()
    all_orgs = get_all_orgs()

    with Pool(
            processes=number_of_processes,
            initializer=initialize_worker,
            initargs=(),
            maxtasksperchild=50,
    ) as pool:
        results = pool.map(worker, all_orgs)

        final_result = {k: v for d in results for k, v in d.items()}
        date = datetime.today().strftime('%Y-%m-%d')

        final_result["reportGeneratedTime"] = datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()
        file_name = f"{date}.json"
        csv_file_name = f"{date}.csv"

        csv_buffer = report_to_csv_buffer(final_result)

        logging.info(f"took {time() - start_time} seconds to generate report")

        blob_service_client = BlobServiceClient.from_connection_string(storage_account_connection_string)

        try:
            blob_service_client.create_container("reports")
        except:
            pass

        blob_client = blob_service_client.get_blob_client(container="reports", blob=file_name)

        json_string = json.dumps(final_result)
        blob_client.upload_blob(json_string, overwrite=True)

        json_sas_url = get_blob_sas("Dependencyreportsdev", storage_account_access_key, "reports", file_name)

        logging.info(json_sas_url)

        blob_client = blob_service_client.get_blob_client(container="reports", blob=csv_file_name)

        blob_client.upload_blob(csv_buffer.getvalue(), overwrite=True)
        csv_buffer.seek(0)

        csv_sas_url = get_blob_sas("Dependencyreportsdev", storage_account_access_key, "reports", csv_file_name)

        logging.info(csv_sas_url)

        queue_client = QueueClient.from_connection_string(storage_account_connection_string, "Dependency-reports")

        try:
            queue_client.create_queue()
        except:
            pass

        queue_message = {
            "generatedDate": date,
            "reportSASUrl": json_sas_url,
            "reportCsvSASUrl": csv_sas_url
        }
        queue_client.send_message(json.dumps(queue_message))

        servicebus_client = ServiceBusClient.from_connection_string(conn_str=servicebus_conection_string,
                                                                    logging_enable=True,
                                                                    transport_type=TransportType.AmqpOverWebsocket)
        with servicebus_client:
            sender = servicebus_client.get_topic_sender(topic_name=servicebus_topic_name)
            with sender:
                message = ServiceBusMessage(json.dumps(queue_message))
                sender.send_messages(message)

        logging.info("uploaded report")

        recipients = ["alexander.aavang@.com", "chris.haisty@.com", "preston_belknap@.com",
                      "rachael_crowthers@.com", "william_wallace@.com", "bruce.mcfadden@.com",
                      "john.prewett@.com", "jesse_aalberg@.com", "lcirne@.com", "david.snider@.com",
                      "patrick_mcnamara@.com", "dawn.jolly@.com"]
        message = f"""
        This is the message that was sent to the Dependency event queue:
        {json.dumps(queue_message, indent=2)}
        
        The reports cannot be attached directly as the file size has grown too large.
        
        Here are the links to the reports (just in case the JSON is weird):
        JSON: {json_sas_url}
        CSV: {csv_sas_url}
        
        """
        send_mail("Dependency@.com", recipients, f"Dependency Report for {date}", message,
                  [],
                  "mailo2.ORG.com")
        logging.info("sent email")


if __name__ == "__main__":
    main()
    # initialize_worker()
    # worker('asingh45')
