use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use percent_encoding::{AsciiSet, NON_ALPHANUMERIC, utf8_percent_encode};
use reqwest::Method;
use reqwest::blocking::RequestBuilder;
use serde::Deserialize;
use serde::de::DeserializeOwned;

use crate::error::{ApiError, Error, Result};

/// Query parameters as sent on the wire; array parameters appear once per value
/// (`ids[]=1&ids[]=2`).
pub type Query = Vec<(String, String)>;

/// How often a request answered with `429 Too Many Requests` is retried.
const MAX_RETRIES_ON_429: u32 = 3;
/// Upper bound for waiting on a `Retry-After` header.
const MAX_RETRY_WAIT: Duration = Duration::from_secs(60);

/// Synchronous ChurchTools API client.
///
/// Cloning is cheap: the connection pool and the rate limit are shared.
#[derive(Clone, Debug)]
pub struct Client {
    http: reqwest::blocking::Client,
    api_url: String,
    token: Option<String>,
    timeout: Duration,
    throttle: Option<Arc<Throttle>>,
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
    /// A trailing `/api` is optional.
    pub fn new(base_url: &str, token: Option<String>) -> Result<Self> {
        Self::with_timeout(base_url, token, Duration::from_secs(30))
    }

    pub fn with_timeout(base_url: &str, token: Option<String>, timeout: Duration) -> Result<Self> {
        let http = reqwest::blocking::Client::builder()
            .timeout(timeout)
            .user_agent(concat!("churchtools-rs/", env!("CARGO_PKG_VERSION")))
            .build()?;
        Ok(Self {
            http,
            api_url: normalize_base_url(base_url)?,
            token,
            timeout,
            throttle: None,
        })
    }

    /// Limits this client (and its clones) to one request per `min_interval`.
    ///
    /// Useful for bulk jobs and tests, so the instance is not flooded. Independent
    /// of this, a `429 Too Many Requests` answer is retried after the time the
    /// server asks for (`Retry-After`, at most 60 s, up to 3 times).
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
    pub fn login_with_password(&self, username: &str, password: &str) -> Result<Self> {
        // The password login answers with a session cookie, which is only needed
        // to fetch the token.
        let session = Self {
            http: reqwest::blocking::Client::builder()
                .timeout(self.timeout)
                .user_agent(concat!("churchtools-rs/", env!("CARGO_PKG_VERSION")))
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

    /// Common part of all requests: rate limit, auth, retry on 429, error mapping.
    fn send(
        &self,
        method: Method,
        path: &str,
        query: &[(String, String)],
        with_body: impl Fn(RequestBuilder) -> Result<RequestBuilder>,
    ) -> Result<Vec<u8>> {
        let mut attempt = 0;
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
                builder = builder.header("Authorization", format!("Login {token}"));
            }
            let response = with_body(builder)?.send()?;
            let status = response.status().as_u16();
            if status == 429 && attempt < MAX_RETRIES_ON_429 {
                attempt += 1;
                std::thread::sleep(retry_after(response.headers(), attempt));
                continue;
            }
            let bytes = response.bytes()?.to_vec();
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

/// Wait time before retrying a 429: the server's `Retry-After` seconds, or an
/// exponential backoff (2, 4, 8 s) when the header is missing.
fn retry_after(headers: &reqwest::header::HeaderMap, attempt: u32) -> Duration {
    headers
        .get(reqwest::header::RETRY_AFTER)
        .and_then(|v| v.to_str().ok())
        .and_then(|v| v.trim().parse::<u64>().ok())
        .map(Duration::from_secs)
        .unwrap_or(Duration::from_secs(1 << attempt))
        .min(MAX_RETRY_WAIT)
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

fn normalize_base_url(base_url: &str) -> Result<String> {
    let trimmed = base_url.trim().trim_end_matches('/');
    if !(trimmed.starts_with("https://") || trimmed.starts_with("http://")) {
        return Err(Error::InvalidBaseUrl(base_url.to_owned()));
    }
    Ok(if trimmed.ends_with("/api") {
        trimmed.to_owned()
    } else {
        format!("{trimmed}/api")
    })
}

const PATH_SEGMENT: &AsciiSet = &NON_ALPHANUMERIC.remove(b'-').remove(b'_').remove(b'.').remove(b'~');

/// Percent-encodes a value for use as a single path segment.
pub fn encode_path_segment(value: impl std::fmt::Display) -> String {
    utf8_percent_encode(&value.to_string(), PATH_SEGMENT).to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn base_url_gets_api_suffix_once() {
        for input in [
            "https://x.church.tools",
            "https://x.church.tools/",
            "https://x.church.tools/api",
            "https://x.church.tools/api/",
        ] {
            assert_eq!(normalize_base_url(input).unwrap(), "https://x.church.tools/api");
        }
        assert!(normalize_base_url("x.church.tools").is_err());
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
    fn path_segments_are_encoded() {
        assert_eq!(encode_path_segment("a b/c"), "a%20b%2Fc");
        assert_eq!(encode_path_segment(42), "42");
    }
}
