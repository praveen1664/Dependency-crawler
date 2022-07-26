from fnmatch import fnmatch

from dotenv import load_dotenv

load_dotenv()

import logging
import os
import sys
import arrow

from dateutil import parser
from multiprocessing import Pool
from time import time
from clients.github import get_all_orgs, get_all_repos_gql
from clients.gremlin import (
    upsert_gremlin_vertex,
    gremlin
)

gremlin_client = None
total_repos = None

graph_github_base_url = "https://github.com/api/graphql"
token = os.environ["GITHUB_API_TOKEN"]

number_of_processes = int(os.environ.setdefault("NUMBER_OF_PROCESSES", "12")) if len(sys.argv) == 1 else 1
force_scan = os.environ.setdefault('FORCE_SCAN', 'False') == 'True' or len(sys.argv) > 2

timestamp = str(arrow.utcnow())


logging.basicConfig(
    format="%(process)s %(asctime)s %(levelname)-8s %(message)s",
    level=logging.DEBUG,
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout
)


def upsert_repository(repo, repo_metadata=None):
    if repo_metadata is None:
        repo_metadata = {}

    try:
        repo_id = repo["nameWithOwner"].replace("/", ".")
        repo_pk = f"repository.{repo_id}"

        upsert_gremlin_vertex(
            gremlin_client, repo_id, repo_pk, repo_metadata, timestamp
        )
    except Exception as e:
        logging.error(f"failed to upsert {repo['url']}, {e}")
        raise e
    return


def parse_protected_branches(repo: dict):
    # Metadata constants to avoid typos in data contract
    branch_name = "defaultBranchName"
    dismisses_stale_reviews = "defaultBranchDismissesStaleReviews"
    is_admin_enforced = "defaultBranchIsAdminEnforced"
    requires_approving_reviews = "defaultBranchRequiresApprovingReviews"
    requires_jenkins_status_checks = "defaultBranchRequiresJenkinsStatusChecks"
    requires_strict_status_check = "defaultBranchRequiresStrictStatusChecks"
    requires_status_checks = "defaultBranchRequiresStatusChecks"
    has_no_review_dismissal_allowances = "defaultBranchHasNoReviewDismissalAllowances"
    protected_branch_rule_count = "protectedBranchRuleCount"

    protected_branch_rule_count_value = repo["branchProtectionRules"]["totalCount"]
    branch_protection_rules = repo["branchProtectionRules"]["nodes"]

    default_branch_name = ""

    try:
        default_branch_name = repo["defaultBranchRef"]["name"]
    except TypeError or AttributeError as e:
        logging.info(f"{repo['url']} has no default branch. This repository may no longer exist.")
    for rule in branch_protection_rules:
        # Checks to see first branch covered by bprs through pattern.
        # THIS MAY FAIL IF A CONFLICT EXISTS ON DEFAULT BRANCH
        # Checking if this fails adds too much cost to gql query, so this has to do.
        if fnmatch(default_branch_name, rule["pattern"]):
            return {
                branch_name: default_branch_name,
                dismisses_stale_reviews: rule["dismissesStaleReviews"],
                is_admin_enforced: rule["isAdminEnforced"],
                requires_approving_reviews: rule["requiresApprovingReviews"],
                requires_jenkins_status_checks:
                    "continuous-integration/jenkins/branch" in rule["requiredStatusCheckContexts"],
                requires_strict_status_check: rule["requiresStrictStatusChecks"],
                requires_status_checks: rule["requiresStatusChecks"],
                has_no_review_dismissal_allowances: rule["reviewDismissalAllowances"]["totalCount"] == 0,
                protected_branch_rule_count: protected_branch_rule_count_value
            }
    return {
        branch_name: default_branch_name,
        dismisses_stale_reviews: False,
        is_admin_enforced: False,
        requires_approving_reviews: False,
        requires_jenkins_status_checks: False,
        requires_strict_status_check: False,
        requires_status_checks: False,
        has_no_review_dismissal_allowances: False,
        protected_branch_rule_count: protected_branch_rule_count_value
    }


def parse_languages(repo: dict):
    language_count = repo["languages"]["totalCount"]
    languages = [language["name"] for language in repo["languages"]["nodes"]]
    return {"languageCount": language_count, "languages": languages}


def parse_pull_requests(repo: dict):
    pr_count = repo["pullRequests"]["totalCount"]
    return {"prCount": pr_count}


def is_blacklisted(repo: dict) -> bool:
    blacklisted_repos = ["paymentintegrity/pps-apca-other", "paymentintegrity/ARO_DOCUMENTS_STORAGE"]

    return repo["nameWithOwner"] in blacklisted_repos


def handle_repo(repo):
    repo_metadata = {} | parse_protected_branches(repo) | parse_languages(repo) | parse_pull_requests(repo)
    logging.info(f"upserting {repo['url']}")
    upsert_repository(repo, repo_metadata)


def worker(repo: dict):

    try:
        if is_blacklisted(repo):
            logging.info(f"Skipping {repo['url']} because it is blacklisted")
            upsert_repository(repo)
        else:
            start_time = time()
            handle_repo(repo)
            elapsed_time = time() - start_time
            logging.info(f"Processed {repo['url']} in {elapsed_time} seconds")

    except Exception as e:
        logging.exception(f"Failed to process {repo['url']}", e)


def initialize_worker():
    global gremlin_client
    logging.info("Initializing worker clients")
    gremlin_client = gremlin()
    os.system("git config --global http.postBuffer 2M")


def main():
    global gremlin_client

    gremlin_client = gremlin()
    logging.info("initialized gremlin client")
    logging.info("initialized sql cosmosdb client")

    all_orgs = get_all_orgs()

    logging.info(f"using {number_of_processes} processes")
    count = 1
    total_orgs = len(all_orgs)
    with Pool(
            processes=number_of_processes, initializer=initialize_worker, maxtasksperchild=50
    ) as pool:
        for org in all_orgs:
            try:
                org_start_time = time()
                global total_repos
                logging.info(f"processing {org.login} - {count}/{total_orgs}")

                # copy all the repos, so we don't have to keep doing paginated queries
                repos = get_all_repos_gql(org)

                total_repos = len(repos)
                logging.info(f"total repositories to process: {total_repos}")
                pool.map(worker, repos)

                logging.info(f"Took %s seconds to process {org.login}", time() - org_start_time)
                gremlin_client.close()
                gremlin_client = gremlin()
                count += 1
            except Exception as e:
                logging.error(f"got error when processing {org.login} %s", e)


if __name__ == "__main__":
    main()
