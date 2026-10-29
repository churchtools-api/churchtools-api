//! Deserializers that tolerate known deviations of the API from its spec.

use std::collections::BTreeMap;

use chrono::{DateTime, Utc};
use serde::{Deserialize, Deserializer};

#[derive(Deserialize)]
#[serde(untagged)]
enum StringOrNumber {
    String(String),
    Number(serde_json::Number),
    Bool(bool),
}

impl From<StringOrNumber> for String {
    fn from(value: StringOrNumber) -> Self {
        match value {
            StringOrNumber::String(s) => s,
            StringOrNumber::Number(n) => n.to_string(),
            StringOrNumber::Bool(b) => b.to_string(),
        }
    }
}

/// Accepts numbers and booleans where the spec says string.
pub fn string<'de, D: Deserializer<'de>>(d: D) -> Result<String, D::Error> {
    StringOrNumber::deserialize(d).map(Into::into)
}

/// Like [`string`], for optional fields.
pub fn opt_string<'de, D: Deserializer<'de>>(d: D) -> Result<Option<String>, D::Error> {
    Option::<StringOrNumber>::deserialize(d).map(|v| v.map(Into::into))
}

#[derive(Deserialize)]
#[serde(untagged)]
enum NumberOrString<N> {
    Number(N),
    String(String),
}

impl<N: std::str::FromStr> NumberOrString<N> {
    fn into_number<E: serde::de::Error>(self) -> Result<N, E> {
        match self {
            Self::Number(n) => Ok(n),
            Self::String(s) => s
                .trim()
                .parse()
                .map_err(|_| E::custom(format!("expected a number, got {s:?}"))),
        }
    }
}

/// Accepts numeric strings (`"3"`) where the spec says number, like Pydantic does.
pub fn number<'de, D, N>(d: D) -> Result<N, D::Error>
where
    D: Deserializer<'de>,
    N: Deserialize<'de> + std::str::FromStr,
{
    NumberOrString::<N>::deserialize(d)?.into_number()
}

/// Like [`number`], for optional fields.
pub fn opt_number<'de, D, N>(d: D) -> Result<Option<N>, D::Error>
where
    D: Deserializer<'de>,
    N: Deserialize<'de> + std::str::FromStr,
{
    Option::<NumberOrString<N>>::deserialize(d)?
        .map(NumberOrString::into_number)
        .transpose()
}

#[derive(Deserialize)]
#[serde(untagged)]
enum MapOrEmptyList<V> {
    Map(BTreeMap<String, V>),
    List([(); 0]),
}

impl<V> From<MapOrEmptyList<V>> for BTreeMap<String, V> {
    fn from(value: MapOrEmptyList<V>) -> Self {
        match value {
            MapOrEmptyList::Map(m) => m,
            MapOrEmptyList::List(_) => BTreeMap::new(),
        }
    }
}

/// A JSON object; also accepts `[]`, which PHP sends for an empty one.
pub fn map<'de, D, V>(d: D) -> Result<BTreeMap<String, V>, D::Error>
where
    D: Deserializer<'de>,
    V: Deserialize<'de>,
{
    MapOrEmptyList::deserialize(d).map(Into::into)
}

/// Like [`map`], for optional fields.
pub fn opt_map<'de, D, V>(d: D) -> Result<Option<BTreeMap<String, V>>, D::Error>
where
    D: Deserializer<'de>,
    V: Deserialize<'de>,
{
    Option::<MapOrEmptyList<V>>::deserialize(d).map(|v| v.map(Into::into))
}

/// An optional timestamp; the PHP zero date (`-0001-11-30T00:00:00Z`, shifted
/// by the time zone) that some old records carry becomes `None`.
pub fn opt_datetime<'de, D: Deserializer<'de>>(d: D) -> Result<Option<DateTime<Utc>>, D::Error> {
    match Option::<String>::deserialize(d)? {
        None => Ok(None),
        Some(s) if s.starts_with('-') || s.starts_with("0000-") => Ok(None),
        Some(s) => s.parse().map(Some).map_err(serde::de::Error::custom),
    }
}

/// `Option<Option<T>>` of request bodies: a present `null` becomes
/// `Some(None)`, a missing field `None` (with `#[serde(default)]`).
pub fn double_option<'de, D, T>(d: D) -> Result<Option<Option<T>>, D::Error>
where
    D: Deserializer<'de>,
    T: Deserialize<'de>,
{
    Option::<T>::deserialize(d).map(Some)
}

#[cfg(test)]
mod tests {
    #[derive(serde::Deserialize)]
    struct S {
        #[serde(deserialize_with = "super::string")]
        a: String,
        #[serde(default, deserialize_with = "super::opt_string")]
        b: Option<String>,
    }

    #[derive(serde::Deserialize)]
    struct N {
        #[serde(deserialize_with = "super::number")]
        a: i64,
        #[serde(default, deserialize_with = "super::opt_number")]
        b: Option<f64>,
    }

    #[test]
    fn numeric_strings_become_numbers() {
        let n: N = serde_json::from_str(r#"{"a": "3", "b": "1.5"}"#).unwrap();
        assert_eq!((n.a, n.b), (3, Some(1.5)));
        let n: N = serde_json::from_str(r#"{"a": 4, "b": null}"#).unwrap();
        assert_eq!((n.a, n.b), (4, None));
        assert!(serde_json::from_str::<N>(r#"{"a": "x"}"#).is_err());
    }

    #[derive(serde::Deserialize)]
    struct M {
        #[serde(deserialize_with = "super::map")]
        a: std::collections::BTreeMap<String, i64>,
        #[serde(default, deserialize_with = "super::opt_map")]
        b: Option<std::collections::BTreeMap<String, serde_json::Value>>,
    }

    #[test]
    fn empty_list_is_an_empty_map() {
        let m: M = serde_json::from_str(r#"{"a": [], "b": []}"#).unwrap();
        assert!(m.a.is_empty() && m.b.unwrap().is_empty());
        let m: M = serde_json::from_str(r#"{"a": {"x": 1}}"#).unwrap();
        assert_eq!((m.a["x"], m.b), (1, None));
        assert!(serde_json::from_str::<M>(r#"{"a": [1]}"#).is_err());
    }

    #[derive(serde::Deserialize)]
    struct D {
        #[serde(default, deserialize_with = "super::opt_datetime")]
        at: Option<chrono::DateTime<chrono::Utc>>,
    }

    #[test]
    fn php_zero_date_becomes_none() {
        let d: D = serde_json::from_str(r#"{"at": "-0001-11-29T23:06:32Z"}"#).unwrap();
        assert_eq!(d.at, None);
        let d: D = serde_json::from_str(r#"{"at": "2026-10-28T08:00:00Z"}"#).unwrap();
        assert_eq!(d.at.unwrap().to_rfc3339(), "2026-10-28T08:00:00+00:00");
        let d: D = serde_json::from_str("{}").unwrap();
        assert_eq!(d.at, None);
    }

    #[derive(serde::Deserialize, serde::Serialize)]
    struct Body {
        #[serde(default, deserialize_with = "super::double_option", skip_serializing_if = "Option::is_none")]
        birthday: Option<Option<String>>,
    }

    #[test]
    fn double_option_tells_null_from_missing() {
        let b: Body = serde_json::from_str(r#"{"birthday": null}"#).unwrap();
        assert_eq!(b.birthday, Some(None));
        assert_eq!(serde_json::to_string(&b).unwrap(), r#"{"birthday":null}"#);
        let b: Body = serde_json::from_str("{}").unwrap();
        assert_eq!(b.birthday, None);
        assert_eq!(serde_json::to_string(&b).unwrap(), "{}");
    }

    #[test]
    fn numbers_become_strings() {
        let s: S = serde_json::from_str(r#"{"a": 0, "b": 1.5}"#).unwrap();
        assert_eq!((s.a.as_str(), s.b.as_deref()), ("0", Some("1.5")));
        let s: S = serde_json::from_str(r#"{"a": "x", "b": null}"#).unwrap();
        assert_eq!((s.a.as_str(), s.b), ("x", None));
    }
}
