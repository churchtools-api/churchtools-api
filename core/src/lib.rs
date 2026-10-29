//! Synchronous client for the ChurchTools REST API.
//!
//! ```no_run
//! use churchtools_api::Client;
//! use churchtools_api::queries::GetEventsQuery;
//!
//! let client = Client::new("https://meinegemeinde.church.tools", Some("token".into()))?;
//! let query = GetEventsQuery {
//!     from: Some("2026-11-01".parse().unwrap()),
//!     to: Some("2026-11-30".parse().unwrap()),
//!     ..Default::default()
//! };
//! for event in client.events().list_with(&query)? {
//!     println!("{} {}", event.start_date, event.name);
//! }
//! # Ok::<(), churchtools_api::Error>(())
//! ```
//!
//! The code is generated from the API description of ChurchTools
//! [`API_VERSION`]. Other versions work as far as their API matches: missing
//! endpoints answer `404`, unknown fields end up in `extra`.
//!
//! The client is blocking. Inside an async runtime such as Tokio, run it in
//! `tokio::task::spawn_blocking`; calling it directly from async code panics.
//!
//! # Public dependencies
//!
//! The models use types of `chrono` (dates and timestamps), `serde`
//! (`Serialize`/`Deserialize`) and `serde_json` (`Value`, `extra` maps); those
//! crates are part of the public API, `chrono` is re-exported. The HTTP
//! library is not: requests take [`Method`], transport errors are wrapped in
//! [`TransportError`].

mod client;
mod datetime;
mod error;
mod generated;
mod lenient;
mod query;
#[cfg(feature = "replay")]
#[doc(hidden)]
pub mod replay;

pub use chrono;
pub use client::{
    Client, ClientBuilder, DEFAULT_MAX_RESPONSE_SIZE, InvalidMethod, Items, Method, Pages, Query, Upload, decode,
    decode_data, encode_path_segment,
};
pub use datetime::DateOrDateTime;
pub use error::{ApiError, Error, Result, TransportError};
pub use generated::api as resources;
pub use generated::{API_BUILD, API_VERSION, models, queries};
