import os
import subprocess
import re

gradle_dependency_pattern = re.compile(".* (\S*:.*):\S*")


def get_gradle_dependencies_local(gradle_file):
    libs = []
    dirname = os.path.dirname(gradle_file)
    if dirname != "":
        os.chdir(dirname)

    filepath = "Dependency-dependencies.txt"
    f = open(filepath, "w")
    subprocess.run(["gradle", "dependencies", "-q"], stdout=f)
    f.close()

    with open(filepath) as fp:
        line = fp.readline()
        while line:
            match = gradle_dependency_pattern.match(line)
            if (
                match
                and match.group(1)
                and not match.group(1).startswith("http:")
                and not match.group(1).startswith("https:")
            ):
                lib = match.group(1)

                if lib not in libs:
                    libs.append(lib)
            line = fp.readline()

    return libs
