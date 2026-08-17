"""Retry a synchronous function."""


def retry(*, attempts, exceptions=(Exception,), sleep=None, delay=0, backoff=1):
    def decorate(function):
        def wrapped(*args, **kwargs):
            for _ in range(attempts):
                try:
                    return function(*args, **kwargs)
                except exceptions:
                    if sleep is not None:
                        sleep(delay)
            return function(*args, **kwargs)

        return wrapped

    return decorate
