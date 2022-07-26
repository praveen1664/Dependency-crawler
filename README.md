# README

## Check your own repo's vitals.yaml file

### Running on a Mac

If you want to check to see if your vitals.yaml file is valid in one of your repos, you can use this tool.  While in the top directory of this repo, execute `python3 -m tests.validate_my_repo <repo_org> <repo_name>`

If you don't have the environment variable `GITHUB_API_TOKEN` set globally on your machine, execute this command instead (and put your token in the command) `GITHUB_API_TOKEN=<token> python3 -m tests.validate_my_repo <repo_org> <repo_name>`

If you don't have a GitHub Personal Access Token already, you can obtain one here: <https://github.com/settings/tokens>

#### Mac installation requirements

Macs should come preinstalled with python 2 and python 3.  This project requires python 3 to execute. You can check if python 3 is installed by running `python3 --version`

You will also need the `yaml` module

    python3 -m pip install pyyaml

#### Examples (personal or org)

    GITHUB_API_TOKEN=zzzzzzz python3 -m tests.validate_my_repo tlarso10 motion-tests
    GITHUB_API_TOKEN=zzzzzzz python3 -m tests.validate_my_repo ORG-Name ORGM.API.Earnings
    GITHUB_API_TOKEN=zzzzzzz python3 -m tests.validate_my_repo ECII Interoperability-CoP

### Output

    hasVitalsFile: True
    hasValidVitalsFile: True
    vitalsFileAskId: poc
    vitalsFileComponentType: docs

![validate my repo command output](validateMyRepoExample.png)

## Tests

### Running tests on a Mac

While in the top directory of this repo, execute `python3 -m unittest discover`

If you don't have the environment variable `GITHUB_API_TOKEN` set globally on your machine, execute this command instead (and put your token in the command) `GITHUB_API_TOKEN=<token> python3 -m unittest discover`

#### Mac installation requirements

you need both the `parameterized` module and `yaml` module

    python3 -m pip install parameterized
    python3 -m pip install pyyaml

### Known failures

Currently a number of unit tests fail all marked with `#fail` after each test.  These need to be figured out if the test is created wrong or if the dev has an issue.
