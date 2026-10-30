import typing as _t

class Client:
    def __init__(
        self,
        base_url: str,
        token: _t.Optional[str] = None,
        timeout: float = 30.0,
        min_interval: _t.Optional[float] = None,
        allow_insecure_http: bool = False,
        max_response_size: _t.Optional[int] = None,
        connect_timeout: _t.Optional[float] = None,
    ) -> None: ...
    def login_with_password(self, username: str, password: str) -> Client: ...
    @property
    def api_url(self) -> str: ...
    def request(
        self, method: str, path: str, query: _t.List[_t.Tuple[str, str]], body: _t.Optional[str] = None
    ) -> bytes: ...
    def request_multipart(
        self,
        method: str,
        path: str,
        query: _t.List[_t.Tuple[str, str]],
        form: _t.List[_t.Tuple[str, str]],
        file_field: str,
        files: _t.List[_t.Tuple[str, bytes, str]],
    ) -> bytes: ...
    def pages(self, path: str, query: _t.List[_t.Tuple[str, str]], prefetch: bool = True) -> Pages: ...

class Pages:
    def __iter__(self) -> Pages: ...
    def __next__(self) -> bytes: ...
