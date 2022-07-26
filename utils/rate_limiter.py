import time
import logging
from datetime import datetime, timezone
from dateutil import parser

import requests
from github import RateLimitExceededException


def rate_limited_retry(github):
    def decorator(func):
        def ret(*args, **kwargs):
            for _ in range(5):
                try:
                    return func(*args, **kwargs)
                except RateLimitExceededException:
                    limits = github.get_rate_limit()
                    reset = limits.core.reset.replace(tzinfo=timezone.utc)
                    now = datetime.now(timezone.utc)
                    seconds = (reset - now).total_seconds()
                    rate_wait(seconds)
            raise Exception("Failed too many times")

        return ret

    return decorator


def rate_limited_retry_gql(token, url):
    def decorator(func):
        def ret(*args, **kwargs):
            for _ in range(5):
                try:
                    return func(*args, **kwargs)
                except KeyError as e:
                    headers = {"Authorization": f"Bearer {token}"}
                    rate_limit_query = "{rateLimit(dryRun: false) {resetAt}}"
                    rate_limit_info = requests.post(url, json={"query": rate_limit_query},
                                      headers=headers).json()["data"]["rateLimit"]
                    # Sometimes the rateLimit takes a little bit to update, so to combat that if the used is close to
                    # the rate limit AND a keyError occurs, that is likely the cause of the error and we should wait.
                    if rate_limit_info["used"] > (rate_limit_info["limit"] - 10):
                        reset = parser.parse(rate_limit_info["resetAt"])
                        now = datetime.now(timezone.utc)
                        seconds = (reset - now).total_seconds()
                        rate_wait(seconds)
                    else:
                        raise e
            raise Exception("Failed too many times")

        return ret

    return decorator


def rate_wait(seconds):
    logging.error(f"Rate limit exceeded")
    logging.error(f"Reset is in {seconds:.3g} seconds.")
    if seconds > 0.0:
        logging.error(f"Waiting for {seconds:.3g} seconds...")
        time.sleep(seconds)
        logging.error("Done waiting - resume!")