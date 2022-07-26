import os
import urllib.request


def read_url_into_string(url):
    file = urllib.request.urlopen(url)
    data = file.read().decode("utf-8").strip()
    file.close()
    return data


def read_file_into_string(filename):
    with open(filename, "r") as file:
        data = file.read()
        file.close()
        return data


def listify(obj):
    return obj if obj is None or isinstance(obj, list) else [obj]


def prefix_var(prefix: str, var_name: str):
    return prefix + var_name[0].upper() + var_name[1:]
