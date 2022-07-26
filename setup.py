from setuptools import setup, find_packages


with open("README.rst") as f:
    readme = f.read()

setup(
    name="Dependency-crawler",
    version="0.1.0",
    description="Package to mine Github for framework information",
    long_description=readme,
    author="Alex Aavang",
    author_email="alexander.aavang@.com",
    url="https://github.com/praveen1664/Dependency-crawler.git",
    packages=find_packages(exclude=("tests", "docs")),
)
