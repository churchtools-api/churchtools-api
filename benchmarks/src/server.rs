//! Local HTTP/1.1 server for the benchmarks, built from recorded responses.
//!
//! Unlike the replay servers of the tests it keeps connections alive, answers
//! with one `write` per response and serves a large paginated person list made
//! by repeating the recorded persons with fresh ids. All bodies except the list
//! pages are prepared once, so the server costs the same for every client.

use std::io::{BufRead, BufReader, Read, Write};
use std::net::{TcpListener, TcpStream};
use std::path::PathBuf;
use std::sync::Arc;

use serde_json::{Value, json};

/// Number of persons behind `GET /persons`.
pub const PERSONS: usize = 5000;
/// Page size used by the list benchmark (the API's maximum).
pub const PAGE_SIZE: usize = 500;

fn recorded(op_id: &str) -> Value {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join(format!("../fixtures/recorded/{op_id}.json"));
    let text = std::fs::read_to_string(&path).unwrap_or_else(|e| panic!("{}: {e}", path.display()));
    let fixture: Value = serde_json::from_str(&text).expect("fixture is JSON");
    fixture["body"].clone()
}

/// The response bodies the server answers with.
pub struct Data {
    pub person: Vec<u8>,
    pub created: Vec<u8>,
    /// Each person of the list, encoded on its own.
    persons: Vec<Vec<u8>>,
}

impl Data {
    pub fn load() -> Self {
        let recorded_list = recorded("get-persons");
        let items = recorded_list["data"].as_array().expect("recorded persons");
        let persons = (0..PERSONS)
            .map(|i| {
                let mut person = items[i % items.len()].clone();
                person["id"] = json!(i + 1);
                serde_json::to_vec(&person).unwrap()
            })
            .collect();
        Self {
            person: serde_json::to_vec(&recorded("get-persons-id")).unwrap(),
            created: serde_json::to_vec(&recorded("post-persons")).unwrap(),
            persons,
        }
    }

    /// Body of `GET /persons?page=..&limit=..`, shaped like ChurchTools' answer.
    pub fn page(&self, page: usize, limit: usize) -> Vec<u8> {
        let limit = limit.clamp(1, PAGE_SIZE);
        let last_page = PERSONS.div_ceil(limit);
        let start = (page.max(1) - 1) * limit;
        let items = self.persons.get(start..(start + limit).min(PERSONS)).unwrap_or_default();
        let mut body = b"{\"data\":[".to_vec();
        for (i, item) in items.iter().enumerate() {
            if i > 0 {
                body.push(b',');
            }
            body.extend_from_slice(item);
        }
        let meta = json!({
            "count": items.len(),
            "pagination": {"total": PERSONS, "limit": limit, "current": page.max(1), "lastPage": last_page},
        });
        body.extend_from_slice(b"],\"meta\":");
        body.extend_from_slice(&serde_json::to_vec(&meta).unwrap());
        body.push(b'}');
        body
    }

    fn respond(&self, method: &str, target: &str) -> Option<Vec<u8>> {
        let (path, query) = target.split_once('?').unwrap_or((target, ""));
        let param = |name: &str| {
            query
                .split('&')
                .find_map(|pair| pair.strip_prefix(name)?.strip_prefix('=')?.parse::<usize>().ok())
        };
        match (method, path) {
            ("GET", "/api/persons") => Some(self.page(param("page").unwrap_or(1), param("limit").unwrap_or(10))),
            ("GET", p) if p.starts_with("/api/persons/") => Some(self.person.clone()),
            ("POST", "/api/persons") => Some(self.created.clone()),
            _ => None,
        }
    }
}

/// Starts the server on a free port and returns its URL; it runs until the process ends.
pub fn start(data: Arc<Data>) -> String {
    let listener = TcpListener::bind("127.0.0.1:0").expect("bind");
    let url = format!("http://{}", listener.local_addr().expect("local address"));
    std::thread::spawn(move || {
        for stream in listener.incoming().flatten() {
            let data = data.clone();
            std::thread::spawn(move || {
                let _ = serve_connection(stream, &data);
            });
        }
    });
    url
}

fn serve_connection(stream: TcpStream, data: &Data) -> std::io::Result<()> {
    stream.set_nodelay(true)?;
    let mut writer = stream.try_clone()?;
    let mut reader = BufReader::new(stream);
    let mut line = String::new();
    loop {
        line.clear();
        if reader.read_line(&mut line)? == 0 {
            return Ok(()); // client closed the connection
        }
        let mut parts = line.split_whitespace();
        let method = parts.next().unwrap_or_default().to_owned();
        let target = parts.next().unwrap_or_default().to_owned();
        let (mut length, mut close) = (0, false);
        loop {
            let mut header = String::new();
            if reader.read_line(&mut header)? == 0 || header == "\r\n" {
                break;
            }
            if let Some((name, value)) = header.split_once(':') {
                if name.eq_ignore_ascii_case("content-length") {
                    length = value.trim().parse().unwrap_or(0);
                } else if name.eq_ignore_ascii_case("connection") {
                    close = value.trim().eq_ignore_ascii_case("close");
                }
            }
        }
        let mut body = vec![0; length];
        reader.read_exact(&mut body)?;
        let (status, payload) = match data.respond(&method, &target) {
            Some(payload) => ("200 OK", payload),
            None => ("404 Not Found", br#"{"message":"not found"}"#.to_vec()),
        };
        let mut response = format!(
            "HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {}\r\n\r\n",
            payload.len()
        )
        .into_bytes();
        response.extend_from_slice(&payload);
        writer.write_all(&response)?;
        if close {
            return Ok(());
        }
    }
}
