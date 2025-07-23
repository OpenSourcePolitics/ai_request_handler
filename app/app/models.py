import base64


class Host:
    """" Host defines Decidim host and redis utilities"""
    def __init__(self, host: str):
        self.host = host
        self.b64_host = self.__to_base64()

    def redis_keys(self) -> tuple:
        return self.period_redis_key(), self.total_redis_key()

    def period_redis_key(self) -> str:
        return f"spam:{self.b64_host}:period"

    def total_redis_key(self) -> str:
        return f"spam:{self.b64_host}:total"

    def __to_base64(self) -> str:
        encoded_host = self.host.encode("utf-8")
        return str(base64.b64encode(encoded_host))
