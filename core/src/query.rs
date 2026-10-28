use crate::client::Query;

/// Converts a query parameter value into `key=value` pairs.
pub trait ToQuery {
    fn push_query(&self, key: &str, query: &mut Query);
}

macro_rules! display_query {
    ($($t:ty),*) => {$(
        impl ToQuery for $t {
            fn push_query(&self, key: &str, query: &mut Query) {
                query.push((key.to_owned(), self.to_string()));
            }
        }
    )*};
}

display_query!(String, i64, f64, bool, chrono::NaiveDate);

impl ToQuery for chrono::DateTime<chrono::Utc> {
    fn push_query(&self, key: &str, query: &mut Query) {
        query.push((key.to_owned(), crate::datetime::to_wire(self)));
    }
}

impl ToQuery for serde_json::Value {
    fn push_query(&self, key: &str, query: &mut Query) {
        match self {
            serde_json::Value::Null => {}
            serde_json::Value::String(s) => s.push_query(key, query),
            other => query.push((key.to_owned(), other.to_string())),
        }
    }
}

impl<T: ToQuery> ToQuery for Option<T> {
    fn push_query(&self, key: &str, query: &mut Query) {
        if let Some(value) = self {
            value.push_query(key, query);
        }
    }
}

impl<T: ToQuery> ToQuery for Vec<T> {
    fn push_query(&self, key: &str, query: &mut Query) {
        for value in self {
            value.push_query(key, query);
        }
    }
}
