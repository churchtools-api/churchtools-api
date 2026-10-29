//! Synchronous client for the ChurchTools REST API.
//!
//! ```no_run
//! use churchtools_core::{Client, GetEventsQuery};
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
//! # Ok::<(), churchtools_core::Error>(())
//! ```

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
pub use client::{Client, ClientBuilder, DEFAULT_MAX_RESPONSE_SIZE, Pages, Query, Upload, decode, decode_data, encode_path_segment};
pub use datetime::DateOrDateTime;
pub use error::{ApiError, Error, Result};
pub use generated::api::*;
pub use generated::models;
pub use reqwest::Method;
