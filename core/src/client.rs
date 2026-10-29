use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use percent_encoding::{AsciiSet, NON_ALPHANUMERIC, percent_decode_str, utf8_percent_encode};
use reqwest::Method;
use reqwest::blocking::RequestBuilder;
use serde::Deserialize;
use serde::de::DeserializeOwned;

use crate::error::{ApiError, Error, Result};

/// Query parameters as sent on the wire; array parameters appear once per value
/// (`ids[]=1&ids[]=2`).
pub type Query = Vec<(String, String)>;

/// Default for [`ClientBuilder::max_response_size`]: 256 MiB.
pub const DEFAULT_MAX_RESPONSE_SIZE: u64 = 256 * 1024 * 1024;

const DEFAULT_CONNECT_TIMEOUT: Duration = Duration::from_secs(10);

/// How often a request answered with a retryable status is repeated.
const MAX_RETRIES: u32 = 3;
/// Statuses after which an idempotent request is repeated: the gateway or
/// the server was briefly unavailable. `429` is repeated for every method.
const RETRY_STATUSES: [u16; 3] = [502, 503, 504];
/// Wait before repeating a request whose connection could not be established.
const CONNECT_RETRY_WAIT: Duration = Duration::from_secs(1);
/// Upper bound for waiting on a `Retry-After` header.
const MAX_RETRY_WAIT: Duration = Duration::from_secs(60);

/// Synchronous ChurchTools API client.
///
/// Cloning is cheap: the connection pool and the rate limit are shared.
#[derive(Clone)]
pub struct Client {
    http: reqwest::blocking::Client,
    api_url: String,
    token: Option<String>,
    timeout: Duration,
    connect_timeout: Duration,
    max_response_size: u64,
    throttle: Option<Arc<Throttle>>,
}

impl std::fmt::Debug for Client {
    // Hand-written so the token never ends up in logs.
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("Client")
            .field("api_url", &self.api_url)
            .field("token", &self.token.as_ref().map(|_| "<redacted>"))
            .field("timeout", &self.timeout)
            .field("connect_timeout", &self.connect_timeout)
            .field("max_response_size", &self.max_response_size)
            .field("throttle", &self.throttle)
            .finish_non_exhaustive()
    }
}

/// A file for an upload endpoint.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Upload {
    pub filename: String,
    pub content: Vec<u8>,
    /// MIME type, e.g. `application/pdf`.
    pub content_type: String,
}

impl Upload {
    pub fn new(filename: impl Into<String>, content: impl Into<Vec<u8>>, content_type: impl Into<String>) -> Self {
        Self {
            filename: filename.into(),
            content: content.into(),
            content_type: content_type.into(),
        }
    }

    /// Reads a file; the MIME type is guessed from the extension.
    pub fn from_path(path: impl AsRef<std::path::Path>) -> std::io::Result<Self> {
        let path = path.as_ref();
        let filename = path.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_default();
        let content_type = guess_content_type(&filename);
        Ok(Self::new(filename, std::fs::read(path)?, content_type))
    }
}

fn guess_content_type(filename: &str) -> &'static str {
    let ext = filename.rsplit_once('.').map(|(_, e)| e.to_ascii_lowercase()).unwrap_or_default();
    match ext.as_str() {
        "pdf" => "application/pdf",
        "png" => "image/png",
        "jpg" | "jpeg" => "image/jpeg",
        "gif" => "image/gif",
        "webp" => "image/webp",
        "svg" => "image/svg+xml",
        "txt" => "text/plain",
        "csv" => "text/csv",
        "xml" => "application/xml",
        "json" => "application/json",
        _ => "application/octet-stream",
    }
}

/// Options for a [`Client`], created with [`Client::builder`].
#[derive(Clone)]
pub struct ClientBuilder {
    base_url: String,
    token: Option<String>,
    timeout: Duration,
    connect_timeout: Option<Duration>,
    max_response_size: u64,
    allow_insecure_http: bool,
}

impl ClientBuilder {
    /// The login token, sent as `Authorization: Login <token>`.
    pub fn token(mut self, token: impl Into<Option<String>>) -> Self {
        self.token = token.into();
        self
    }

    /// Timeout for a whole request including reading the body (default 30 s).
    ///
    /// Raise it for large downloads, uploads or slow exports.
    pub fn timeout(mut self, timeout: Duration) -> Self {
        self.timeout = timeout;
        self
    }

    /// Timeout for establishing the connection (default 10 s, at most
    /// [`timeout`](Self::timeout)), so an unreachable host fails fast even
    /// with a long request timeout.
    pub fn connect_timeout(mut self, timeout: Duration) -> Self {
        self.connect_timeout = Some(timeout);
        self
    }

    /// Largest response body that is read (default
    /// [`DEFAULT_MAX_RESPONSE_SIZE`]); larger ones fail with
    /// [`Error::ResponseTooLarge`] instead of filling the memory.
    pub fn max_response_size(mut self, bytes: u64) -> Self {
        self.max_response_size = bytes;
        self
    }

    /// Allows `http://` for hosts other than `localhost` and loopback addresses.
    ///
    /// The token then travels unencrypted; only for instances in a trusted network.
    pub fn allow_insecure_http(mut self, allow: bool) -> Self {
        self.allow_insecure_http = allow;
        self
    }

    pub fn build(self) -> Result<Client> {
        let connect_timeout = self.connect_timeout.unwrap_or(DEFAULT_CONNECT_TIMEOUT).min(self.timeout);
        let http = reqwest::blocking::Client::builder()
            .timeout(self.timeout)
            .connect_timeout(connect_timeout)
            .user_agent(USER_AGENT)
            .redirect(redirect_policy())
            .build()?;
        Ok(Client {
            http,
            api_url: normalize_base_url(&self.base_url, self.allow_insecure_http)?,
            token: self.token,
            timeout: self.timeout,
            connect_timeout,
            max_response_size: self.max_response_size,
            throttle: None,
        })
    }
}

/// Follows only redirects that keep method and body (307, 308).
///
/// On 301/302/303 reqwest would repeat a POST/PUT/DELETE as GET and drop the
/// body, so a write would look successful without having happened. Those are
/// reported as [`Error::Redirect`] instead.
fn redirect_policy() -> reqwest::redirect::Policy {
    reqwest::redirect::Policy::custom(|attempt| {
        if attempt.previous().len() >= 10 {
            attempt.error("too many redirects")
        } else if matches!(attempt.status().as_u16(), 307 | 308) {
            attempt.follow()
        } else {
            attempt.stop()
        }
    })
}

const USER_AGENT: &str = concat!("churchtools-rs/", env!("CARGO_PKG_VERSION"));

/// Spaces requests at least `interval` apart, across all clones of a client.
#[derive(Debug)]
struct Throttle {
    interval: Duration,
    next: Mutex<Instant>,
}

impl Throttle {
    fn wait(&self) {
        let now = Instant::now();
        let start = {
            let mut next = self.next.lock().unwrap_or_else(|e| e.into_inner());
            let start = (*next).max(now);
            *next = start + self.interval;
            start
        };
        std::thread::sleep(start - now);
    }
}

impl Client {
    /// Creates a client for `base_url`, e.g. `https://meinegemeinde.church.tools`.
    ///
    /// A trailing `/api` is optional. See [`Client::builder`] for more options.
    pub fn new(base_url: &str, token: Option<String>) -> Result<Self> {
        Self::builder(base_url).token(token).build()
    }

    pub fn with_timeout(base_url: &str, token: Option<String>, timeout: Duration) -> Result<Self> {
        Self::builder(base_url).token(token).timeout(timeout).build()
    }

    /// Starts configuring a client for `base_url`.
    pub fn builder(base_url: &str) -> ClientBuilder {
        ClientBuilder {
            base_url: base_url.to_owned(),
            token: None,
            timeout: Duration::from_secs(30),
            connect_timeout: None,
            max_response_size: DEFAULT_MAX_RESPONSE_SIZE,
            allow_insecure_http: false,
        }
    }

    /// Limits this client (and its clones) to one request per `min_interval`.
    ///
    /// Useful for bulk jobs and tests, so the instance is not flooded. Independent
    /// of this, a `429 Too Many Requests` answer is retried after the time the
    /// server asks for (`Retry-After`, at most 60 s, up to 3 times); so are
    /// `502`/`503`/`504` for idempotent methods (GET, HEAD, PUT, DELETE,
    /// OPTIONS). A failed connection is retried once after 1 s.
    pub fn with_min_interval(mut self, min_interval: Duration) -> Self {
        self.throttle = Some(Arc::new(Throttle {
            interval: min_interval,
            next: Mutex::new(Instant::now()),
        }));
        self
    }

    /// Logs in with username (or email) and password and returns a client that
    /// uses the login token of that person.
    ///
    /// Keeps the rate limit of `self`. Prefer a stored token for scripts; this is
    /// meant for tests and interactive tools.
    ///
    /// The token is the person's persistent login token: ChurchTools creates one
    /// if there is none, and it stays valid after this client is dropped, until
    /// it is revoked with `client.persons().delete_logintoken(person_id)`. The
    /// password session used to fetch it is not reused; the API has no logout,
    /// so it ends when the server expires it.
    pub fn login_with_password(&self, username: &str, password: &str) -> Result<Self> {
        // The password login answers with a session cookie, which is only needed
        // to fetch the token.
        let session = Self {
            http: reqwest::blocking::Client::builder()
                .timeout(self.timeout)
                .connect_timeout(self.connect_timeout)
                .user_agent(USER_AGENT)
                .redirect(redirect_policy())
                .cookie_store(true)
                .build()?,
            token: None,
            ..self.clone()
        };
        #[derive(Deserialize)]
        #[serde(rename_all = "camelCase")]
        struct LoginData {
            person_id: i64,
        }
        let body = serde_json::json!({ "username": username, "password": password, "rememberMe": false });
        let login: LoginData = session.request_data(Method::POST, "/login", &[], Some(&body))?;
        let token: String = session.request_data(
            Method::GET,
            &format!("/persons/{}/logintoken", login.person_id),
            &[],
            None,
        )?;
        Ok(Self {
            token: Some(token),
            ..self.clone()
        })
    }

    /// Reads the instance URL from `CT_URL` and the login token from `CT_TOKEN`.
    pub fn from_env() -> Result<Self> {
        let url = std::env::var("CT_URL").map_err(|_| Error::InvalidBaseUrl("CT_URL is not set".into()))?;
        Self::new(&url, std::env::var("CT_TOKEN").ok())
    }

    /// The API root, always ending in `/api`.
    pub fn api_url(&self) -> &str {
        &self.api_url
    }

    /// Sends a request and returns the raw body of a successful response.
    ///
    /// `path` starts with `/` and is relative to the API root; path parameters
    /// must already be encoded (see [`encode_path_segment`]).
    pub fn request(
        &self,
        method: Method,
        path: &str,
        query: &[(String, String)],
        body: Option<&serde_json::Value>,
    ) -> Result<Vec<u8>> {
        self.send(method, path, query, |builder| match body {
            Some(body) => Ok(builder.json(body)),
            None => Ok(builder),
        })
    }

    /// Sends a `multipart/form-data` request: the text fields of `form` plus one
    /// part named `file_field` (e.g. `files[]`) per file.
    pub fn request_multipart(
        &self,
        method: Method,
        path: &str,
        query: &[(String, String)],
        form: &[(String, String)],
        file_field: &str,
        files: &[Upload],
    ) -> Result<Vec<u8>> {
        self.send(method, path, query, |builder| {
            // Sending consumes a form, so it is rebuilt for every attempt.
            let mut multipart = reqwest::blocking::multipart::Form::new();
            for (key, value) in form {
                multipart = multipart.text(key.clone(), value.clone());
            }
            for file in files {
                let part = reqwest::blocking::multipart::Part::bytes(file.content.clone())
                    .file_name(file.filename.clone())
                    .mime_str(&file.content_type)?;
                multipart = multipart.part(file_field.to_owned(), part);
            }
            Ok(builder.multipart(multipart))
        })
    }

    /// Common part of all requests: rate limit, auth, retries, error mapping.
    fn send(
        &self,
        method: Method,
        path: &str,
        query: &[(String, String)],
        with_body: impl Fn(RequestBuilder) -> Result<RequestBuilder>,
    ) -> Result<Vec<u8>> {
        check_path(path)?;
        let mut attempt = 0;
        let mut connect_retried = false;
        loop {
            if let Some(throttle) = &self.throttle {
                throttle.wait();
            }
            let mut builder = self
                .http
                .request(method.clone(), format!("{}{}", self.api_url, path))
                .header("Accept", "application/json")
                .query(query);
            if let Some(token) = &self.token {
                let mut value = reqwest::header::HeaderValue::try_from(format!("Login {token}"))
                    .map_err(|_| Error::InvalidToken)?;
                // Keeps the token out of reqwest's own debug output.
                value.set_sensitive(true);
                builder = builder.header(reqwest::header::AUTHORIZATION, value);
            }
            let response = match with_body(builder)?.send() {
                Ok(response) => response,
                // Not connected means the request did not reach the server, so
                // repeating it is safe for every method.
                Err(err) if err.is_connect() && !connect_retried => {
                    connect_retried = true;
                    std::thread::sleep(CONNECT_RETRY_WAIT);
                    continue;
                }
                Err(err) => return Err(err.into()),
            };
            let status = response.status().as_u16();
            let retryable = status == 429 || (RETRY_STATUSES.contains(&status) && is_idempotent(&method));
            if retryable && attempt < MAX_RETRIES {
                attempt += 1;
                std::thread::sleep(retry_after(response.headers(), attempt));
                continue;
            }
            if response.status().is_redirection() {
                let location = response.headers().get(reqwest::header::LOCATION);
                return Err(Error::Redirect {
                    status,
                    location: location.and_then(|v| v.to_str().ok()).map(str::to_owned),
                });
            }
            let bytes = read_body(response, self.max_response_size)?;
            if !(200..300).contains(&status) {
                return Err(ApiError::from_response(status, bytes).into());
            }
            return Ok(bytes);
        }
    }

    /// Sends a request and decodes the `data` field of the response envelope.
    pub fn request_data<T: DeserializeOwned>(
        &self,
        method: Method,
        path: &str,
        query: &[(String, String)],
        body: Option<&serde_json::Value>,
    ) -> Result<T> {
        decode_data(&self.request(method, path, query, body)?)
    }

    /// Sends a request and decodes the whole response body.
    pub fn request_json<T: DeserializeOwned>(
        &self,
        method: Method,
        path: &str,
        query: &[(String, String)],
        body: Option<&serde_json::Value>,
    ) -> Result<T> {
        decode(&self.request(method, path, query, body)?)
    }

    /// Iterates over the raw bodies of all pages of a paginated GET endpoint.
    ///
    /// Any `page` entry in `query` is replaced. Iteration stops after the page
    /// whose `meta.pagination.current` reaches `lastPage`, or after the first
    /// page if the response carries no pagination info.
    pub fn pages(&self, path: &str, query: Query) -> Pages {
        Pages {
            client: self.clone(),
            path: path.to_owned(),
            query: query.into_iter().filter(|(k, _)| k != "page").collect(),
            next_page: Some(1),
        }
    }

    /// Fetches all pages and concatenates their `data` arrays.
    pub fn collect_pages<T: DeserializeOwned>(&self, path: &str, query: Query) -> Result<Vec<T>> {
        let mut items = Vec::new();
        for page in self.pages(path, query) {
            items.extend(decode::<Envelope<Vec<T>>>(&page?)?.data);
        }
        Ok(items)
    }
}

/// Iterator returned by [`Client::pages`].
pub struct Pages {
    client: Client,
    path: String,
    query: Query,
    next_page: Option<u64>,
}

impl Iterator for Pages {
    type Item = Result<Vec<u8>>;

    fn next(&mut self) -> Option<Self::Item> {
        let page = self.next_page.take()?;
        let mut query = self.query.clone();
        query.push(("page".into(), page.to_string()));
        let result = self.client.request(Method::GET, &self.path, &query, None);
        if let Ok(bytes) = &result {
            self.next_page = next_page_number(bytes, page);
        }
        Some(result)
    }
}

/// Reads the whole body, but at most `limit` bytes.
fn read_body(response: reqwest::blocking::Response, limit: u64) -> Result<Vec<u8>> {
    use std::io::Read;

    let too_large = || Error::ResponseTooLarge { limit };
    if response.content_length().is_some_and(|len| len > limit) {
        return Err(too_large());
    }
    // Reserve what the server announces, but not more than 1 MiB up front.
    let mut bytes = Vec::with_capacity(response.content_length().unwrap_or(0).min(1 << 20) as usize);
    response.take(limit.saturating_add(1)).read_to_end(&mut bytes).map_err(Error::Read)?;
    if bytes.len() as u64 > limit {
        return Err(too_large());
    }
    Ok(bytes)
}

fn next_page_number(body: &[u8], requested: u64) -> Option<u64> {
    #[derive(Deserialize)]
    struct Meta {
        pagination: Option<Pagination>,
    }
    #[derive(Deserialize)]
    #[serde(rename_all = "camelCase")]
    struct Pagination {
        current: u64,
        last_page: u64,
    }
    #[derive(Deserialize)]
    struct Body {
        meta: Option<Meta>,
    }
    let pagination = serde_json::from_slice::<Body>(body).ok()?.meta?.pagination?;
    // Guard against servers that echo a page number we did not ask for.
    (pagination.current == requested && pagination.current < pagination.last_page)
        .then_some(requested + 1)
}

fn is_idempotent(method: &Method) -> bool {
    [Method::GET, Method::HEAD, Method::PUT, Method::DELETE, Method::OPTIONS].contains(method)
}

/// Wait time before a retry: the server's `Retry-After` (seconds or an HTTP
/// date), or an exponential backoff (2, 4, 8 s) when the header is missing.
fn retry_after(headers: &reqwest::header::HeaderMap, attempt: u32) -> Duration {
    headers
        .get(reqwest::header::RETRY_AFTER)
        .and_then(|v| v.to_str().ok())
        .and_then(|v| parse_retry_after(v.trim(), chrono::Utc::now()))
        .unwrap_or(Duration::from_secs(1 << attempt))
        .min(MAX_RETRY_WAIT)
}

fn parse_retry_after(value: &str, now: chrono::DateTime<chrono::Utc>) -> Option<Duration> {
    if let Ok(seconds) = value.parse::<u64>() {
        return Some(Duration::from_secs(seconds));
    }
    // `Wed, 21 Oct 2026 07:28:00 GMT`; a date in the past means no wait.
    let at = chrono::DateTime::parse_from_rfc2822(value).ok()?;
    Some((at.to_utc() - now).to_std().unwrap_or_default())
}

/// Decodes the `data` field of a response envelope.
pub fn decode_data<T: DeserializeOwned>(bytes: &[u8]) -> Result<T> {
    if bytes.trim_ascii().is_empty() {
        return decode(bytes); // no envelope without a body
    }
    decode::<Envelope<T>>(bytes).map(|e| e.data).or_else(|err| {
        // PHP encodes an empty associative array as `[]`; retry as `{}` for map results.
        match serde_json::from_slice::<Envelope<serde_json::Value>>(bytes) {
            Ok(Envelope { data: serde_json::Value::Array(a) }) if a.is_empty() => {
                serde_json::from_value(serde_json::json!({})).map_err(|_| err)
            }
            _ => Err(err),
        }
    })
}

#[derive(Deserialize)]
struct Envelope<T> {
    data: T,
}

/// Decodes a whole response body.
pub fn decode<T: DeserializeOwned>(bytes: &[u8]) -> Result<T> {
    if bytes.trim_ascii().is_empty() {
        // 204 No Content: only an `Option` result (or `()`) accepts this.
        return serde_json::from_value(serde_json::Value::Null).map_err(|source| Error::Decode {
            source,
            body: String::new(),
        });
    }
    serde_json::from_slice(bytes).map_err(|source| Error::Decode {
        source,
        body: String::from_utf8_lossy(bytes).into_owned(),
    })
}

/// Parses the instance URL and returns the API root ending in `/api`.
///
/// Accepts a path prefix (`https://example.org/ct` becomes
/// `https://example.org/ct/api`) and an existing `/api` suffix.
fn normalize_base_url(base_url: &str, allow_insecure_http: bool) -> Result<String> {
    let invalid = |why: &str| Error::InvalidBaseUrl(format!("{base_url}: {why}"));
    let mut url = reqwest::Url::parse(base_url.trim()).map_err(|e| invalid(&e.to_string()))?;
    match url.scheme() {
        "https" => {}
        "http" if allow_insecure_http || is_loopback(&url) => {}
        "http" => {
            return Err(invalid(
                "http:// would send the token unencrypted; use https:// \
                 (or allow_insecure_http for a trusted network)",
            ));
        }
        _ => return Err(invalid("expected https://")),
    }
    if url.host_str().is_none_or(str::is_empty) {
        return Err(invalid("no host"));
    }
    if url.query().is_some() || url.fragment().is_some() {
        return Err(invalid("must not contain `?` or `#`"));
    }
    if !url.username().is_empty() || url.password().is_some() {
        return Err(invalid("must not contain user name or password; pass a token instead"));
    }
    let path = url.path().trim_end_matches('/');
    let path = path.strip_suffix("/api").unwrap_or(path).to_owned();
    url.set_path(&format!("{path}/api"));
    Ok(url.into())
}

/// Rejects paths the URL parser would rewrite or that address a different
/// endpoint: `.` and `..` segments (also percent-encoded, which the parser
/// resolves as well) and empty segments, e.g. from an ID `".."` or `""`.
fn check_path(path: &str) -> Result<()> {
    let valid = path.strip_prefix('/').is_some_and(|rest| {
        rest.split('/').all(|segment| {
            let decoded = percent_decode_str(segment).decode_utf8_lossy();
            !segment.is_empty() && decoded != "." && decoded != ".."
        })
    });
    if valid { Ok(()) } else { Err(Error::InvalidPath(path.to_owned())) }
}

fn is_loopback(url: &reqwest::Url) -> bool {
    let host = url.host_str().unwrap_or_default();
    host == "localhost"
        || host
            .trim_start_matches('[')
            .trim_end_matches(']')
            .parse::<std::net::IpAddr>()
            .is_ok_and(|ip| ip.is_loopback())
}

const PATH_SEGMENT: &AsciiSet = &NON_ALPHANUMERIC.remove(b'-').remove(b'_').remove(b'.').remove(b'~');

/// Percent-encodes a value for use as a single path segment.
pub fn encode_path_segment(value: impl std::fmt::Display) -> String {
    utf8_percent_encode(&value.to_string(), PATH_SEGMENT).to_string()
}

#[cfg(test)]
mod tests {
    use std::io::{BufRead, BufReader, Read, Write};

    use super::*;

    /// Answers each connection with the next of `responses` (raw HTTP) and
    /// records method and path of each request, e.g. `"POST /api/x"`.
    fn serve(responses: Vec<String>) -> (String, Arc<Mutex<Vec<String>>>) {
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let url = format!("http://{}", listener.local_addr().unwrap());
        let seen = Arc::new(Mutex::new(Vec::new()));
        let log = seen.clone();
        std::thread::spawn(move || {
            for (stream, response) in listener.incoming().zip(responses) {
                let mut stream = stream.unwrap();
                let mut reader = BufReader::new(stream.try_clone().unwrap());
                let mut line = String::new();
                reader.read_line(&mut line).unwrap();
                let request: Vec<&str> = line.split_whitespace().take(2).collect();
                log.lock().unwrap().push(request.join(" "));
                let mut length = 0;
                loop {
                    let mut header = String::new();
                    if reader.read_line(&mut header).unwrap() == 0 || header == "\r\n" {
                        break;
                    }
                    if let Some((name, value)) = header.split_once(':')
                        && name.eq_ignore_ascii_case("content-length")
                    {
                        length = value.trim().parse().unwrap();
                    }
                }
                reader.read_exact(&mut vec![0; length]).unwrap();
                stream.write_all(response.as_bytes()).unwrap();
            }
        });
        (url, seen)
    }

    fn reply(status: &str, headers: &str, body: &str) -> String {
        format!(
            "HTTP/1.1 {status}\r\n{headers}Content-Length: {}\r\nConnection: close\r\n\r\n{body}",
            body.len()
        )
    }

    #[test]
    fn connect_timeout_defaults_to_10s_but_not_above_timeout() {
        let client = Client::new("https://x.church.tools", None).unwrap();
        assert_eq!(client.connect_timeout, Duration::from_secs(10));
        let short = Client::with_timeout("https://x.church.tools", None, Duration::from_secs(3)).unwrap();
        assert_eq!(short.connect_timeout, Duration::from_secs(3));
        let custom = Client::builder("https://x.church.tools")
            .timeout(Duration::from_secs(600))
            .connect_timeout(Duration::from_millis(200))
            .build()
            .unwrap();
        assert_eq!((custom.timeout, custom.connect_timeout), (Duration::from_secs(600), Duration::from_millis(200)));
        // A blackholed address fails after the connect timeout, not after 600 s.
        let start = Instant::now();
        let blackhole = Client::builder("http://10.255.255.1").allow_insecure_http(true);
        let blackhole = blackhole.timeout(Duration::from_secs(600)).connect_timeout(Duration::from_millis(200));
        assert!(blackhole.build().unwrap().request(Method::GET, "/x", &[], None).is_err());
        assert!(start.elapsed() < Duration::from_secs(5));
    }

    #[test]
    fn responses_above_the_size_limit_are_rejected() {
        let declared = reply("200 OK", "", r#"{"data":"0123456789"}"#);
        // Without Content-Length the body ends when the connection closes.
        let undeclared = "HTTP/1.1 200 OK\r\nConnection: close\r\n\r\n{\"data\":\"0123456789\"}".to_owned();
        let small = reply("200 OK", "", r#"{"data":1}"#);
        let (url, _) = serve(vec![declared, undeclared, small]);
        let client = Client::builder(&url).max_response_size(12).build().unwrap();
        for _ in 0..2 {
            let err = client.request(Method::GET, "/x", &[], None).unwrap_err();
            assert!(matches!(err, Error::ResponseTooLarge { limit: 12 }), "{err}");
        }
        assert_eq!(client.request(Method::GET, "/x", &[], None).unwrap(), br#"{"data":1}"#);
    }

    #[test]
    fn redirects_that_would_turn_a_write_into_a_get_are_errors() {
        let (url, seen) = serve(vec![reply("302 Found", "Location: /api/elsewhere\r\n", "")]);
        let client = Client::new(&url, None).unwrap();
        let body = serde_json::json!({"name": "x"});
        let err = client.request(Method::POST, "/groups", &[], Some(&body)).unwrap_err();
        let Error::Redirect { status, location } = err else { panic!("{err}") };
        assert_eq!((status, location.as_deref()), (302, Some("/api/elsewhere")));
        assert_eq!(*seen.lock().unwrap(), ["POST /api/groups"]); // no GET afterwards
    }

    #[test]
    fn method_preserving_redirects_are_followed() {
        let (url, seen) = serve(vec![
            reply("307 Temporary Redirect", "Location: /api/moved\r\n", ""),
            reply("200 OK", "", r#"{"data":1}"#),
        ]);
        let client = Client::new(&url, None).unwrap();
        let body = serde_json::json!({"name": "x"});
        let data: i64 = client.request_data(Method::POST, "/groups", &[], Some(&body)).unwrap();
        assert_eq!(data, 1);
        assert_eq!(*seen.lock().unwrap(), ["POST /api/groups", "POST /api/moved"]);
    }

    #[test]
    fn base_url_gets_api_suffix_once() {
        for input in [
            "https://x.church.tools",
            "https://x.church.tools/",
            "https://x.church.tools/api",
            "https://x.church.tools/api/",
        ] {
            assert_eq!(normalize_base_url(input, false).unwrap(), "https://x.church.tools/api");
        }
        assert!(normalize_base_url("x.church.tools", false).is_err());
        assert_eq!(normalize_base_url(" https://X.Church.Tools ", false).unwrap(), "https://x.church.tools/api");
        assert_eq!(normalize_base_url("https://example.org/ct/", false).unwrap(), "https://example.org/ct/api");
        assert_eq!(normalize_base_url("https://example.org:8443/ct/api", false).unwrap(), "https://example.org:8443/ct/api");
        for bad in [
            "https://x.church.tools?a=b",
            "https://x.church.tools/#top",
            "https://user:pw@x.church.tools",
            "ftp://x.church.tools",
            "https://",
        ] {
            assert!(normalize_base_url(bad, false).is_err(), "{bad}");
        }
    }

    #[test]
    fn plain_http_only_for_loopback_or_when_allowed() {
        for local in ["http://localhost:8080", "http://127.0.0.1:1", "http://[::1]:80", "http://LOCALHOST"] {
            assert!(normalize_base_url(local, false).is_ok(), "{local}");
        }
        let err = normalize_base_url("http://x.church.tools", false).unwrap_err();
        assert!(err.to_string().contains("unencrypted"), "{err}");
        assert!(normalize_base_url("http://localhost.evil.org", false).is_err());
        assert_eq!(
            normalize_base_url("http://ct.intern", true).unwrap(),
            "http://ct.intern/api"
        );
        let client = Client::builder("http://ct.intern").allow_insecure_http(true).build().unwrap();
        assert_eq!(client.api_url(), "http://ct.intern/api");
    }

    #[test]
    fn pagination_stops_on_last_page_or_missing_meta() {
        let page = |c: u64, l: u64| {
            format!(r#"{{"data":[],"meta":{{"pagination":{{"current":{c},"lastPage":{l}}}}}}}"#)
        };
        assert_eq!(next_page_number(page(1, 3).as_bytes(), 1), Some(2));
        assert_eq!(next_page_number(page(3, 3).as_bytes(), 3), None);
        assert_eq!(next_page_number(page(1, 3).as_bytes(), 2), None);
        assert_eq!(next_page_number(br#"{"data":[],"meta":{"count":3}}"#, 1), None);
    }

    #[test]
    fn empty_body_is_none_for_optional_results() {
        assert_eq!(decode::<Option<i64>>(b"").unwrap(), None);
        assert_eq!(decode::<Option<i64>>(b"7").unwrap(), Some(7));
        assert!(decode::<i64>(b" ").is_err());
    }

    #[test]
    fn retry_after_uses_header_or_backoff() {
        let mut headers = reqwest::header::HeaderMap::new();
        assert_eq!(retry_after(&headers, 1), Duration::from_secs(2));
        assert_eq!(retry_after(&headers, 3), Duration::from_secs(8));
        headers.insert(reqwest::header::RETRY_AFTER, "5".parse().unwrap());
        assert_eq!(retry_after(&headers, 1), Duration::from_secs(5));
        headers.insert(reqwest::header::RETRY_AFTER, "3600".parse().unwrap());
        assert_eq!(retry_after(&headers, 1), MAX_RETRY_WAIT);
        headers.insert(reqwest::header::RETRY_AFTER, "soon".parse().unwrap());
        assert_eq!(retry_after(&headers, 2), Duration::from_secs(4));

        let now = "2026-10-21T07:28:00Z".parse().unwrap();
        assert_eq!(parse_retry_after("Wed, 21 Oct 2026 07:28:10 GMT", now), Some(Duration::from_secs(10)));
        assert_eq!(parse_retry_after("Wed, 21 Oct 2026 07:27:00 GMT", now), Some(Duration::ZERO));
    }

    #[test]
    fn unavailable_server_is_retried_for_idempotent_methods_only() {
        let unavailable = || reply("503 Service Unavailable", "Retry-After: 0\r\n", "");
        let (url, seen) = serve(vec![unavailable(), reply("200 OK", "", r#"{"data":1}"#), unavailable()]);
        let client = Client::new(&url, None).unwrap();
        assert_eq!(client.request(Method::GET, "/x", &[], None).unwrap(), br#"{"data":1}"#);
        let err = client.request(Method::POST, "/x", &[], None).unwrap_err();
        assert!(matches!(&err, Error::Api(api) if api.status == 503), "{err}");
        assert_eq!(*seen.lock().unwrap(), ["GET /api/x", "GET /api/x", "POST /api/x"]);
    }

    #[test]
    fn refused_connection_is_retried_once() {
        // Nothing listens on the port: both attempts are refused, after one wait.
        let port = std::net::TcpListener::bind("127.0.0.1:0").unwrap().local_addr().unwrap().port();
        let client = Client::new(&format!("http://127.0.0.1:{port}"), None).unwrap();
        let start = Instant::now();
        let err = client.request(Method::POST, "/x", &[], None).unwrap_err();
        assert!(matches!(&err, Error::Transport(e) if e.is_connect()), "{err}");
        assert!(start.elapsed() >= CONNECT_RETRY_WAIT);
    }

    #[test]
    fn throttle_spaces_requests() {
        let throttle = Throttle {
            interval: Duration::from_millis(30),
            next: Mutex::new(Instant::now()),
        };
        let start = Instant::now();
        for _ in 0..4 {
            throttle.wait();
        }
        // First call is immediate, the next three wait one interval each.
        assert!(start.elapsed() >= Duration::from_millis(90));
    }

    #[test]
    fn debug_output_hides_the_token() {
        let client = Client::new("https://x.church.tools", Some("geheim123".into())).unwrap();
        let debug = format!("{client:?}");
        assert!(!debug.contains("geheim123"), "{debug}");
        assert!(debug.contains("<redacted>") && debug.contains("https://x.church.tools/api"));
    }

    #[test]
    fn dot_and_empty_segments_are_rejected() {
        let client = Client::new("http://127.0.0.1:9", None).unwrap();
        for id in ["..", ".", ""] {
            let path = format!("/groups/7/members/{}", encode_path_segment(id));
            let err = client.request(Method::DELETE, &path, &[], None).unwrap_err();
            assert!(matches!(err, Error::InvalidPath(_)), "{id:?}: {err}");
        }
        // Raw paths: the URL parser treats percent-encoded dots as dots, too.
        assert!(check_path("/groups/7/members/%2e%2E").is_err());
        assert!(check_path("/groups/7/members/.%2e").is_err());
        assert!(check_path("persons").is_err());
        assert!(check_path("/persons/").is_err());
        assert!(check_path("/persons/a.b/..x").is_ok());
        // An ID `%2e%2e` is encoded to `%252e%252e` and reaches the server literally.
        assert_eq!(encode_path_segment("%2e%2e"), "%252e%252e");
        assert!(check_path("/files/%252e%252e").is_ok());
    }

    #[test]
    fn path_segments_are_encoded() {
        assert_eq!(encode_path_segment("a b/c"), "a%20b%2Fc");
        assert_eq!(encode_path_segment(42), "42");
    }
}
