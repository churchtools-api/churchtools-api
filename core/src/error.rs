use serde::Deserialize;

pub type Result<T> = std::result::Result<T, Error>;

#[derive(Debug, thiserror::Error)]
pub enum Error {
    /// The server answered with a non-2xx status.
    #[error("{0}")]
    Api(Box<ApiError>),
    /// The request did not reach the server or the response could not be read.
    #[error("transport error: {0}")]
    Transport(#[from] reqwest::Error),
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
    /// A path parameter was empty, `.` or `..`; the request was not sent.
    #[error("invalid path (empty, `.` or `..` segment): {0}")]
    InvalidPath(String),
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
#[derive(Debug, Clone, thiserror::Error)]
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
