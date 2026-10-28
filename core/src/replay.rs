//! Local HTTP server that answers with responses recorded from a real instance
//! (`fixtures/recorded/<operationId>.json`), so documentation examples can run
//! offline. Only built with the `replay` feature, which the crate's own tests
//! enable; not meant for library users.

use std::collections::HashMap;
use std::io::{BufRead, BufReader, Read, Write};
use std::net::{TcpListener, TcpStream};
use std::path::PathBuf;
use std::sync::{Arc, OnceLock};

use crate::Client;

fn fixtures_dir() -> PathBuf {
    PathBuf::from(concat!(env!("CARGO_MANIFEST_DIR"), "/../fixtures/recorded"))
}

/// Recorded body of an operation, if there is one.
pub fn recorded(op_id: &str) -> Option<Vec<u8>> {
    let text = std::fs::read_to_string(fixtures_dir().join(format!("{op_id}.json"))).ok()?;
    let fixture: serde_json::Value = serde_json::from_str(&text).ok()?;
    serde_json::to_vec(&fixture["body"]).ok()
}

/// A client whose server answers every request with the recording of `op_id`.
///
/// Panics if nothing was recorded; the generated doctests only use it for
/// recorded operations.
pub fn client(op_id: &str) -> Client {
    let body = recorded(op_id).unwrap_or_else(|| panic!("no recording for {op_id}"));
    let url = serve(Arc::new(move |_: &str, _: &str| Some(body.clone())));
    Client::new(&url, Some("replay".into())).expect("valid replay url")
}

/// URL of a shared server that picks the recording by method and path.
pub fn routing_url() -> &'static str {
    static URL: OnceLock<String> = OnceLock::new();
    URL.get_or_init(|| {
        let routes = Routes::load();
        serve(Arc::new(move |method: &str, path: &str| routes.find(method, path).and_then(recorded)))
    })
}

type Responder = Arc<dyn Fn(&str, &str) -> Option<Vec<u8>> + Send + Sync>;

fn serve(respond: Responder) -> String {
    let listener = TcpListener::bind("127.0.0.1:0").expect("bind replay server");
    let url = format!("http://{}", listener.local_addr().expect("local address"));
    std::thread::spawn(move || {
        for stream in listener.incoming().flatten() {
            let respond = respond.clone();
            std::thread::spawn(move || {
                let _ = handle(stream, &*respond);
            });
        }
    });
    url
}

fn handle(mut stream: TcpStream, respond: &dyn Fn(&str, &str) -> Option<Vec<u8>>) -> std::io::Result<()> {
    let mut reader = BufReader::new(stream.try_clone()?);
    let mut request_line = String::new();
    reader.read_line(&mut request_line)?;
    let mut parts = request_line.split_whitespace();
    let method = parts.next().unwrap_or_default().to_owned();
    let target = parts.next().unwrap_or_default();
    let path = target.split('?').next().unwrap_or_default().trim_start_matches("/api").to_owned();
    let mut length = 0;
    loop {
        let mut line = String::new();
        if reader.read_line(&mut line)? == 0 || line == "\r\n" {
            break;
        }
        if let Some((name, value)) = line.split_once(':')
            && name.eq_ignore_ascii_case("content-length")
        {
            length = value.trim().parse().unwrap_or(0);
        }
    }
    let mut body = vec![0; length];
    reader.read_exact(&mut body)?;
    let (status, payload) = match respond(&method, &path) {
        Some(data) => ("200 OK", data),
        None => ("501 Not Implemented", br#"{"message":"no recording for this request"}"#.to_vec()),
    };
    write!(
        stream,
        "HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
        payload.len()
    )?;
    stream.write_all(&payload)
}

/// Path templates of all operations, from the catalog the live tests use.
struct Routes(Vec<(String, Vec<Option<String>>, String)>);

impl Routes {
    fn load() -> Self {
        let path = concat!(env!("CARGO_MANIFEST_DIR"), "/../python/tests/live/operations.json");
        let catalog: Vec<HashMap<String, serde_json::Value>> =
            serde_json::from_str(&std::fs::read_to_string(path).expect("operations.json")).expect("catalog");
        let mut routes: Vec<_> = catalog
            .iter()
            .map(|e| {
                let segments = e["path"]
                    .as_str()
                    .unwrap_or_default()
                    .split('/')
                    .map(|s| (!s.starts_with('{')).then(|| s.to_owned()))
                    .collect::<Vec<_>>();
                let method = e["method"].as_str().unwrap_or_default().to_owned();
                (method, segments, e["op_id"].as_str().unwrap_or_default().to_owned())
            })
            .collect();
        // Most literal segments first, so /persons/birthdays wins over /persons/{id}.
        routes.sort_by_key(|(_, segments, _)| segments.iter().filter(|s| s.is_none()).count());
        Self(routes)
    }

    fn find(&self, method: &str, path: &str) -> Option<&str> {
        let parts: Vec<&str> = path.split('/').collect();
        self.0
            .iter()
            .find(|(m, segments, _)| {
                m == method
                    && segments.len() == parts.len()
                    && segments.iter().zip(&parts).all(|(s, p)| s.as_deref().is_none_or(|s| s == *p))
            })
            .map(|(_, _, op)| op.as_str())
    }
}
