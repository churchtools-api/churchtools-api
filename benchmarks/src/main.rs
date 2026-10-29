//! Benchmarks of churchtools-core against a local server.
//!
//! `churchtools-bench`         runs the Rust scenarios (starts its own server process)
//! `churchtools-bench serve`   only starts the server and prints its URL (used by bench.py)
//!
//! Options: `--rounds N` (default 15), `--json` (one JSON object per line).

mod server;

use std::hint::black_box;
use std::io::{BufRead, BufReader};
use std::process::{Child, Command, Stdio};
use std::sync::Arc;
use std::time::{Duration, Instant};

use churchtools_core::queries::{GetPersonsQuery, PostPersonsQuery};
use churchtools_core::{Client, Method, decode_data, models};

/// Minimum time spent on warm-up before measuring.
const WARMUP: Duration = Duration::from_millis(300);
/// Target duration of one measured round; the number of calls per round follows from it.
const ROUND: Duration = Duration::from_millis(100);

/// Time per call over all rounds, in microseconds.
struct Stats {
    median: f64,
    min: f64,
    max: f64,
}

fn measure(rounds: usize, mut f: impl FnMut()) -> Stats {
    let start = Instant::now();
    let mut calls = 0u32;
    while calls < 3 || start.elapsed() < WARMUP {
        f();
        calls += 1;
    }
    let per_call = start.elapsed() / calls;
    let n = (ROUND.as_secs_f64() / per_call.as_secs_f64()).ceil().max(1.0) as u32;
    let mut times: Vec<f64> = (0..rounds)
        .map(|_| {
            let t = Instant::now();
            for _ in 0..n {
                f();
            }
            t.elapsed().as_secs_f64() * 1e6 / n as f64
        })
        .collect();
    times.sort_by(f64::total_cmp);
    Stats {
        median: times[times.len() / 2],
        min: times[0],
        max: times[times.len() - 1],
    }
}

fn report(json: bool, scenario: &str, variant: &str, s: &Stats) {
    if json {
        let line = serde_json::json!({
            "scenario": scenario, "variant": variant, "median_us": s.median, "min_us": s.min, "max_us": s.max,
        });
        println!("{line}");
    } else {
        println!("{scenario:<18} {variant:<26} {:>12.1} µs  ({:.1} – {:.1})", s.median, s.min, s.max);
    }
}

/// The server process; killed when dropped, also after a panic.
struct Server(Child);

impl Drop for Server {
    fn drop(&mut self) {
        let _ = self.0.kill();
    }
}

/// Starts `<this binary> serve` and returns it with the URL it prints.
fn spawn_server() -> (Server, String) {
    let exe = std::env::current_exe().expect("current exe");
    let mut child = Command::new(exe).arg("serve").stdout(Stdio::piped()).spawn().expect("start server");
    let mut line = String::new();
    BufReader::new(child.stdout.take().unwrap()).read_line(&mut line).expect("server URL");
    (Server(child), line.trim().to_owned())
}

fn run(rounds: usize, json: bool) {
    let (_server, url) = spawn_server();
    let data = server::Data::load();
    let client = Client::new(&url, Some("bench".into())).expect("client");

    let s = measure(rounds, || {
        black_box(client.persons().get(1).unwrap());
    });
    report(json, "get_person", "rust", &s);
    // Transport only, without decoding.
    let s = measure(rounds, || {
        black_box(client.request(Method::GET, "/persons/1", &[], None).unwrap());
    });
    report(json, "get_person", "rust (nur HTTP)", &s);

    let query = GetPersonsQuery {
        limit: Some(server::PAGE_SIZE as i64),
        ..Default::default()
    };
    let s = measure(rounds, || {
        let mut n = 0;
        for person in client.persons().list_iter(&query) {
            black_box(person.unwrap());
            n += 1;
        }
        assert_eq!(n, server::PERSONS);
    });
    report(json, "list_persons", "rust", &s);

    let body = models::PostPersonsBody {
        department_ids: vec![1],
        first_name: Some("ctrs-test".into()),
        last_name: Some("Vereinbarung".into()),
        birthday: Some(Some("1990-05-17".parse().unwrap())),
        campus_id: Some(0),
        status_id: Some(0),
        privacy_policy_agreement_date: Some("2026-10-29".parse().unwrap()),
        privacy_policy_agreement_type_id: Some(1),
        privacy_policy_agreement_who_id: Some(1),
        ..Default::default()
    };
    let force = PostPersonsQuery {
        force: Some(true),
        ..Default::default()
    };
    let s = measure(rounds, || {
        black_box(client.persons().create_with(&force, &body).unwrap());
    });
    report(json, "create_person", "rust", &s);

    let page = data.page(1, server::PAGE_SIZE);
    let s = measure(rounds, || {
        let persons: Vec<models::Person> = decode_data(black_box(&page)).unwrap();
        assert_eq!(persons.len(), server::PAGE_SIZE);
    });
    report(json, "decode_page", "rust serde", &s);
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let rounds = args
        .iter()
        .position(|a| a == "--rounds")
        .and_then(|i| args.get(i + 1)?.parse().ok())
        .unwrap_or(15);
    if args.first().is_some_and(|a| a == "serve") {
        println!("{}", server::start(Arc::new(server::Data::load())));
        loop {
            std::thread::park();
        }
    }
    run(rounds, args.iter().any(|a| a == "--json"));
}
