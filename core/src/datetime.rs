use std::fmt;

use chrono::{DateTime, NaiveDate, SecondsFormat, Utc};
use serde::{Deserialize, Serialize, Serializer};

/// Formats a timestamp the way the API accepts it: `2026-11-01T10:00:00Z`.
///
/// The server rejects offsets (`+00:00`) and fractional seconds.
pub fn to_wire(value: &DateTime<Utc>) -> String {
    value.to_rfc3339_opts(SecondsFormat::Secs, true)
}

pub(crate) fn serialize_utc<S: Serializer>(value: &DateTime<Utc>, s: S) -> Result<S::Ok, S::Error> {
    s.serialize_str(&to_wire(value))
}

pub(crate) fn serialize_opt_utc<S: Serializer>(value: &Option<DateTime<Utc>>, s: S) -> Result<S::Ok, S::Error> {
    match value {
        Some(v) => serialize_utc(v, s),
        None => s.serialize_none(),
    }
}

pub(crate) fn serialize_double_opt_utc<S: Serializer>(
    value: &Option<Option<DateTime<Utc>>>,
    s: S,
) -> Result<S::Ok, S::Error> {
    match value {
        Some(v) => serialize_opt_utc(v, s),
        None => s.serialize_none(),
    }
}

/// A value that is a date for all-day entries and a UTC timestamp otherwise.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(untagged)]
pub enum DateOrDateTime {
    #[serde(serialize_with = "serialize_utc")]
    DateTime(DateTime<Utc>),
    Date(NaiveDate),
}

impl DateOrDateTime {
    /// The calendar date (in UTC for timestamps).
    pub fn date(&self) -> NaiveDate {
        match self {
            Self::DateTime(dt) => dt.date_naive(),
            Self::Date(d) => *d,
        }
    }

    pub fn is_all_day(&self) -> bool {
        matches!(self, Self::Date(_))
    }
}

/// `1970-01-01`; only there so models can derive `Default` for
/// `..Default::default()` in struct literals.
impl Default for DateOrDateTime {
    fn default() -> Self {
        Self::Date(NaiveDate::default())
    }
}

impl fmt::Display for DateOrDateTime {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::DateTime(dt) => dt.fmt(f),
            Self::Date(d) => d.fmt(f),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_both_forms() {
        let v: Vec<DateOrDateTime> = serde_json::from_str(r#"["2026-11-01T10:00:00Z", "2026-11-01"]"#).unwrap();
        assert!(!v[0].is_all_day());
        assert!(v[1].is_all_day());
        assert_eq!(v[0].date(), v[1].date());
    }

    #[test]
    fn serializes_without_offset_and_fraction() {
        let at: DateTime<Utc> = "2026-11-01T10:00:00.123+00:00".parse().unwrap();
        assert_eq!(to_wire(&at), "2026-11-01T10:00:00Z");
        let v = serde_json::to_string(&[DateOrDateTime::DateTime(at), DateOrDateTime::Date(at.date_naive())]).unwrap();
        assert_eq!(v, r#"["2026-11-01T10:00:00Z","2026-11-01"]"#);
    }
}
