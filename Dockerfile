FROM python:3.9.0-alpine

# add credentials on build

# set work directory
WORKDIR /usr/src/app

# set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV GRADLE_OPTS -Dorg.gradle.daemon=false

RUN apk add build-base

# install dependencies
# According to this https://github.com/Azure/azure-sdk-for-python/issues/8654#issuecomment-555614017
# the Azure SDKs require cryptography and according to this https://cryptography.io/en/latest/installation/#alpine 
# is how you add cryptography
RUN apk add postgresql-dev gcc python3-dev musl-dev libffi-dev libressl-dev
RUN apk add postgresql-dev gcc python3-dev musl-dev libffi-dev openssl-dev
RUN apk add --update python3 py-pip python3-dev cmake gcc g++ openssl-dev build-base
RUN apk add --update make
RUN apk add openssh
RUN apk add git
# RUN apk add gradle

RUN python3 -m pip install --upgrade pip
COPY ./requirements.txt /usr/src/app/requirements.txt
RUN pip3 install -r requirements.txt

# Setup the user and install the SSH private key

# copy project
COPY . /usr/src/app/

CMD ["python3", "Dependency.py"]
