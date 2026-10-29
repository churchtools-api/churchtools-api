use serde::Deserialize;

pub type Result<T> = std::result::Result<T, Error>;

/// Everything that can go wrong with a request.
///
/// New variants may be added in minor versions, so a `match` needs a `_` arm.
/// For the common checks there are helpers like [`Error::is_not_found`].
#[derive(thiserror::Error)]
#[non_exhaustive]
pub enum Error {
    /// The server answered with a non-2xx status.
    #[error("{0}")]
    Api(Box<ApiError>),
    /// The request did not reach the server or the response could not be read.
    #[error("transport error: {0}")]
    Transport(#[from] reqwest::Error),
    /// The response body could not be read completely.
    #[error("could not read response body: {0}")]
    Read(#[source] std::io::Error),
    /// The response body is larger than `ClientBuilder::max_response_size`.
    #[error("response body larger than the limit of {limit} bytes")]
    ResponseTooLarge { limit: u64 },
    /// The response body did not match the expected shape.
    #[error("could not decode response: {source}")]
    Decode {
        #[source]
        source: serde_json::Error,
        /// Response body (lossy UTF-8) for debugging.
        body: String,
    },
    #[error("invalid base URL: {0}")]
    InvalidBaseUrl(String),
    /// The server answered with a redirect that is not followed (301, 302,
    /// 303: it would repeat the request as GET without its body).
    #[error("unexpected redirect (HTTP {status}) to {}", .location.as_deref().unwrap_or("<no location>"))]
    Redirect { status: u16, location: Option<String> },
    /// The token contains characters not allowed in an HTTP header.
    #[error("invalid token: contains characters not allowed in an HTTP header")]
    InvalidToken,
    /// A path parameter was empty, `.` or `..`; the request was not sent.
    #[error("invalid path (empty, `.` or `..` segment): {0}")]
    InvalidPath(String),
}

/// Longest part of a response body shown by `Debug`; bodies may contain
/// personal data and end up in logs. The full body stays in the field.
const BODY_PREVIEW: usize = 300;

struct Preview<'a>(&'a [u8]);

impl std::fmt::Debug for Preview<'_> {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let text = String::from_utf8_lossy(&self.0[..self.0.len().min(BODY_PREVIEW)]);
        if self.0.len() > BODY_PREVIEW {
            write!(f, "{text:?}… ({} bytes)", self.0.len())
        } else {
            write!(f, "{text:?}")
        }
    }
}

impl std::fmt::Debug for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Api(api) => f.debug_tuple("Api").field(api).finish(),
            Self::Transport(err) => f.debug_tuple("Transport").field(err).finish(),
            Self::Decode { source, body } => f
                .debug_struct("Decode")
                .field("source", source)
                .field("body", &Preview(body.as_bytes()))
                .finish(),
            Self::Read(err) => f.debug_tuple("Read").field(err).finish(),
            Self::ResponseTooLarge { limit } => f.debug_struct("ResponseTooLarge").field("limit", limit).finish(),
            Self::InvalidBaseUrl(url) => f.debug_tuple("InvalidBaseUrl").field(url).finish(),
            Self::Redirect { status, location } => f
                .debug_struct("Redirect")
                .field("status", status)
                .field("location", location)
                .finish(),
            Self::InvalidToken => f.write_str("InvalidToken"),
            Self::InvalidPath(path) => f.debug_tuple("InvalidPath").field(path).finish(),
        }
    }
}

impl Error {
    /// The error response of the server, if it answered with a non-2xx status.
    pub fn api(&self) -> Option<&ApiError> {
        match self {
            Self::Api(api) => Some(api),
            _ => None,
        }
    }

    /// HTTP status of an error response or an unfollowed redirect.
    pub fn status(&self) -> Option<u16> {
        match self {
            Self::Api(api) => Some(api.status),
            Self::Redirect { status, .. } => Some(*status),
            _ => None,
        }
    }

    /// `404 Not Found`: the object does not exist or the person may not see it.
    pub fn is_not_found(&self) -> bool {
        self.status() == Some(404)
    }

    /// `401 Unauthorized`: no token, or an expired one.
    pub fn is_unauthorized(&self) -> bool {
        self.status() == Some(401)
    }

    /// `403 Forbidden`: logged in, but without permission.
    pub fn is_forbidden(&self) -> bool {
        self.status() == Some(403)
    }

    /// The request took longer than the timeout.
    pub fn is_timeout(&self) -> bool {
        matches!(self, Self::Transport(e) if e.is_timeout())
    }

    /// No connection to the server (wrong address, network down, connect timeout).
    pub fn is_connect(&self) -> bool {
        matches!(self, Self::Transport(e) if e.is_connect())
    }
}

impl From<ApiError> for Error {
    fn from(err: ApiError) -> Self {
        Self::Api(Box::new(err))
    }
}

/// Error response of the ChurchTools API.
///
/// ChurchTools reports errors as
/// `{"message", "translatedMessage", "messageKey", "args", "errors"}`;
/// all fields are optional here because not every error path fills them.
#[derive(Clone, thiserror::Error)]
#[error("HTTP {status}: {}", .message.as_deref().unwrap_or("<no message>"))]
pub struct ApiError {
    pub status: u16,
    pub message: Option<String>,
    pub translated_message: Option<String>,
    pub message_key: Option<String>,
    pub args: serde_json::Value,
    pub errors: serde_json::Value,
    /// Raw response body.
    pub body: Vec<u8>,
}

impl std::fmt::Debug for ApiError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("ApiError")
            .field("status", &self.status)
            .field("message", &self.message)
            .field("translated_message", &self.translated_message)
            .field("message_key", &self.message_key)
            .field("args", &self.args)
            .field("errors", &self.errors)
            .field("body", &Preview(&self.body))
            .finish()
    }
}

#[derive(Deserialize, Default)]
#[serde(rename_all = "camelCase", default)]
struct ErrorBody {
    message: Option<String>,
    translated_message: Option<String>,
    message_key: Option<String>,
    args: serde_json::Value,
    errors: serde_json::Value,
}

impl ApiError {
    pub fn from_response(status: u16, body: Vec<u8>) -> Self {
        let parsed: ErrorBody = serde_json::from_slice(&body).unwrap_or_default();
        Self {
            status,
            message: parsed.message,
            translated_message: parsed.translated_message,
            message_key: parsed.message_key,
            args: parsed.args,
            errors: parsed.errors,
            body,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn helpers_classify_errors() {
        let not_found = Error::from(ApiError::from_response(404, br#"{"message":"nope"}"#.to_vec()));
        assert!(not_found.is_not_found() && !not_found.is_forbidden());
        assert_eq!(not_found.api().and_then(|a| a.message.as_deref()), Some("nope"));
        let redirect = Error::Redirect { status: 302, location: None };
        assert_eq!((redirect.status(), redirect.api().is_none()), (Some(302), true));
        assert_eq!(Error::InvalidToken.status(), None);
    }

    #[test]
    fn debug_shortens_long_bodies() {
        let body = format!(r#"{{"data":[{}]}}"#, r#"{"email":"anna@example.org"},"#.repeat(100));
        let err = crate::decode::<i64>(body.as_bytes()).unwrap_err();
        let debug = format!("{err:?}");
        assert!(debug.len() < 1000, "{debug}");
        assert!(debug.contains(&format!("({} bytes)", body.len())));
        let Error::Decode { body: full, .. } = &err else { panic!() };
        assert_eq!(full.len(), body.len()); // the field keeps everything

        let api = ApiError::from_response(500, body.into_bytes());
        assert!(format!("{api:?}").len() < 1000);
        let short = ApiError::from_response(404, br#"{"message":"nope"}"#.to_vec());
        assert!(format!("{short:?}").contains(r#"body: "{\"message\":\"nope\"}""#));
    }
}
