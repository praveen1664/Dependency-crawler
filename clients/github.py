import logging
import sys
import os
import requests
import time

from typing import List
from dotenv import load_dotenv
from github import Github, Organization
from github.Repository import Repository
from utils.rate_limiter import rate_limited_retry, rate_limited_retry_gql

load_dotenv()



token = os.environ["GITHUB_API_TOKEN"]

github = Github(token, base_url=github_base_url, per_page=100)

logging.basicConfig(
    format="%(process)s %(asctime)s %(levelname)-8s %(message)s",
    level=logging.DEBUG,
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout
)


@rate_limited_retry(github)
def get_all_orgs():
    orgs = []
    try:
        all_orgs = (
            github.get_organizations() if len(sys.argv) < 2 else [github.get_organization(sys.argv[1])])
        for org in all_orgs:
            logging.info(f"will process org: {org}")
            orgs.append(org)

        logging.info(f"Will process {len(orgs)} organizations")
        return orgs
    except Exception as e:
        logging.exception(f"Exception when getting all the orgs %s", e)
        return orgs


@rate_limited_retry(github)
def get_all_repos(organization: Organization) -> List[Repository]:
    repos = []
    try:
        for repo in (organization.get_repos() if len(sys.argv) < 3 else [organization.get_repo(sys.argv[2])]):
            logging.info(f"will process {repo}")

            repos.append(repo)
        return repos
    except Exception as e:
        try:
            logging.exception(f"Exception when getting all the repos for {organization}", e)
        except:
            logging.exception(f"Exception when getting all the repos for an organization (couldn't lookup login) %s", e)
        return repos


def get_all_repos_gql(organization: Organization) -> List[dict]:
    repos = []
    try:
        cursor = None
        has_next_page = True
        while has_next_page:
            repo_list = get_gql_response(organization.login, cursor)["data"]["organization"]["repositories"]
            repos.extend(repo_list["nodes"])
            cursor = repo_list["pageInfo"]["endCursor"]
            has_next_page = repo_list["pageInfo"]["hasNextPage"]
        return repos
    except Exception as e:
        try:
            logging.exception(f"Exception when getting all the repos for {organization}", e)
        except Exception as e:
            logging.exception(f"Exception when getting all the repos for an organization (couldn't lookup login) %s", e)
        return repos


# This should make 2 calls per query
@rate_limited_retry_gql(token, gql_github_base_url)
def get_gql_response(login: str, cursor = None):
    headers = {"Authorization": f"Bearer {token}"}
    variables = {"login": login, "cursor": cursor}
    gql_query = """
        query getGitHubRepoData($login: String!, $cursor: String) {
          organization(login: $login) {
            repositories(first: 100, after: $cursor) {
              pageInfo {
                endCursor
                hasNextPage
              }
              nodes {
                url
                name
                nameWithOwner
                languages(first: 100) {
                  totalCount
                  nodes {
                    name
                  }
                }
                defaultBranchRef {
                  name
                }
                branchProtectionRules(first: 100) {
                  totalCount
                  nodes {
                    pattern
                    dismissesStaleReviews
                    isAdminEnforced
                    requiresApprovingReviews
                    requiredStatusCheckContexts
                    requiresStrictStatusChecks
                    requiresStatusChecks
                    reviewDismissalAllowances {
                      totalCount
                    }
                  }
                }      
                pullRequests(first: 1){
                  totalCount
                }
              }
            }
          }
        }        
        """
    response = requests.post(gql_github_base_url, json={"query": gql_query, "variables": variables}, headers=headers)
    if response.status_code == 200:
        return response.json()
    else:
        response.raise_for_status()
