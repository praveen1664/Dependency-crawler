from dotenv import load_dotenv

load_dotenv()

import subprocess
import logging
import os
import re
import sys
import tempfile
import arrow
import urllib.parse
import urllib.request

from multiprocessing import Pool
from time import time
from typing import List
from azure.cosmos import CosmosClient
from github.Repository import Repository
from clients.github import get_all_orgs, get_all_repos
from clients.gremlin import (
    upsert_gremlin_vertex,
    upsert_gremlin_edge,
    gremlin,
    cleanup_old_edges,
    get_technologies,
    cleanup_old_outbound_neighbors,
    get_vertex,
)
from handlers.docker import DockerFileParser
from handlers.gem import GemFileParser
from handlers.maven import MavenFileParser
from handlers.npm import NpmFileParser
from handlers.nuget import NugetFileParser
from handlers.file import fileParser
from handlers.pip import PipFileParser
from handlers.vitals import VitalsFileParser
from handlers.jenkinsfile import JenkinsFileParser
from handlers.readme import ReadmeFileParser
from handlers.sonar import SonarParser
from model.issue import Issue


logging.basicConfig(
    format="%(process)s %(asctime)s %(levelname)-8s %(message)s",
    level=logging.DEBUG,
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout
)


parsers = [
    DockerFileParser(),
    GemFileParser(),
    MavenFileParser(),
    NpmFileParser(),
    NugetFileParser(),
    PipFileParser(),
    VitalsFileParser(),  # must be before FileParser
    fileParser(),  # must be after VitalsFileParser
    JenkinsFileParser(),
    ReadmeFileParser(),
    SonarParser()  # must be after VitalsFileParser and fileParser
]

# Github credentials
token = os.environ["GITHUB_API_TOKEN"]
cosmos_uri = os.environ["COSMOS_URI"]
cosmos_primary_key = os.environ["COSMOS_PRIMARY_KEY"]
cosmos_database_name = "DependencySqlDatabase"
cosmos_padu_container_name = "PADU"
cosmos_libraries_table_name = "Libraries"
cosmos_statistics_table_name = "Statistics"
cosmos_errors_table_name = "Errors"

cosmos_graph_primary_key = os.environ["COSMOS_GRAPH_PRIMARY_KEY"]

number_of_processes = int(os.environ.setdefault("NUMBER_OF_PROCESSES", "12")) if len(sys.argv) == 1 else 1

force_scan = os.environ.setdefault('FORCE_SCAN', 'False') == 'True' or len(sys.argv) > 2

cosmos = None
gremlin_client = None

counter = None
total_repos = None
technologies = []

timestamp = str(arrow.utcnow())

padu = []


def get_padu_ranking(dependency):
    for tech in padu:
        for regex in tech["regexes"]:
            match = regex.match(dependency)
            if match:
                return {
                    "name": tech["name"],
                    "ranking": tech["ranking"],
                    "matched_regex": regex.pattern,
                }

    return {"name": "Unknown", "ranking": "Uncategorized", "matched_regex": ""}


def should_process_repo(repo: Repository):
    clone_url = f"https://{token}:x-oauth-basic@github.com/{repo.owner.login}/{repo.name}"
    current_hash = os.popen(f"git ls-remote {clone_url} HEAD | cut -f1").read().strip()

    logging.info(f"current hash: {current_hash}")

    if current_hash == "reset":
        logging.info("repo has manually reset hash, will scan")
        return True, current_hash

    repo_id = f"{repo.owner.login}.{repo.name}"
    repo_pk = f"repository.{repo_id}"
    vertex = get_vertex(gremlin_client, repo_id, repo_pk)

    stored_hash = None
    try:
        stored_hash = vertex["properties"]["hash"][0]["value"]
    except:
        # hash not present, move on
        pass

    logging.info(f"stored hash: {stored_hash}")

    hash_match = stored_hash == current_hash

    if force_scan or (vertex is None) or (not hash_match):
        logging.info(
            f"Will scan {repo.name}. Vertex not present: {vertex is None}, Hashes match: {hash_match}, Force scan: {force_scan}"
        )
        return True, current_hash
    else:
        logging.info(
            f"Will NOT scan {repo.name}. Vertex not present: {vertex is None}, Hashes match: {hash_match}"
        )
        return False, current_hash


library_technology_cache = {}


def find_technology_for_dependency(dependency: str):
    global technologies

    results = []

    for technology in technologies:
        for regex in technology["regexes"]:
            match = regex.match(dependency)
            if match:
                results.append(technology)
                break

    if len(results) > 1:
        # TODO: flag overlapping technologies
        logging.error(f"Found more than one technologies for {dependency}: {results}")
        return results[0]
    elif len(results) == 1:
        return results[0]
    else:
        return None


def update_cosmos_graph(
        repo: Repository, dependencies: List[any], issues: List[Issue], repo_metadata: any
):
    repo_id = f"{repo.owner.login}.{repo.name}"
    repo_pk = f"repository.{repo_id}"

    for parser in parsers:
        parser.create_postcrawl_issues(repo, dependencies, issues, repo_metadata)

    upsert_repository(repo, repo_metadata)

    for dependency in dependencies:
        escaped_dependency = urllib.parse.quote(dependency["lib"], safe="")
        escaped_regex = urllib.parse.quote(
            dependency["padu_ranking"]["matched_regex"], safe=""
        )
        library_properties = {
            "lastScanned": timestamp,
            "name": dependency["lib"],
            "normalizedName": dependency["lib"].lower(),
            "type": "library",
            "technology": dependency["padu_ranking"]["name"],
            "ranking": dependency["padu_ranking"]["ranking"],
            "matchedRegex": escaped_regex,
        }

        dependency_pk = f"library.{escaped_dependency}"
        upsert_gremlin_vertex(
            gremlin_client,
            escaped_dependency,
            dependency_pk,
            library_properties,
            timestamp,
        )

        upsert_gremlin_edge(
            gremlin_client,
            "references",
            repo_id,
            repo_pk,
            escaped_dependency,
            dependency_pk,
            {},
            timestamp,
        )
        upsert_gremlin_edge(
            gremlin_client,
            "is referenced by",
            escaped_dependency,
            dependency_pk,
            repo_id,
            repo_pk,
            {},
            timestamp,
        )

        if escaped_dependency not in library_technology_cache:
            # we haven't seen this dependency before, we need to figure out if it matches a technology
            technology = find_technology_for_dependency(dependency["lib"])
            if technology is not None:
                # We found a technology to link this dependency to
                upsert_gremlin_edge(
                    gremlin_client,
                    "matches technology",
                    escaped_dependency,
                    dependency_pk,
                    technology["id"],
                    technology["pk"],
                    {},
                    timestamp,
                )

                upsert_gremlin_edge(
                    gremlin_client,
                    "matches dependency",
                    technology["id"],
                    technology["pk"],
                    escaped_dependency,
                    dependency_pk,
                    {},
                    timestamp,
                )

            # store the result in the cache
            library_technology_cache[escaped_dependency] = technology
        elif library_technology_cache[escaped_dependency] is None:
            # This dependency doesn't match any technologies we care about, ignore it
            pass
        else:
            # we've seen this dependency before, we don't need to relink it
            pass

    for issue in issues:
        issue_idpk = f"issue.{repo_id}.{issue.id}"

        issue_props = {
            "type": "issue",
            "description": issue.description,
            "name": issue.name,
        }
        upsert_gremlin_vertex(
            gremlin_client, issue_idpk, issue_idpk, issue_props, timestamp
        )

        upsert_gremlin_edge(
            gremlin_client,
            "has issue",
            repo_id,
            repo_pk,
            issue_idpk,
            issue_idpk,
            {},
            timestamp,
        )

        upsert_gremlin_edge(
            gremlin_client,
            "found in repo",
            issue_idpk,
            issue_idpk,
            repo_id,
            repo_pk,
            {},
            timestamp,
        )

    cleanup_old_outbound_neighbors(
        gremlin_client, repo_id, repo_pk, "has issue", "lastScanned", timestamp
    )
    cleanup_old_edges(gremlin_client, repo_id, repo_pk, "lastScanned", timestamp)


def handle_repo_new(repo: Repository):
    process_repo, current_hash = should_process_repo(repo)
    if not process_repo:
        return

    logging.info(f"cloning {repo.url}")
    clone_url = f"https://{token}:x-oauth-basic@github.com/{repo.owner.login}/{repo.name}"
    try:
        subprocess.check_output(["git", "clone", clone_url, "."], stderr=subprocess.STDOUT, text=True)

    except subprocess.CalledProcessError as e:
        logging.error(f"Failed to clone {repo.url} with the following output: {e.output!r}")
        return

    last_commit_date = ""
    last_committer = ""
    most_frequent_committer = ""
    try:
        last_commit_date = os.popen("git --no-pager log -1 --format=%cd").read().strip()
        last_committer = os.popen("git --no-pager log -1 --pretty=format:'%ae'").read().strip()
        most_frequent_commiter_line = os.popen(
            "git --no-pager log --pretty=format:'%ae' | sort | uniq -c | sort -n -r | head -n 1").read().strip()
        most_frequent_committer = most_frequent_commiter_line.strip().split(" ", 1)[1]
    except Exception as e:
        logging.error("Couldn't determine committer statistics", e)

    branch_count = ""
    try:
        branch_count = int(subprocess.getoutput("git fetch & git branch -r | grep -v -- \"->\" | wc -l").strip())
    except Exception as e:
        logging.error("Couldn't determine branch count", e)

    frameworks = []
    dependencies = []
    dependency_records = []
    issues = []
    repo_metadata = {"hash": current_hash,
                     "lastCommitDate": last_commit_date,
                     "lastCommitter": last_committer,
                     "mostFrequentCommitter": most_frequent_committer,
                     "branchCount": branch_count}
    state = {}

    file_paths = [os.path.join(path, name) for path, _, files in os.walk(".") for name in files]

    for parser in parsers:
        match_was_not_found = True
        for file_path in file_paths:
            if parser.will_parse(file_path):
                match_was_not_found = False
                logging.info(f"{type(parser).__name__} will handle {file_path}")
                try:
                    result = parser.parse(file_path, state)
                    frameworks.append(result.framework)
                    dependencies += result.dependencies
                    issues += result.issues
                    repo_metadata.update(result.metadata)
                except Exception as e:
                    logging.error(f"Failed to parse {file_path} with {type(parser).__name__}", e)
        if match_was_not_found:
            repo_metadata.update(parser.create_default_metadata())

    dependencies = list(set(dependencies))

    for dependency in dependencies:
        padu_ranking = get_padu_ranking(dependency)
        dependency_record = {"lib": dependency, "padu_ranking": padu_ranking}

        dependency_records.append(dependency_record)

    update_cosmos_graph(repo, dependency_records, issues, repo_metadata)


def init_padu():
    global padu
    global cosmos
    cosmos = CosmosClient(cosmos_uri, {"masterKey": cosmos_primary_key})
    database = cosmos.get_database_client("DependencySqlDatabase")
    container = database.get_container_client("PADU")
    container.read_all_items()

    for item in container.read_all_items():
        regexes = [re.compile(x) for x in item["regexes"]]
        padu_properties = {
            "name": item["name"],
            "ranking": item["ranking"],
            "regexes": regexes,
            "type": "technology",
        }
        padu.append(padu_properties)


def is_blacklisted(repo) -> bool:
    blacklisted_repos = ["pps-apca-other", "ARO_DOCUMENTS_STORAGE"]

    return repo.name in blacklisted_repos


def worker(repo):
    global cosmos
    global gremlin_client

    try:
        if is_blacklisted(repo):
            logging.info(f"Skipping {repo.html_url} because it is blacklisted")
            upsert_repository(repo)
        else:
            logging.info(f"upserting {repo.html_url}")
            upsert_repository(repo)
            logging.debug("Acquiring temp directory")
            with tempfile.TemporaryDirectory() as tempdir:
                logging.debug(f"Acquired temp directory: {tempdir}")
                os.chdir(tempdir)

                start_time = time()
                handle_repo_new(repo)
                elapsed_time = time() - start_time
                logging.info(f"Processed {repo.html_url} in {elapsed_time} seconds")
                logging.debug("Cleaning up temp directory")
            logging.debug("Cleaned up temp directory")
    except Exception as e:
        logging.exception(f"Failed to process {repo.html_url}", e)


def initialize_worker(techs, padus):
    global cosmos
    global gremlin_client
    global counter
    global technologies
    global padu
    logging.info("Initializing worker clients")
    # cosmos = CosmosClient(cosmos_uri, {"masterKey": cosmos_primary_key})
    gremlin_client = gremlin()
    technologies = techs
    padu = padus
    os.system("git config --global http.postBuffer 2M")


def upsert_repository(repo, repo_metadata=None):
    if repo_metadata is None:
        repo_metadata = {}

    try:
        org_id = f"github-organization.{repo.owner.login}"
        org_pk = f"github-organization"
        repo_id = f"{repo.owner.login}.{repo.name}"
        repo_pk = f"repository.{repo_id}"
        repo_properties = {
            "lastScanned": timestamp,
            "name": repo.name,
            "normalizedName": repo.name.lower(),
            "owner": repo.owner.login,
            "type": "repository",
            "isPrivate": repo.private,
            "isArchived": repo.archived,
            "isForked": repo.fork
        }
        repo_properties.update(repo_metadata)

        upsert_gremlin_vertex(
            gremlin_client, repo_id, repo_pk, repo_properties, timestamp
        )
        upsert_gremlin_edge(
            gremlin_client,
            "is in github org",
            repo_id,
            repo_pk,
            org_id,
            org_pk,
            {},
            timestamp,
        )
        upsert_gremlin_edge(
            gremlin_client,
            "is github org for",
            org_id,
            org_pk,
            repo_id,
            repo_pk,
            {},
            timestamp,
        )
    except Exception as e:
        logging.error(f"failed to upsert {repo.name}, {e}")
        raise e


def main():
    global technologies
    global gremlin_client
    global number_of_processes
    global cosmos
    start_time = time()

    gremlin_client = gremlin()
    logging.info("initialized gremlin client")
    logging.info("initialized github client")
    cosmos = CosmosClient(cosmos_uri, {"masterKey": cosmos_primary_key})
    logging.info("initialized sql cosmosdb client")
    init_padu()

    technologies = get_technologies(gremlin_client)

    all_orgs = get_all_orgs()

    logging.info(f"using {number_of_processes} processes")
    count = 1
    total_orgs = len(all_orgs)
    with Pool(
            processes=number_of_processes,
            initializer=initialize_worker,
            initargs=(technologies, padu),
            maxtasksperchild=50
    ) as pool:
        for org in all_orgs:
            try:
                logging.info(f"processing {org.login} - {count}/{total_orgs}")
                gremlin_client = gremlin()
                org_start_time = time()
                org_properties = {
                    "lastScanned": timestamp,
                    "name": org.login,
                    "type": "organization",
                    "normalizedName": org.login.lower(),
                }
                org_id = f"github-organization.{org.login}"
                org_pk = f"github-organization"
                upsert_gremlin_vertex(gremlin_client, org_id, org_pk, org_properties, timestamp)

                global total_repos
                # copy all the repos, so we don't have to keep doing paginated queries
                repos = get_all_repos(org)

                total_repos = len(repos)
                logging.info(f"total repositories to process: {total_repos}")
                pool.map(worker, repos)

                logging.info(f"Took %s seconds to process {org.login}", time() - org_start_time)
                gremlin_client.close()
                gremlin_client = gremlin()
                count += 1
            except Exception as e:
                logging.error(f"got error when processing {org.login} %s", e)

    logging.info("Took %s seconds to process all repos", time() - start_time)


if __name__ == "__main__":
    main()
