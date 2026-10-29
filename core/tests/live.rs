//! Checks against a real instance; run with `cargo test -- --ignored`.
//!
//! `CT_URL` selects the instance (default: demo.church.tools). With `CT_USER`
//! and `CT_PASSWORD` (or `CT_TOKEN`) the tests log in. Requests are spaced by
//! `CT_MIN_INTERVAL` seconds (default 0.25). The full API is covered by the
//! Python live tests in `python/tests/live`; the responses they record are
//! decoded into the Rust types by `tests/recorded.rs`.

use std::time::{Duration, Instant};

use churchtools_api::Client;
use churchtools_api::queries::GetCalendarsAppointmentsQuery;

fn base_url() -> String {
    std::env::var("CT_URL").unwrap_or_else(|_| "https://demo.church.tools".into())
}

fn client() -> Client {
    let interval = std::env::var("CT_MIN_INTERVAL")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(0.25);
    let client = Client::new(&base_url(), std::env::var("CT_TOKEN").ok())
        .unwrap()
        .with_min_interval(Duration::from_secs_f64(interval));
    match (std::env::var("CT_USER"), std::env::var("CT_PASSWORD")) {
        (Ok(user), Ok(password)) => client.login_with_password(&user, &password).unwrap(),
        _ => client,
    }
}

#[test]
#[ignore = "network"]
fn public_calendars_and_appointments_decode() {
    let client = client();
    let calendars = client.calendars().list().unwrap();
    assert!(!calendars.is_empty());
    let from = std::env::var("CT_FROM").unwrap_or_else(|_| "2020-01-01".into());
    let to = std::env::var("CT_TO").unwrap_or_else(|_| "2020-12-31".into());
    let query = GetCalendarsAppointmentsQuery {
        calendar_ids: Some(calendars.iter().map(|c| c.id).collect()),
        from: Some(from.parse().unwrap()),
        to: Some(to.parse().unwrap()),
        include: Some(vec!["event".into(), "tags".into(), "group".into()]),
        ..Default::default()
    };
    let appointments = client.calendars().appointments().list(&query).unwrap();
    assert!(!appointments.is_empty());
    println!("{} appointments", appointments.len());
}

#[test]
#[ignore = "network, needs CT_USER and CT_PASSWORD"]
fn password_login_and_rate_limit() {
    let client = client();
    let me = client.whoami().get().unwrap();
    assert!(me.id > 0);

    let limited = client.clone().with_min_interval(Duration::from_millis(500));
    let start = Instant::now();
    for _ in 0..3 {
        limited.info().get().unwrap();
    }
    assert!(start.elapsed() >= Duration::from_millis(1000));
}

#[test]
#[ignore = "network"]
fn wrong_password_is_rejected() {
    let err = Client::new(&base_url(), None)
        .unwrap()
        .login_with_password("ctrs-test-unknown", "wrong")
        .unwrap_err();
    let churchtools_api::Error::Api(api) = err else {
        panic!("expected an API error, got {err}");
    };
    assert!((400..500).contains(&api.status), "status {}", api.status);
}
